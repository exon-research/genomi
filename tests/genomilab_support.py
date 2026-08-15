"""Shared non-production helpers for GenomiLab tests."""

from genomi.lab.encrypted_sqlite import StaticEncryptionKeyProvider

TEST_LAB_KEY_PROVIDER = StaticEncryptionKeyProvider(b"genomilab-test-key-material-0001")
