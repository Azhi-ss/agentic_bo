from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Objective(StrictModel):
    target: str = Field(min_length=1)
    direction: Literal["maximize", "minimize"]


class Experiment(StrictModel):
    name: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    output: str = Field(min_length=1)
    policies: list[Literal["default", "autonomous_agent"]] = Field(min_length=1)
    seeds: list[int] = Field(min_length=1)
    budget: int = Field(gt=0)
    objective: Objective

    @field_validator("policies", "seeds")
    @classmethod
    def unique(cls, values: list[object]) -> list[object]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate values are not allowed")
        return values


class Acquisition(StrictModel):
    name: Literal["noisy_logei", "logei", "ucb", "sobol"]
    beta: float

    @field_validator("beta")
    @classmethod
    def valid_beta(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("must be finite and non-negative")
        return value


class RuntimeDefaults(StrictModel):
    acquisition: Acquisition


class Runtime(StrictModel):
    provider: Literal["ai-modeling"]
    model: str = Field(min_length=1)
    thinking: str = Field(min_length=1)
    defaults: RuntimeDefaults


class ExperimentConfig(StrictModel):
    schema_version: Literal[1]
    experiment: Experiment
    runtime: Runtime


@dataclass(frozen=True)
class LoadedExperiment:
    config_path: Path
    config: ExperimentConfig
    dataset_path: Path
    output_path: Path
    source_config_hash: str
    normalized_config_hash: str

    def runs(self) -> list[dict[str, object]]:
        experiment = self.config.experiment
        runtime = self.config.runtime
        acquisition = runtime.defaults.acquisition
        return [
            {
                "experiment_name": experiment.name,
                "policy": policy,
                "seed": seed,
                "budget": experiment.budget,
                "target": experiment.objective.target,
                "direction": experiment.objective.direction,
                "provider": runtime.provider,
                "model": runtime.model,
                "thinking": runtime.thinking,
                "provider_generation_seed": "unavailable",
                "dataset": str(self.dataset_path),
                "output": str(self.output_path / policy / f"seed-{seed}"),
                "initial_acquisition": {"name": acquisition.name, "beta": acquisition.beta},
                "preflight": "mandatory_fail_closed_before_provider_startup",
            }
            for policy in experiment.policies
            for seed in experiment.seeds
        ]

    def public_plan(self) -> dict[str, object]:
        experiment = self.config.experiment
        public_runs = [{
            **run,
            "dataset": _authored_path(experiment.dataset),
            "output": str(PurePosixPath(_authored_path(experiment.output)) / str(run["policy"]) / f"seed-{run['seed']}"),
        } for run in self.runs()]
        return {
            "schema_version": self.config.schema_version,
            "experiment_name": experiment.name,
            "source_config": self.config_path.name,
            "source_config_hash": self.source_config_hash,
            "normalized_config_hash": self.normalized_config_hash,
            "runs": public_runs,
        }


def _authored_path(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix()


def _validation_error(error: ValidationError) -> ValueError:
    details = []
    for item in error.errors(include_input=False, include_url=False, include_context=False):
        path = ".".join(str(part) for part in item["loc"])
        details.append(f"{path}: {item['msg']}")
    return ValueError("invalid experiment config: " + "; ".join(details))


def load_experiment_config(path: Path, *, check_output_collisions: bool = True) -> LoadedExperiment:
    config_path = path.resolve()
    source = config_path.read_bytes()
    try:
        parsed = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise ValueError("invalid experiment config YAML") from error
    if not isinstance(parsed, dict):
        raise ValueError("invalid experiment config: root must be a mapping")
    try:
        config = ExperimentConfig.model_validate(parsed)
    except ValidationError as error:
        raise _validation_error(error) from error

    dataset = (config_path.parent / config.experiment.dataset).resolve()
    output = (config_path.parent / config.experiment.output).resolve()
    if not dataset.is_dir():
        raise ValueError("experiment.dataset: dataset directory does not exist")
    for name in ("test_features.csv", "options.json"):
        if not (dataset / name).is_file():
            raise ValueError(f"experiment.dataset: missing public input {name}")
    import pandas as pd
    candidates = pd.read_csv(dataset / "test_features.csv")
    train_path = dataset / "train.csv"
    if train_path.exists():
        train = pd.read_csv(train_path)
        if list(train.columns[:-1]) != candidates.columns.tolist() or train.columns[-1] != config.experiment.objective.target:
            raise ValueError("experiment.dataset: train/test_features schema mismatch")
    try:
        options = json.loads((dataset / "options.json").read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError("experiment.dataset: invalid options.json") from error
    if any(feature not in options for feature in candidates.columns):
        raise ValueError("experiment.dataset: options.json missing public features")

    semantic = config.model_dump(mode="json")
    semantic["experiment"]["dataset"] = _authored_path(config.experiment.dataset)
    semantic["experiment"]["output"] = _authored_path(config.experiment.output)
    normalized = json.dumps(semantic, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    loaded = LoadedExperiment(
        config_path=config_path,
        config=config,
        dataset_path=dataset,
        output_path=output,
        source_config_hash=hashlib.sha256(source).hexdigest(),
        normalized_config_hash=hashlib.sha256(normalized).hexdigest(),
    )
    if check_output_collisions:
        for run in loaded.runs():
            campaign = Path(str(run["output"]))
            if campaign.exists():
                raise FileExistsError(f"campaign directory already exists: {campaign}")
    return loaded
