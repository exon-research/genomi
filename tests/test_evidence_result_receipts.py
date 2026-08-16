from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.operations.registry.evidence_result_receipts import (
    EVIDENCE_RESULT_RECEIPTS,
    EvidenceResultReceiptError,
)


class EvidenceResultReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self.genomi_home = Path(self._temporary_home.name) / "genomi-home"
        self._environment = mock.patch.dict(
            os.environ, {"GENOMI_HOME": str(self.genomi_home)}, clear=False
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        EVIDENCE_RESULT_RECEIPTS.clear()
        self.addCleanup(EVIDENCE_RESULT_RECEIPTS.clear)

    def test_child_process_receipt_is_redeemed_once_by_parent(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(repository_root / "src")
        issued = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from genomi.operations.registry.evidence_result_receipts "
                    "import EVIDENCE_RESULT_RECEIPTS; "
                    "print(EVIDENCE_RESULT_RECEIPTS.issue("
                    "session_id='session-a', "
                    "operation='paperclip.search_biomedical', "
                    "params={'query': 'synthetic mechanism'}, "
                    "result={'records': [{'title': 'Exact child result'}]}))"
                ),
            ],
            cwd=repository_root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        receipt_id = issued.stdout.strip()

        receipt_path = (
            self.genomi_home
            / "runtime"
            / "evidence-result-receipts"
            / f"{receipt_id}.json"
        )
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(receipt_path.parent.stat().st_mode), 0o700)

        with self.assertRaisesRegex(
            EvidenceResultReceiptError, "different session"
        ):
            EVIDENCE_RESULT_RECEIPTS.resolve(
                receipt_id, session_id="session-b"
            )

        captured = EVIDENCE_RESULT_RECEIPTS.redeem(
            receipt_id,
            session_id="session-a",
            consumer=lambda receipt: {
                "captured_operation": receipt["operation"],
                "captured_result": receipt["result"],
            },
        )
        self.assertEqual(
            captured,
            {
                "captured_operation": "paperclip.search_biomedical",
                "captured_result": {
                    "records": [{"title": "Exact child result"}]
                },
            },
        )
        self.assertFalse(receipt_path.exists())
        with self.assertRaisesRegex(
            EvidenceResultReceiptError, "unknown or expired"
        ):
            EVIDENCE_RESULT_RECEIPTS.resolve(
                receipt_id, session_id="session-a"
            )

    def test_tampered_payload_is_rejected(self) -> None:
        receipt_id = EVIDENCE_RESULT_RECEIPTS.issue(
            session_id="session-a",
            operation="paperclip.search_biomedical",
            params={"query": "original"},
            result={"records": [{"title": "Original"}]},
        )
        receipt_path = (
            self.genomi_home
            / "runtime"
            / "evidence-result-receipts"
            / f"{receipt_id}.json"
        )
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        payload["result"]["records"][0]["title"] = "Tampered"
        receipt_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            EvidenceResultReceiptError, "invalid or tampered"
        ):
            EVIDENCE_RESULT_RECEIPTS.resolve(
                receipt_id, session_id="session-a"
            )

    def test_failed_consumer_does_not_redeem_receipt(self) -> None:
        receipt_id = EVIDENCE_RESULT_RECEIPTS.issue(
            session_id="session-a",
            operation="paperclip.search_biomedical",
            params={"query": "retryable"},
            result={"records": []},
        )

        def fail(_receipt: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("durable write failed")

        with self.assertRaisesRegex(RuntimeError, "durable write failed"):
            EVIDENCE_RESULT_RECEIPTS.redeem(
                receipt_id,
                session_id="session-a",
                consumer=fail,
            )

        resolved = EVIDENCE_RESULT_RECEIPTS.resolve(
            receipt_id, session_id="session-a"
        )
        self.assertEqual(resolved["params"], {"query": "retryable"})


if __name__ == "__main__":
    unittest.main()
