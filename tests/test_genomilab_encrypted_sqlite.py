from __future__ import annotations

import multiprocessing
import os
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from genomi.lab.encrypted_sqlite import (
    EncryptedSQLiteAuthenticationError,
    EncryptedSQLiteDatabase,
    EncryptedSQLiteFormatError,
    EncryptionKeyUnavailableError,
    EncryptedSQLiteNestedTransactionError,
    OSKeyringKeyProvider,
    PlaintextSQLiteRejectedError,
    StaticEncryptionKeyProvider,
)


class _RememberingKeyProvider:
    def __init__(self) -> None:
        self.keys: dict[str, bytes] = {}

    def get_or_create_key(self, key_id: str) -> bytes:
        return self.keys.setdefault(key_id, b"k" * 32)


class _InvalidKeyProvider:
    def get_or_create_key(self, key_id: str) -> bytes:
        del key_id
        return b"short"


def _increment_encrypted_counter(
    path: str,
    key: bytes,
    ready: object,
    start: object,
) -> None:
    database = EncryptedSQLiteDatabase(
        path,
        key_provider=StaticEncryptionKeyProvider(key),
        timeout_seconds=10,
    )
    ready.put(True)
    start.wait()
    with database.connect() as connection:
        connection.execute("UPDATE counters SET value = value + 1")


class EncryptedSQLiteDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name) / "private"
        self.path = self.root / "lab.sqlite3"
        self.provider = _RememberingKeyProvider()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _database(self) -> EncryptedSQLiteDatabase:
        return EncryptedSQLiteDatabase(self.path, key_provider=self.provider)

    def _seed(self, secret: str = "patient molecular profile") -> None:
        with self._database().connect() as connection:
            connection.execute("CREATE TABLE records(value TEXT NOT NULL)")
            connection.execute("INSERT INTO records(value) VALUES (?)", (secret,))

    def test_persists_only_authenticated_ciphertext_and_reopens(self) -> None:
        secret = "rare private patient finding"
        self._seed(secret)

        container = self.path.read_bytes()
        self.assertFalse(container.startswith(b"SQLite format 3\x00"))
        self.assertNotIn(secret.encode("utf-8"), container)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertFalse(self.path.with_name(f"{self.path.name}-wal").exists())
        self.assertFalse(self.path.with_name(f"{self.path.name}-shm").exists())

        with self._database().connect() as connection:
            value = connection.execute("SELECT value FROM records").fetchone()[0]
        self.assertEqual(value, secret)
        self.assertEqual(len(self.provider.keys), 1)

    def test_plaintext_sqlite_is_rejected_without_rewriting_it(self) -> None:
        self.root.mkdir(mode=0o700)
        plaintext = sqlite3.connect(self.path)
        plaintext.execute("CREATE TABLE private_data(value TEXT)")
        plaintext.commit()
        plaintext.close()
        original = self.path.read_bytes()

        with self.assertRaises(PlaintextSQLiteRejectedError):
            with self._database().connect():
                pass

        self.assertEqual(self.path.read_bytes(), original)

    def test_tampering_and_wrong_keys_fail_authentication(self) -> None:
        self._seed()
        container = bytearray(self.path.read_bytes())
        container[-1] ^= 0x01
        self.path.write_bytes(container)

        with self.assertRaises(EncryptedSQLiteAuthenticationError):
            with self._database().connect():
                pass

        self.path.unlink()
        self.provider = _RememberingKeyProvider()
        self._seed()
        wrong_key = StaticEncryptionKeyProvider(b"w" * 32)
        with self.assertRaises(EncryptedSQLiteAuthenticationError):
            with EncryptedSQLiteDatabase(self.path, key_provider=wrong_key).connect():
                pass

    def test_invalid_or_truncated_container_fails_closed(self) -> None:
        self.root.mkdir(mode=0o700)
        self.path.write_bytes(b"not an encrypted database")

        with self.assertRaises(EncryptedSQLiteFormatError):
            with self._database().connect():
                pass

        self.assertEqual(self.path.read_bytes(), b"not an encrypted database")

    def test_failed_transaction_and_failed_atomic_replace_preserve_prior_state(
        self,
    ) -> None:
        self._seed("before")
        original = self.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "stop"):
            with self._database().connect() as connection:
                connection.execute("UPDATE records SET value = 'not committed'")
                raise ValueError("stop")
        self.assertEqual(self.path.read_bytes(), original)

        with (
            mock.patch(
                "genomi.lab.encrypted_sqlite.os.replace",
                side_effect=OSError("replace failed"),
            ),
            self.assertRaisesRegex(OSError, "replace failed"),
        ):
            with self._database().connect() as connection:
                connection.execute("UPDATE records SET value = 'also not committed'")

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.glob(f".{self.path.name}.*.tmp")), [])
        with self._database().connect() as connection:
            value = connection.execute("SELECT value FROM records").fetchone()[0]
        self.assertEqual(value, "before")

    def test_multiple_instances_serialize_threaded_updates(self) -> None:
        with self._database().connect() as connection:
            connection.execute("CREATE TABLE counters(value INTEGER NOT NULL)")
            connection.execute("INSERT INTO counters(value) VALUES (0)")

        def increment(_: int) -> None:
            database = EncryptedSQLiteDatabase(self.path, key_provider=self.provider)
            with database.connect() as connection:
                connection.execute("UPDATE counters SET value = value + 1")

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(increment, range(40)))

        with self._database().connect() as connection:
            value = connection.execute("SELECT value FROM counters").fetchone()[0]
        self.assertEqual(value, 40)

    def test_nested_transaction_is_rejected_immediately(self) -> None:
        self._seed()
        outer = self._database()
        inner = self._database()

        with outer.connect():
            started = time.monotonic()
            with self.assertRaisesRegex(
                EncryptedSQLiteNestedTransactionError,
                "Nested GenomiLab database transactions",
            ):
                with inner.connect():
                    pass
            self.assertLess(time.monotonic() - started, 0.5)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process locking")
    def test_multiple_processes_preserve_every_serialized_update(self) -> None:
        key = b"p" * 32
        database = EncryptedSQLiteDatabase(
            self.path,
            key_provider=StaticEncryptionKeyProvider(key),
        )
        with database.connect() as connection:
            connection.execute("CREATE TABLE counters(value INTEGER NOT NULL)")
            connection.execute("INSERT INTO counters(value) VALUES (0)")

        context = multiprocessing.get_context("spawn")
        ready = context.Queue()
        start = context.Event()
        processes = [
            context.Process(
                target=_increment_encrypted_counter,
                args=(str(self.path), key, ready, start),
            )
            for _ in range(8)
        ]
        for process in processes:
            process.start()
        for _ in processes:
            self.assertTrue(ready.get(timeout=10))
        start.set()
        for process in processes:
            process.join(timeout=20)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)

        with database.connect() as connection:
            value = connection.execute("SELECT value FROM counters").fetchone()[0]
        self.assertEqual(value, len(processes))
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        self.assertTrue(lock_path.exists())
        self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

    @unittest.skipUnless(
        os.name == "posix" and "fork" in multiprocessing.get_all_start_methods(),
        "requires POSIX fork locking",
    )
    def test_forked_child_rebinds_inherited_process_and_os_locks(self) -> None:
        key = b"f" * 32
        database = EncryptedSQLiteDatabase(
            self.path,
            key_provider=StaticEncryptionKeyProvider(key),
        )
        with database.connect() as connection:
            connection.execute("CREATE TABLE counters(value INTEGER NOT NULL)")
            connection.execute("INSERT INTO counters(value) VALUES (0)")

        entered = threading.Event()
        release = threading.Event()

        def hold_parent_transaction() -> None:
            with database.connect() as connection:
                connection.execute("UPDATE counters SET value = value + 1")
                entered.set()
                release.wait(timeout=10)

        holder = threading.Thread(target=hold_parent_transaction)
        holder.start()
        self.assertTrue(entered.wait(timeout=5))

        context = multiprocessing.get_context("fork")
        ready = context.Queue()
        start = context.Event()
        child = context.Process(
            target=_increment_encrypted_counter,
            args=(str(self.path), key, ready, start),
        )
        child.start()
        self.assertTrue(ready.get(timeout=5))
        start.set()
        time.sleep(0.1)
        self.assertTrue(child.is_alive())
        release.set()
        holder.join(timeout=10)
        child.join(timeout=10)
        self.assertFalse(holder.is_alive())
        self.assertFalse(child.is_alive())
        self.assertEqual(child.exitcode, 0)

        with database.connect() as connection:
            value = connection.execute("SELECT value FROM counters").fetchone()[0]
        self.assertEqual(value, 2)

    def test_invalid_provider_key_is_rejected_before_creating_database(self) -> None:
        database = EncryptedSQLiteDatabase(
            self.path, key_provider=_InvalidKeyProvider()
        )

        with self.assertRaises(EncryptionKeyUnavailableError):
            with database.connect() as connection:
                connection.execute("CREATE TABLE records(value TEXT)")
        self.assertFalse(self.path.exists())

    def test_os_keyring_provider_creates_and_reuses_a_secret_store_key(self) -> None:
        saved: dict[tuple[str, str], str] = {}

        def get_password(service: str, account: str) -> str | None:
            return saved.get((service, account))

        def set_password(service: str, account: str, value: str) -> None:
            saved[(service, account)] = value

        fake_keyring = mock.Mock(
            get_password=mock.Mock(side_effect=get_password),
            set_password=mock.Mock(side_effect=set_password),
        )
        provider = OSKeyringKeyProvider("test.genomilab", keyring_backend=fake_keyring)
        first = provider.get_or_create_key("a" * 32)
        second = provider.get_or_create_key("a" * 32)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        fake_keyring.set_password.assert_called_once()
        self.assertEqual(
            fake_keyring.set_password.call_args.args[:2],
            ("test.genomilab", "database:" + "a" * 32),
        )

    def test_os_keyring_provider_fails_closed_without_a_working_backend(self) -> None:
        fake_keyring = mock.Mock()
        fake_keyring.get_password.side_effect = RuntimeError("backend unavailable")
        with self.assertRaises(EncryptionKeyUnavailableError):
            OSKeyringKeyProvider(
                "test.genomilab", keyring_backend=fake_keyring
            ).get_or_create_key("b" * 32)


@unittest.skipUnless(os.name == "posix", "private modes require a POSIX filesystem")
class EncryptedSQLitePathSafetyTests(unittest.TestCase):
    def test_database_refuses_a_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private"
            root.mkdir(mode=0o700)
            victim = Path(temporary) / "victim"
            victim.write_bytes(b"untouched")
            target = root / "lab.sqlite3"
            target.symlink_to(victim)

            with self.assertRaises(OSError):
                EncryptedSQLiteDatabase(
                    target,
                    key_provider=StaticEncryptionKeyProvider(b"k" * 32),
                )
            self.assertEqual(victim.read_bytes(), b"untouched")

    def test_database_refuses_a_symlink_lock_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private"
            root.mkdir(mode=0o700)
            victim = Path(temporary) / "victim"
            victim.write_bytes(b"untouched")
            target = root / "lab.sqlite3"
            target.with_name(f".{target.name}.lock").symlink_to(victim)
            database = EncryptedSQLiteDatabase(
                target,
                key_provider=StaticEncryptionKeyProvider(b"k" * 32),
            )

            with self.assertRaises(OSError):
                with database.connect():
                    pass
            self.assertEqual(victim.read_bytes(), b"untouched")


if __name__ == "__main__":
    unittest.main()
