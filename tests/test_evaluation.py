from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
import torch

from boagent.evaluation import SEEDS, summarize, validate_trajectory


class EvaluationTest(unittest.TestCase):
    def test_accepts_verified_non_empty_early_stop(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([{"x": "a"}]).to_csv(root / "test_features.csv", index=False)
            pd.DataFrame([{"x": "a", "Yield": 80.0}]).to_csv(root / "test.csv", index=False)
            artifact = root / "result.pkl"
            torch.save({
                "seed": 1,
                "trajectory": [{"step": 1, "query_index": 0, "condition": {"x": "a"}, "observed_yield": 80.0}],
                "stop": {"status": "stopped", "verified": True, "observed": 1, "budget": 2, "budget_remaining": 1},
            }, artifact)

            result = validate_trajectory(artifact, root, budget=2)

            self.assertEqual(result["best_found"], 80.0)

    def test_legacy_artifacts_always_use_maximize_semantics(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([{"x": "a"}, {"x": "b"}]).to_csv(root / "test_features.csv", index=False)
            pd.DataFrame([{"x": "a", "Yield": 1.0}, {"x": "b", "Yield": 9.0}]).to_csv(root / "test.csv", index=False)
            artifact = root / "legacy.pt"
            torch.save({
                "seed": 1,
                "direction": "minimize",
                "trajectory": [
                    {"step": 1, "query_index": 0, "condition": {"x": "a"}, "observed_yield": 1.0},
                    {"step": 2, "query_index": 1, "condition": {"x": "b"}, "observed_yield": 9.0},
                ],
            }, artifact)

            result = validate_trajectory(artifact, root, budget=2)

            self.assertEqual(result["best_found"], 9.0)

    def test_rejects_over_budget_early_stop(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [{"x": value} for value in ("a", "b", "c")]
            pd.DataFrame(rows).to_csv(root / "test_features.csv", index=False)
            pd.DataFrame([{**row, "Yield": value} for row, value in zip(rows, (1.0, 2.0, 3.0), strict=True)]).to_csv(root / "test.csv", index=False)
            artifact = root / "over-budget.pt"
            torch.save({
                "seed": 1,
                "trajectory": [
                    {"step": index, "query_index": index - 1, "condition": row, "observed_yield": float(index)}
                    for index, row in enumerate(rows, 1)
                ],
                "stop": {"status": "stopped", "verified": True, "observed": 3, "budget": 2, "budget_remaining": -1},
            }, artifact)

            with self.assertRaisesRegex(ValueError, "expected 2 steps"):
                validate_trajectory(artifact, root, budget=2)

    def test_rejects_unknown_modern_target(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([{"x": "a"}]).to_csv(root / "test_features.csv", index=False)
            pd.DataFrame([{"x": "a", "Loss": 2.0}]).to_csv(root / "test.csv", index=False)
            artifact = root / "unknown-target.pt"
            torch.save({
                "seed": 1,
                "target": "Missing",
                "direction": "minimize",
                "trajectory": [{"step": 1, "query_index": 0, "condition": {"x": "a"}, "observed_value": 2.0}],
            }, artifact)

            with self.assertRaisesRegex(ValueError, "target not found in test.csv: Missing"):
                validate_trajectory(artifact, root, budget=1)

    def test_uses_minimum_for_minimization_campaigns(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([{"x": "a"}, {"x": "b"}]).to_csv(root / "test_features.csv", index=False)
            pd.DataFrame([{"x": "a", "Loss": 10.0}, {"x": "b", "Loss": 2.0}]).to_csv(root / "test.csv", index=False)
            artifact = root / "result.pt"
            torch.save({
                "seed": 1,
                "target": "Loss",
                "direction": "minimize",
                "trajectory": [
                    {"step": 1, "query_index": 0, "condition": {"x": "a"}, "observed_value": 10.0},
                    {"step": 2, "query_index": 1, "condition": {"x": "b"}, "observed_value": 2.0},
                ],
            }, artifact)

            result = validate_trajectory(artifact, root, budget=2)

            self.assertEqual(result["initial_round_found_best"], 10.0)
            self.assertEqual(result["best_found"], 2.0)
            self.assertEqual(result["round_to_95_global_best"], 2)
            self.assertEqual(result["auc_best_so_far"], 6.0)

    def test_paper_protocol_uses_ten_seeds_and_median_iqr(self) -> None:
        self.assertEqual(len(SEEDS), 10)
        summary = summarize([
            {"initial_round_found_best": value, "best_found": value, "round_to_95_global_best": value, "auc_best_so_far": value, "simple_regret": value}
            for value in range(1, 5)
        ])
        self.assertEqual(summary["simple_regret"], {"median": 2.5, "q25": 1.75, "q75": 3.25})


if __name__ == "__main__":
    unittest.main()
