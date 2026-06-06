from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support.runtime.genomi import GenomiRuntimeTestCase

from genomi.active_genome_index.active_genome_index import (
    ActiveGenomeIndexIncomplete,
    ActiveGenomeIndexNeed,
    ActiveGenomeIndexNeedsReparse,
    SCHEMA_VERSION,
    append_reference_pass,
    active_genome_index_readiness,
    create_active_genome_index,
    ensure_active_genome_index_complete,
    open_reader,
    query_region,
)
from genomi.operations.registry import agi_access, defaults_applied_for_call
from genomi.operations.registry.errors import OperationError
from genomi.operations.registry.table import call_operation
from genomi.runtime import context as runtime_context
from genomi.runtime.sqlite_support import connect_sqlite


def _write_gvcf(path: Path, *, variant_mod: int = 500) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write('##INFO=<ID=END,Number=1,Type=Integer,Description="End">\n')
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n")
        for pos in range(1, 6001):
            if pos % variant_mod == 0:
                handle.write(f"1\t{pos}\trs{pos}\tA\tG\t.\tPASS\t.\tGT:DP:GQ\t0/1:42:99\n")
            else:
                handle.write(f"1\t{pos}\t.\tA\t<NON_REF>\t.\tPASS\tEND={pos}\tGT:DP:GQ\t0/0:35:50\n")


class ReaderParseStateTests(unittest.TestCase):
    """The reader is the single data door and reports what is still parsing."""

    def test_two_phase_parse_state_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "s.vcf"
            index = Path(tmp) / "s.sqlite"
            _write_gvcf(vcf)
            create_active_genome_index(vcf, index, parallel_workers=4, defer_reference=True)

            reader = open_reader(index, need=ActiveGenomeIndexNeed.REFERENCE)
            self.assertTrue(reader.variants_ready)
            self.assertFalse(reader.complete)
            self.assertTrue(reader.reference_pending)
            self.assertTrue(reader.parse_state()["reference_pending"])

            append_reference_pass(index)
            done = open_reader(index, need=ActiveGenomeIndexNeed.REFERENCE)
            self.assertTrue(done.complete)
            self.assertFalse(done.reference_pending)

    def test_connect_gates_lazily_by_need(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.sqlite"
            # NONE never gates: building the reader is cheap, connect is the
            # caller's responsibility (build-on-demand). REFERENCE/VARIANT gate
            # at connect time.
            none_reader = open_reader(missing, need=ActiveGenomeIndexNeed.NONE)
            self.assertFalse(none_reader.complete)
            ref_reader = open_reader(missing, need=ActiveGenomeIndexNeed.REFERENCE)
            with self.assertRaises(ActiveGenomeIndexIncomplete):
                with ref_reader.connect():
                    pass

    def test_point_region_queries_are_readiness_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.vcf"
            index = Path(tmp) / "sample.sqlite"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            create_active_genome_index(vcf, index)
            with connect_sqlite(index) as connection:
                connection.execute(
                    "update metadata set value = ? where key = 'active_genome_index_complete'",
                    (json.dumps(False),),
                )
                connection.execute(
                    "update metadata set value = ? where key = 'active_genome_index_build_status'",
                    (json.dumps("in_progress"),),
                )
                connection.commit()

            with self.assertRaises(ActiveGenomeIndexIncomplete):
                query_region(index, "1", 100, 100)

    def test_variants_ready_indexes_still_enforce_schema_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vcf = Path(tmp) / "sample.g.vcf"
            index = Path(tmp) / "sample.sqlite"
            _write_gvcf(vcf)
            create_active_genome_index(vcf, index, parallel_workers=4, defer_reference=True)
            with connect_sqlite(index) as connection:
                connection.execute(
                    "update metadata set value = ? where key = 'schema_version'",
                    (json.dumps(1),),
                )
                connection.commit()

            readiness = active_genome_index_readiness(index)
            self.assertFalse(readiness["variants_ready"], readiness)
            self.assertEqual(readiness["status"], "needs_reparse")
            with self.assertRaises(ActiveGenomeIndexNeedsReparse):
                ensure_active_genome_index_complete(index)


class OpenAgiAuthTests(GenomiRuntimeTestCase):
    """open_agi composes session authorization with the reader."""

    def _set_active(
        self,
        *,
        genome_build: str = "GRCh38",
        stem: str = "active",
        variant_mod: int = 500,
    ) -> Path:
        vcf = self.genomi_home / f"{stem}.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        index = vcf.with_suffix(".sqlite")
        _write_gvcf(vcf, variant_mod=variant_mod)
        create_active_genome_index(vcf, index)
        runtime_context.set_active_agi_from_source(
            vcf, status="parsed", agi_path=index, genome_build=genome_build
        )
        return index

    def test_unapproved_active_raises_approval_required(self) -> None:
        self._set_active()
        with self.assertRaises(OperationError) as raised:
            agi_access.open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="testing", params={})
        self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

    def test_approved_active_returns_reader(self) -> None:
        index = self._set_active()
        runtime_context.approve_agi_access()
        reader = agi_access.open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="testing", params={})
        # Compare resolved paths: the stored run path is symlink-resolved, and
        # GENOMI_HOME lives under /tmp (a /private/tmp symlink on macOS).
        self.assertEqual(reader.agi_path.resolve(), index.resolve())
        self.assertEqual(reader.genome_build, "GRCh38")

    def test_no_active_and_not_optional_raises_missing_context(self) -> None:
        with self.assertRaises(OperationError) as raised:
            agi_access.open_agi(need=ActiveGenomeIndexNeed.NONE, action="testing", params={})
        self.assertEqual(raised.exception.code, "missing_context")

    def test_optional_returns_none_without_context(self) -> None:
        self.assertIsNone(
            agi_access.open_agi(need=ActiveGenomeIndexNeed.NONE, action="testing", params={}, optional=True)
        )

    def test_source_parameter_does_not_resolve_agi(self) -> None:
        vcf = self.genomi_home / "supplied.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        _write_gvcf(vcf)
        with self.assertRaises(OperationError) as raised:
            agi_access.open_agi(
                need=ActiveGenomeIndexNeed.REFERENCE, action="testing", params={"source": str(vcf)}
            )
        self.assertEqual(raised.exception.code, "missing_context")

    def test_unregistered_explicit_agi_path_requires_approval(self) -> None:
        vcf = self.genomi_home / "supplied.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        index = vcf.with_suffix(".sqlite")
        _write_gvcf(vcf)
        create_active_genome_index(vcf, index)
        with self.assertRaises(OperationError) as raised:
            agi_access.open_agi(
                need=ActiveGenomeIndexNeed.VARIANT,
                action="testing",
                params={"agi_path": str(index), "genome_build": "GRCh38"},
            )
        self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

    def test_unapproved_explicit_agi_path_requires_approval(self) -> None:
        index = self._set_active()
        with self.assertRaises(OperationError) as raised:
            agi_access.open_agi(
                need=ActiveGenomeIndexNeed.VARIANT,
                action="testing",
                params={"agi_path": str(index)},
            )
        self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

    def test_registered_explicit_agi_path_returns_approved_reader(self) -> None:
        index = self._set_active(genome_build="GRCh37")
        runtime_context.approve_agi_access()
        reader = agi_access.open_agi(
            need=ActiveGenomeIndexNeed.VARIANT,
            action="testing",
            params={"agi_path": str(index)},
        )
        self.assertEqual(reader.agi_path.resolve(), index.resolve())
        self.assertEqual(reader.genome_build, "GRCh37")

    def test_defaults_applied_use_explicit_approved_agi_path_build(self) -> None:
        grch37_index = self._set_active(genome_build="GRCh37", stem="explicit_grch37")
        runtime_context.approve_agi_access()
        self._set_active(genome_build="GRCh38", stem="active_grch38", variant_mod=499)

        defaults = {
            item["parameter"]: item
            for item in defaults_applied_for_call(
                "ancestry.check_sample_overlap",
                {"agi_path": str(grch37_index)},
            )
        }

        self.assertEqual(defaults["genome_build"]["value"], "GRCh37")

    def test_reference_pending_for_call_tracks_active_index(self) -> None:
        vcf = self.genomi_home / "tp.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        index = vcf.with_suffix(".sqlite")
        _write_gvcf(vcf)
        create_active_genome_index(vcf, index, parallel_workers=4, defer_reference=True)
        runtime_context.set_active_agi_from_source(
            vcf, status="parsed", agi_path=index, genome_build="GRCh38"
        )
        runtime_context.approve_agi_access()
        self.assertTrue(agi_access.reference_pending_for_call({}))
        append_reference_pass(index)
        self.assertFalse(agi_access.reference_pending_for_call({}))

    def test_reference_operations_reject_incomplete_selected_index(self) -> None:
        vcf = self.genomi_home / "incomplete.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        index = vcf.with_suffix(".sqlite")
        _write_gvcf(vcf)
        create_active_genome_index(vcf, index)
        with connect_sqlite(index) as connection:
            connection.execute(
                "update metadata set value = ? where key = 'active_genome_index_complete'",
                (json.dumps(False),),
            )
            connection.execute(
                "update metadata set value = ? where key = 'active_genome_index_build_status'",
                (json.dumps("in_progress"),),
            )
            connection.commit()
        runtime_context.set_active_agi_from_source(
            vcf, status="parsed", agi_path=index, genome_build="GRCh38"
        )
        runtime_context.approve_agi_access()

        operations = [
            ("active_genome_index.classify_callset_qc", {}),
            (
                "active_genome_index.classify_genotype_support",
                {"chrom": "1", "pos": 500, "ref": "A", "alt": "G"},
            ),
            ("active_genome_index.classify_region_callability", {"region": "1:1-10"}),
        ]
        for operation, params in operations:
            with self.subTest(operation=operation), self.assertRaises(OperationError) as raised:
                call_operation(operation, params)
            self.assertEqual(raised.exception.code, "active_genome_index_incomplete")

    def test_variant_lookup_rejects_too_new_selected_index(self) -> None:
        index = self._set_active(stem="too_new_schema")
        with connect_sqlite(index) as connection:
            connection.execute(
                "update metadata set value = ? where key = 'schema_version'",
                (json.dumps(SCHEMA_VERSION + 1),),
            )
            connection.commit()
        runtime_context.approve_agi_access()

        with self.assertRaises(OperationError) as raised:
            call_operation("variant.resolve", {"rsid": "rs500"})

        self.assertEqual(raised.exception.code, "active_genome_index_schema_too_new")


if __name__ == "__main__":
    unittest.main()
