from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

SEEDS = list(range(100, 1001, 100))


def validate_trajectory_rows(trajectory: list[dict[str, Any]], candidates: pd.DataFrame) -> str | None:
    """Validate shared trajectory row invariants: step ordering, query_index
    uniqueness/range, and exact condition match against the candidate pool.

    Returns an error message or None when the rows are valid. Shared by
    evaluation.validate_trajectory and competition artifact validation.
    """
    seen: set[int] = set()
    for expected_step, row in enumerate(trajectory, 1):
        if not isinstance(row, dict) or row.get("step") != expected_step:
            return f"invalid step at {expected_step}"
        index = row.get("query_index")
        if isinstance(index, bool) or not isinstance(index, int) or index in seen or index < 0 or index >= len(candidates):
            return f"invalid query_index: {index}"
        if row.get("condition") != candidates.loc[index].to_dict():
            return f"condition mismatch: {index}"
        seen.add(index)
    return None


def validate_trajectory(path: Path | str, dataset_root: Path | str, budget: int = 40) -> dict[str, Any]:
    path = Path(path)
    dataset_root = Path(dataset_root)
    payload = torch.load(path, weights_only=False)
    trajectory = payload["trajectory"] if isinstance(payload, dict) else payload
    stop = payload.get("stop") if isinstance(payload, dict) else None
    if len(trajectory) != budget:
        valid_stop = len(trajectory) < budget and stop and stop.get("status") == "stopped" and stop.get("verified") is True and stop.get("observed") == len(trajectory) and stop.get("budget") == budget and stop.get("budget_remaining") == budget - len(trajectory)
        if not valid_stop or not trajectory:
            raise ValueError(f"expected {budget} steps or a verified non-empty early stop, got {len(trajectory)}")
    candidates = pd.read_csv(dataset_root / "test_features.csv")
    modern = isinstance(payload, dict) and "target" in payload
    target_key = "observed_value" if modern else "observed_yield"
    row_error = validate_trajectory_rows(trajectory, candidates)
    if row_error:
        raise ValueError(row_error)
    values = [float(row[target_key]) for row in trajectory]
    direction = payload.get("direction", "maximize") if modern else "maximize"
    if direction not in {"maximize", "minimize"}:
        raise ValueError(f"invalid direction: {direction}")
    target = payload.get("target") if modern else None
    labels = pd.read_csv(dataset_root / "test.csv")
    if modern and target not in labels.columns:
        raise ValueError(f"target not found in test.csv: {target}")
    label_values = labels[target] if modern else labels.iloc[:, -1]
    if direction == "maximize":
        best = np.maximum.accumulate(values)
        global_best = float(label_values.max())
        threshold = global_best - 0.05 * abs(global_best)
        reached = lambda value: value >= threshold
    else:
        best = np.minimum.accumulate(values)
        global_best = float(label_values.min())
        threshold = global_best + 0.05 * abs(global_best)
        reached = lambda value: value <= threshold
    t95 = next((i for i, value in enumerate(best, 1) if reached(value)), budget + 1)
    return {
        "seed": payload.get("seed"),
        "initial_round_found_best": float(best[0]),
        "best_found": float(best[-1]),
        "round_to_95_global_best": t95,
        "auc_best_so_far": float(best.mean()),
        "simple_regret": abs(float(best[-1]) - global_best),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    keys = ["initial_round_found_best", "best_found", "round_to_95_global_best", "auc_best_so_far", "simple_regret"]
    summary = {}
    for key in keys:
        if not all(key in result for result in results):
            continue
        values = np.array([result[key] for result in results], dtype=float)
        summary[key] = {"median": float(np.median(values)), "q25": float(np.quantile(values, 0.25)), "q75": float(np.quantile(values, 0.75))}
    return summary
