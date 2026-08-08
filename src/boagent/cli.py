from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import typer

from .backend import acquisition_values, diagnostics as model_diagnostics, diverse_candidate_positions, encode_frame, fit_surrogate, posterior_rows
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
    if index not in candidates.index:
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



def observed_records(study: Study) -> list[dict[str, Any]]:
    return [*study.initial, *[{**trial.config, **(trial.metrics or {})} for trial in study.all_observed]]


def is_feasible(row: dict[str, Any], constraints: list[dict[str, Any]]) -> bool:
    return all(
        (constraint.get("lower") is None or float(row[constraint["metric"]]) >= float(constraint["lower"]))
        and (constraint.get("upper") is None or float(row[constraint["metric"]]) <= float(constraint["upper"]))
        for constraint in constraints
    )


def dominates(left: dict[str, Any], right: dict[str, Any], objectives: dict[str, str]) -> bool:
    weak = all(float(left[key]) >= float(right[key]) if direction == "maximize" else float(left[key]) <= float(right[key]) for key, direction in objectives.items())
    strict = any(float(left[key]) > float(right[key]) if direction == "maximize" else float(left[key]) < float(right[key]) for key, direction in objectives.items())
    return weak and strict

def restrict_candidates(candidates: pd.DataFrame, restrictions: dict[str, Any]) -> pd.DataFrame:
    selected = candidates
    for feature, allowed in restrictions.items():
        if isinstance(allowed, list) and len(allowed) == 2 and pd.api.types.is_numeric_dtype(candidates[feature]) and len(allowed) < candidates[feature].nunique(dropna=False) and all(isinstance(value, (int, float)) for value in allowed):
            selected = selected[selected[feature].between(allowed[0], allowed[1])]
        else:
            values = allowed if isinstance(allowed, list) else [allowed]
            selected = selected[selected[feature].isin(values)]
    return selected


def combine_restrictions(candidates: pd.DataFrame, active: dict[str, Any], temporary: dict[str, Any]) -> dict[str, Any]:
    combined = dict(active)
    for feature, restriction in temporary.items():
        if feature not in combined:
            combined[feature] = restriction
            continue
        allowed = restrict_candidates(candidates[[feature]], {feature: combined[feature]})
        allowed = restrict_candidates(allowed, {feature: restriction})[feature].tolist()
        if not allowed:
            combined[feature] = []
        elif pd.api.types.is_numeric_dtype(candidates[feature]) and len(allowed) < candidates[feature].nunique(dropna=False):
            combined[feature] = [min(allowed), max(allowed)]
        else:
            combined[feature] = allowed
    return combined




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
        historical = [
            Trial(
                trial_id=f"historical-{index}",
                candidate_id=candidate_id({feature: row[feature] for feature in features}),
                query_index=None,
                config={feature: row[feature] for feature in features},
                status="observed",
                source="historical",
                metrics={target: float(row[target])},
            )
            for index, row in enumerate(train.to_dict("records"))
        ]
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
            trials=historical,
        )
        study.objectives = {target: direction}
        study.original_domain = categories
        study.append_event("campaign_created", candidates=len(candidates), initial=len(train))
        study.save(state)
        emit(command, {"features": features, "target": target, "direction": direction, "initial": len(train), "candidates": len(candidates), "budget": budget, "acqf": study.acqf}, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc

@app.command()
def candidates(
    state: Path = typer.Option(...),
    filters: str | None = typer.Option(None),
    cursor: int = typer.Option(0, min=0),
    limit: int = typer.Option(20, min=1, max=100),
) -> None:
    command = "candidates"
    try:
        study = load_state(state)
        candidates = load_candidates(study)
        frame = candidates
        restrictions = parse_json_object(filters, "filters") if filters else {}
        for feature, allowed in restrictions.items():
            if feature not in study.features:
                raise ValueError(f"unknown filter feature: {feature}")
            values = allowed if isinstance(allowed, list) else [allowed]
            if not values:
                raise ValueError(f"filter values must not be empty: {feature}")
            legal = candidates[feature].drop_duplicates().tolist()
            if any(value not in legal for value in values):
                raise ValueError(f"illegal filter value for {feature}")
            frame = frame[frame[feature].isin(values)]
        total = len(frame)
        page = frame.iloc[cursor:cursor + limit]
        rows = [
            {
                "pool_index": int(index),
                "candidate_id": candidate_id(config_at(candidates, int(index), study.features), int(index)),
                "config": config_at(candidates, int(index), study.features),
            }
            for index in page.index
        ]
        next_cursor = cursor + len(rows)
        emit(command, {
            "total_matching": total,
            "cursor": cursor,
            "next_cursor": next_cursor if next_cursor < total else None,
            "candidates": rows,
        }, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def suggest(
    state: Path = typer.Option(...),
    q: int = typer.Option(1, min=1),
    acqf: str | None = typer.Option(None),
    beta: float | None = typer.Option(None),
    bounds: str | None = typer.Option(None),
    around: bool = typer.Option(False),
    radius: float = typer.Option(0.1),
) -> None:
    command = "suggest"
    try:
        study = load_state(state)
        candidates = load_candidates(study)
        restrictions = combine_restrictions(candidates, study.active_bounds, parse_json_object(bounds, "bounds") if bounds else {})
        if around:
            if not 0 < radius <= 1:
                raise ValueError("radius must be in (0, 1]")
            incumbent_rows = [row for row in observed_records(study) if is_feasible(row, study.constraints)]
            if not incumbent_rows:
                raise ValueError("around requires an observed incumbent")
            objective, direction = next(iter(study.objectives.items()))
            best = (max if direction == "maximize" else min)(incumbent_rows, key=lambda row: float(row[objective]))
            local = {}
            for feature in study.features:
                domain = study.original_domain[feature]
                if domain and all(isinstance(value, (int, float)) for value in domain):
                    width = max(domain) - min(domain)
                    local[feature] = [max(min(domain), best[feature] - radius * width), min(max(domain), best[feature] + radius * width)]
                else:
                    local[feature] = [best[feature]]
            restrictions = combine_restrictions(candidates, restrictions, local)
        candidates = restrict_candidates(candidates, restrictions)
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
            order = diverse_candidate_positions(scores, x, q)
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
        if len(study.observed) + len(study.pending) >= study.budget:
            raise ValueError("evaluation budget exhausted")
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

def revise(study: Study, state: Path, field: str, value: Any, rationale: str) -> None:
    previous = getattr(study, field)
    setattr(study, field, value)
    if field == "objectives":
        study.target, study.direction = next(iter(value.items()))
    study.configuration_revision += 1
    study.append_event("configuration_revised", field=field, previous=previous, current=value, rationale=rationale)
    study.save(state)


@app.command("set-bounds")
def set_bounds(state: Path = typer.Option(...), bounds: str = typer.Option(...), rationale: str = typer.Option(...)) -> None:
    command = "set-bounds"
    try:
        study = load_state(state)
        parsed = parse_json_object(bounds, "bounds")
        for feature, values in parsed.items():
            if feature not in study.features:
                raise ValueError(f"unknown bound feature: {feature}")
            allowed = study.original_domain[feature]
            if isinstance(values, list) and len(values) == 2 and all(isinstance(value, (int, float)) for value in values) and all(isinstance(value, (int, float)) for value in allowed):
                if values[0] > values[1] or values[0] < min(allowed) or values[1] > max(allowed):
                    raise ValueError(f"bounds outside original domain: {feature}")
            elif not set(values if isinstance(values, list) else [values]) <= set(allowed):
                raise ValueError(f"bounds outside original domain: {feature}")
        revise(study, state, "active_bounds", parsed, rationale)
        emit(command, parsed, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command("set-objectives")
def set_objectives(state: Path = typer.Option(...), objectives: str = typer.Option(...), rationale: str = typer.Option(...)) -> None:
    command = "set-objectives"
    try:
        study = load_state(state)
        parsed = parse_json_object(objectives, "objectives")
        if len(parsed) != 1:
            raise ValueError("multi-objective acquisition is not yet supported")
        if any(direction not in {"maximize", "minimize"} for direction in parsed.values()):
            raise ValueError("objectives require maximize/minimize directions")
        revise(study, state, "objectives", parsed, rationale)
        emit(command, parsed, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command("set-constraints")
def set_constraints(state: Path = typer.Option(...), constraints: str = typer.Option(...), rationale: str = typer.Option(...)) -> None:
    command = "set-constraints"
    try:
        study = load_state(state)
        parsed = parse_json_list(constraints, "constraints")
        if parsed:
            raise ValueError("constraint-aware acquisition is not yet supported")
        revise(study, state, "constraints", parsed, rationale)
        emit(command, parsed, study=study)
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
        selected_beta = beta if beta is not None else study.beta
        values = acquisition_values(fitted, x, name, selected_beta)
        mean, variance = posterior_rows(fitted, x, study.direction)
        emit(command, [{
            "candidate_id": candidate_id(config, index),
            "pool_index": index,
            "config": config,
            "posterior_mean": float(mu),
            "posterior_variance": float(var),
            "acquisition_value": float(value),
            "acqf": name,
            name: float(value),
        } for index, config, mu, var, value in zip(indices, parsed, mean, variance, values, strict=True)], study=study)
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
        records = [row for row in observed_records(study) if is_feasible(row, study.constraints)]
        if not records:
            raise ValueError("need a feasible observed trial")
        objective, direction = next(iter(study.objectives.items()))
        key = lambda row: float(row[objective])
        best = (max if direction == "maximize" else min)(records, key=key)
        emit(command, {"config": {feature: best[feature] for feature in study.features}, "metrics": {metric: float(best[metric]) for metric in {*study.objectives, *(constraint["metric"] for constraint in study.constraints)}}}, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def pareto(state: Path = typer.Option(...)) -> None:
    command = "pareto"
    try:
        study = load_state(state)
        records = [row for row in observed_records(study) if is_feasible(row, study.constraints)]
        front = [row for row in records if not any(dominates(other, row, study.objectives) for other in records if other is not row)]
        emit(command, [{"config": {feature: row[feature] for feature in study.features}, "metrics": {metric: float(row[metric]) for metric in study.objectives}} for row in front], study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def trials(state: Path = typer.Option(...)) -> None:
    command = "trials"
    try:
        study = load_state(state)
        emit(command, [vars(trial) for trial in study.all_observed + study.pending], study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


@app.command()
def status(state: Path = typer.Option(...)) -> None:
    command = "status"
    try:
        study = load_state(state)
        candidates = load_candidates(study)
        emit(command, {"campaign_id": study.campaign_id, "target": study.target, "direction": study.direction, "acqf": study.acqf, "beta": study.beta, "budget": study.budget, "initial": len(study.historical), "historical_observed": len(study.historical), "observed": len(study.observed), "pending": [trial.trial_id for trial in study.pending], "budget_remaining": study.budget - len(study.observed), "remaining": len(candidates) - len(study.submitted)}, study=study)
    except Exception as exc:
        emit(command, error=str(exc))
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
