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
from dotenv import load_dotenv
from .competition import COMPETITION_SEEDS, package_competition
from .experiment_config import LoadedExperiment, load_experiment_config

from .state import Study

app = typer.Typer(add_completion=False, no_args_is_help=True)

def project_env() -> dict[str, str]:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env", override=False)
    env = os.environ.copy()
    project_scripts = project_root / ".venv" / "bin"
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


def initialize_campaign(
    dataset_root: Path,
    output: Path,
    seed: int = 100,
    budget: int = 40,
    target: str = "Yield",
    direction: str = "maximize",
    provenance: dict[str, object] | None = None,
    initial_acquisition: dict[str, object] | None = None,
) -> dict[str, str]:
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
        **(provenance or {}),
        **({"initial_runtime": initial_acquisition} if initial_acquisition else {}),
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
    if provenance or initial_acquisition:
        study_path = output / "frame" / "state.json"
        study = Study.load(study_path)
        study.declared_config_hash = str((provenance or {}).get("normalized_config_hash")) if (provenance or {}).get("normalized_config_hash") else None
        study.source_config_hash = str((provenance or {}).get("source_config_hash")) if (provenance or {}).get("source_config_hash") else None
        study.source_config = str((provenance or {}).get("source_config")) if (provenance or {}).get("source_config") else None
        study.experiment_name = str((provenance or {}).get("experiment_name")) if (provenance or {}).get("experiment_name") else None
        study.experiment_policy = str((provenance or {}).get("experiment_policy")) if (provenance or {}).get("experiment_policy") else None
        if initial_acquisition:
            study.acqf = str(initial_acquisition["acqf"])
            study.beta = float(initial_acquisition["beta"])
            study.initial_acquisition = {**initial_acquisition, "origin": "experiment_config"}
        study.save(study_path)
    result = {"ok": True, "campaign": str(output), "campaign_id": campaign_id}
    return result


@app.command()
def init(
    dataset_root: Path = typer.Option(...),
    output: Path = typer.Option(...),
    seed: int = typer.Option(100),
    budget: int = typer.Option(40, min=1),
    target: str = typer.Option("Yield"),
    direction: str = typer.Option("maximize"),
) -> None:
    typer.echo(json.dumps(initialize_campaign(dataset_root, output, seed, budget, target, direction), ensure_ascii=False))

def run_campaign(campaign: Path, model: str = "gpt-5.6-sol", thinking: str = "xhigh", policy: str = "default") -> None:
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
def run(
    campaign: Path = typer.Option(...),
    model: str = typer.Option("gpt-5.6-sol"),
    thinking: str = typer.Option("xhigh"),
    policy: str = typer.Option("default", help="Campaign profile: default or autonomous_agent."),
) -> None:
    run_campaign(campaign, model, thinking, policy)


def validate_experiment_campaign(campaign: Path, loaded: LoadedExperiment, item: dict[str, object]) -> None:
    required = (campaign / "manifest.json", campaign / "frame" / "state.json", campaign / ".receipt-key")
    missing = next((path for path in required if not path.is_file()), None)
    if missing:
        raise typer.BadParameter(f"existing campaign is missing required file: {missing.relative_to(campaign)}")
    try:
        manifest = json.loads(required[0].read_text())
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")
        study = Study.load(required[1])
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        raise typer.BadParameter(f"existing campaign metadata is malformed: {exc}") from exc

    acquisition = item["initial_acquisition"]
    provenance = {
        "experiment_name": item["experiment_name"],
        "experiment_policy": item["policy"],
        "source_config": loaded.config_path.name,
        "source_config_hash": loaded.source_config_hash,
        "normalized_config_hash": loaded.normalized_config_hash,
    }
    manifest_expected = {
        "dataset_root": str(loaded.dataset_path),
        "seed": item["seed"],
        "budget": item["budget"],
        "target": item["target"],
        "direction": item["direction"],
    }
    frame_expected = {
        "public_root": str(loaded.dataset_path),
        "seed": item["seed"],
        "budget": item["budget"],
        "target": item["target"],
        "direction": item["direction"],
    }
    if manifest.get("campaign_id") != study.campaign_id:
        raise typer.BadParameter("existing campaign mismatch: campaign_id")
    for field, expected in manifest_expected.items():
        if manifest.get(field) != expected:
            raise typer.BadParameter(f"existing campaign manifest mismatch: {field}")
    for field, expected in frame_expected.items():
        if getattr(study, field) != expected:
            raise typer.BadParameter(f"existing campaign Frame mismatch: {field}")

    manifest_provenance = {**provenance, "initial_runtime": {"acqf": acquisition["name"], "beta": acquisition["beta"]}}
    frame_provenance = {
        "experiment_name": provenance["experiment_name"],
        "experiment_policy": provenance["experiment_policy"],
        "source_config": provenance["source_config"],
        "source_config_hash": provenance["source_config_hash"],
        "declared_config_hash": provenance["normalized_config_hash"],
        "initial_acquisition": {"acqf": acquisition["name"], "beta": acquisition["beta"], "origin": "experiment_config"},
    }
    declared = [
        *(manifest.get(field) for field in provenance),
        *(getattr(study, field) for field in ("experiment_name", "experiment_policy", "source_config", "source_config_hash", "declared_config_hash")),
    ]
    if all(value is None for value in declared):
        if manifest.get("initial_runtime") is not None or study.initial_acquisition is not None or study.configuration_revision != 1 or study.acqf != acquisition["name"] or study.beta != acquisition["beta"]:
            raise typer.BadParameter("existing legacy campaign mismatch: initial acquisition")
        audit_path = campaign / "campaign-run-config.json"
        try:
            revisions = json.loads(audit_path.read_text())["revisions"]
            latest = revisions[-1]
            if not isinstance(latest, dict):
                raise TypeError("latest revision must be an object")
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError, IndexError) as exc:
            raise typer.BadParameter("existing legacy campaign run audit is missing or malformed") from exc
        audit_expected = {
            "campaign_id": study.campaign_id,
            "provider": item["provider"],
            "model": item["model"],
            "thinking": item["thinking"],
            "policy": item["policy"],
            "provider_generation_seed": item["provider_generation_seed"],
            "declared_config_hash": None,
            "experiment_name": None,
            "experiment_policy": item["policy"],
        }
        for field, expected in audit_expected.items():
            if latest.get(field) != expected:
                raise typer.BadParameter(f"existing legacy campaign run audit mismatch: {field}")
        return

    for field, expected in manifest_provenance.items():
        if manifest.get(field) != expected:
            raise typer.BadParameter(f"existing campaign manifest mismatch: {field}")
    for field, expected in frame_provenance.items():
        if getattr(study, field) != expected:
            raise typer.BadParameter(f"existing campaign Frame mismatch: {field}")


@app.command()
def experiment(
    config: Path = typer.Option(...),
    plan: bool = typer.Option(False, "--plan"),
    resume: bool = typer.Option(False, "--resume"),
) -> None:
    try:
        loaded = load_experiment_config(config, check_output_collisions=not (plan or resume))
    except (ValueError, FileExistsError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    public_plan = loaded.public_plan()
    if plan:
        typer.echo(json.dumps(public_plan, ensure_ascii=False, sort_keys=True))
        return
    for item in loaded.runs():
        campaign = Path(str(item["output"]))
        provenance = {
            "experiment_name": item["experiment_name"],
            "experiment_policy": item["policy"],
            "source_config": loaded.config_path.name,
            "source_config_hash": loaded.source_config_hash,
            "normalized_config_hash": loaded.normalized_config_hash,
        }
        acquisition = item["initial_acquisition"]
        if campaign.exists():
            if not resume:
                raise typer.BadParameter(f"output already exists: {campaign}")
            validate_experiment_campaign(campaign, loaded, item)
        else:
            initialize_campaign(
                loaded.dataset_path,
                campaign,
                int(item["seed"]),
                int(item["budget"]),
                str(item["target"]),
                str(item["direction"]),
                provenance,
                {"acqf": acquisition["name"], "beta": acquisition["beta"]},
            )
        run_campaign(campaign, model=str(item["model"]), thinking=str(item["thinking"]), policy=str(item["policy"]))
    typer.echo(json.dumps({"ok": True, "campaigns": len(public_plan["runs"]), "normalized_config_hash": loaded.normalized_config_hash}, ensure_ascii=False))



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


@app.command("package-competition")
def package_competition_command(
    config: Path = typer.Option(...),
    destination: Path = typer.Option(...),
    seed: list[int] | None = typer.Option(None, "--seed"),
) -> None:
    try:
        loaded = load_experiment_config(config, check_output_collisions=False)
        requested = tuple(seed) if seed else COMPETITION_SEEDS
        report = package_competition(loaded, destination, requested)
    except (ValueError, FileExistsError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if not report["ok"]:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
