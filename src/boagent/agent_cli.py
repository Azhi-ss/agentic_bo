from __future__ import annotations

import hashlib
import json
import os
import secrets
import fcntl
import subprocess
import sys
import uuid
from pathlib import Path

import torch
import pandas as pd
import typer

from .state import Study

app = typer.Typer(add_completion=False, no_args_is_help=True)

def project_env() -> dict[str, str]:
    env = os.environ.copy()
    project_scripts = Path(__file__).resolve().parents[2] / ".venv" / "bin"
    candidates = [Path(sys.executable).resolve().parent]
    if project_scripts.is_dir():
        candidates.append(project_scripts)
    env["PATH"] = os.pathsep.join([*(str(path) for path in dict.fromkeys(candidates)), env.get("PATH", "")])
    return env

def summarize_dataset(train: pd.DataFrame, candidates: pd.DataFrame, target: str) -> dict[str, object]:
    features = candidates.columns.tolist()
    return {
        "rows": {"initial_observations": len(train), "candidate_pool": len(candidates)},
        "features": {
            feature: {
                "kind": "numeric_discrete" if pd.api.types.is_numeric_dtype(candidates[feature]) else "categorical",
                "role": "context" if candidates[feature].nunique(dropna=False) == 1 and train[feature].nunique(dropna=False) > 1 else "decision",
                "candidate_values": int(candidates[feature].nunique(dropna=False)),
            }
            for feature in features
        },
        "target": {
            "name": target,
            "initial_observed": {
                "minimum": float(train[target].min()),
                "maximum": float(train[target].max()),
                "mean": float(train[target].mean()),
            },
        },
    }


@app.command()
def init(
    dataset_root: Path = typer.Option(...),
    output: Path = typer.Option(...),
    seed: int = typer.Option(100),
    budget: int = typer.Option(40, min=1),
    target: str = typer.Option("Yield"),
    direction: str = typer.Option("maximize"),
) -> None:
    dataset_root = dataset_root.resolve()
    output = output.resolve()
    candidates = pd.read_csv(dataset_root / "test_features.csv")
    train_path = dataset_root / "train.csv"
    train = pd.read_csv(train_path) if train_path.exists() else None
    if train is not None and (list(train.columns[:-1]) != candidates.columns.tolist() or train.columns[-1] != target):
        raise typer.BadParameter("train/test_features schema mismatch")
    output.mkdir(parents=True, exist_ok=False)
    campaign_id = str(uuid.uuid4())
    prior_path = dataset_root / "PRIOR.md"
    prior_text = prior_path.read_text(encoding="utf-8").strip() if prior_path.exists() else ""
    forbidden_prior_terms = ("test.csv", "global_best", "hidden rank", "hidden outcome")
    manifest = {
        "campaign_id": campaign_id,
        "dataset_root": str(dataset_root),
        "seed": seed,
        "budget": budget,
        "target": target,
        "direction": direction,
        "prior_hash": hashlib.sha256(prior_text.encode()).hexdigest(),
        "prior_source": "PRIOR.md",
        "prior_scan": "label_free" if not any(term in prior_text.lower() for term in forbidden_prior_terms) else "failed",
        "prior_provenance": "mechanism_or_pre_experiment_source",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    options = json.loads((dataset_root / "options.json").read_text())
    public_options = {feature: options[feature] for feature in candidates.columns}
    summary_note = ""
    if train is not None:
        summary = summarize_dataset(train, candidates, target)
        summary_json = json.dumps(summary, ensure_ascii=False, indent=2)
        (output / "dataset-summary.json").write_text(summary_json)
        summary_note = f"\n\n## Dataset understanding\n\n```json\n{summary_json}\n```"
    domain_context = (
        "Use domain priors to compare exact public Candidates. You may inspect and reconfigure lenz through the typed tools exposed by the Campaign Supervisor. "
        "Only identical candidate_id values are Replicates; Experiment Receipts are the sole source of new Outcomes."
    )
    if prior_text:
        domain_context += "\n\n" + prior_text
    (output / "TASK.md").write_text(
        "# Optimization Task\n\n"
        f"Optimize `{target}` with direction `{direction}` using {budget} sequential black-box evaluations. "
        "The domain is a finite public candidate pool. Hidden outcomes are never available before commitment.\n\n"
        f"## Search variables\n\n```json\n{json.dumps(public_options, ensure_ascii=False, indent=2)}\n```\n\n"
        "## Domain context\n\n"
        f"{domain_context}"
        f"{summary_note}\n"
    )
    (output / "CAMPAIGN.md").write_text(
        f"# Campaign\n\n- Campaign ID: `{campaign_id}`\n- Seed: `{seed}`\n- Budget: `{budget}` sequential evaluations\n- Target: `{target}` ({direction})\n- Public inputs: the sanitized task description and Supervisor-supplied Frame outputs.\n- Hidden labels are available only through signed Experiment Receipts.\n"
    )
    (output / "frame").mkdir()
    command = [
        "lenz", "create", "--state", str(output / "frame" / "state.json"), "--dataset-root", str(dataset_root),
        "--target", target, "--direction", direction, "--seed", str(seed), "--budget", str(budget), "--campaign-id", campaign_id,
    ]
    subprocess.run(command, check=True, cwd=output, env=project_env())
    key_path = output / ".receipt-key"
    key_path.write_text(secrets.token_hex(32))
    key_path.chmod(0o600)
    typer.echo(json.dumps({"ok": True, "campaign": str(output), "campaign_id": campaign_id}, ensure_ascii=False))

@app.command()
def run(
    campaign: Path = typer.Option(...),
    model: str = typer.Option("gpt-5.6-sol"),
    thinking: str = typer.Option("xhigh"),
    policy: str = typer.Option("default", help="Campaign profile: default or autonomous_agent."),
) -> None:
    if policy not in {"default", "autonomous_agent"}:
        raise typer.BadParameter("policy must be one of: default, autonomous_agent")
    campaign = campaign.resolve()
    env = project_env()
    key_path = campaign / ".receipt-key"
    if not key_path.exists():
        raise typer.BadParameter("campaign receipt key is missing")
    env["BOAGENT_RECEIPT_KEY"] = key_path.read_text().strip()
    lock_path = campaign / ".run.lock"
    supervisor = Path(__file__).resolve().parents[2] / "supervisor"
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise typer.BadParameter("campaign is already running") from exc
        command = ["npm", "run", "run", "--", "--campaign", str(campaign), "--model", model, "--thinking", thinking]
        if policy != "default":
            command.extend(["--policy", policy])
        subprocess.run(command, cwd=supervisor, env=env, check=True)


@app.command()
def export(campaign: Path = typer.Option(...), output: Path = typer.Option(...)) -> None:
    campaign = campaign.resolve()
    study = Study.load(campaign / "frame" / "state.json")
    if study.pending:
        raise typer.BadParameter("campaign has pending trials")
    observed = len(study.observed)
    if observed == 0:
        raise typer.BadParameter("campaign has no observed trials")
    stop = None
    if observed < study.budget:
        status_path = campaign / "campaign-status.json"
        try:
            stop = json.loads(status_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise typer.BadParameter(f"campaign has {observed} observations, expected {study.budget}") from exc
        expected = {
            "status": "stopped",
            "campaign_id": study.campaign_id,
            "state_revision": study.state_revision,
            "observed": observed,
            "budget": study.budget,
            "budget_remaining": study.budget - observed,
            "verified": True,
        }
        conditions = {"target_reached", "observed_candidates_exhausted"}
        if any(stop.get(key) != value for key, value in expected.items()) or stop.get("condition") not in conditions or not str(stop.get("rationale", "")).strip():
            raise typer.BadParameter("campaign stop record does not match Frame")
    elif observed > study.budget:
        raise typer.BadParameter(f"campaign has {observed} observations, exceeds budget {study.budget}")
    trajectory = [
        {
            "step": index,
            "query_index": trial.query_index,
            "condition": trial.config,
            "observed_value": float((trial.metrics or {})[study.target]),
            "candidate_id": trial.candidate_id,
            "trial_id": trial.trial_id,
            "receipt_id": trial.receipt_id,
        }
        for index, trial in enumerate(study.observed, start=1)
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"seed": study.seed, "dataset": Path(study.public_root).name, "target": study.target, "direction": study.direction, "trajectory": trajectory}
    if stop is not None:
        payload["stop"] = stop
    torch.save(payload, output)
    typer.echo(json.dumps({"ok": True, "output": str(output), "evaluations": len(trajectory), "stop": stop}, ensure_ascii=False))


if __name__ == "__main__":
    app()
