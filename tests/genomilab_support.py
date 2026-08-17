"""Shared non-production helpers for GenomiLab tests."""

from genomi.lab.encrypted_sqlite import StaticEncryptionKeyProvider

TEST_LAB_KEY_PROVIDER = StaticEncryptionKeyProvider(b"genomilab-test-key-material-0001")


def synthetic_ready_agi_context(
    user_id: str,
    nickname: str,
    *,
    agi_id: str | None = None,
    agi_snapshot_id: str | None = None,
) -> dict[str, object]:
    """Return the smallest path-free current-user context accepted by Lab."""

    selected_agi_id = agi_id or f"agi-{user_id}"
    selected_snapshot_id = agi_snapshot_id or f"agi-snapshot-{user_id}"
    return {
        "status": "completed",
        "active_user_id": user_id,
        "active_user": {
            "user_id": user_id,
            "nickname": nickname,
            "active_agi_id": selected_agi_id,
            "agi_ids": [selected_agi_id],
        },
        "has_active_genome_index": True,
        "active_agi_id": selected_agi_id,
        "active_agi_snapshot_id": selected_snapshot_id,
        "active_genome_index": {
            "agi_id": selected_agi_id,
            "agi_snapshot_id": selected_snapshot_id,
            "genome_build": "GRCh38",
            "status": "completed",
            "active_genome_index_readiness": {
                "status": "completed",
                "complete": True,
                "variants_ready": True,
            },
        },
        "active_genome_index_access": {"approved": False},
    }
