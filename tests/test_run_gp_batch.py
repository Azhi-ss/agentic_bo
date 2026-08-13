from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import torch

from benchmark.run_gp_batch import run_batch, validate_seed


class GPBatchTest(unittest.TestCase):
    def write_dataset(self, root: Path) -> Path:
        dataset = root / "buchwald_sub4"
        dataset.mkdir()
        pd.DataFrame({"x": ["a"], "Yield": [1.0]}).to_csv(dataset / "train.csv", index=False)
        pd.DataFrame({"x": ["b", "c", "d"]}).to_csv(dataset / "test_features.csv", index=False)
        pd.DataFrame({"x": ["b", "c", "d"], "Yield": [2.0, 4.0, 3.0]}).to_csv(dataset / "test.csv", index=False)
        return dataset

    def write_artifact(self, output: Path, dataset: Path, seed: int, *, bad_best: bool = False) -> None:
        output.mkdir(parents=True)
        trajectory = [
            {"step": 1, "pool_index": 0, "config": {"x": "b"}, "predicted_mean": 0.0, "posterior_variance": 1.0, "acquisition_value": 1.0, "observed_yield": 2.0, "best_so_far": 2.0},
            {"step": 2, "pool_index": 1, "config": {"x": "c"}, "predicted_mean": 0.0, "posterior_variance": 1.0, "acquisition_value": 1.0, "observed_yield": 4.0, "best_so_far": 3.0 if bad_best else 4.0},
        ]
        (output / "trajectory.json").write_text(json.dumps(trajectory))
        torch.save({"method": "pure_gp_noisy_logei", "seed": seed, "dataset": dataset.name, "budget": 2, "trajectory": trajectory}, output / f"seed_{seed}.pt")

    def test_validation_checks_complete_aligned_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = self.write_dataset(root)
            output = root / "seed-100-gp"
            self.write_artifact(output, dataset, 100)
            validate_seed(output, dataset, 100, 2)

            self.write_artifact(root / "bad", dataset, 100, bad_best=True)
            with self.assertRaisesRegex(ValueError, "best_so_far"):
                validate_seed(root / "bad", dataset, 100, 2)

    def test_resume_skips_only_valid_seed_and_archives_partial_before_ordered_rerun(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = self.write_dataset(root)
            output_root = root / "runs"
            self.write_artifact(output_root / "seed-100-gp", dataset, 100)
            partial = output_root / "seed-200-gp"
            partial.mkdir(parents=True)
            (partial / "trajectory.json").write_text("[]")
            launched: list[int] = []

            def fake_run(command: list[str], check: bool) -> None:
                seed = int(command[command.index("--seed") + 1])
                output = Path(command[command.index("--output") + 1])
                launched.append(seed)
                self.write_artifact(output, dataset, seed)

            with patch("benchmark.run_gp_batch.subprocess.run", side_effect=fake_run):
                report = run_batch(dataset, output_root, seeds=(100, 200, 300), budget=2, resume=True)

            self.assertEqual(launched, [200, 300])
            self.assertTrue((output_root / "seed-200-gp.partial-1" / "trajectory.json").is_file())
            self.assertEqual(report, {"completed": [200, 300], "skipped": [100], "archived": [str(output_root / "seed-200-gp.partial-1")]})
            for seed in (100, 200, 300):
                validate_seed(output_root / f"seed-{seed}-gp", dataset, seed, 2)

    def test_existing_output_requires_resume_even_when_valid(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = self.write_dataset(root)
            output_root = root / "runs"
            self.write_artifact(output_root / "seed-100-gp", dataset, 100)

            with self.assertRaisesRegex(FileExistsError, "use --resume"):
                run_batch(dataset, output_root, seeds=(100,), budget=2, resume=False)


if __name__ == "__main__":
    unittest.main()
