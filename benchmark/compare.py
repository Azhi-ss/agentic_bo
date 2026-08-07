from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, stdev


def _values(path: Path, target: str, agent: bool) -> list[float]:
    rows = json.loads((path / "trajectory.json").read_text())
    return [float(row["metrics"][target] if agent else row["observed_yield"]) for row in rows]


def _summary(values: list[float], global_best: float | None = None) -> dict[str, float | int]:
    best_so_far = []
    for value in values:
        best_so_far.append(max(value, best_so_far[-1] if best_so_far else value))
    summary = {"evaluations": len(values), "initial": values[0], "best": max(values), "auc_best_so_far": mean(best_so_far)}
    if global_best is not None:
        threshold = global_best - 0.05 * abs(global_best)
        t95 = next((step for step, value in enumerate(best_so_far, 1) if value >= threshold), len(values) + 1)
        summary.update(
            simple_regret=global_best - summary["best"],
            t95=t95,
            score=100 * (
                0.4 * summary["best"] / global_best
                + 0.3 * summary["auc_best_so_far"] / global_best
                + 0.2 * (t95 <= len(values))
                + 0.1 * summary["initial"] / global_best
            ),
        )
    return summary


def summarize_pair(agent_path: Path, gp_path: Path, target: str, global_best: float | None = None) -> dict[str, dict[str, float | int]]:
    return {
        "agent": _summary(_values(agent_path, target, agent=True), global_best),
        "gp": _summary(_values(gp_path, target, agent=False), global_best),
    }


def summarize_many(agent_root: Path, gp_root: Path, seeds: list[int], target: str, global_best: float | None = None) -> dict:
    per_seed = {
        str(seed): summarize_pair(agent_root / f"seed-{seed}-agentic", gp_root / f"seed-{seed}-gp", target, global_best)
        for seed in seeds
    }
    metrics = ("best", "auc_best_so_far") if global_best is None else ("best", "auc_best_so_far", "simple_regret", "score")
    return {
        "seeds": per_seed,
        "aggregate": {
            method: {
                metric: mean(per_seed[str(seed)][method][metric] for seed in seeds)
                for metric in metrics
            }
            for method in ("agent", "gp")
        },
    }


def benchmark_report(agent_root: Path, gp_root: Path, seeds: list[int], target: str, labels: Path) -> dict:
    global_best = float(__import__("pandas").read_csv(labels)[target].max())
    report = summarize_many(agent_root, gp_root, seeds, target, global_best)
    differences = [report["seeds"][str(seed)]["agent"]["score"] - report["seeds"][str(seed)]["gp"]["score"] for seed in seeds]
    lcb = mean(differences) - 1.96 * stdev(differences) / len(differences) ** 0.5 if len(differences) > 1 else differences[0]
    agent = report["aggregate"]["agent"]
    gp = report["aggregate"]["gp"]
    report["global_best"] = global_best
    report["paired_score_lcb95"] = lcb
    report["passed"] = agent["best"] > gp["best"] and agent["auc_best_so_far"] > gp["auc_best_so_far"] and agent["simple_regret"] < gp["simple_regret"] and lcb > 0
    return report

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, required=True)
    parser.add_argument("--gp", type=Path, required=True)
    parser.add_argument("--target", default="Yield")
    parser.add_argument("--seeds", nargs="*", type=int)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.labels:
        if not args.seeds:
            parser.error("--labels requires --seeds")
        summary = benchmark_report(args.agent, args.gp, args.seeds, args.target, args.labels)
    else:
        summary = summarize_many(args.agent, args.gp, args.seeds, args.target) if args.seeds else summarize_pair(args.agent, args.gp, args.target)
    rendered = json.dumps(summary, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered)

if __name__ == "__main__":
    main()
