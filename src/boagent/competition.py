from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

import pandas as pd
import torch

from .evaluation import validate_trajectory_rows
from .experiment_config import LoadedExperiment
from .state import Study

COMPETITION_SEEDS = tuple(range(100, 2001, 100))
COMPETITION_BUDGET = 40


@dataclass(frozen=True)
class SeedResult:
    seed: int
    state: Literal["complete", "incomplete", "invalid"]
    detail: str
    artifact: str | None = None
    steps: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "state": self.state,
            "detail": self.detail,
            "artifact": self.artifact,
            "steps": self.steps,
        }


def _trajectory(study: Study, candidates: pd.DataFrame) -> tuple[list[dict[str, object]] | None, str]:
    if study.budget != COMPETITION_BUDGET:
        return None, f"budget is {study.budget}, expected {COMPETITION_BUDGET}"
    if study.pending:
        return None, "campaign has pending trials"
    observed = study.observed
    if len(observed) < COMPETITION_BUDGET:
        return None, f"campaign has {len(observed)} observed steps, expected {COMPETITION_BUDGET}"
    if len(observed) != COMPETITION_BUDGET:
        return None, f"campaign has {len(observed)} observed steps, expected exactly {COMPETITION_BUDGET}"

    rows: list[dict[str, object]] = []
    seen: set[int] = set()
    for step, trial in enumerate(observed, start=1):
        if trial.query_index is None or isinstance(trial.query_index, bool):
            return None, f"step {step} has invalid query_index"
        query_index = int(trial.query_index)
        if query_index in seen:
            return None, f"step {step} repeats query_index {query_index}"
        if query_index < 0 or query_index >= len(candidates):
            return None, f"step {step} query_index {query_index} is out of range"
        expected = candidates.iloc[query_index].to_dict()
        if trial.config != expected:
            return None, f"step {step} condition does not match test_features row {query_index}"
        if not trial.receipt_id or not trial.candidate_id or not trial.trial_id:
            return None, f"step {step} is missing provenance"
        try:
            observed_value = float((trial.metrics or {})[study.target])
        except (KeyError, TypeError, ValueError):
            return None, f"step {step} has invalid observed value"
        seen.add(query_index)
        rows.append({
            "step": step,
            "query_index": query_index,
            "condition": trial.config,
            "observed_value": observed_value,
            "candidate_id": trial.candidate_id,
            "trial_id": trial.trial_id,
            "receipt_id": trial.receipt_id,
        })
    return rows, "valid"


def validate_artifact(path: Path | str, dataset_root: Path | str, seed: int) -> SeedResult:
    path = Path(path)
    dataset_root = Path(dataset_root)
    try:
        payload = torch.load(path, weights_only=False)
    except (OSError, RuntimeError, EOFError) as error:
        return SeedResult(seed, "invalid", f"cannot load artifact: {error}", str(path))
    if not isinstance(payload, dict):
        return SeedResult(seed, "invalid", "artifact root is not a dict", str(path))
    required = {"seed", "dataset", "target", "direction", "trajectory"}
    if not required.issubset(payload):
        return SeedResult(seed, "invalid", "artifact is missing modern schema fields", str(path))
    if payload["seed"] != seed or payload["dataset"] != dataset_root.name:
        return SeedResult(seed, "invalid", "artifact seed or dataset does not match", str(path))
    trajectory = payload["trajectory"]
    if not isinstance(trajectory, list) or len(trajectory) != COMPETITION_BUDGET:
        steps = len(trajectory) if isinstance(trajectory, list) else 0
        return SeedResult(seed, "invalid", f"artifact has {steps} steps, expected {COMPETITION_BUDGET}", str(path), steps)
    candidates = pd.read_csv(dataset_root / "test_features.csv")
    row_error = validate_trajectory_rows(trajectory, candidates)
    if row_error:
        return SeedResult(seed, "invalid", row_error, str(path), len(trajectory))
    for step, row in enumerate(trajectory, start=1):
        observed_value = row.get("observed_value")
        if isinstance(observed_value, bool) or not isinstance(observed_value, (int, float)) or not all(row.get(key) for key in ("candidate_id", "trial_id", "receipt_id")):
            return SeedResult(seed, "invalid", f"artifact step {step} is missing or has invalid modern fields", str(path), len(trajectory))
    return SeedResult(seed, "complete", "valid artifact", str(path), len(trajectory))


def package_competition(loaded: LoadedExperiment, destination: Path, seeds: tuple[int, ...]) -> dict[str, object]:
    configured = tuple(loaded.config.experiment.seeds)
    if configured != COMPETITION_SEEDS or loaded.config.experiment.budget != COMPETITION_BUDGET:
        raise ValueError("competition config must declare seeds 100..2000 and budget 40")
    if any(seed not in COMPETITION_SEEDS for seed in seeds) or len(seeds) != len(set(seeds)):
        raise ValueError("requested seeds must be unique competition seeds")

    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    expected_names = {f"seed_{seed}.pt" for seed in seeds}
    actual_names = {path.name for path in destination.glob("*.pt")}
    results: list[SeedResult] = []
    candidates = pd.read_csv(loaded.dataset_path / "test_features.csv")

    for seed in seeds:
        artifact = destination / f"seed_{seed}.pt"
        campaign = loaded.output_path / "autonomous_agent" / f"seed-{seed}"
        state_path = campaign / "frame" / "state.json"
        if not state_path.is_file():
            results.append(SeedResult(seed, "incomplete", "campaign Frame is missing"))
            continue
        try:
            study = Study.load(state_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            results.append(SeedResult(seed, "invalid", f"cannot load campaign Frame: {error}"))
            continue
        if study.seed != seed or Path(study.public_root).resolve() != loaded.dataset_path:
            results.append(SeedResult(seed, "invalid", "campaign seed or dataset does not match config"))
            continue
        trajectory, detail = _trajectory(study, candidates)
        if trajectory is None:
            state = "incomplete" if study.budget == COMPETITION_BUDGET and (study.pending or len(study.observed) < COMPETITION_BUDGET) else "invalid"
            results.append(SeedResult(seed, state, detail, steps=len(study.observed)))
            continue
        payload = {
            "seed": seed,
            "dataset": loaded.dataset_path.name,
            "target": study.target,
            "direction": study.direction,
            "trajectory": trajectory,
        }
        torch.save(payload, artifact)
        results.append(validate_artifact(artifact, loaded.dataset_path, seed))

    extras = sorted(actual_names - expected_names)
    missing = sorted(expected_names - {Path(result.artifact).name for result in results if result.state == "complete" and result.artifact})
    manifest_valid = not extras and not missing
    return {
        "ok": manifest_valid and all(result.state == "complete" for result in results),
        "dataset": loaded.dataset_path.name,
        "mode": "full" if seeds == COMPETITION_SEEDS else "subset",
        "destination": str(destination),
        "manifest": {"valid": manifest_valid, "missing": missing, "extra": extras},
        "seeds": [result.as_dict() for result in results],
    }
