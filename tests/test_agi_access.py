from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _genomi_runtime_helpers import GenomiRuntimeTestCase

from genomi.active_genome_index.active_genome_index import (
    ActiveGenomeIndexIncomplete,
    ActiveGenomeIndexNeed,
    append_reference_pass,
    create_active_genome_index,
    default_active_genome_index_path,
    open_reader,
)
from genomi.operations.registry import agi_access
from genomi.operations.registry.errors import OperationError
from genomi.runtime import context as runtime_context


def _write_gvcf(path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write('##INFO=<ID=END,Number=1,Type=Integer,Description="End">\n')
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n")
        for pos in range(1, 6001):
            if pos % 500 == 0:
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


class OpenAgiAuthTests(GenomiRuntimeTestCase):
    """open_agi composes session authorization with the reader."""

    def _set_active(self) -> Path:
        vcf = self.genomi_home / "active.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        index = vcf.with_suffix(".sqlite")
        _write_gvcf(vcf)
        create_active_genome_index(vcf, index)
        runtime_context.set_active_genome_index(
            vcf, status="parsed", active_genome_index_path=index, genome_build="GRCh38"
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
        self.assertEqual(reader.active_genome_index_path, index)
        self.assertEqual(reader.genome_build, "GRCh38")

    def test_no_active_and_not_optional_raises_missing_context(self) -> None:
        with self.assertRaises(OperationError) as raised:
            agi_access.open_agi(need=ActiveGenomeIndexNeed.NONE, action="testing", params={})
        self.assertEqual(raised.exception.code, "missing_context")

    def test_optional_returns_none_without_context(self) -> None:
        self.assertIsNone(
            agi_access.open_agi(need=ActiveGenomeIndexNeed.NONE, action="testing", params={}, optional=True)
        )

    def test_supplied_source_grants_access(self) -> None:
        # A genome source supplied in this chat is approval to read it: open_agi
        # resolves the source's default index path and returns a reader without
        # requiring a prior approval call. (Readiness is gated lazily at connect,
        # so the index need not exist yet for resolution to succeed.)
        vcf = self.genomi_home / "supplied.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        _write_gvcf(vcf)
        reader = agi_access.open_agi(
            need=ActiveGenomeIndexNeed.REFERENCE, action="testing", params={"source": str(vcf)}
        )
        self.assertEqual(reader.active_genome_index_path, default_active_genome_index_path(str(vcf)))

    def test_reference_pending_for_call_tracks_active_index(self) -> None:
        vcf = self.genomi_home / "tp.vcf"
        vcf.parent.mkdir(parents=True, exist_ok=True)
        index = vcf.with_suffix(".sqlite")
        _write_gvcf(vcf)
        create_active_genome_index(vcf, index, parallel_workers=4, defer_reference=True)
        runtime_context.set_active_genome_index(
            vcf, status="parsed", active_genome_index_path=index, genome_build="GRCh38"
        )
        self.assertTrue(agi_access.reference_pending_for_call({}))
        append_reference_pass(index)
        self.assertFalse(agi_access.reference_pending_for_call({}))


if __name__ == "__main__":
    unittest.main()
