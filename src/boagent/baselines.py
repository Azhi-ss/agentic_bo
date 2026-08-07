from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def random_trajectory(dataset_root: Path, seed: int, budget: int) -> list[dict[str, float | int]]:
    private = pd.read_csv(dataset_root / "test.csv")
    rng = np.random.default_rng(seed)
    indices = rng.choice(len(private), size=budget, replace=False)
    target = private.columns[-1]
    return [{"step": step, "query_index": int(index), "value": float(private.loc[index, target])} for step, index in enumerate(indices, 1)]
