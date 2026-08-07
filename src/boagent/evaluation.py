from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

SEEDS = list(range(100, 2001, 100))


def validate_trajectory(path: Path, dataset_root: Path, budget: int = 40) -> dict[str, Any]:
    payload = torch.load(path, weights_only=False)
    trajectory = payload["trajectory"] if isinstance(payload, dict) else payload
    stop = payload.get("stop") if isinstance(payload, dict) else None
    if len(trajectory) != budget:
        valid_stop = len(trajectory) < budget and stop and stop.get("status") == "stopped" and stop.get("verified") is True and stop.get("observed") == len(trajectory) and stop.get("budget") == budget and stop.get("budget_remaining") == budget - len(trajectory)
        if not valid_stop or not trajectory:
            raise ValueError(f"expected {budget} steps or a verified non-empty early stop, got {len(trajectory)}")
    candidates = pd.read_csv(dataset_root / "test_features.csv")
    seen: set[int] = set()
    modern = isinstance(payload, dict) and "target" in payload
    target_key = "observed_value" if modern else "observed_yield"
    values = []
    for expected_step, row in enumerate(trajectory, 1):
        index = int(row["query_index"])
        if row["step"] != expected_step:
            raise ValueError(f"invalid step at {expected_step}")
        if index in seen or index < 0 or index >= len(candidates):
            raise ValueError(f"invalid query_index: {index}")
        if row["condition"] != candidates.loc[index].to_dict():
            raise ValueError(f"condition mismatch: {index}")
        seen.add(index)
        values.append(float(row[target_key]))
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
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    keys = ["initial_round_found_best", "best_found", "round_to_95_global_best", "auc_best_so_far"]
    summary = {}
    for key in keys:
        values = np.array([result[key] for result in results], dtype=float)
        sem = values.std(ddof=1) / math.sqrt(len(values)) if len(values) > 1 else 0.0
        summary[key] = {"mean": float(values.mean()), "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0, "ci95": float(1.96 * sem)}
    return summary
