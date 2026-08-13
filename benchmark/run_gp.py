from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from boagent.backend import acquisition_values, encode_frame, fit_surrogate, posterior_rows
from boagent.state import Study, Trial, candidate_id, now


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--budget", type=int, default=40)
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    dataset_root = args.dataset_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    train = pd.read_csv(dataset_root / "train.csv")
    candidates = pd.read_csv(dataset_root / "test_features.csv")
    private = pd.read_csv(dataset_root / "test.csv")
    features = candidates.columns.tolist()
    target = train.columns[-1]
    study = Study(
        study_id=f"gp-seed-{args.seed}",
        campaign_id=f"gp-seed-{args.seed}",
        public_root=str(dataset_root),
        target=target,
        direction="maximize",
        seed=args.seed,
        budget=args.budget,
        features=features,
        categories={feature: pd.concat([train[feature], candidates[feature]], ignore_index=True).drop_duplicates().tolist() for feature in features},
        initial=train.to_dict("records"),
    )
    trajectory = []
    for step in range(1, args.budget + 1):
        available = np.array([index for index in candidates.index if index not in study.submitted], dtype=int)
        fitted = fit_surrogate(study, candidates)
        x = encode_frame(candidates.loc[available, features], study)
        scores = acquisition_values(fitted, x, study.acqf, study.beta)
        mean, variance = posterior_rows(fitted, x, study.direction)
        position = int(np.argmax(scores))
        index = int(available[position])
        config = candidates.loc[index, features].to_dict()
        value = float(private.loc[index, target])
        trial = Trial(
            trial_id=f"gp-{args.seed}-{step}",
            candidate_id=candidate_id(config, index),
            query_index=index,
            config=config,
            status="observed",
            metrics={target: value},
            submitted_at=now(),
            observed_at=now(),
        )
        study.trials.append(trial)
        trajectory.append({
            "step": step,
            "pool_index": index,
            "config": config,
            "predicted_mean": float(mean[position]),
            "posterior_variance": float(variance[position]),
            "acquisition_value": float(scores[position]),
            "observed_yield": value,
            "best_so_far": max(item["observed_yield"] for item in trajectory) if trajectory else value,
        })
        trajectory[-1]["best_so_far"] = max(item["observed_yield"] for item in trajectory)
        (output / "trajectory.json").write_text(json.dumps(trajectory, ensure_ascii=False, indent=2))

    result = {"method": "pure_gp_noisy_logei", "seed": args.seed, "dataset": dataset_root.name, "budget": args.budget, "trajectory": trajectory}
    torch.save(result, output / f"seed_{args.seed}.pt")
    print(json.dumps({"ok": True, "output": str(output), "evaluations": len(trajectory), "best_yield": max(item["observed_yield"] for item in trajectory)}))


if __name__ == "__main__":
    main()
