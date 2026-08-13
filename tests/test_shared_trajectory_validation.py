import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
import torch

from boagent.competition import validate_artifact
from boagent.evaluation import validate_trajectory, validate_trajectory_rows


def make_artifact(path: Path, candidates: pd.DataFrame, trajectory: list[dict], *, seed: int = 100, dataset_name: str = "dataset") -> None:
    payload = {"seed": seed, "dataset": dataset_name, "target": "Yield", "direction": "maximize", "trajectory": trajectory}
    torch.save(payload, path)


def rows_from_indices(candidates: pd.DataFrame, indices: list[int], target_key: str = "observed_value") -> list[dict]:
    return [
        {
            "step": step,
            "query_index": index,
            "condition": candidates.loc[index].to_dict(),
            target_key: float(index),
            "candidate_id": f"c{index}",
            "trial_id": f"t{index}",
            "receipt_id": f"r{index}",
        }
        for step, index in enumerate(indices, 1)
    ]


class SharedTrajectoryValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.dataset = self.directory / "dataset"
        self.dataset.mkdir()
        self.candidates = pd.DataFrame([{"x": i, "kind": f"k{i}"} for i in range(5)])
        self.candidates.to_csv(self.dataset / "test_features.csv", index=False)
        pd.DataFrame([{"x": i, "kind": f"k{i}", "Yield": float(i)} for i in range(5)]).to_csv(self.dataset / "test.csv", index=False)

    def test_shared_validator_accepts_valid_rows(self) -> None:
        rows = rows_from_indices(self.candidates, [0, 1, 2])
        self.assertIsNone(validate_trajectory_rows(rows, self.candidates))

    def test_shared_validator_rejects_duplicate_index(self) -> None:
        rows = rows_from_indices(self.candidates, [0, 1, 1])
        self.assertIn("query_index", validate_trajectory_rows(rows, self.candidates))

    def test_shared_validator_rejects_out_of_range_index(self) -> None:
        rows = [
            {"step": 1, "query_index": 0, "condition": self.candidates.loc[0].to_dict(), "observed_value": 0.0},
            {"step": 2, "query_index": 99, "condition": {"x": 99, "kind": "k99"}, "observed_value": 1.0},
        ]
        self.assertIn("query_index", validate_trajectory_rows(rows, self.candidates))

    def test_shared_validator_rejects_wrong_step_order(self) -> None:
        rows = rows_from_indices(self.candidates, [0, 1])
        rows[1]["step"] = 3
        self.assertIn("step", validate_trajectory_rows(rows, self.candidates))

    def test_shared_validator_rejects_condition_mismatch(self) -> None:
        rows = rows_from_indices(self.candidates, [0, 1])
        rows[1]["condition"] = {"x": 99, "kind": "nope"}
        self.assertIn("condition", validate_trajectory_rows(rows, self.candidates))

    def test_evaluation_validate_trajectory_uses_shared_validator(self) -> None:
        rows = rows_from_indices(self.candidates, [0, 1, 2, 3, 4], target_key="observed_value")
        artifact = self.directory / "ok.pt"
        make_artifact(artifact, self.candidates, rows)
        result = validate_trajectory(artifact, self.dataset, budget=5)
        self.assertEqual(result["best_found"], 4.0)

    def test_evaluation_validate_trajectory_rejects_duplicate_via_shared(self) -> None:
        rows = rows_from_indices(self.candidates, [0, 1, 2, 3, 3], target_key="observed_value")
        artifact = self.directory / "dup.pt"
        make_artifact(artifact, self.candidates, rows)
        with self.assertRaisesRegex(ValueError, "query_index"):
            validate_trajectory(artifact, self.dataset, budget=5)

    def test_validate_artifact_uses_shared_validator(self) -> None:
        from boagent.competition import COMPETITION_BUDGET
        dataset = self.directory / "dataset2"
        dataset.mkdir(exist_ok=True)
        candidates = pd.DataFrame([{"x": i, "kind": f"k{i}"} for i in range(COMPETITION_BUDGET)])
        candidates.to_csv(dataset / "test_features.csv", index=False)
        rows = rows_from_indices(candidates, list(range(COMPETITION_BUDGET)), target_key="observed_value")
        artifact = self.directory / "a.pt"
        make_artifact(artifact, candidates, rows, dataset_name="dataset2")
        result = validate_artifact(artifact, dataset, 100)
        self.assertEqual(result.state, "complete")

    def test_validate_artifact_rejects_condition_via_shared(self) -> None:
        from boagent.competition import COMPETITION_BUDGET
        dataset = self.directory / "dataset2"
        dataset.mkdir(exist_ok=True)
        candidates = pd.DataFrame([{"x": i, "kind": f"k{i}"} for i in range(COMPETITION_BUDGET)])
        candidates.to_csv(dataset / "test_features.csv", index=False)
        rows = rows_from_indices(candidates, list(range(COMPETITION_BUDGET)), target_key="observed_value")
        rows[3]["condition"] = {"x": 99, "kind": "nope"}
        artifact = self.directory / "bad.pt"
        make_artifact(artifact, candidates, rows, dataset_name="dataset2")
        result = validate_artifact(artifact, dataset, 100)
        self.assertEqual(result.state, "invalid")
        self.assertIn("condition", result.detail)


if __name__ == "__main__":
    unittest.main()
