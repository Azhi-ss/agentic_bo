from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
import torch
from dotenv import load_dotenv

from .state import Study

def parse_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError(f"pi returned no JSON object: {text[-500:]}")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("pi decision must be a JSON object")
    return value


def run_pi(prompt: str, project_root: Path, model: str) -> dict[str, Any]:
    load_dotenv(project_root / ".env")
    env = os.environ.copy()
    env["PI_CODING_AGENT_DIR"] = str(project_root / ".pi")
    command = [
        "pi",
        "--provider",
        "ai-modeling",
        "--model",
        model,
        "--tools",
        "read,bash",
        "--thinking",
        "high",
        "--system-prompt",
        (project_root / "src/boagent/SYSTEM.md").read_text(),
        "--append-system-prompt",
        (project_root / "src/boagent/LENZ_REF.md").read_text(),
        "--no-session",
        "-p",
        prompt,
    ]
    with tempfile.TemporaryDirectory(prefix="boagent-pi-") as sandbox:
        completed = subprocess.run(command, cwd=sandbox, env=env, text=True, capture_output=True, check=True)
    return parse_json(completed.stdout)


def run_command(command: list[str], project_root: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=project_root, text=True, capture_output=True, check=True)
    response = json.loads(completed.stdout)
    if response.get("ok") is False:
        raise RuntimeError(response["error"])
    return response.get("result", response)


def oracle_query(dataset_root: Path, state_path: Path, index: int, project_root: Path) -> dict[str, float]:
    completed = subprocess.run(
        ["uv", "run", "--project", str(project_root), "boagent-oracle", "--dataset-root", str(dataset_root), "--state", str(state_path), "--query-index", str(index)],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return {key: float(value) for key, value in json.loads(completed.stdout)["metrics"].items()}


def run_campaign(dataset_root: Path, output: Path, seed: int, budget: int, model: str, project_root: Path) -> dict[str, Any]:
    from .cli import config_at

    state_path = output / "state.json"
    output.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        raise FileExistsError(state_path)
    train = pd.read_csv(dataset_root / "train.csv")
    candidates = pd.read_csv(dataset_root / "test_features.csv")
    target = train.columns[-1]
    features = candidates.columns.tolist()
    run_command(["uv", "run", "--project", str(project_root), "lenz", "create", "--state", str(state_path), "--dataset-root", str(dataset_root), "--target", target, "--direction", "maximize", "--seed", str(seed)], project_root)
    trajectory: list[dict[str, Any]] = []
    task_context = (dataset_root / "README.md").read_text()
    for step in range(1, budget + 1):
        study = Study.load(state_path)
        available = [index for index in candidates.index if index not in study.submitted]
        if not available:
            break
        from .backend import acquisition_values, encode_frame, fit_surrogate, posterior_rows
        import numpy as np

        fitted = fit_surrogate(study, candidates)
        x = encode_frame(candidates.loc[available, features], study)
        scores = acquisition_values(fitted, x, study.acqf, study.beta)
        mean, variance = posterior_rows(fitted, x, study.direction)
        menu_positions = np.argsort(scores)[-12:][::-1]
        menu = [
            {
                "query_index": int(available[pos]),
                "config": config_at(candidates, int(available[pos]), features),
                "posterior_mean": float(mean[pos]),
                "posterior_variance": float(variance[pos]),
                "acquisition_value": float(scores[pos]),
            }
            for pos in menu_positions
        ]
        recent = trajectory[-5:]
        prompt = f"""This is one externally orchestrated decision step. Do not call tools: the supplied evidence is complete and tools cannot access the campaign sandbox. Return the requested JSON object and no prose.

Run campaign step {step}/{budget}. This is a strict black-box offline evaluation.

Domain context:
{task_context}

Recent real observations:
{json.dumps(recent, ensure_ascii=False)}

Current candidate menu from lenz:
{json.dumps(menu, ensure_ascii=False)}

Choose a menu index, or propose an exact public-pool configuration from the domain options.
Return exactly: {{"query_index": <menu index or null>, "config": <exact feature mapping or null>, "rationale": "short evidence-based reason"}}
"""
        decision = run_pi(prompt, project_root, model)
        if decision.get("config") is not None:
            matches = candidates.index[(candidates[features] == pd.Series(decision["config"])).all(axis=1)].tolist()
            matches = [candidate for candidate in matches if candidate in available]
            if not matches:
                raise ValueError("pi proposed a config outside the remaining public pool")
            index = int(matches[0])
        else:
            index = int(decision["query_index"])
        if index not in available:
            raise ValueError(f"pi selected unavailable index: {index}")
        run_command(["uv", "run", "--project", str(project_root), "lenz", "submit", "--state", str(state_path), "--query-index", str(index)], project_root)
        metrics = oracle_query(dataset_root, state_path, index, project_root)
        run_command(["uv", "run", "--project", str(project_root), "lenz", "observe", "--state", str(state_path), "--query-index", str(index), "--metrics", json.dumps(metrics)], project_root)
        chosen = next((item for item in menu if item["query_index"] == index), None)
        trajectory.append({"step": step, "query_index": index, "condition": candidates.loc[index, features].to_dict(), "observed_yield": metrics[target], "predicted_yield": chosen["posterior_mean"] if chosen else None, "rationale": decision["rationale"], "acqf": study.acqf})
    result = {"seed": seed, "dataset": dataset_root.name, "trajectory": trajectory}
    torch.save(result, output / f"seed_{seed}.pt")
    return result
