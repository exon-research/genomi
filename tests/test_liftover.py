from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.runtime.liftover import (
    LiftOver,
    LiftoverConfigurationError,
    chain_file_path,
    get_liftover,
    liftover_preflight,
    normalize_build,
)


# Known SNPs with curated GRCh37/GRCh38 coordinates (dbSNP + UCSC verified).
# rs429358 (APOE): GRCh38 chr19:44908684, GRCh37 chr19:45411941
# rs7412   (APOE): GRCh38 chr19:44908822, GRCh37 chr19:45412079
# rs1815739 (ACTN3): GRCh38 chr11:66560624, GRCh37 chr11:66328095
_GRCH38_GRCH37_PAIRS = [
    ("chr19", 44908684, "chr19", 45411941),
    ("chr19", 44908822, "chr19", 45412079),
    ("chr11", 66560624, "chr11", 66328095),
]


def _chain_files_available() -> bool:
    return (
        chain_file_path("GRCh38", "GRCh37").is_file()
        and chain_file_path("GRCh37", "GRCh38").is_file()
    )


def _liftover_available() -> bool:
    return (
        liftover_preflight("GRCh38", "GRCh37")["status"] == "available"
        and liftover_preflight("GRCh37", "GRCh38")["status"] == "available"
    )


@unittest.skipUnless(
    _liftover_available(),
    "liftover setup unavailable; install liftover-chains and the pyliftover Python package",
)
class LiftoverChainTests(unittest.TestCase):
    def test_grch38_to_grch37_known_snps(self) -> None:
        lifter = get_liftover("GRCh38", "GRCh37")
        for grch38_chrom, grch38_pos, grch37_chrom, grch37_pos in _GRCH38_GRCH37_PAIRS:
            with self.subTest(snp=f"{grch38_chrom}:{grch38_pos}"):
                self.assertEqual(
                    lifter.lift_position(grch38_chrom, grch38_pos),
                    (grch37_chrom, grch37_pos),
                )

    def test_grch37_to_grch38_round_trip(self) -> None:
        lifter = get_liftover("GRCh37", "GRCh38")
        for grch38_chrom, grch38_pos, grch37_chrom, grch37_pos in _GRCH38_GRCH37_PAIRS:
            with self.subTest(snp=f"{grch37_chrom}:{grch37_pos}"):
                self.assertEqual(
                    lifter.lift_position(grch37_chrom, grch37_pos),
                    (grch38_chrom, grch38_pos),
                )

    def test_accepts_unprefixed_chrom_and_preserves_style(self) -> None:
        lifter = get_liftover("GRCh38", "GRCh37")
        result = lifter.lift_position("19", 44908684)
        self.assertEqual(result, ("19", 45411941))

    def test_unmapped_position_returns_none(self) -> None:
        # Beyond the end of chromosome 1 in any reasonable assembly.
        lifter = get_liftover("GRCh38", "GRCh37")
        self.assertIsNone(lifter.lift_position("chr1", 10**12))

    def test_lift_records_splits_lifted_and_dropped(self) -> None:
        lifter = get_liftover("GRCh38", "GRCh37")
        records = [
            {"chrom": "chr19", "pos": 44908684, "rsid": "rs429358"},
            {"chrom": "chr1", "pos": 10**12, "rsid": "rs_unmappable"},
            {"chrom": "chrX", "pos": None, "rsid": "rs_missing_pos"},
        ]
        result = lifter.lift_records(records)
        self.assertEqual(len(result.lifted), 1)
        self.assertEqual(result.lifted[0]["pos"], 45411941)
        self.assertEqual(result.lifted[0]["rsid"], "rs429358")
        reasons = sorted(r["liftover_reason"] for r in result.dropped)
        self.assertEqual(reasons, ["missing_coordinates", "unmapped"])

    def test_cached_singleton_returns_same_instance(self) -> None:
        self.assertIs(
            get_liftover("GRCh38", "GRCh37"),
            get_liftover("GRCh38", "GRCh37"),
        )


class LiftoverConfigTests(unittest.TestCase):
    def test_normalize_build_aliases(self) -> None:
        for alias in ("GRCh38", "grch38", "hg38", "HG38", "38", "b38"):
            self.assertEqual(normalize_build(alias), "GRCh38")
        for alias in ("GRCh37", "hg19", "37", "b37"):
            self.assertEqual(normalize_build(alias), "GRCh37")

    def test_normalize_build_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            normalize_build("CHM13")
        with self.assertRaises(ValueError):
            normalize_build("")

    def test_chain_file_path_unknown_pair_raises(self) -> None:
        with self.assertRaises(LiftoverConfigurationError):
            chain_file_path("GRCh38", "GRCh38")

    def test_preflight_reports_missing_pyliftover_with_chains_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for source_build, target_build in (("GRCh38", "GRCh37"), ("GRCh37", "GRCh38")):
                path = chain_file_path(source_build, target_build, root=root)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")

            with mock.patch("genomi.runtime.liftover.importlib.import_module", side_effect=ImportError("missing pyliftover")):
                result = liftover_preflight(
                    "GRCh38",
                    "GRCh37",
                    root=root,
                    operation="prs.calculate_score",
                    intent="testing PRS liftover setup",
                    genome_build="GRCh37",
                )
                with self.assertRaisesRegex(LiftoverConfigurationError, "pyliftover"):
                    LiftOver("GRCh38", "GRCh37", root=root)

        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["reason"], "missing_python_dependency")
        self.assertEqual(result["missing_library"]["library"], "pyliftover")
        self.assertFalse(result["missing_library"]["installed"])
        self.assertTrue(result["liftover_setup"]["chain_file"]["exists"])
        self.assertFalse(result["liftover_setup"]["python_dependency"]["installed"])

    def test_identical_builds_rejected(self) -> None:
        # Even when the chain file exists, lifting a build onto itself is a bug.
        if _chain_files_available():
            with self.assertRaises(ValueError):
                LiftOver("GRCh38", "GRCh38")


if __name__ == "__main__":
    unittest.main()
