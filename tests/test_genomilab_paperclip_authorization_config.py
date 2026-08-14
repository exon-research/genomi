from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.paperclip_authorization_config import (
    PaperclipAuthorizationConfigError,
    load_paperclip_authorization_config,
)
from genomi.lab.provider_policy import (
    AuthorizationBasis,
    EvidenceDataClass,
    SourceFamily,
)


def _deployment_authorization() -> dict[str, object]:
    return {
        "provider": "paperclip",
        "authorization_id": "gxl-written-authorization-2026-08",
        "basis": "written_provider_authorization",
        "permitted_source_families": ["literature", "regulatory"],
        "permitted_operations": ["search", "lookup"],
        "permitted_purposes": [
            "Verify public Paperclip connection",
            "Investigate disease relevance against the approved molecular profile",
        ],
        "permitted_data_classes": [
            "public_query",
            "patient_influenced_public_evidence_query",
        ],
        "effective_at": "2026-08-01T00:00:00Z",
        "expires_at": "2027-08-01T00:00:00Z",
        "revoked_at": None,
        "policy_version_id": "paperclip-policy-2026-08",
        "aup_version_id": "paperclip-aup-2026-08",
        "terms_version_id": "paperclip-terms-2026-08",
        "privacy_version_id": "paperclip-privacy-2026-08",
        "live_use_authorized": True,
    }


def _patient_data_contract() -> dict[str, object]:
    return {
        "provider": "paperclip",
        "contract_id": "gxl-patient-data-contract-2026-08",
        "permitted_source_families": ["literature"],
        "permitted_operations": ["search"],
        "permitted_purposes": [
            "Investigate disease relevance against the approved molecular profile"
        ],
        "permitted_data_classes": ["patient_influenced_public_evidence_query"],
        "effective_at": "2026-08-01T00:00:00Z",
        "expires_at": "2027-08-01T00:00:00Z",
        "revoked_at": None,
        "policy_version_id": "paperclip-patient-policy-2026-08",
        "aup_version_id": "paperclip-patient-aup-2026-08",
        "terms_version_id": "paperclip-patient-terms-2026-08",
        "privacy_version_id": "paperclip-patient-privacy-2026-08",
        "patient_influenced_data_authorized": True,
    }


class PaperclipAuthorizationConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "paperclip-authorization.json"

    def _write(self, payload: object) -> None:
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def test_loads_owner_policy_and_keeps_patient_contract_independent(self) -> None:
        self._write({"deployment_authorization": _deployment_authorization()})

        loaded = load_paperclip_authorization_config(self.path)

        self.assertEqual(loaded.deployment_authorization.provider, "paperclip")
        self.assertEqual(
            loaded.deployment_authorization.basis,
            AuthorizationBasis.WRITTEN_PROVIDER_AUTHORIZATION,
        )
        self.assertEqual(
            loaded.deployment_authorization.permitted_source_families,
            frozenset({SourceFamily.LITERATURE, SourceFamily.REGULATORY}),
        )
        self.assertIn(
            EvidenceDataClass.PUBLIC_QUERY,
            loaded.deployment_authorization.permitted_data_classes,
        )
        self.assertIsNone(loaded.patient_data_contract)

    def test_loads_separately_scoped_patient_data_contract_when_supplied(self) -> None:
        self._write(
            {
                "deployment_authorization": _deployment_authorization(),
                "patient_data_contract": _patient_data_contract(),
            }
        )

        loaded = load_paperclip_authorization_config(self.path)

        self.assertIsNotNone(loaded.patient_data_contract)
        assert loaded.patient_data_contract is not None
        self.assertEqual(
            loaded.patient_data_contract.permitted_operations,
            frozenset({"search"}),
        )
        self.assertEqual(
            loaded.patient_data_contract.permitted_data_classes,
            frozenset({EvidenceDataClass.PATIENT_INFLUENCED_PUBLIC_EVIDENCE_QUERY}),
        )

    def test_rejects_duplicate_unknown_and_self_attestation_fields(self) -> None:
        deployment = json.dumps(_deployment_authorization())
        self.path.write_text(
            "{"
            f'"deployment_authorization":{deployment},'
            f'"deployment_authorization":{deployment}'
            "}",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            PaperclipAuthorizationConfigError, "duplicate field"
        ):
            load_paperclip_authorization_config(self.path)

        for field, value in (
            ("accepted_terms", True),
            ("api_key", "must-never-live-here"),
            ("secret-used-as-a-field-name", True),
        ):
            with self.subTest(field=field):
                payload = {"deployment_authorization": _deployment_authorization()}
                payload[field] = value
                self._write(payload)
                with self.assertRaisesRegex(
                    PaperclipAuthorizationConfigError, "unsupported field"
                ) as raised:
                    load_paperclip_authorization_config(self.path)
                self.assertNotIn("must-never-live-here", str(raised.exception))
                self.assertNotIn(field, str(raised.exception))

    def test_rejects_wrong_types_scope_and_timestamps(self) -> None:
        mutations: tuple[tuple[str, object], ...] = (
            ("provider", "another-provider"),
            ("permitted_operations", ["search", "execute"]),
            ("permitted_source_families", "literature"),
            ("effective_at", "2026-08-01T00:00:00"),
            ("live_use_authorized", 1),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                deployment = _deployment_authorization()
                deployment[field] = value
                self._write({"deployment_authorization": deployment})
                with self.assertRaises(PaperclipAuthorizationConfigError):
                    load_paperclip_authorization_config(self.path)

        inconsistent = _deployment_authorization()
        inconsistent["expires_at"] = "2026-07-01T00:00:00Z"
        self._write({"deployment_authorization": inconsistent})
        with self.assertRaisesRegex(
            PaperclipAuthorizationConfigError, "internally inconsistent"
        ):
            load_paperclip_authorization_config(self.path)

        self._write(
            {
                "deployment_authorization": _deployment_authorization(),
                "patient_data_contract": None,
            }
        )
        with self.assertRaisesRegex(
            PaperclipAuthorizationConfigError, "patient_data_contract"
        ):
            load_paperclip_authorization_config(self.path)

    def test_rejects_missing_deployment_authorization_and_oversized_input(self) -> None:
        self._write({"patient_data_contract": _patient_data_contract()})
        with self.assertRaisesRegex(
            PaperclipAuthorizationConfigError, "deployment_authorization"
        ):
            load_paperclip_authorization_config(self.path)

        self.path.write_bytes(b" " * (64 * 1024 + 1))
        with self.assertRaisesRegex(PaperclipAuthorizationConfigError, "too large"):
            load_paperclip_authorization_config(self.path)

    def test_rejects_replaceable_or_indirect_authorization_files(self) -> None:
        self._write({"deployment_authorization": _deployment_authorization()})
        self.path.chmod(0o666)
        with self.assertRaisesRegex(
            PaperclipAuthorizationConfigError, "group- or world-writable"
        ):
            load_paperclip_authorization_config(self.path)

        self.path.chmod(0o600)
        link = self.path.with_name("paperclip-authorization-link.json")
        try:
            link.symlink_to(self.path)
        except (NotImplementedError, OSError):
            self.skipTest("symlinks are unavailable on this platform")
        with self.assertRaises(PaperclipAuthorizationConfigError):
            load_paperclip_authorization_config(link)

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX ownership check")
    def test_owner_check_accepts_the_current_user(self) -> None:
        self._write({"deployment_authorization": _deployment_authorization()})
        self.path.chmod(0o640)

        loaded = load_paperclip_authorization_config(self.path)

        self.assertEqual(loaded.deployment_authorization.provider, "paperclip")

    @unittest.skipUnless(hasattr(os, "O_NONBLOCK"), "POSIX non-blocking file open")
    def test_opens_candidate_nonblocking_before_checking_file_type(self) -> None:
        self._write({"deployment_authorization": _deployment_authorization()})

        with mock.patch(
            "genomi.lab.paperclip_authorization_config.os.open", wraps=os.open
        ) as open_file:
            load_paperclip_authorization_config(self.path)

        flags = open_file.call_args.args[1]
        self.assertTrue(flags & os.O_NONBLOCK)


if __name__ == "__main__":
    unittest.main()
