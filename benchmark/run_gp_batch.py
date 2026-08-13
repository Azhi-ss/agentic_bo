from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Iterable

import pandas as pd
import torch

SEEDS = tuple(range(100, 2001, 100))
BUDGET = 40
DATASET_ROOT = Path("datasets/chemical_reactions/buchwald_sub4")
OUTPUT_ROOT = Path("runs/buchwald_sub4/gp-budget40-v2")


def validate_seed(output: Path, dataset_root: Path, seed: int, budget: int = BUDGET) -> None:
    trajectory_path = output / "trajectory.json"
    artifact_path = output / f"seed_{seed}.pt"
    try:
        trajectory = json.loads(trajectory_path.read_text())
        payload = torch.load(artifact_path, weights_only=False)
    except (FileNotFoundError, json.JSONDecodeError, OSError, RuntimeError, EOFError) as error:
        raise ValueError(f"seed {seed} artifact cannot be loaded: {error}") from error

    if not isinstance(trajectory, list) or len(trajectory) != budget:
        raise ValueError(f"seed {seed} trajectory has {len(trajectory) if isinstance(trajectory, list) else 0} steps, expected {budget}")
    if not isinstance(payload, dict) or payload != {
        "method": "pure_gp_noisy_logei",
        "seed": seed,
        "dataset": dataset_root.name,
        "budget": budget,
        "trajectory": trajectory,
    }:
        raise ValueError(f"seed {seed} PT/JSON or artifact metadata mismatch")

    candidates = pd.read_csv(dataset_root / "test_features.csv")
    labels = pd.read_csv(dataset_root / "test.csv")
    target = pd.read_csv(dataset_root / "train.csv").columns[-1]
    features = candidates.columns.tolist()
    seen: set[int] = set()
    best = -math.inf
    for step, row in enumerate(trajectory, 1):
        if not isinstance(row, dict) or row.get("step") != step:
            raise ValueError(f"seed {seed} step {step} is malformed")
        index = row.get("pool_index")
        if isinstance(index, bool) or not isinstance(index, int) or index in seen or not 0 <= index < len(candidates):
            raise ValueError(f"seed {seed} step {step} has invalid or duplicate pool_index")
        config = candidates.loc[index, features].to_dict()
        if row.get("config") != config or labels.loc[index, features].to_dict() != config:
            raise ValueError(f"seed {seed} step {step} config does not align with dataset")
        value = row.get("observed_yield")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) != float(labels.loc[index, target]):
            raise ValueError(f"seed {seed} step {step} observed_yield does not align with label")
        best = max(best, float(value))
        if row.get("best_so_far") != best:
            raise ValueError(f"seed {seed} step {step} best_so_far is invalid")
        seen.add(index)


def _partial_path(output: Path) -> Path:
    number = 1
    while (candidate := output.with_name(f"{output.name}.partial-{number}")).exists():
        number += 1
    return candidate


def run_batch(
    dataset_root: Path,
    output_root: Path,
    *,
    seeds: Iterable[int] = SEEDS,
    budget: int = BUDGET,
    resume: bool = False,
) -> dict[str, list[int] | list[str]]:
    dataset_root = dataset_root.resolve()
    output_root = output_root.resolve()
    seeds = tuple(seeds)
    skipped: list[int] = []
    rerun: list[tuple[int, Path | None]] = []

    for seed in seeds:
        output = output_root / f"seed-{seed}-gp"
        if not output.exists():
            rerun.append((seed, None))
            continue
        if not resume:
            raise FileExistsError(f"output already exists: {output}; use --resume")
        try:
            validate_seed(output, dataset_root, seed, budget)
        except ValueError:
            rerun.append((seed, _partial_path(output)))
        else:
            skipped.append(seed)

    output_root.mkdir(parents=True, exist_ok=True)
    archived: list[str] = []
    completed: list[int] = []
    runner = Path(__file__).with_name("run_gp.py")
    for seed, archive in rerun:
        output = output_root / f"seed-{seed}-gp"
        if archive is not None:
            output.rename(archive)
            archived.append(str(archive))
        subprocess.run([
            sys.executable,
            str(runner),
            "--dataset-root", str(dataset_root),
            "--output", str(output),
            "--seed", str(seed),
            "--budget", str(budget),
        ], check=True)
        validate_seed(output, dataset_root, seed, budget)
        completed.append(seed)

    return {"completed": completed, "skipped": skipped, "archived": archived}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    report = run_batch(args.dataset_root, args.output_root, resume=args.resume)
    print(json.dumps({"ok": True, **report}))


if __name__ == "__main__":
    main()
