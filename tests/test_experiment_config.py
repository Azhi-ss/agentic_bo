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


def write_config(
    path: Path,
    *,
    policies: str = "[default, autonomous_agent]",
    seeds: str = "[300, 301, 302, 303, 304]",
    budget: int = 2,
    acquisition: str = "ucb",
    beta: float = 4.0,
    extra: str = "",
) -> None:
    path.write_text(
        "schema_version: 1\n"
        "experiment:\n"
        "  name: test-experiment\n"
        "  dataset: data\n"
        "  output: output\n"
        f"  policies: {policies}\n"
        f"  seeds: {seeds}\n"
        f"  budget: {budget}\n"
        "  objective:\n"
        "    target: Yield\n"
        "    direction: maximize\n"
        "runtime:\n"
        "  provider: ai-modeling\n"
        "  model: gpt-5.6-sol\n"
        "  thinking: xhigh\n"
        "  defaults:\n"
        "    acquisition:\n"
        f"      name: {acquisition}\n"
        f"      beta: {beta}\n"
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

    def test_resume_initializes_missing_campaign_before_dispatch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")

            with patch("boagent.agent_cli.run_campaign") as run_campaign:
                result = runner.invoke(app, ["experiment", "--config", str(config), "--resume"])

            campaign = root / "output" / "default" / "seed-300"
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((campaign / "manifest.json").is_file())
            run_campaign.assert_called_once_with(campaign, model="gpt-5.6-sol", thinking="xhigh", policy="default")

    def test_resume_dispatches_matching_existing_campaign(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")
            with patch("boagent.agent_cli.run_campaign"):
                created = runner.invoke(app, ["experiment", "--config", str(config)])
            self.assertEqual(created.exit_code, 0, created.output)

            campaign = root / "output" / "default" / "seed-300"
            with patch("boagent.agent_cli.initialize_campaign") as initialize, patch("boagent.agent_cli.run_campaign") as run_campaign:
                resumed = runner.invoke(app, ["experiment", "--config", str(config), "--resume"])

            self.assertEqual(resumed.exit_code, 0, resumed.output)
            initialize.assert_not_called()
            run_campaign.assert_called_once_with(campaign, model="gpt-5.6-sol", thinking="xhigh", policy="default")

    def test_resume_dispatches_matching_audited_legacy_campaign(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[autonomous_agent]", seeds="[100]", budget=40, acquisition="noisy_logei", beta=2.0)
            with patch("boagent.agent_cli.run_campaign"):
                created = runner.invoke(app, ["experiment", "--config", str(config)])
            self.assertEqual(created.exit_code, 0, created.output)

            campaign = root / "output" / "autonomous_agent" / "seed-100"
            manifest_path = campaign / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for field in ("experiment_name", "experiment_policy", "source_config", "source_config_hash", "normalized_config_hash", "initial_runtime"):
                manifest.pop(field)
            manifest_path.write_text(json.dumps(manifest))
            frame_path = campaign / "frame" / "state.json"
            frame = Study.load(frame_path)
            frame.declared_config_hash = None
            frame.source_config_hash = None
            frame.source_config = None
            frame.experiment_name = None
            frame.experiment_policy = None
            frame.initial_acquisition = None
            frame.save(frame_path)
            audit_path = campaign / "campaign-run-config.json"
            audit_path.write_text(json.dumps({"revisions": [{
                "campaign_id": frame.campaign_id,
                "provider": "ai-modeling",
                "model": "gpt-5.6-sol",
                "thinking": "xhigh",
                "policy": "autonomous_agent",
                "provider_generation_seed": "unavailable",
                "declared_config_hash": None,
                "experiment_name": None,
                "experiment_policy": "autonomous_agent",
            }]}))

            with patch("boagent.agent_cli.initialize_campaign") as initialize, patch("boagent.agent_cli.run_campaign") as run_campaign:
                resumed = runner.invoke(app, ["experiment", "--config", str(config), "--resume"])

            self.assertEqual(resumed.exit_code, 0, resumed.output)
            initialize.assert_not_called()
            run_campaign.assert_called_once_with(campaign, model="gpt-5.6-sol", thinking="xhigh", policy="autonomous_agent")

            audit = json.loads(audit_path.read_text())
            audit["revisions"][-1]["provider"] = "other-provider"
            audit_path.write_text(json.dumps(audit))
            with patch("boagent.agent_cli.run_campaign") as run_campaign:
                rejected = runner.invoke(app, ["experiment", "--config", str(config), "--resume"])

            self.assertNotEqual(rejected.exit_code, 0)
            self.assertIn("run audit mismatch: provider", rejected.output)
            run_campaign.assert_not_called()

    def test_resume_rejects_mismatched_existing_campaign_before_dispatch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")
            with patch("boagent.agent_cli.run_campaign"):
                created = runner.invoke(app, ["experiment", "--config", str(config)])
            self.assertEqual(created.exit_code, 0, created.output)

            campaign = root / "output" / "default" / "seed-300"
            manifest_path = campaign / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["seed"] = 301
            manifest_path.write_text(json.dumps(manifest))
            before = manifest_path.read_bytes(), (campaign / "frame" / "state.json").read_bytes()
            with patch("boagent.agent_cli.initialize_campaign") as initialize, patch("boagent.agent_cli.run_campaign") as run_campaign:
                resumed = runner.invoke(app, ["experiment", "--config", str(config), "--resume"])

            self.assertNotEqual(resumed.exit_code, 0)
            self.assertIn("manifest mismatch: seed", resumed.output)
            initialize.assert_not_called()
            run_campaign.assert_not_called()
            self.assertEqual(before, (manifest_path.read_bytes(), (campaign / "frame" / "state.json").read_bytes()))

    def test_experiment_without_resume_keeps_collision_rejection(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")
            (root / "output" / "default" / "seed-300").mkdir(parents=True)

            with patch("boagent.agent_cli.initialize_campaign") as initialize, patch("boagent.agent_cli.run_campaign") as run_campaign:
                result = runner.invoke(app, ["experiment", "--config", str(config)])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("already exists", result.output)
            initialize.assert_not_called()
            run_campaign.assert_not_called()

    def test_experiment_without_resume_rejects_a_post_preflight_collision(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root / "data")
            config = root / "experiment.yaml"
            write_config(config, policies="[default]", seeds="[300]")
            loaded = self.load(config)
            campaign = root / "output" / "default" / "seed-300"
            campaign.mkdir(parents=True)

            with patch("boagent.agent_cli.load_experiment_config", return_value=loaded), patch("boagent.agent_cli.run_campaign") as run_campaign:
                result = runner.invoke(app, ["experiment", "--config", str(config)])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("already exists", result.output)
            run_campaign.assert_not_called()

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
