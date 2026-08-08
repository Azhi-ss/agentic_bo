from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median, stdev

from boagent.oracle import verify_receipt


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

EXPERIMENT_SEEDS = [300, 301, 302, 303, 304]
EXPERIMENT_POLICIES = {"default", "autonomous_agent"}


def experiment_run_plan(output: Path, dataset: Path, policies: list[str]) -> list[dict]:
    unknown = set(policies) - EXPERIMENT_POLICIES
    if unknown:
        raise ValueError(f"unknown policies: {', '.join(sorted(unknown))}")
    plan = []
    for policy in policies:
        for seed in EXPERIMENT_SEEDS:
            campaign = output / policy / f"seed-{seed}"
            if campaign.exists():
                raise FileExistsError(f"campaign directory already exists: {campaign}")
            plan.append({
                "policy": policy,
                "seed": seed,
                "budget": 2,
                "provider": "ai-modeling",
                "model": "gpt-5.6-sol",
                "thinking": "xhigh",
                "provider_generation_seed": "unavailable",
                "output": str(campaign),
                "init_command": ["boagent", "init", "--dataset-root", str(dataset), "--output", str(campaign), "--seed", str(seed), "--budget", "2"],
                "preflight": "mandatory_fail_closed_before_provider_startup",
                "run_command": ["boagent", "run", "--campaign", str(campaign), "--model", "gpt-5.6-sol", "--thinking", "xhigh", "--policy", policy],
            })
    return plan


def _historical_incumbent(campaign: Path, target: str) -> float | None:
    diagnostics_path = campaign / "initial-diagnostics.json"
    if diagnostics_path.exists():
        return json.loads(diagnostics_path.read_text()).get("historical_incumbent")
    state_path = campaign / "frame" / "state.json"
    if not state_path.exists():
        return None
    state = json.loads(state_path.read_text())
    values = [trial.get("metrics", {}).get(target) for trial in state.get("trials", []) if trial.get("source") == "historical"]
    values = [float(value) for value in values if value is not None]
    return max(values) if values else None


def _experiment_run(campaign: Path) -> dict:
    if not campaign.exists():
        return {"status": "failed", "failure": "campaign directory missing"}
    try:
        manifest = json.loads((campaign / "manifest.json").read_text())
        trajectory = json.loads((campaign / "trajectory.json").read_text())
        if len(trajectory) != 2 or any("metrics" not in entry for entry in trajectory):
            raise ValueError("expected exactly two completed trajectory entries")
        state = json.loads((campaign / "frame" / "state.json").read_text())
        campaign_trials = {trial["trial_id"]: trial for trial in state["trials"] if trial.get("source") == "campaign"}
        receipt_paths = list((campaign / "receipts").glob("*.json"))
        trial_ids = {entry.get("trial_id") for entry in trajectory}
        if len(receipt_paths) != 2 or {path.stem for path in receipt_paths} != trial_ids:
            raise ValueError("expected exactly two matching receipt artifacts")
        secret = (campaign / ".receipt-key").read_text().strip()
        for entry in trajectory:
            decision = entry["decision"]
            trial = campaign_trials.get(entry["trial_id"])
            receipt = json.loads((campaign / "receipts" / f"{entry['trial_id']}.json").read_text())
            if not trial or trial.get("query_index") != decision.get("pool_index") or trial.get("config") != decision.get("config") or trial.get("candidate_id") != decision.get("candidate_id"):
                raise ValueError("trajectory Candidate identity does not match Frame")
            if not verify_receipt(receipt, secret) or any(receipt.get(key) != value for key, value in {"campaign_id": manifest.get("campaign_id"), "trial_id": entry["trial_id"], "candidate_id": decision.get("candidate_id"), "request_id": entry.get("request_id"), "status": "succeeded"}.items()):
                raise ValueError("receipt signature or identity is invalid")
        session_path = campaign / "pi-session.jsonl"
        if not session_path.exists():
            raise ValueError("expected an inspectable session trace")
        session_rows = [json.loads(line) for line in session_path.read_text().splitlines() if line.strip()]
        if not session_rows or session_rows[0].get("type") != "session":
            raise ValueError("expected an inspectable session trace")
        config = json.loads((campaign / "campaign-run-config.json").read_text())["revisions"][-1]
        events = json.loads((campaign / "supervisor-events.json").read_text())
        successful_calls = [event.get("toolName") for event in events if event.get("type") == "tool_execution_end" and event.get("result", {}).get("details", {}).get("ok")]
        commit_results = [event for event in events if event.get("type") == "tool_execution_end" and event.get("toolName") == "commit_candidate"]
        if len(commit_results) < 2:
            raise ValueError("expected a complete Supervisor event trace")
        transient_retries = [row["message"]["errorMessage"] for row in session_rows if row.get("type") == "message" and row.get("message", {}).get("role") == "assistant" and row["message"].get("stopReason") == "error" and row["message"].get("errorMessage")]
        first, second = trajectory
        values = [float(first["metrics"][manifest["target"]]), float(second["metrics"][manifest["target"]])]
        incumbent = _historical_incumbent(campaign, manifest["target"])
        decisions = [entry["decision"] for entry in trajectory]
        configs = [decision.get("config") for decision in decisions]
        tool_names = ("lenz_trials", "lenz_candidates", "lenz_diagnostics", "lenz_suggest", "lenz_score", "lenz_predict")
        return {
            "status": "completed",
            "policy": config.get("policy", "default"),
            "seed": manifest["seed"],
            "behavior": {
                "tool_calls": {name: successful_calls.count(name) for name in tool_names},
                "tool_calls_per_step": [{name: decision.get("actual_tool_use", {}).get("calls", []).count(name) for name in tool_names} for decision in decisions],
                "candidate_rows_inspected": sum(decision.get("actual_tool_use", {}).get("candidate_rows", 0) for decision in decisions),
                "acquisition_beta_revisions": successful_calls.count("lenz_set_acqf"),
                "ranked_proposals_consulted": [decision.get("actual_tool_use", {}).get("ranked_proposals_consulted", False) for decision in decisions],
                "surrogate_relationship": [decision.get("surrogate_relationship") for decision in decisions],
                "acquisition_rank": [decision.get("policy_audit", {}).get("acquisition_rank") for decision in decisions],
                "decision_evidence_complete": [decision.get("decision_evidence_complete", config.get("policy", "default") == "default") for decision in decisions],
                "candidate_configs": configs,
            },
            "outcomes": {"first_yield": values[0], "second_yield": values[1], "two_step_best": max(values), "incumbent_improvement": max(values) - incumbent if incumbent is not None else None},
            "integrity": {
                "prompt_hash": config.get("prompt_hash"), "prior_hash": config.get("prior_hash"), "config_hash": config.get("config_hash"),
                "code_revision_hash": config.get("code_revision_hash"), "leakage_gate": config.get("leakage_gate"),
                "candidate_ids": [decision.get("candidate_id") for decision in decisions], "receipts": 2, "receipt_signatures_valid": True, "trajectory_entries": 2, "session_trace": True, "supervisor_event_trace": True,
                "provider_transient_retries": transient_retries,
            },
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return {"status": "failed", "failure": str(exc)}


def experiment_report(root: Path, policies: list[str], seeds: list[int] = EXPERIMENT_SEEDS) -> dict:
    runs = {policy: {str(seed): _experiment_run(root / policy / f"seed-{seed}") for seed in seeds} for policy in policies}
    aggregate = {}
    for policy, rows_by_seed in runs.items():
        completed = [row for row in rows_by_seed.values() if row["status"] == "completed"]
        best = [row["outcomes"]["two_step_best"] for row in completed]
        first = [row["outcomes"]["first_yield"] for row in completed]
        second = [row["outcomes"]["second_yield"] for row in completed]
        configs = [json.dumps(config, sort_keys=True) for row in completed for config in row["behavior"]["candidate_configs"]]
        first_configs = [json.dumps(row["behavior"]["candidate_configs"][0], sort_keys=True) for row in completed]
        aggregate[policy] = {
            "completed": len(completed), "failures": len(rows_by_seed) - len(completed),
            "behavior": {"unique_candidates_first_step": len(set(first_configs)), "unique_candidates_all_steps": len(set(configs)), "tool_calls": {name: sum(row["behavior"]["tool_calls"][name] for row in completed) for name in ("lenz_trials", "lenz_candidates", "lenz_diagnostics", "lenz_suggest", "lenz_score", "lenz_predict")}},
            "outcomes": {"first_yield": {"mean": mean(first), "median": median(first), "minimum": min(first)}, "second_yield": {"mean": mean(second), "median": median(second), "minimum": min(second)}, "two_step_best": {"mean": mean(best), "median": median(best), "minimum": min(best)}} if completed else None,
            "integrity": {"all_completed_have_two_receipts": all(row["integrity"]["receipts"] == 2 for row in completed), "failure_reasons": [row["failure"] for row in rows_by_seed.values() if row["status"] == "failed"]},
        }
    return {"seeds": seeds, "runs": runs, "aggregate": aggregate, "note": "Descriptive five-seed comparison; no statistical significance or cross-dataset superiority is claimed."}

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path)
    parser.add_argument("--gp", type=Path)
    parser.add_argument("--target", default="Yield")
    parser.add_argument("--seeds", nargs="*", type=int)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--experiment-root", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--policies", nargs="*", choices=sorted(EXPERIMENT_POLICIES))
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.experiment_root:
        policies = args.policies or ["default", "autonomous_agent"]
        if args.plan and not args.dataset:
            parser.error("--plan requires --dataset")
        summary = experiment_run_plan(args.experiment_root, args.dataset, policies) if args.plan else experiment_report(args.experiment_root, policies, args.seeds or EXPERIMENT_SEEDS)
    elif args.labels:
        if not args.agent or not args.gp or not args.seeds:
            parser.error("--labels requires --agent, --gp, and --seeds")
        summary = benchmark_report(args.agent, args.gp, args.seeds, args.target, args.labels)
    else:
        if not args.agent or not args.gp:
            parser.error("--agent and --gp are required outside experiment mode")
        summary = summarize_many(args.agent, args.gp, args.seeds, args.target) if args.seeds else summarize_pair(args.agent, args.gp, args.target)
    rendered = json.dumps(summary, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered)

if __name__ == "__main__":
    main()
