import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import ANY, patch

import pandas as pd
from boagent.agent_cli import app as agent_app
from boagent.state import Study, Trial
import torch
from typer.testing import CliRunner

from boagent.cli import app


runner = CliRunner()


def create_state(root: Path) -> Path:
    pd.DataFrame([
        {"ligand": "PPh3", "base": "NaHCO3", "Yield": 80.0},
        {"ligand": "XPhos", "base": "KOH", "Yield": 40.0},
    ]).to_csv(root / "train.csv", index=False)
    pd.DataFrame([
        {"ligand": "PPh3", "base": "KOH"},
        {"ligand": "XPhos", "base": "NaHCO3"},
    ]).to_csv(root / "test_features.csv", index=False)
    state = root / "state.json"
    result = runner.invoke(app, [
        "create", "--state", str(state), "--dataset-root", str(root),
        "--target", "Yield", "--direction", "maximize", "--seed", "1",
        "--budget", "2", "--campaign-id", "test-campaign",
    ])
    assert result.exit_code == 0, result.output
    return state


class LenzCliContractTest(unittest.TestCase):
    def test_exposes_read_only_deliberation_and_acquisition_control(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            for command in (
                ["suggest", "--state", str(state), "--q", "2"],
                ["predict", "--state", str(state), "--configs", '[{"ligand":"PPh3","base":"KOH"}]'],
                ["score", "--state", str(state), "--configs", '[{"ligand":"PPh3","base":"KOH"}]'],
                ["diagnostics", "--state", str(state)],
                ["set-acqf", "--state", str(state), "--acqf", "ucb", "--beta", "3", "--rationale", "broader exploration"],
            ):
                result = runner.invoke(app, command)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn('"ok": true', result.output)

    def test_candidates_are_label_free_filtered_and_paginated(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            first = runner.invoke(app, ["candidates", "--state", str(state), "--filters", '{"ligand":["PPh3","XPhos"]}', "--limit", "1"])
            second = runner.invoke(app, ["candidates", "--state", str(state), "--cursor", "1", "--limit", "100"])

            self.assertEqual(first.exit_code, 0, first.output)
            page = json.loads(first.output)["result"]
            self.assertEqual(set(page["candidates"][0]), {"pool_index", "candidate_id", "config"})
            self.assertEqual(page["candidates"][0]["pool_index"], 0)
            self.assertEqual(page["next_cursor"], 1)
            self.assertEqual(json.loads(second.output)["result"]["candidates"][0]["pool_index"], 1)

            invalid = runner.invoke(app, ["candidates", "--state", str(state), "--filters", '{"ligand":"hidden"}'])
            too_large = runner.invoke(app, ["candidates", "--state", str(state), "--limit", "101"])
            self.assertNotEqual(invalid.exit_code, 0)
            self.assertNotEqual(too_large.exit_code, 0)

    def test_create_exposes_historical_observations_without_spending_campaign_budget(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))

            trials = runner.invoke(app, ["trials", "--state", str(state)])
            status = runner.invoke(app, ["status", "--state", str(state)])

            self.assertEqual(trials.exit_code, 0, trials.output)
            trial_rows = json.loads(trials.output)["result"]
            self.assertEqual(len(trial_rows), 2)
            self.assertTrue(all(row["source"] == "historical" for row in trial_rows))
            self.assertTrue(all(row["status"] == "observed" for row in trial_rows))
            self.assertEqual(trial_rows[0]["metrics"], {"Yield": 80.0})
            status_payload = json.loads(status.output)["result"]
            self.assertEqual(status_payload["historical_observed"], 2)
            self.assertEqual(status_payload["observed"], 0)
            self.assertEqual(status_payload["budget_remaining"], 2)

    def test_submit_budget_counts_only_campaign_observations(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))

            result = runner.invoke(app, [
                "submit", "--state", str(state), "--pool-index", "0",
                "--config", '{"ligand":"PPh3","base":"KOH"}', "--request-id", "request-1",
            ])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.output)["result"]["source"], "campaign")

    def test_load_migrates_legacy_initial_rows_into_historical_trials(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            payload = json.loads(state.read_text())
            historical = [trial for trial in payload["trials"] if trial["source"] == "historical"]
            payload["initial"] = [
                {**trial["config"], "Yield": trial["metrics"]["Yield"]}
                for trial in historical
            ]
            payload["trials"] = [trial for trial in payload["trials"] if trial["source"] != "historical"]
            state.write_text(json.dumps(payload))

            migrated = Study.load(state)

            self.assertEqual(len(migrated.historical), 2)
            self.assertEqual(migrated.initial, [])
            self.assertEqual(migrated.historical[0].metrics, {"Yield": 80.0})

    def test_load_migrates_legacy_objective_and_initializes_domain_config(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))

            study = Study.load(state)

            self.assertEqual(study.objectives, {"Yield": "maximize"})
            self.assertEqual(study.constraints, [])
            self.assertEqual(study.original_domain, study.categories)
            self.assertEqual(study.active_bounds, {})

    def test_feasible_incumbent_and_pareto_use_configured_outcomes(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            study = Study.load(state)
            study.objectives = {"Yield": "maximize", "Cost": "minimize"}
            study.constraints = [{"metric": "Cost", "upper": 10.0}]
            study.trials[0].metrics = {"Yield": 80.0, "Cost": 5.0}
            study.trials[1].metrics = {"Yield": 90.0, "Cost": 9.0}
            study.save(state)

            incumbent = runner.invoke(app, ["incumbent", "--state", str(state)])
            front = runner.invoke(app, ["pareto", "--state", str(state)])

            self.assertEqual(json.loads(incumbent.output)["result"]["metrics"], {"Yield": 90.0, "Cost": 9.0})
            self.assertEqual(len(json.loads(front.output)["result"]), 2)

    def test_persistent_and_temporary_steering_and_multiple_pending(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))

            for command in (
                ["set-bounds", "--state", str(state), "--bounds", '{"ligand":["PPh3"]}', "--rationale", "trusted ligand"],
                ["set-objectives", "--state", str(state), "--objectives", '{"Yield":"maximize"}', "--rationale", "confirm objective"],
                ["set-constraints", "--state", str(state), "--constraints", '[]', "--rationale", "no constraints"],
            ):
                result = runner.invoke(app, command)
                self.assertEqual(result.exit_code, 0, result.output)

            temporary = runner.invoke(app, ["suggest", "--state", str(state), "--bounds", '{"base":["KOH"]}', "--q", "2"])
            self.assertEqual(temporary.exit_code, 0, temporary.output)
            self.assertTrue(all(row["config"]["ligand"] == "PPh3" and row["config"]["base"] == "KOH" for row in json.loads(temporary.output)["result"]))

            first = runner.invoke(app, ["submit", "--state", str(state), "--pool-index", "0", "--config", '{"ligand":"PPh3","base":"KOH"}', "--request-id", "request-1"])
            second = runner.invoke(app, ["submit", "--state", str(state), "--pool-index", "1", "--config", '{"ligand":"XPhos","base":"NaHCO3"}', "--request-id", "request-2"])
            self.assertEqual(first.exit_code, 0, first.output)
            self.assertEqual(second.exit_code, 0, second.output)
            self.assertEqual(len(Study.load(state).pending), 2)

    def test_numeric_bounds_are_intervals_and_temporary_bounds_only_narrow(self) -> None:
        frame = pd.DataFrame({"x": [0, 1, 2, 3, 4, 5]})
        from boagent.cli import combine_restrictions, restrict_candidates

        self.assertEqual(restrict_candidates(frame, {"x": [1, 4]})["x"].tolist(), [1, 2, 3, 4])
        self.assertEqual(combine_restrictions(frame, {"x": [1, 4]}, {"x": [3, 5]}), {"x": [3, 4]})

    def test_rejects_unimplemented_multiobjective_and_constraint_setters(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            multi = runner.invoke(app, ["set-objectives", "--state", str(state), "--objectives", '{"Yield":"maximize","Cost":"minimize"}', "--rationale", "moo"])
            constrained = runner.invoke(app, ["set-constraints", "--state", str(state), "--constraints", '[{"metric":"Cost","upper":5}]', "--rationale", "safe"])
            self.assertNotEqual(multi.exit_code, 0)
            self.assertNotEqual(constrained.exit_code, 0)
            self.assertIn("not yet supported", multi.output)
            self.assertIn("not yet supported", constrained.output)

    def test_score_defaults_to_persisted_policy_and_records_revision_audit(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            revised = runner.invoke(app, [
                "set-acqf", "--state", str(state), "--acqf", "ucb", "--beta", "3",
                "--rationale", "broader exploration",
            ])
            self.assertEqual(revised.exit_code, 0, revised.output)
            study = Study.load(state)
            event = study.event_log[-1]
            self.assertEqual(event["type"], "configuration_revised")
            self.assertEqual(event["prior_acqf"], "noisy_logei")
            self.assertEqual(event["new_acqf"], "ucb")
            self.assertEqual(event["prior_beta"], 2.0)
            self.assertEqual(event["new_beta"], 3.0)
            self.assertEqual(event["rationale"], "broader exploration")

            with (
                patch("boagent.cli.fit_surrogate", return_value=object()),
                patch("boagent.cli.encode_frame", return_value=object()),
                patch("boagent.cli.acquisition_values", return_value=[1.25]) as acquisition,
                patch("boagent.cli.posterior_rows", return_value=([81.0], [4.0])),
            ):
                scored = runner.invoke(app, [
                    "score", "--state", str(state),
                    "--configs", '[{"ligand":"PPh3","base":"KOH"}]',
                ])
            self.assertEqual(scored.exit_code, 0, scored.output)
            acquisition.assert_called_once_with(ANY, ANY, "ucb", 3.0)
            self.assertIn('"ucb": 1.25', scored.output)

            payload = json.loads(scored.output)["result"][0]
            self.assertEqual(payload["pool_index"], 0)
            self.assertEqual(payload["config"], {"ligand": "PPh3", "base": "KOH"})
            self.assertEqual(payload["posterior_mean"], 81.0)
            self.assertEqual(payload["posterior_variance"], 4.0)
            self.assertEqual(payload["acquisition_value"], 1.25)
            self.assertEqual(payload["acqf"], "ucb")

    def test_run_forwards_autonomous_profile_without_changing_default(self) -> None:
        with TemporaryDirectory() as directory:
            campaign = Path(directory)
            (campaign / ".receipt-key").write_text("secret")
            with patch("boagent.agent_cli.subprocess.run") as process:
                default = runner.invoke(agent_app, ["run", "--campaign", str(campaign)])
                autonomous = runner.invoke(agent_app, ["run", "--campaign", str(campaign), "--policy", "autonomous_agent"])

            self.assertEqual(default.exit_code, 0, default.output)
            self.assertEqual(autonomous.exit_code, 0, autonomous.output)
            default_command, autonomous_command = [call.args[0] for call in process.call_args_list]
            self.assertNotIn("--policy", default_command)
            self.assertEqual(autonomous_command[-2:], ["--policy", "autonomous_agent"])

    def test_run_rejects_unknown_experiment_policy(self) -> None:
        with TemporaryDirectory() as directory:
            campaign = Path(directory)
            (campaign / ".receipt-key").write_text("secret")
            result = runner.invoke(agent_app, ["run", "--campaign", str(campaign), "--policy", "unknown"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("default", result.output)
            self.assertIn("autonomous_agent", result.output)
    def test_diagnostics_reuses_the_same_state_revision(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            with (
                patch("boagent.cli.fit_surrogate", return_value=object()) as fit,
                patch("boagent.cli.model_diagnostics", return_value={"cv_r2": 0.5, "cv_r2_status": "ok"}),
            ):
                first = runner.invoke(app, ["diagnostics", "--state", str(state)])
                second = runner.invoke(app, ["diagnostics", "--state", str(state)])
            self.assertEqual(first.exit_code, 0, first.output)
            self.assertEqual(second.exit_code, 0, second.output)
            fit.assert_called_once()

    def test_set_acqf_rejects_negative_beta(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            result = runner.invoke(app, [
                "set-acqf", "--state", str(state), "--acqf", "ucb", "--beta", "-1",
                "--rationale", "invalid",
            ])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("beta must be finite and non-negative", result.output)

    def test_export_rejects_zero_observation_early_stop(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            frame = campaign / "frame"
            frame.mkdir(parents=True)
            state = create_state(root)
            frame_state = frame / "state.json"
            frame_state.write_text(state.read_text())
            study = Study.load(frame_state)
            stop = {
                "status": "stopped",
                "campaign_id": study.campaign_id,
                "state_revision": study.state_revision,
                "observed": 0,
                "budget": study.budget,
                "budget_remaining": study.budget,
                "condition": "target_reached",
                "rationale": "verified evidence",
                "verified": True,
            }
            (campaign / "campaign-status.json").write_text(json.dumps(stop))

            exported = runner.invoke(agent_app, ["export", "--campaign", str(campaign), "--output", str(root / "export.pt")])

            self.assertNotEqual(exported.exit_code, 0)
            self.assertIn("campaign has no observed trials", exported.output)

    def test_run_exposes_project_cli_scripts_to_supervisor(self) -> None:
        with TemporaryDirectory() as directory:
            campaign = Path(directory)
            (campaign / ".receipt-key").write_text("secret")
            with (
                patch.dict("boagent.agent_cli.os.environ", {"PATH": "/usr/bin"}, clear=True),
                patch("boagent.agent_cli.subprocess.run") as process,
            ):
                result = runner.invoke(agent_app, ["run", "--campaign", str(campaign)])

            self.assertEqual(result.exit_code, 0, result.output)
            env = process.call_args.kwargs["env"]
            self.assertEqual(Path(env["PATH"].split(os.pathsep)[0]), Path(sys.executable).resolve().parent)

    def test_init_exposes_project_cli_scripts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([{"x": 1}]).to_csv(root / "test_features.csv", index=False)
            (root / "options.json").write_text(json.dumps({"x": [1]}))
            with patch("boagent.agent_cli.subprocess.run") as process:
                result = runner.invoke(agent_app, ["init", "--dataset-root", str(root), "--output", str(root / "campaign")])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Path(process.call_args.kwargs["env"]["PATH"].split(os.pathsep)[0]), Path(sys.executable).resolve().parent)

    def test_init_gives_agent_a_leak_free_dataset_summary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([
                {"product": "A", "ligand": "PPh3", "temperature": 80, "Yield": 10.0},
                {"product": "B", "ligand": "XPhos", "temperature": 100, "Yield": 70.0},
            ]).to_csv(root / "train.csv", index=False)
            pd.DataFrame([
                {"product": "B", "ligand": "PPh3", "temperature": 80},
                {"product": "B", "ligand": "XPhos", "temperature": 100},
            ]).to_csv(root / "test_features.csv", index=False)
            (root / "options.json").write_text(json.dumps({
                "product": ["A", "B"], "ligand": ["PPh3", "XPhos"], "temperature": [80, 100],
                "catalyst": ["Pd"],
            }))
            (root / "README.md").write_text("# Reaction dataset\n\nOptimize this coupling reaction without hidden labels.\n")

            with patch("boagent.agent_cli.subprocess.run"):
                result = runner.invoke(agent_app, [
                    "init", "--dataset-root", str(root), "--output", str(root / "campaign"), "--budget", "40",
                ])

            self.assertEqual(result.exit_code, 0, result.output)
            task = (root / "campaign" / "TASK.md").read_text()
            summary = json.loads((root / "campaign" / "dataset-summary.json").read_text())
            self.assertIn("## Dataset understanding", task)
            self.assertIn(json.dumps(summary, ensure_ascii=False, indent=2), task)
            self.assertEqual(summary["rows"], {"initial_observations": 2, "candidate_pool": 2})
            self.assertEqual(summary["features"]["product"]["role"], "context")
            self.assertEqual(summary["features"]["temperature"]["kind"], "numeric_discrete")
            self.assertEqual(summary["target"]["initial_observed"]["maximum"], 70.0)
            manifest = json.loads((root / "campaign" / "manifest.json").read_text())
            self.assertEqual(manifest["prior_source"], "PRIOR.md")
            self.assertEqual(manifest["prior_scan"], "label_free")
            self.assertEqual(manifest["prior_provenance"], "mechanism_or_pre_experiment_source")
            self.assertEqual(len(manifest["prior_hash"]), 64)
            self.assertNotIn("test.csv", task)

    def test_init_rejects_misaligned_dataset_schema(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([{"x": 1, "Yield": 2.0}]).to_csv(root / "train.csv", index=False)
            pd.DataFrame([{"y": 1}]).to_csv(root / "test_features.csv", index=False)
            (root / "options.json").write_text(json.dumps({"x": [1], "y": [1]}))

            result = runner.invoke(agent_app, [
                "init", "--dataset-root", str(root), "--output", str(root / "campaign"),
            ])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("train/test_features schema mismatch", result.output)


    def test_export_writes_target_direction_and_observed_value(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "campaign"
            frame = campaign / "frame"
            frame.mkdir(parents=True)
            state = create_state(root)
            study = Study.load(state)
            study.budget = 1
            study.trials.append(Trial(
                trial_id="trial-1",
                candidate_id="candidate-1",
                query_index=0,
                config={"ligand": "PPh3", "base": "KOH"},
                status="observed",
                metrics={"Yield": 81.0},
            ))
            study.save(frame / "state.json")
            output = root / "export.pt"

            exported = runner.invoke(agent_app, ["export", "--campaign", str(campaign), "--output", str(output)])

            self.assertEqual(exported.exit_code, 0, exported.output)
            payload = torch.load(output, weights_only=False)
            self.assertEqual(payload["target"], "Yield")
            self.assertEqual(payload["direction"], "maximize")
            self.assertEqual(payload["trajectory"][0]["observed_value"], 81.0)
            self.assertNotIn("observed_yield", payload["trajectory"][0])

    def test_submit_rejects_mismatched_candidate_identity(self) -> None:
        with TemporaryDirectory() as directory:
            state = create_state(Path(directory))
            result = runner.invoke(app, [
                "submit", "--state", str(state), "--pool-index", "0",
                "--config", '{"ligand":"XPhos","base":"NaHCO3"}', "--request-id", "request-1",
            ])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("config does not match pool_index", result.output)


if __name__ == "__main__":
    unittest.main()
