import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from boagent.oracle import receipt_signature, verify_receipt
from boagent.state import Study, Trial

from test_cli_contract import create_state, runner


SECRET = "test-receipt-secret"


def receipt_for(payload: dict, secret: str = SECRET) -> dict:
    signed = copy.deepcopy(payload)
    signed["signature"] = receipt_signature(signed, secret)
    return signed


def valid_receipt(study: Study, trial: Trial) -> dict:
    return receipt_for({
        "receipt_id": "receipt-1",
        "campaign_id": study.campaign_id,
        "trial_id": trial.trial_id,
        "candidate_id": trial.candidate_id,
        "request_id": trial.request_id,
        "status": "succeeded",
        "metrics": {"Yield": 55.0},
    })


class ReceiptSignatureTest(unittest.TestCase):
    def test_signature_roundtrip_and_verify(self) -> None:
        payload = {"campaign_id": "c", "trial_id": "t", "metrics": {"Yield": 1.0}}
        signed = receipt_for(payload)
        self.assertTrue(verify_receipt(signed, SECRET))
        self.assertFalse(verify_receipt(signed, "wrong-secret"))
        self.assertFalse(verify_receipt({}, SECRET))

    def test_signature_changes_with_any_field(self) -> None:
        base = {"campaign_id": "c", "trial_id": "t", "metrics": {"Yield": 1.0}}
        signed = receipt_for(base)
        # mutate every field -> signature must no longer verify
        for key in base:
            mutated = copy.deepcopy(signed)
            mutated[key] = "CHANGED"
            self.assertFalse(verify_receipt(mutated, SECRET), f"field {key} mutation not detected")
        # missing signature
        stripped = copy.deepcopy(signed)
        stripped.pop("signature")
        self.assertFalse(verify_receipt(stripped, SECRET))


class ObserveReceiptContractTest(unittest.TestCase):
    def _pending_state(self, root: Path) -> Path:
        state = create_state(root)
        study = Study.load(state)
        study.trials.append(Trial(
            trial_id="trial-1", candidate_id="cand-1", query_index=0,
            config={"ligand": "PPh3", "base": "KOH"}, status="pending",
            request_id="req-1",
        ))
        study.save(state)
        return state

    def test_observe_applies_valid_receipt(self) -> None:
        with TemporaryDirectory() as directory:
            state = self._pending_state(Path(directory))
            study = Study.load(state)
            trial = study.trial("trial-1")
            receipt = valid_receipt(study, trial)
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))

            with patch.dict(os.environ, {"BOAGENT_RECEIPT_KEY": SECRET}):
                result = runner.invoke(app := __import__("boagent.cli", fromlist=["app"]).app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(receipt_path)])

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)["result"]
            self.assertEqual(payload["status"], "observed")
            self.assertEqual(payload["metrics"], {"Yield": 55.0})
            self.assertEqual(payload["receipt_id"], "receipt-1")

    def test_observe_rejects_tampered_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            state = self._pending_state(Path(directory))
            study = Study.load(state)
            trial = study.trial("trial-1")
            receipt = valid_receipt(study, trial)
            receipt["metrics"] = {"Yield": 99.0}
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))

            with patch.dict(os.environ, {"BOAGENT_RECEIPT_KEY": SECRET}):
                result = runner.invoke(__import__("boagent.cli", fromlist=["app"]).app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(receipt_path)])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("receipt signature is invalid", result.output)

    def test_observe_rejects_wrong_secret(self) -> None:
        with TemporaryDirectory() as directory:
            state = self._pending_state(Path(directory))
            study = Study.load(state)
            trial = study.trial("trial-1")
            receipt = valid_receipt(study, trial)
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))

            with patch.dict(os.environ, {"BOAGENT_RECEIPT_KEY": "different-secret"}):
                result = runner.invoke(__import__("boagent.cli", fromlist=["app"]).app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(receipt_path)])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("receipt signature is invalid", result.output)

    def test_observe_rejects_cross_campaign_identity(self) -> None:
        with TemporaryDirectory() as directory:
            state = self._pending_state(Path(directory))
            study = Study.load(state)
            trial = study.trial("trial-1")
            receipt = valid_receipt(study, trial)
            receipt["campaign_id"] = "other-campaign"
            # resign so only the identity check fires (signature valid, identity wrong)
            receipt = receipt_for(receipt)
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))

            with patch.dict(os.environ, {"BOAGENT_RECEIPT_KEY": SECRET}):
                result = runner.invoke(__import__("boagent.cli", fromlist=["app"]).app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(receipt_path)])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("receipt identity does not match trial", result.output)

    def test_observe_rejects_wrong_trial_id_identity(self) -> None:
        with TemporaryDirectory() as directory:
            state = self._pending_state(Path(directory))
            study = Study.load(state)
            trial = study.trial("trial-1")
            receipt = valid_receipt(study, trial)
            receipt["trial_id"] = "trial-999"
            receipt = receipt_for(receipt)
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))

            with patch.dict(os.environ, {"BOAGENT_RECEIPT_KEY": SECRET}):
                result = runner.invoke(__import__("boagent.cli", fromlist=["app"]).app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(receipt_path)])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("receipt identity does not match trial", result.output)

    def test_observe_rejects_non_succeeded_receipt(self) -> None:
        with TemporaryDirectory() as directory:
            state = self._pending_state(Path(directory))
            study = Study.load(state)
            trial = study.trial("trial-1")
            receipt = valid_receipt(study, trial)
            receipt["status"] = "failed"
            receipt = receipt_for(receipt)
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))

            with patch.dict(os.environ, {"BOAGENT_RECEIPT_KEY": SECRET}):
                result = runner.invoke(__import__("boagent.cli", fromlist=["app"]).app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(receipt_path)])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("receipt is not successful", result.output)

    def test_observe_is_idempotent_for_same_receipt(self) -> None:
        with TemporaryDirectory() as directory:
            state = self._pending_state(Path(directory))
            study = Study.load(state)
            trial = study.trial("trial-1")
            receipt = valid_receipt(study, trial)
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))

            with patch.dict(os.environ, {"BOAGENT_RECEIPT_KEY": SECRET}):
                first = runner.invoke(__import__("boagent.cli", fromlist=["app"]).app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(receipt_path)])
                second = runner.invoke(__import__("boagent.cli", fromlist=["app"]).app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(receipt_path)])

            self.assertEqual(first.exit_code, 0, first.output)
            self.assertEqual(second.exit_code, 0, second.output)
            self.assertEqual(json.loads(first.output)["result"]["status"], "observed")
            self.assertEqual(json.loads(second.output)["result"]["status"], "observed")

    def test_observe_rejects_second_receipt_for_observed_trial(self) -> None:
        with TemporaryDirectory() as directory:
            state = self._pending_state(Path(directory))
            study = Study.load(state)
            trial = study.trial("trial-1")
            first_receipt = valid_receipt(study, trial)
            first_path = Path(directory) / "receipt1.json"
            first_path.write_text(json.dumps(first_receipt))

            # different receipt_id for same trial -> rejected after already observed
            second_receipt = receipt_for({
                **first_receipt, "receipt_id": "receipt-2",
            })
            second_path = Path(directory) / "receipt2.json"
            second_path.write_text(json.dumps(second_receipt))

            with patch.dict(os.environ, {"BOAGENT_RECEIPT_KEY": SECRET}):
                app = __import__("boagent.cli", fromlist=["app"]).app
                runner.invoke(app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(first_path)])
                second = runner.invoke(app, ["observe", "--state", str(state), "--trial-id", "trial-1", "--receipt", str(second_path)])

            self.assertNotEqual(second.exit_code, 0)
            self.assertIn("already observed with a different receipt", second.output)


if __name__ == "__main__":
    unittest.main()
