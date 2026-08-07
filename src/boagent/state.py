from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FRAME_VERSION = 1


def now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def candidate_id(config: dict[str, Any], query_index: int | None = None) -> str:
    identity = config if query_index is None else {"pool_index": query_index, "config": config}
    return hashlib.sha256(canonical_json(identity).encode()).hexdigest()


@dataclass
class Trial:
    trial_id: str
    candidate_id: str
    query_index: int
    config: dict[str, Any]
    status: str
    source: str = "campaign"
    request_id: str | None = None
    receipt_id: str | None = None
    metrics: dict[str, float] | None = None
    submitted_at: str | None = None
    observed_at: str | None = None


@dataclass
class Study:
    study_id: str
    campaign_id: str
    public_root: str
    target: str
    direction: str
    seed: int
    budget: int
    features: list[str]
    categories: dict[str, list[Any]]
    initial: list[dict[str, Any]]
    trials: list[Trial] = field(default_factory=list)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    frame_version: int = FRAME_VERSION
    state_revision: int = 0
    configuration_revision: int = 1
    acqf: str = "noisy_logei"
    beta: float = 2.0

    @classmethod
    def load(cls, path: Path) -> Study:
        raw = json.loads(path.read_text())
        raw["trials"] = [Trial(**trial) for trial in raw.get("trials", [])]
        return cls(**raw)

    def append_event(self, event_type: str, **payload: Any) -> None:
        self.event_log.append({"event_id": str(uuid.uuid4()), "type": event_type, "at": now(), **payload})

    def save(self, path: Path) -> None:
        self.state_revision += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2, allow_nan=False)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @property
    def submitted(self) -> set[int]:
        return {trial.query_index for trial in self.trials}

    @property
    def pending(self) -> list[Trial]:
        return [trial for trial in self.trials if trial.status == "pending"]

    @property
    def observed(self) -> list[Trial]:
        return [trial for trial in self.trials if trial.status == "observed"]

    def trial(self, trial_id: str) -> Trial:
        matches = [trial for trial in self.trials if trial.trial_id == trial_id]
        if len(matches) != 1:
            raise ValueError(f"unknown trial_id: {trial_id}")
        return matches[0]


def envelope(command: str, result: Any = None, error: str | None = None, study: Study | None = None) -> str:
    base: dict[str, Any] = {
        "ok": error is None,
        "command": command,
        "schema_version": 1,
    }
    if study is not None:
        base.update(
            study_id=study.study_id,
            state_revision=study.state_revision,
            configuration_revision=study.configuration_revision,
        )
    if error is None:
        base["result"] = result
    else:
        base["error"] = {"code": "COMMAND_ERROR", "message": error, "details": {}}
    return json.dumps(base, ensure_ascii=False, allow_nan=False)
