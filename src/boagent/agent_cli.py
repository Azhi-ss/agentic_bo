from __future__ import annotations

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
    output.mkdir(parents=True, exist_ok=False)
    campaign_id = str(uuid.uuid4())
    manifest = {
        "campaign_id": campaign_id,
        "dataset_root": str(dataset_root),
        "seed": seed,
        "budget": budget,
        "target": target,
        "direction": direction,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    options = json.loads((dataset_root / "options.json").read_text())
    public_options = {feature: options[feature] for feature in pd.read_csv(dataset_root / "test_features.csv").columns}
    (output / "TASK.md").write_text(
        "# Optimization Task\n\n"
        f"Optimize `{target}` with direction `{direction}` using {budget} sequential black-box evaluations. "
        "The domain is a finite public candidate pool. Hidden outcomes are never available before commitment.\n\n"
        f"## Search variables\n\n```json\n{json.dumps(public_options, ensure_ascii=False, indent=2)}\n```\n\n"
        "## Domain context\n\n"
        "Use domain priors to compare exact public Candidates. You may inspect and reconfigure lenz through the typed tools exposed by the Campaign Supervisor. "
        "Only identical candidate_id values are Replicates; Experiment Receipts are the sole source of new Outcomes.\n"
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
) -> None:
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
        subprocess.run(["npm", "run", "run", "--", "--campaign", str(campaign), "--model", model, "--thinking", thinking], cwd=supervisor, env=env, check=True)


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
