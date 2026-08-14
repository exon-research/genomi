from __future__ import annotations

import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from genomi.lab.provider_credentials import (
    BIOHUB_ESM_PROVIDER_ID,
    PAPERCLIP_PROVIDER_ID,
    PROTO_PROVIDER_ID,
    PROVIDER_CREDENTIAL_SERVICE,
    PROVIDER_IDS,
    OSKeyringProviderCredentialStore,
    ProviderCredentialCorruptError,
    ProviderCredentialStoreUnavailableError,
    ProviderCredentialValidationError,
)


class _MemoryKeyring:
    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}
        self.set_calls: list[tuple[str, str, str]] = []
        self.delete_calls: list[tuple[str, str]] = []

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.passwords.get((service_name, username))

    def set_password(
        self,
        service_name: str,
        username: str,
        password: str,
    ) -> None:
        self.set_calls.append((service_name, username, password))
        self.passwords[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.delete_calls.append((service_name, username))
        del self.passwords[(service_name, username)]


class ProviderCredentialStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.keyring = _MemoryKeyring()
        self.store = OSKeyringProviderCredentialStore(self.keyring)

    def test_fixed_catalog_accepts_only_each_exact_schema(self) -> None:
        self.assertEqual(
            PROVIDER_IDS,
            (
                PAPERCLIP_PROVIDER_ID,
                BIOHUB_ESM_PROVIDER_ID,
                PROTO_PROVIDER_ID,
            ),
        )
        credentials = {
            PAPERCLIP_PROVIDER_ID: {"api_key": "paperclip-secret"},
            BIOHUB_ESM_PROVIDER_ID: {"api_token": "biohub-secret"},
            PROTO_PROVIDER_ID: {
                "modal_token_id": "modal-id",
                "modal_token_secret": "modal-secret",
                "modal_environment": "genomilab",
            },
        }

        for provider_id, expected in credentials.items():
            self.store.replace(provider_id, expected)
            loaded = self.store.get(provider_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(dict(loaded), expected)

        self.assertEqual(len(self.keyring.passwords), 3)
        self.assertTrue(
            all(
                service == PROVIDER_CREDENTIAL_SERVICE
                for service, _account in self.keyring.passwords
            )
        )
        self.assertEqual(
            {account for _service, account in self.keyring.passwords},
            {"provider:paperclip", "provider:biohub-esm", "provider:proto"},
        )

    def test_proto_credential_is_one_atomic_json_value(self) -> None:
        expected = {
            "modal_token_id": "modal-id",
            "modal_token_secret": "modal-secret",
            "modal_environment": "production",
        }
        self.store.replace(PROTO_PROVIDER_ID, expected)

        self.assertEqual(len(self.keyring.set_calls), 1)
        service, account, encoded = self.keyring.set_calls[0]
        self.assertEqual(service, PROVIDER_CREDENTIAL_SERVICE)
        self.assertEqual(account, "provider:proto")
        self.assertEqual(json.loads(encoded), expected)

    def test_replace_replaces_the_complete_record(self) -> None:
        first = {
            "modal_token_id": "old-id",
            "modal_token_secret": "old-secret",
            "modal_environment": "old-environment",
        }
        second = {
            "modal_token_id": "new-id",
            "modal_token_secret": "new-secret",
            "modal_environment": "new-environment",
        }
        self.store.replace(PROTO_PROVIDER_ID, first)
        self.store.replace(PROTO_PROVIDER_ID, second)

        loaded = self.store.get(PROTO_PROVIDER_ID)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(dict(loaded), second)
        self.assertEqual(len(self.keyring.passwords), 1)
        self.assertEqual(len(self.keyring.set_calls), 2)

    def test_credential_revision_changes_only_when_the_saved_record_changes(
        self,
    ) -> None:
        self.store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "first-secret"})
        first = self.store.get_with_revision(PAPERCLIP_PROVIDER_ID)
        self.store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "first-secret"})
        same = self.store.get_with_revision(PAPERCLIP_PROVIDER_ID)
        self.store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "second-secret"})
        second = self.store.get_with_revision(PAPERCLIP_PROVIDER_ID)

        assert first is not None and same is not None and second is not None
        self.assertEqual(first[1], same[1])
        self.assertNotEqual(first[1], second[1])
        self.assertNotIn("first-secret", first[1])
        self.assertNotIn("second-secret", second[1])

    def test_snapshot_restore_is_redacted_and_compare_and_swap_guarded(self) -> None:
        self.store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "first-secret"})
        original = self.store.capture_snapshot(PAPERCLIP_PROVIDER_ID)
        self.store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "command-secret"})
        command_result = self.store.capture_snapshot(PAPERCLIP_PROVIDER_ID)

        rendered = repr(original) + repr(command_result)
        self.assertNotIn("first-secret", rendered)
        self.assertNotIn("command-secret", rendered)
        self.store.restore_snapshot(original, expected_current=command_result)
        restored = self.store.get(PAPERCLIP_PROVIDER_ID)
        assert restored is not None
        self.assertEqual(restored["api_key"], "first-secret")

        self.store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "newer-secret"})
        with self.assertRaises(ProviderCredentialStoreUnavailableError):
            self.store.restore_snapshot(original, expected_current=command_result)
        newest = self.store.get(PAPERCLIP_PROVIDER_ID)
        assert newest is not None
        self.assertEqual(newest["api_key"], "newer-secret")

    def test_missing_extra_empty_and_non_string_values_are_rejected(self) -> None:
        invalid_credentials: tuple[tuple[str, object], ...] = (
            (PAPERCLIP_PROVIDER_ID, {}),
            (
                PAPERCLIP_PROVIDER_ID,
                {"api_key": "secret", "unexpected": "value"},
            ),
            (PAPERCLIP_PROVIDER_ID, {"api_key": ""}),
            (PAPERCLIP_PROVIDER_ID, {"api_key": "   "}),
            (PAPERCLIP_PROVIDER_ID, {"api_key": 123}),
            (
                PROTO_PROVIDER_ID,
                {
                    "modal_token_id": "id",
                    "modal_token_secret": "secret",
                },
            ),
        )

        for provider_id, credentials in invalid_credentials:
            with self.subTest(provider_id=provider_id, credentials=credentials):
                with self.assertRaises(ProviderCredentialValidationError):
                    self.store.replace(provider_id, credentials)  # type: ignore[arg-type]

        self.assertEqual(self.keyring.set_calls, [])
        with self.assertRaises(ProviderCredentialValidationError):
            self.store.replace("unknown", {"api_key": "secret"})

    def test_reads_do_not_create_credentials(self) -> None:
        self.assertIsNone(self.store.get(PAPERCLIP_PROVIDER_ID))
        self.assertFalse(self.store.has(BIOHUB_ESM_PROVIDER_ID))
        statuses = self.store.status()

        self.assertEqual(self.keyring.set_calls, [])
        self.assertEqual(
            [(status.provider_id, status.configured) for status in statuses],
            [(provider_id, False) for provider_id in PROVIDER_IDS],
        )

    def test_status_and_credential_repr_never_include_secret_values(self) -> None:
        secrets = ("paperclip-secret", "biohub-secret")
        self.store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": secrets[0]})
        self.store.replace(BIOHUB_ESM_PROVIDER_ID, {"api_token": secrets[1]})

        credential = self.store.get(PAPERCLIP_PROVIDER_ID)
        status = self.store.status(PAPERCLIP_PROVIDER_ID)
        rendered = repr(credential) + repr(status) + json.dumps(status.to_dict())

        for secret in secrets:
            self.assertNotIn(secret, rendered)
        self.assertEqual(
            status.to_dict(),
            {
                "provider_id": PAPERCLIP_PROVIDER_ID,
                "configured": True,
                "storage": "os_keyring",
            },
        )

    def test_delete_is_idempotent_and_does_not_require_valid_json(self) -> None:
        self.assertFalse(self.store.delete(PAPERCLIP_PROVIDER_ID))
        self.store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "secret"})
        self.keyring.passwords[(PROVIDER_CREDENTIAL_SERVICE, "provider:paperclip")] = (
            "corrupt-secret"
        )

        self.assertTrue(self.store.delete(PAPERCLIP_PROVIDER_ID))
        self.assertFalse(self.store.delete(PAPERCLIP_PROVIDER_ID))
        self.assertEqual(
            self.keyring.delete_calls,
            [(PROVIDER_CREDENTIAL_SERVICE, "provider:paperclip")],
        )

    def test_delete_fails_when_the_keyring_claims_success_but_retains_secret(
        self,
    ) -> None:
        class _NoOpDeleteKeyring(_MemoryKeyring):
            def delete_password(self, service_name: str, username: str) -> None:
                self.delete_calls.append((service_name, username))

        keyring = _NoOpDeleteKeyring()
        store = OSKeyringProviderCredentialStore(keyring)
        store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "retained-secret"})

        with self.assertRaises(ProviderCredentialStoreUnavailableError):
            store.delete(PAPERCLIP_PROVIDER_ID)
        self.assertTrue(store.has(PAPERCLIP_PROVIDER_ID))

    def test_corrupt_stored_value_fails_without_disclosing_it(self) -> None:
        secret = "corrupt-secret-material"
        self.keyring.passwords[(PROVIDER_CREDENTIAL_SERVICE, "provider:paperclip")] = (
            secret
        )

        with self.assertRaises(ProviderCredentialCorruptError) as caught:
            self.store.get(PAPERCLIP_PROVIDER_ID)

        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, repr(caught.exception))
        self.assertIsNone(caught.exception.__context__)

    def test_keyring_errors_fail_closed_without_disclosing_secret_values(self) -> None:
        secret = "never-render-this-secret"

        class _FailingKeyring(_MemoryKeyring):
            def set_password(
                self,
                service_name: str,
                username: str,
                password: str,
            ) -> None:
                raise RuntimeError(f"could not save {password}")

        store = OSKeyringProviderCredentialStore(_FailingKeyring())
        with self.assertRaises(ProviderCredentialStoreUnavailableError) as caught:
            store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": secret})

        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, repr(caught.exception))
        self.assertIsNone(caught.exception.__context__)

    def test_ambient_non_native_keyring_backend_is_rejected(self) -> None:
        insecure = _MemoryKeyring()
        facade = SimpleNamespace(get_keyring=lambda: insecure)
        with mock.patch.dict(sys.modules, {"keyring": facade}):
            store = OSKeyringProviderCredentialStore()
            with self.assertRaisesRegex(
                ProviderCredentialStoreUnavailableError,
                "native operating-system credential store",
            ):
                store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "must-not-save"})

        self.assertEqual(insecure.passwords, {})

    def test_validation_errors_do_not_retain_failing_mapping_exceptions(self) -> None:
        secret = "secret-from-hostile-mapping"

        class _FailingMapping(dict[str, object]):
            def __iter__(self):  # type: ignore[no-untyped-def]
                raise RuntimeError(secret)

        with self.assertRaises(ProviderCredentialValidationError) as caught:
            self.store.replace(
                PAPERCLIP_PROVIDER_ID,
                _FailingMapping(api_key="otherwise-valid"),
            )

        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, repr(caught.exception))
        self.assertIsNone(caught.exception.__context__)

    def test_keyring_must_retain_the_exact_atomic_value(self) -> None:
        class _ForgetfulKeyring(_MemoryKeyring):
            def set_password(
                self,
                service_name: str,
                username: str,
                password: str,
            ) -> None:
                del service_name, username, password

        store = OSKeyringProviderCredentialStore(_ForgetfulKeyring())
        with self.assertRaises(ProviderCredentialStoreUnavailableError):
            store.replace(PAPERCLIP_PROVIDER_ID, {"api_key": "secret"})


if __name__ == "__main__":
    unittest.main()
