from __future__ import annotations

import contextlib
import os
import re
import shutil
import sqlite3
import stat
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index
from genomi.active_genome_index.identity import read_agi_snapshot_identity
from genomi.active_genome_index.revisions import compute_agi_artifact_sha256
from genomi.active_genome_index import reader as agi_reader_module
from genomi.active_genome_index.reader import ActiveGenomeIndexNeed, open_reader
from genomi.operations import call_operation
from genomi.operations.registry.errors import OperationError
from genomi.runtime import context as runtime_context
from genomi.lab import agi_authority

from tests.support.runtime.genomi import GenomiRuntimeTestCase


class ActiveGenomeIndexRevisionIntegrityTests(GenomiRuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        agi_authority._reset_investigation_agi_authorization_epoch_for_testing()
        self.addCleanup(
            agi_authority._reset_investigation_agi_authorization_epoch_for_testing
        )
        source_path = self.genomi_home / "integrity-patient.vcf"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPatient\n"
            "1\t100\trs900000001\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:31:99\n",
            encoding="utf-8",
        )
        build_path = self.genomi_home / "integrity-patient.sqlite"
        create_active_genome_index(
            source_path,
            build_path,
            genome_build="GRCh38",
            reuse_existing=False,
        )
        call_operation(
            "active_genome_index.assign_user_genome",
            {
                "nickname": "Integrity patient",
                "source": str(source_path),
                "agi_path": str(build_path),
                "genome_build": "GRCh38",
            },
        )
        context = call_operation("genomi.describe_context")
        self.user_id = str(context["active_user_id"])
        self.agi_id = str(context["active_agi_id"])
        self.snapshot_id = str(context["active_agi_snapshot_id"])
        self.revision = runtime_context.load_registry()["agi_revisions"][
            self.snapshot_id
        ]
        self.revision_path = Path(str(self.revision["agi_path"]))

    def test_registry_pins_exact_revision_artifact_sha256(self) -> None:
        digest = str(self.revision["agi_artifact_sha256"])

        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert digest == compute_agi_artifact_sha256(self.revision_path)
        assert not bool(self.revision_path.stat().st_mode & stat.S_IWUSR)

    def test_verified_reader_hashes_artifact_once_for_multiple_queries(self) -> None:
        with mock.patch.object(
            agi_reader_module,
            "verify_immutable_agi_revision",
            wraps=agi_reader_module.verify_immutable_agi_revision,
        ) as verify:
            reader = open_reader(
                self.revision_path,
                need=ActiveGenomeIndexNeed.VARIANT,
                expected_artifact_sha256=str(
                    self.revision["agi_artifact_sha256"]
                ),
                expected_snapshot_id=self.snapshot_id,
            )
            assert len(reader.query_rsid("rs900000001")) == 1
            assert len(reader.query_rsid("rs900000001")) == 1
            reader.ensure_ready()

        assert verify.call_count == 1

    def test_session_read_rejects_row_tamper_with_identity_unchanged(self) -> None:
        runtime_context.approve_agi_access(agi_id=self.agi_id)
        identity_before = read_agi_snapshot_identity(self.revision_path)
        self._tamper_variant_row()

        assert read_agi_snapshot_identity(self.revision_path) == identity_before
        with self.assertRaises(OperationError) as raised:
            call_operation("variant.resolve", {"rsid": "rs900000001"})
        assert raised.exception.code == "active_genome_index_artifact_integrity_failed"

    def test_investigation_authorization_rechecks_bytes_before_use(self) -> None:
        handle = agi_authority.issue_investigation_agi_authorization(
            workspace_session_id="workspace-integrity",
            user_id=self.user_id,
            investigation_id="investigation-integrity",
            patient_molecular_snapshot_id="molecular-snapshot-integrity",
            consent_receipt_id="consent-integrity",
            agi_id=self.agi_id,
            agi_snapshot_id=self.snapshot_id,
            purpose="Investigate a synthetic disease",
            genomic_scope={
                "operation": "variant.resolve",
                "rsid": "rs900000001",
            },
        )
        identity_before = read_agi_snapshot_identity(self.revision_path)
        self._tamper_variant_row()

        assert read_agi_snapshot_identity(self.revision_path) == identity_before
        with self.assertRaises(
            agi_authority.InvestigationAgiAuthorizationError
        ) as raised:
            params = {"rsid": "rs900000001"}
            execution_context = (
                agi_authority.execution_context_for_investigation_authorization(
                    handle,
                    operation="variant.resolve",
                    params=params,
                )
            )
            call_operation(
                "variant.resolve",
                params,
                execution_context=execution_context,
            )
        assert raised.exception.code == "investigation_agi_authorization_context_mismatch"

    def _tamper_variant_row(self) -> None:
        tampered_path = self.revision_path.with_suffix(".tampered.sqlite")
        shutil.copyfile(self.revision_path, tampered_path)
        os.chmod(tampered_path, 0o600)
        try:
            with contextlib.closing(sqlite3.connect(tampered_path)) as connection:
                connection.execute("pragma journal_mode = delete")
                connection.execute(
                    "update records set genotype = '1/1' where rsid = 'rs900000001'"
                )
                connection.commit()
            os.replace(tampered_path, self.revision_path)
        finally:
            tampered_path.unlink(missing_ok=True)
            os.chmod(self.revision_path, 0o400)
