from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path

import pandas as pd
import typer

from .state import Study, canonical_json, now

app = typer.Typer(add_completion=False, no_args_is_help=True)


def receipt_signature(payload: dict[str, object], secret: str) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    return hmac.new(secret.encode(), canonical_json(unsigned).encode(), hashlib.sha256).hexdigest()


def verify_receipt(payload: dict[str, object], secret: str) -> bool:
    signature = payload.get("signature")
    return isinstance(signature, str) and hmac.compare_digest(signature, receipt_signature(payload, secret))


@app.command()
def run(
    dataset_root: Path = typer.Option(..., hidden=True),
    state: Path = typer.Option(..., hidden=True),
    trial_id: str = typer.Option(...),
    request_id: str = typer.Option(...),
    receipts: Path = typer.Option(..., hidden=True),
) -> None:
    """Trusted idempotent execution for one pending Trial."""
    secret = os.environ.get("BOAGENT_RECEIPT_KEY")
    if not secret:
        raise RuntimeError("BOAGENT_RECEIPT_KEY is required")
    study = Study.load(state)
    dataset_root = Path(study.public_root).resolve()
    trial = study.trial(trial_id)
    if trial.status not in {"pending", "observed"}:
        raise typer.BadParameter("trial is not executable")
    if trial.request_id != request_id:
        raise typer.BadParameter("request_id does not match trial")
    receipts.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts / f"{trial_id}.json"
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text())
        if not verify_receipt(existing, secret):
            raise RuntimeError("existing receipt signature is invalid")
        expected = {
            "campaign_id": study.campaign_id,
            "trial_id": trial.trial_id,
            "candidate_id": trial.candidate_id,
            "request_id": request_id,
            "status": "succeeded",
        }
        if any(existing.get(key) != value for key, value in expected.items()):
            raise RuntimeError("existing receipt conflicts with trial")
        typer.echo(json.dumps({"ok": True, "receipt": str(receipt_path), "result": existing}, ensure_ascii=False))
        return
    public = pd.read_csv(dataset_root / "test_features.csv")
    private = pd.read_csv(dataset_root / "test.csv")
    if trial.query_index < 0 or trial.query_index >= len(public):
        raise typer.BadParameter("trial pool index is out of range")
    features = public.columns.tolist()
    if trial.config != public.loc[trial.query_index, features].to_dict():
        raise RuntimeError("trial config does not match public candidate")
    if private.loc[trial.query_index, features].to_dict() != trial.config:
        raise RuntimeError("public/private candidate rows do not match")
    metrics = {column: float(private.loc[trial.query_index, column]) for column in private.columns if column not in features}
    started_at = now()
    payload: dict[str, object] = {
        "receipt_id": str(uuid.uuid4()),
        "campaign_id": study.campaign_id,
        "trial_id": trial.trial_id,
        "candidate_id": trial.candidate_id,
        "request_id": request_id,
        "oracle_profile": "offline-csv-v1",
        "started_at": started_at,
        "completed_at": now(),
        "status": "succeeded",
        "metrics": metrics,
        "metrics_sha256": hashlib.sha256(canonical_json(metrics).encode()).hexdigest(),
        "oracle_response_sha256": hashlib.sha256(canonical_json({"trial_id": trial_id, "metrics": metrics}).encode()).hexdigest(),
        "previous_receipt_hash": None,
    }
    payload["signature"] = receipt_signature(payload, secret)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    typer.echo(json.dumps({"ok": True, "receipt": str(receipt_path), "result": payload}, ensure_ascii=False))


if __name__ == "__main__":
    app()
