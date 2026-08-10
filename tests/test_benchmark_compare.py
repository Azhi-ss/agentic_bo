from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import pandas as pd
from boagent.oracle import receipt_signature

from benchmark.compare import SAMPLE_EXPERIMENT_CONFIG, benchmark_report, experiment_report, experiment_run_plan, summarize_many, summarize_pair


class BenchmarkComparisonTest(unittest.TestCase):
    def test_reports_per_seed_and_aggregate_agent_vs_gp_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            agent = root / "agent"
            gp = root / "gp"
            agent.mkdir()
            gp.mkdir()
            (agent / "trajectory.json").write_text(json.dumps([
                {"metrics": {"Yield": 80.0}},
                {"metrics": {"Yield": 95.0}},
            ]))
            (gp / "trajectory.json").write_text(json.dumps([
                {"observed_yield": 90.0},
                {"observed_yield": 92.0},
            ]))

            summary = summarize_pair(agent, gp, target="Yield")

            self.assertEqual(summary["agent"]["best"], 95.0)
            self.assertEqual(summary["gp"]["best"], 92.0)
            self.assertEqual(summary["agent"]["auc_best_so_far"], 87.5)
            self.assertEqual(summary["gp"]["auc_best_so_far"], 91.0)

    def test_aggregates_multiple_seed_pairs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            agent_root = root / "agent"
            gp_root = root / "gp"
            for seed, agent_values, gp_values in ((1, [80, 95], [90, 92]), (2, [70, 90], [75, 85])):
                agent = agent_root / f"seed-{seed}-agentic"
                gp = gp_root / f"seed-{seed}-gp"
                agent.mkdir(parents=True)
                gp.mkdir(parents=True)
                (agent / "trajectory.json").write_text(json.dumps([{"metrics": {"Yield": value}} for value in agent_values]))
                (gp / "trajectory.json").write_text(json.dumps([{"observed_yield": value} for value in gp_values]))

            summary = summarize_many(agent_root, gp_root, [1, 2], "Yield")

            self.assertEqual(summary["aggregate"]["agent"]["best"], 92.5)
            self.assertEqual(summary["aggregate"]["gp"]["best"], 88.5)

    def test_reports_locked_score_lcb_and_dataset_pass(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            labels = root / "test.csv"
            pd.DataFrame({"Yield": [100.0]}).to_csv(labels, index=False)
            agent_root = root / "agent"
            gp_root = root / "gp"
            for seed in range(1, 11):
                agent = agent_root / f"seed-{seed}-agentic"
                gp = gp_root / f"seed-{seed}-gp"
                agent.mkdir(parents=True)
                gp.mkdir(parents=True)
                (agent / "trajectory.json").write_text(json.dumps([
                    {"metrics": {"Yield": 96.0}},
                    {"metrics": {"Yield": 100.0}},
                ]))
                (gp / "trajectory.json").write_text(json.dumps([
                    {"observed_yield": 80.0},
                    {"observed_yield": 90.0},
                ]))

            report = benchmark_report(agent_root, gp_root, list(range(1, 11)), "Yield", labels)

            self.assertTrue(report["passed"])
            self.assertGreater(report["paired_score_lcb95"], 0)
            self.assertGreater(report["aggregate"]["agent"]["best"], report["aggregate"]["gp"]["best"])
            self.assertLess(report["aggregate"]["agent"]["simple_regret"], report["aggregate"]["gp"]["simple_regret"])
            self.assertEqual(len(report["seeds"]), 10)

    def test_experiment_plan_comes_from_checked_in_config_and_refuses_existing_directories(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            copied = root / "experiment.yaml"
            config = SAMPLE_EXPERIMENT_CONFIG.read_text().replace("../runs/suzuki/autonomous-agent-bo", "output")
            config = config.replace("../datasets/chemical_reactions/suzuki", str((SAMPLE_EXPERIMENT_CONFIG.parent.parent / "datasets/chemical_reactions/suzuki").resolve()))
            copied.write_text(config)
            plan = experiment_run_plan(copied)

            self.assertEqual({item["seed"] for item in plan}, {300, 301, 302, 303, 304})
            self.assertTrue(all(item["budget"] == 2 for item in plan))
            self.assertTrue(all(item["policy"] in {"default", "autonomous_agent"} for item in plan))
            self.assertTrue(all(item["provider_generation_seed"] == "unavailable" for item in plan))
            self.assertEqual(len({item["output"] for item in plan}), 10)

            Path(plan[0]["output"]).mkdir(parents=True)
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                experiment_run_plan(copied)

    def test_experiment_report_aggregates_action_and_two_step_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for policy in ("default", "autonomous_agent"):
                campaign = root / policy / "seed-300"
                campaign.mkdir(parents=True)
                manifest = {"campaign_id": f"campaign-{policy}", "seed": 300, "budget": 2, "target": "Yield"}
                (campaign / "manifest.json").write_text(json.dumps(manifest))
                (campaign / "campaign-run-config.json").write_text(json.dumps({"revisions": [{"policy": policy, "prompt_hash": f"prompt-{policy}", "prior_hash": "prior", "config_hash": f"config-{policy}", "leakage_gate": {"passed": True}}]}))
                (campaign / "initial-diagnostics.json").write_text(json.dumps({"historical_incumbent": 80.0}))
                evidence = {"surrogate_relationship": "not_consulted", "decision_evidence_complete": True, "actual_tool_use": {"calls": [], "candidate_rows": 4, "ranked_proposals_consulted": False}} if policy == "autonomous_agent" else {}
                trajectory = [
                    {"step": 1, "request_id": "request-1", "trial_id": "trial-1", "decision": {"pool_index": 1, "candidate_id": "a", "config": {"x": 1}, **evidence}, "metrics": {"Yield": 82.0}},
                    {"step": 2, "request_id": "request-2", "trial_id": "trial-2", "decision": {"pool_index": 3, "candidate_id": "b", "config": {"x": 3}, **evidence}, "metrics": {"Yield": 85.0}},
                ]
                (campaign / "trajectory.json").write_text(json.dumps(trajectory))
                frame = campaign / "frame"
                frame.mkdir()
                (frame / "state.json").write_text(json.dumps({"trials": [{"source": "campaign", "trial_id": row["trial_id"], "query_index": row["decision"]["pool_index"], "candidate_id": row["decision"]["candidate_id"], "config": row["decision"]["config"]} for row in trajectory]}))
                secret = "secret"
                (campaign / ".receipt-key").write_text(secret)
                receipts = campaign / "receipts"
                receipts.mkdir()
                for row in trajectory:
                    receipt = {"campaign_id": manifest["campaign_id"], "trial_id": row["trial_id"], "candidate_id": row["decision"]["candidate_id"], "request_id": row["request_id"], "status": "succeeded"}
                    receipt["signature"] = receipt_signature(receipt, secret)
                    (receipts / f"{row['trial_id']}.json").write_text(json.dumps(receipt))
                (campaign / "pi-session.jsonl").write_text('{"type":"session"}\n')
                (campaign / "supervisor-events.json").write_text(json.dumps([{"type": "tool_execution_end", "toolName": "lenz_candidates", "result": {"details": {"ok": True}}}, {"type": "tool_execution_end", "toolName": "commit_candidate"}, {"type": "tool_execution_end", "toolName": "commit_candidate"}]))

            report = experiment_report(root, ["default", "autonomous_agent"], seeds=[300])

            autonomous = report["runs"]["autonomous_agent"]["300"]
            self.assertEqual(autonomous["outcomes"]["two_step_best"], 85.0)
            self.assertEqual(autonomous["behavior"]["candidate_rows_inspected"], 8)
            self.assertEqual(report["aggregate"]["autonomous_agent"]["behavior"]["tool_calls"]["lenz_candidates"], 1)
            self.assertEqual(report["aggregate"]["autonomous_agent"]["outcomes"]["two_step_best"]["median"], 85.0)


    def test_experiment_report_rejects_missing_receipt_or_session_trace(self) -> None:
        with TemporaryDirectory() as directory:
            campaign = Path(directory) / "default" / "seed-300"
            campaign.mkdir(parents=True)
            manifest = {"campaign_id": "campaign", "seed": 300, "budget": 2, "target": "Yield"}
            (campaign / "manifest.json").write_text(json.dumps(manifest))
            (campaign / "campaign-run-config.json").write_text(json.dumps({"revisions": [{"policy": "default", "prompt_hash": "prompt", "config_hash": "config"}]}))
            trajectory = [
                {"request_id": "request-1", "trial_id": "trial-1", "decision": {"pool_index": 1, "candidate_id": "a", "config": {"x": 1}}, "metrics": {"Yield": 1}},
                {"request_id": "request-2", "trial_id": "trial-2", "decision": {"pool_index": 2, "candidate_id": "b", "config": {"x": 2}}, "metrics": {"Yield": 2}},
            ]
            (campaign / "trajectory.json").write_text(json.dumps(trajectory))
            (campaign / "supervisor-events.json").write_text(json.dumps([{"type": "tool_execution_end", "toolName": "commit_candidate"}, {"type": "tool_execution_end", "toolName": "commit_candidate"}]))
            frame = campaign / "frame"
            frame.mkdir()
            (frame / "state.json").write_text(json.dumps({"trials": [{"source": "campaign", "trial_id": row["trial_id"], "query_index": row["decision"]["pool_index"], "candidate_id": row["decision"]["candidate_id"], "config": row["decision"]["config"]} for row in trajectory]}))
            (campaign / ".receipt-key").write_text("secret")
            receipts = campaign / "receipts"
            receipts.mkdir()
            (receipts / "trial-1.json").write_text("{}")
            report = experiment_report(Path(directory), ["default"], seeds=[300])
            self.assertEqual(report["runs"]["default"]["300"]["status"], "failed")
            self.assertIn("two matching receipt", report["runs"]["default"]["300"]["failure"])

            for row in trajectory:
                receipt = {"campaign_id": manifest["campaign_id"], "trial_id": row["trial_id"], "candidate_id": row["decision"]["candidate_id"], "request_id": row["request_id"], "status": "succeeded"}
                receipt["signature"] = receipt_signature(receipt, "secret")
                (receipts / f"{row['trial_id']}.json").write_text(json.dumps(receipt))
            report = experiment_report(Path(directory), ["default"], seeds=[300])
            self.assertIn("session trace", report["runs"]["default"]["300"]["failure"])


if __name__ == "__main__":
    unittest.main()
