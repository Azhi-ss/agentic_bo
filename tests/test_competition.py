import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
import torch
from typer.testing import CliRunner

from boagent.agent_cli import app
from boagent.competition import COMPETITION_BUDGET, COMPETITION_SEEDS, package_competition, validate_artifact
from boagent.experiment_config import load_experiment_config
from boagent.state import Study, Trial, candidate_id


runner = CliRunner()


def write_fixture(root: Path, *, count: int = COMPETITION_BUDGET, budget: int = COMPETITION_BUDGET) -> tuple[Path, Path, Path]:
    dataset = root / "dataset"
    dataset.mkdir()
    candidates = pd.DataFrame([{"x": index, "kind": f"k{index}"} for index in range(COMPETITION_BUDGET + 1)])
    candidates.to_csv(dataset / "test_features.csv", index=False)
    pd.DataFrame([{"x": 99, "kind": "train", "Yield": 1.0}]).to_csv(dataset / "train.csv", index=False)
    (dataset / "options.json").write_text(json.dumps({"x": list(range(100)), "kind": ["train", *[f"k{i}" for i in range(COMPETITION_BUDGET + 1)]]}))
    config = root / "competition.yaml"
    config.write_text(
        "schema_version: 1\n"
        "experiment:\n"
        "  name: test\n"
        "  dataset: dataset\n"
        "  output: runs\n"
        "  policies: [autonomous_agent]\n"
        f"  seeds: {list(COMPETITION_SEEDS)}\n"
        "  budget: 40\n"
        "  objective: {target: Yield, direction: maximize}\n"
        "runtime:\n"
        "  provider: ai-modeling\n"
        "  model: gpt-5.6-sol\n"
        "  thinking: xhigh\n"
        "  defaults:\n"
        "    acquisition: {name: noisy_logei, beta: 2.0}\n"
    )
    campaign = root / "runs" / "autonomous_agent" / "seed-100"
    state_path = campaign / "frame" / "state.json"
    study = Study(
        study_id="study",
        campaign_id="campaign",
        public_root=str(dataset.resolve()),
        target="Yield",
        direction="maximize",
        seed=100,
        budget=budget,
        features=["x", "kind"],
        categories={},
        trials=[
            Trial(
                trial_id=f"trial-{index}",
                candidate_id=candidate_id(row, index),
                query_index=index,
                config=row,
                status="observed",
                receipt_id=f"receipt-{index}",
                metrics={"Yield": float(index)},
            )
            for index, row in enumerate(candidates.iloc[:count].to_dict(orient="records"))
        ],
    )
    study.save(state_path)
    return config, dataset, state_path


class CompetitionPackagerTest(unittest.TestCase):
    def test_pilot_subset_packages_and_validates_modern_artifact(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, dataset, _ = write_fixture(root)
            report = package_competition(load_experiment_config(config, check_output_collisions=False), root / "submission", (100,))

            self.assertTrue(report["ok"], report)
            self.assertEqual(report["manifest"], {"valid": True, "missing": [], "extra": []})
            artifact = root / "submission" / "seed_100.pt"
            result = validate_artifact(artifact, dataset, 100)
            self.assertEqual((result.state, result.steps), ("complete", 40))
            payload = torch.load(artifact, weights_only=False)
            self.assertEqual(set(payload), {"seed", "dataset", "target", "direction", "trajectory"})

    def test_validator_rejects_non_numeric_observed_value(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, dataset, _ = write_fixture(root)
            artifact = root / "submission" / "seed_100.pt"
            package_competition(load_experiment_config(config, check_output_collisions=False), artifact.parent, (100,))
            payload = torch.load(artifact, weights_only=False)
            payload["trajectory"][0]["observed_value"] = None
            torch.save(payload, artifact)

            self.assertEqual(validate_artifact(artifact, dataset, 100).state, "invalid")

    def test_full_manifest_reports_other_seeds_incomplete(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, _, _ = write_fixture(root)
            report = package_competition(load_experiment_config(config, check_output_collisions=False), root / "submission", COMPETITION_SEEDS)

            self.assertFalse(report["ok"])
            self.assertEqual(report["seeds"][0]["state"], "complete")
            self.assertTrue(all(item["state"] == "incomplete" for item in report["seeds"][1:]))
            self.assertEqual(len(report["manifest"]["missing"]), 19)

    def test_hard_failures_are_invalid_or_incomplete(self) -> None:
        cases = {
            "short": (39, 40, "incomplete"),
            "wrong_budget": (40, 39, "invalid"),
        }
        for name, (count, budget, expected) in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                config, _, _ = write_fixture(root, count=count, budget=budget)
                report = package_competition(load_experiment_config(config, check_output_collisions=False), root / "submission", (100,))
                self.assertEqual(report["seeds"][0]["state"], expected)

    def test_rejects_pending_duplicate_mismatch_out_of_range_and_missing_provenance(self) -> None:
        mutations = {
            "pending": lambda study: setattr(study.trials[0], "status", "pending"),
            "duplicate": lambda study: setattr(study.trials[1], "query_index", 0),
            "condition": lambda study: study.trials[0].config.update({"x": -1}),
            "range": lambda study: setattr(study.trials[0], "query_index", 99),
            "provenance": lambda study: setattr(study.trials[0], "receipt_id", None),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory)
                config, _, state_path = write_fixture(root)
                study = Study.load(state_path)
                mutate(study)
                study.save(state_path)
                report = package_competition(load_experiment_config(config, check_output_collisions=False), root / "submission", (100,))
                self.assertEqual(report["seeds"][0]["state"], "incomplete" if name == "pending" else "invalid")

    def test_manifest_rejects_extra_artifact_and_cli_returns_failure(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config, _, _ = write_fixture(root)
            destination = root / "submission"
            destination.mkdir()
            torch.save({}, destination / "seed_999.pt")

            result = runner.invoke(app, ["package-competition", "--config", str(config), "--destination", str(destination), "--seed", "100"])

            self.assertEqual(result.exit_code, 1, result.output)
            report = json.loads(result.output)
            self.assertEqual(report["manifest"]["extra"], ["seed_999.pt"])


if __name__ == "__main__":
    unittest.main()
