from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import pandas as pd

from benchmark.compare import benchmark_report, summarize_many, summarize_pair


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


if __name__ == "__main__":
    unittest.main()
