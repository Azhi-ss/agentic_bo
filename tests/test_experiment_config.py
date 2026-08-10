import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
from typer.testing import CliRunner

from boagent.agent_cli import app
from boagent.state import Study


runner = CliRunner()


def write_dataset(root: Path) -> None:
    root.mkdir(parents=True)
    pd.DataFrame([{"x": 1, "Yield": 2.0}]).to_csv(root / "train.csv", index=False)
    pd.DataFrame([{"x": 2}, {"x": 3}]).to_csv(root / "test_features.csv", index=False)
    (root / "options.json").write_text(json.dumps({"x": [1, 2, 3]}))


def write_config(path: Path, *, policies: str = "[default, autonomous_agent]", seeds: str = "[300, 301, 302, 303, 304]", extra: str = "") -> None:
    path.write_text(
        "schema_version: 1\n"
        "experiment:\n"
        "  name: test-experiment\n"
        "  dataset: data\n"
        "  output: output\n"
        f"  policies: {policies}\n"
        f"  seeds: {seeds}\n"
        "  budget: 2\n"
        "  objective:\n"
        "    target: Yield\n"
        "    direction: maximize\n"
        "runtime:\n"
        "  provider: ai-modeling\n"
        "  model: gpt-5.6-sol\n"
        "  thinking: xhigh\n"
        "  defaults:\n"
        "    acquisition:\n"
        "      name: ucb\n"
        "      beta: 4.0\n"
        f"{extra}"
    )


class ExperimentConfigTest(unittest.TestCase):
    def load(self, path: Path):
        module = importlib.import_module("boagent.experiment_config")
        return module.load_experiment_config(path)

    def test_loads_strict_yaml_and_expands_authored_matrix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config)

            loaded = self.load(config)
            plan = loaded.public_plan()

            self.assertEqual([(run["policy"], run["seed"]) for run in plan["runs"]], [
                *(('default', seed) for seed in range(300, 305)),
                *(('autonomous_agent', seed) for seed in range(300, 305)),
            ])
            self.assertEqual(plan["runs"][0]["initial_acquisition"], {"name": "ucb", "beta": 4.0})
            self.assertEqual(len(plan["source_config_hash"]), 64)
            self.assertEqual(len(plan["normalized_config_hash"]), 64)

    def test_relative_paths_are_config_relative_and_cwd_independent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()

            first = self.load(config).public_plan()
            with patch("pathlib.Path.cwd", return_value=elsewhere):
                second = self.load(config).public_plan()

            self.assertEqual(first, second)
            self.assertEqual(first["runs"][0]["output"], "output/default/seed-300")
            self.assertNotIn(str(root), json.dumps(first))

    def test_rejects_unknown_secret_and_hidden_keys_without_echoing_values(self) -> None:
        for key in ("api_key", "hidden_labels", "global_optimum", "candidate_rankings"):
            with self.subTest(key=key), TemporaryDirectory() as directory:
                root = Path(directory)
                write_dataset(root / "data")
                config = root / "experiment.yaml"
                secret = "must-not-appear"
                write_config(config, policies="[default]", seeds="[300]", extra=f"  {key}: {secret}\n")

                with self.assertRaises(Exception) as caught:
                    self.load(config)

                self.assertIn(f"runtime.{key}", str(caught.exception))
                self.assertNotIn(secret, str(caught.exception))

    def test_rejects_invalid_duplicates_missing_dataset_and_output_collisions(self) -> None:
        cases = [
            ("[default, default]", "[300]", "duplicate"),
            ("[default]", "[300, 300]", "duplicate"),
        ]
        for policies, seeds, message in cases:
            with self.subTest(policies=policies, seeds=seeds), TemporaryDirectory() as directory:
                root = Path(directory)
                write_dataset(root / "data")
                config = root / "experiment.yaml"
                write_config(config, policies=policies, seeds=seeds)
                with self.assertRaisesRegex(Exception, message):
                    self.load(config)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")
            with self.assertRaisesRegex(Exception, "dataset"):
                self.load(config)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            (root / "output" / "default" / "seed-300").mkdir(parents=True)
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                self.load(config)

    def test_plan_cli_is_deterministic_and_does_not_mutate_or_start_processes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")

            with patch("boagent.agent_cli.subprocess.run") as process:
                result = runner.invoke(app, ["experiment", "--config", str(config), "--plan"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertFalse((root / "output").exists())
            process.assert_not_called()
            self.assertEqual(json.loads(result.output)["runs"][0]["policy"], "default")

    def test_execute_reuses_init_run_and_records_provenance_and_initial_acquisition(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")

            with patch("boagent.agent_cli.run_campaign") as run_campaign:
                result = runner.invoke(app, ["experiment", "--config", str(config)])

            self.assertEqual(result.exit_code, 0, result.output)
            campaign = root / "output" / "default" / "seed-300"
            manifest = json.loads((campaign / "manifest.json").read_text())
            frame = Study.load(campaign / "frame" / "state.json")
            self.assertEqual(manifest["experiment_name"], "test-experiment")
            self.assertEqual(manifest["experiment_policy"], "default")
            self.assertEqual(manifest["normalized_config_hash"], frame.declared_config_hash)
            self.assertEqual(frame.initial_acquisition, {"acqf": "ucb", "beta": 4.0, "origin": "experiment_config"})
            self.assertEqual(manifest["source_config"], "experiment.yaml")
            self.assertEqual(len(manifest["source_config_hash"]), 64)
            self.assertEqual(manifest["initial_runtime"], {"acqf": "ucb", "beta": 4.0})
            self.assertEqual(frame.acqf, "ucb")
            self.assertEqual(frame.beta, 4.0)
            self.assertEqual(frame.configuration_revision, 1)
            self.assertFalse(any(event["type"] == "configuration_revised" for event in frame.event_log))
            run_campaign.assert_called_once_with(campaign, model="gpt-5.6-sol", thinking="xhigh", policy="default")

    def test_direct_init_and_run_contract_remains_compatible(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            campaign = root / "campaign"
            with patch("boagent.agent_cli.subprocess.run") as process:
                initialized = runner.invoke(app, ["init", "--dataset-root", str(root / "data"), "--output", str(campaign)])
            self.assertEqual(initialized.exit_code, 0, initialized.output)
            self.assertNotIn("normalized_config_hash", json.loads((campaign / "manifest.json").read_text()))
            with patch("boagent.agent_cli.subprocess.run") as process:
                executed = runner.invoke(app, ["run", "--campaign", str(campaign)])
            self.assertEqual(executed.exit_code, 0, executed.output)
            self.assertNotIn("--policy", process.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
