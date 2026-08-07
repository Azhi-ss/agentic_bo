from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from .backend import acquisition_values, diagnostics as model_diagnostics, encode_frame, fit_surrogate, posterior_rows, ranked_candidate_positions
from .oracle import verify_receipt
from .state import Study, Trial, candidate_id, envelope, now

app = typer.Typer(add_completion=False, no_args_is_help=True)


def emit(command: str, result: Any = None, error: str | None = None, study: Study | None = None) -> None:
    typer.echo(envelope(command, result, error, study))


def load_state(path: Path) -> Study:
    if not path.exists():
        raise ValueError(f"state not found: {path}")
    return Study.load(path)


def load_candidates(study: Study) -> pd.DataFrame:
    return pd.read_csv(Path(study.public_root) / "test_features.csv")


def config_at(candidates: pd.DataFrame, index: int, features: list[str]) -> dict[str, Any]:
    if index < 0 or index >= len(candidates):
        raise ValueError(f"query_index out of range: {index}")
    return candidates.loc[index, features].to_dict()

def find_candidate(study: Study, candidates: pd.DataFrame, config: dict[str, Any]) -> int:
    matches = candidates.index[
        candidates[study.features].eq(pd.Series(config, index=study.features)).all(axis=1)
    ].tolist()
    if len(matches) != 1:
        raise ValueError("config must match exactly one public candidate")
    return int(matches[0])


def parse_json_object(value: str, name: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    return parsed


def parse_json_list(value: str, name: str) -> list[Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError(f"{name} must be a JSON list")
    return parsed




@app.command()
def create(
    state: Path = typer.Option(...),
    dataset_root: Path = typer.Option(...),
    target: str = typer.Option(...),
    direction: str = typer.Option("maximize"),
    seed: int = typer.Option(0),
    budget: int = typer.Option(40, min=1),
    campaign_id: str | None = typer.Option(None),
) -> None:
    command = "create"
    try:
        if state.exists():
            raise ValueError(f"state already exists: {state}")
        if direction not in {"maximize", "minimize"}:
            raise ValueError("direction must be maximize or minimize")
        train = pd.read_csv(dataset_root / "train.csv")
        candidates = pd.read_csv(dataset_root / "test_features.csv")
        if target not in train.columns:
            raise ValueError(f"target not found in train.csv: {target}")
        features = candidates.columns.tolist()
        if list(train.columns[:-1]) != features or train.columns[-1] != target:
            raise ValueError("train/test_features schema mismatch")
        categories = {
            feature: pd.concat([train[feature], candidates[feature]], ignore_index=True).drop_duplicates().tolist()
            for feature in features
        }
        study = Study(
            study_id=str(uuid.uuid4()),
            campaign_id=campaign_id or str(uuid.uuid4()),
            public_root=str(dataset_root.resolve()),
            target=target,
            direction=direction,
            seed=seed,
            budget=budget,
            features=features,
            categories=categories,
            initial=train.to_dict("records"),
        )
        study.append_event("campaign_created", candidates=len(candidates), initial=len(train))
        study.save(state)
        emit(command, {"features": features, "target": target, "direction": direction, "initial": len(train), "candidates": len(candidates), "budget": budget, "acqf": study.acqf}, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def suggest(
    state: Path = typer.Option(...),
    q: int = typer.Option(1, min=1),
    acqf: str | None = typer.Option(None),
    beta: float | None = typer.Option(None),
) -> None:
    command = "suggest"
    try:
        study = load_state(state)
        candidates = load_candidates(study)
        available = np.array([index for index in candidates.index if index not in study.submitted], dtype=int)
        if not len(available):
            emit(command, [], study=study)
            return
        name = acqf or study.acqf
        q = min(q, len(available))
        rng = np.random.default_rng(study.seed + len(study.observed))
        if name == "sobol":
            chosen = rng.choice(available, size=q, replace=False)
            result = [{"candidate_id": candidate_id(config_at(candidates, int(index), study.features), int(index)), "pool_index": int(index), "config": config_at(candidates, int(index), study.features), "acqf": "sobol"} for index in chosen]
        else:
            fitted = fit_surrogate(study, candidates)
            x = encode_frame(candidates.loc[available, study.features], study)
            scores = acquisition_values(fitted, x, name, beta if beta is not None else study.beta)
            mean, variance = posterior_rows(fitted, x, study.direction)
            order = ranked_candidate_positions(scores, q)
            result = []
            for position in order:
                config = config_at(candidates, int(available[position]), study.features)
                result.append({"candidate_id": candidate_id(config, int(available[position])), "pool_index": int(available[position]), "config": config, "posterior_mean": float(mean[position]), "posterior_variance": float(variance[position]), "acquisition_value": float(scores[position]), "acqf": name})
        emit(command, result, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def submit(
    state: Path = typer.Option(...),
    pool_index: int = typer.Option(..., min=0),
    config: str = typer.Option(...),
    request_id: str = typer.Option(...),
) -> None:
    command = "submit"
    try:
        study = load_state(state)
        parsed = parse_json_object(config, "config")
        candidates = load_candidates(study)
        expected = config_at(candidates, pool_index, study.features)
        if parsed != expected:
            raise ValueError("config does not match pool_index")
        index = pool_index
        existing = [trial for trial in study.trials if trial.request_id == request_id]
        if existing:
            if existing[0].config != parsed or existing[0].query_index != index:
                raise ValueError("request_id conflicts with a different candidate")
            emit(command, vars(existing[0]), study=study)
            return
        if study.pending:
            raise ValueError("a sequential trial is already in flight")
        if index in study.submitted:
            raise ValueError("candidate already submitted; benchmark replicates are forbidden")
        if len(study.observed) >= study.budget:
            raise ValueError("evaluation budget exhausted")
        trial = Trial(
            trial_id=str(uuid.uuid4()),
            candidate_id=candidate_id(parsed, index),
            query_index=index,
            config=parsed,
            status="pending",
            request_id=request_id,
            submitted_at=now(),
        )
        study.trials.append(trial)
        study.append_event("trial_submitted", trial_id=trial.trial_id, candidate_id=trial.candidate_id, request_id=request_id)
        study.save(state)
        emit(command, vars(trial), study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def observe(
    state: Path = typer.Option(...),
    trial_id: str = typer.Option(...),
    receipt: Path = typer.Option(...),
) -> None:
    command = "observe"
    try:
        study = load_state(state)
        trial = study.trial(trial_id)
        payload = json.loads(receipt.read_text())
        secret = os.environ.get("BOAGENT_RECEIPT_KEY")
        if not secret or not verify_receipt(payload, secret):
            raise ValueError("receipt signature is invalid")
        if (
            payload.get("campaign_id") != study.campaign_id
            or payload.get("trial_id") != trial_id
            or payload.get("candidate_id") != trial.candidate_id
            or payload.get("request_id") != trial.request_id
        ):
            raise ValueError("receipt identity does not match trial")
        if payload.get("status") != "succeeded":
            raise ValueError("receipt is not successful")
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict) or study.target not in metrics or not np.isfinite(float(metrics[study.target])):
            raise ValueError(f"receipt metrics must contain finite {study.target}")
        if trial.status == "observed":
            if trial.receipt_id == payload.get("receipt_id") and trial.metrics == metrics:
                emit(command, vars(trial), study=study)
                return
            raise ValueError("trial already observed with a different receipt")
        if trial.status != "pending":
            raise ValueError("trial is not pending")
        trial.status = "observed"
        trial.metrics = {key: float(value) for key, value in metrics.items()}
        trial.receipt_id = str(payload["receipt_id"])
        trial.observed_at = now()
        study.append_event("trial_observed", trial_id=trial_id, receipt_id=trial.receipt_id, metrics=trial.metrics)
        study.save(state)
        emit(command, vars(trial), study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command("set-acqf")
def set_acqf(
    state: Path = typer.Option(...),
    acqf: str = typer.Option(...),
    beta: float = typer.Option(2.0),
    rationale: str = typer.Option(...),
) -> None:
    command = "set-acqf"
    try:
        if not np.isfinite(beta) or beta < 0:
            raise ValueError("beta must be finite and non-negative")
        if acqf not in {"noisy_logei", "logei", "ucb", "sobol"}:
            raise ValueError(f"unknown acqf: {acqf}")
        study = load_state(state)
        prior_acqf = study.acqf
        prior_beta = study.beta
        study.acqf = acqf
        study.beta = beta
        study.configuration_revision += 1
        study.append_event(
            "configuration_revised",
            prior_acqf=prior_acqf,
            new_acqf=acqf,
            prior_beta=prior_beta,
            new_beta=beta,
            rationale=rationale,
        )
        study.save(state)
        emit(command, {"acqf": acqf, "beta": beta, "observed": len(study.observed)}, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def predict(state: Path = typer.Option(...), configs: str = typer.Option(...)) -> None:
    command = "predict"
    try:
        study = load_state(state)
        candidates = load_candidates(study)
        parsed = parse_json_list(configs, "configs")
        indices = [find_candidate(study, candidates, item) for item in parsed]
        fitted = fit_surrogate(study, candidates)
        x = encode_frame(candidates.loc[indices, study.features], study)
        mean, variance = posterior_rows(fitted, x, study.direction)
        emit(command, [{"candidate_id": candidate_id(config), "config": config, "mean": float(mu), "variance": float(var)} for config, mu, var in zip(parsed, mean, variance, strict=True)], study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def score(
    state: Path = typer.Option(...),
    configs: str = typer.Option(...),
    acqf: str | None = typer.Option(None),
    beta: float | None = typer.Option(None),
) -> None:
    command = "score"
    try:
        study = load_state(state)
        candidates = load_candidates(study)
        parsed = parse_json_list(configs, "configs")
        indices = [find_candidate(study, candidates, item) for item in parsed]
        fitted = fit_surrogate(study, candidates)
        x = encode_frame(candidates.loc[indices, study.features], study)
        name = acqf or study.acqf
        values = acquisition_values(fitted, x, name, beta if beta is not None else study.beta)
        emit(command, [{"candidate_id": candidate_id(config), "config": config, name: float(value)} for config, value in zip(parsed, values, strict=True)], study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def diagnostics(state: Path = typer.Option(...)) -> None:
    command = "diagnostics"
    try:
        study = load_state(state)
        cache_path = state.with_suffix(f"{state.suffix}.diagnostics.json")
        try:
            cached = json.loads(cache_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            cached = None
        cache_key = {
            "schema_version": 1,
            "study_id": study.study_id,
            "state_revision": study.state_revision,
            "configuration_revision": study.configuration_revision,
        }
        if cached and all(cached.get(key) == value for key, value in cache_key.items()) and {"cv_r2", "cv_r2_status"} <= cached.get("result", {}).keys():
            result = cached["result"]
        else:
            result = model_diagnostics(fit_surrogate(study, load_candidates(study)), study)
            temporary = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
            temporary.write_text(json.dumps({**cache_key, "result": result}))
            os.replace(temporary, cache_path)
        emit(command, result, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def incumbent(state: Path = typer.Option(...)) -> None:
    command = "incumbent"
    try:
        study = load_state(state)
        records = [*study.initial, *[{**trial.config, **(trial.metrics or {})} for trial in study.observed]]
        if not records:
            raise ValueError("need observed trials")
        key = lambda row: float(row[study.target])
        best = (max if study.direction == "maximize" else min)(records, key=key)
        emit(command, {"config": {feature: best[feature] for feature in study.features}, "metrics": {study.target: float(best[study.target])}}, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def trials(state: Path = typer.Option(...)) -> None:
    command = "trials"
    try:
        study = load_state(state)
        emit(command, [vars(trial) for trial in study.trials], study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def status(state: Path = typer.Option(...)) -> None:
    command = "status"
    try:
        study = load_state(state)
        candidates = load_candidates(study)
        emit(command, {"campaign_id": study.campaign_id, "target": study.target, "direction": study.direction, "acqf": study.acqf, "budget": study.budget, "initial": len(study.initial), "observed": len(study.observed), "pending": [trial.trial_id for trial in study.pending], "remaining": len(candidates) - len(study.submitted)}, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
