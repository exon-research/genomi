from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from genomi.capabilities.ancestry import panel_build, source_context
from genomi.runtime.liftover import chain_file_path
from genomi.runtime.paths import ancestry_reference_panel_dir


def _chain_files_available() -> bool:
    return chain_file_path("GRCh38", "GRCh37").is_file()


# Three SNPs with curated GRCh38 coordinates that lift cleanly to GRCh37
# (verified against UCSC liftOver): APOE rs429358, APOE rs7412, ACTN3
# rs1815739. Expected GRCh37 marker IDs in test assertions below.
_SYNTHETIC_GRCH38_MARKERS = [
    ("19:44908684:T:C", "19", 44908684, "T", "C", "0.10", "0.30"),
    ("19:44908822:C:T", "19", 44908822, "C", "T", "0.05", "0.22"),
    ("11:66560624:C:T", "11", 66560624, "C", "T", "0.42", "0.49"),
]
_EXPECTED_GRCH37_MARKER_IDS = [
    "19:45411941:T:C",
    "19:45412079:C:T",
    "11:66328095:C:T",
]


def _write_synthetic_panel(panel_dir: Path) -> None:
    panel_dir.mkdir(parents=True, exist_ok=True)
    with (panel_dir / "markers.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["marker_id", "chrom", "pos", "ref", "alt", "mean", "scale"])
        for row in _SYNTHETIC_GRCH38_MARKERS:
            writer.writerow(row)
    with (panel_dir / "pca_loadings.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["marker_id", "PC1", "PC2"])
        for index, row in enumerate(_SYNTHETIC_GRCH38_MARKERS):
            writer.writerow([row[0], f"0.{index + 1}", f"-0.{index + 1}"])
    (panel_dir / "samples.tsv").write_text(
        "sample_id\tpopulation\tsuperpopulation\tsex\nHG00096\tGBR\tEUR\tmale\n",
        encoding="utf-8",
    )
    (panel_dir / "reference_scores.tsv").write_text(
        "sample_id\tpopulation\tsuperpopulation\tPC1\tPC2\nHG00096\tGBR\tEUR\t-19.8\t-25.3\n",
        encoding="utf-8",
    )
    (panel_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "genomi-ancestry-reference-panel-v1",
                "panel_id": source_context.PANEL_ID_GRCH38,
                "library": source_context.PANEL_LIBRARY_GRCH38,
                "genome_build": "GRCh38",
                "marker_count": len(_SYNTHETIC_GRCH38_MARKERS),
                "sample_count": 1,
                "component_count": 2,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (panel_dir / "panel_stats.json").write_text(
        json.dumps({"marker_count": len(_SYNTHETIC_GRCH38_MARKERS), "sample_count": 1}),
        encoding="utf-8",
    )


@unittest.skipUnless(
    _chain_files_available(),
    "liftover-chains library not installed; run scripts/install_for_agents.py --libraries liftover-chains",
)
class PanelBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.grch38_dir = ancestry_reference_panel_dir(
            source_context.PANEL_ID_GRCH38, root=self.root
        )
        self.grch37_dir = ancestry_reference_panel_dir(
            source_context.PANEL_ID_GRCH37, root=self.root
        )
        _write_synthetic_panel(self.grch38_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_lifts_markers_and_remaps_loadings(self) -> None:
        result = panel_build.build_grch37_panel_from_grch38(root=self.root)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["genome_build"], "GRCh37")
        self.assertEqual(result["source_panel_id"], source_context.PANEL_ID_GRCH38)
        self.assertEqual(result["marker_count"], 3)
        self.assertEqual(result["dropped_marker_count"], 0)

        lifted_markers = _read_tsv(self.grch37_dir / "markers.tsv")
        self.assertEqual(
            [row["marker_id"] for row in lifted_markers],
            _EXPECTED_GRCH37_MARKER_IDS,
        )
        self.assertEqual(
            [(row["chrom"], int(row["pos"])) for row in lifted_markers],
            [("19", 45411941), ("19", 45412079), ("11", 66328095)],
        )
        for row in lifted_markers:
            # Mean/scale must be preserved exactly.
            self.assertIn(row["mean"], {"0.10", "0.05", "0.42"})

        lifted_loadings = _read_tsv(self.grch37_dir / "pca_loadings.tsv")
        self.assertEqual(
            [row["marker_id"] for row in lifted_loadings],
            _EXPECTED_GRCH37_MARKER_IDS,
        )
        # Loadings rows must stay in lock step with markers.
        self.assertEqual(lifted_loadings[0]["PC1"], "0.1")
        self.assertEqual(lifted_loadings[2]["PC2"], "-0.3")

    def test_samples_and_scores_copied_verbatim(self) -> None:
        panel_build.build_grch37_panel_from_grch38(root=self.root)
        self.assertEqual(
            (self.grch37_dir / "samples.tsv").read_bytes(),
            (self.grch38_dir / "samples.tsv").read_bytes(),
        )
        self.assertEqual(
            (self.grch37_dir / "reference_scores.tsv").read_bytes(),
            (self.grch38_dir / "reference_scores.tsv").read_bytes(),
        )

    def test_manifest_records_provenance(self) -> None:
        panel_build.build_grch37_panel_from_grch38(root=self.root)
        manifest = json.loads((self.grch37_dir / "manifest.json").read_text())
        self.assertEqual(manifest["panel_id"], source_context.PANEL_ID_GRCH37)
        self.assertEqual(manifest["library"], source_context.PANEL_LIBRARY_GRCH37)
        self.assertEqual(manifest["genome_build"], "GRCh37")
        self.assertEqual(manifest["source_panel_id"], source_context.PANEL_ID_GRCH38)
        self.assertEqual(manifest["source_genome_build"], "GRCh38")
        self.assertEqual(manifest["marker_count"], 3)
        self.assertEqual(manifest["dropped_marker_count"], 0)
        self.assertIn("hg38ToHg19", manifest["lifted_with"])

    def test_missing_source_panel_raises(self) -> None:
        # Wipe the markers file so the build sees the source as incomplete.
        (self.grch38_dir / "markers.tsv").unlink()
        with self.assertRaises(panel_build.PanelBuildError):
            panel_build.build_grch37_panel_from_grch38(root=self.root)

    def test_cached_build_skips_when_outputs_exist(self) -> None:
        first = panel_build.build_grch37_panel_from_grch38(root=self.root)
        self.assertEqual(first["status"], "completed")
        second = panel_build.build_grch37_panel_from_grch38(root=self.root)
        self.assertEqual(second["status"], "cached")

    def test_unmapped_marker_is_dropped(self) -> None:
        # Append a synthetic marker at an impossible coordinate so liftover
        # returns no match; it must be excluded from both files and counted.
        with (self.grch38_dir / "markers.tsv").open("a", encoding="utf-8") as handle:
            handle.write("1:99999999999:A:T\t1\t99999999999\tA\tT\t0.5\t0.5\n")
        with (self.grch38_dir / "pca_loadings.tsv").open("a", encoding="utf-8") as handle:
            handle.write("1:99999999999:A:T\t0.0\t0.0\n")
        result = panel_build.build_grch37_panel_from_grch38(root=self.root, force=True)
        self.assertEqual(result["marker_count"], 3)
        self.assertEqual(result["dropped_marker_count"], 1)
        self.assertEqual(result["dropped_reasons"], {"unmapped": 1})
        markers = _read_tsv(self.grch37_dir / "markers.tsv")
        self.assertEqual(len(markers), 3)
        loadings = _read_tsv(self.grch37_dir / "pca_loadings.tsv")
        self.assertEqual(len(loadings), 3)


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


if __name__ == "__main__":
    unittest.main()
