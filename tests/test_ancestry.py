from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import numpy as np

from genomi.active_genome_index.active_genome_index import (
    ActiveGenomeIndexReader,
    create_active_genome_index,
    default_agi_path,
)
from genomi.capabilities.ancestry import policy as ancestry_policy
from genomi.capabilities.ancestry import reference_panels
from genomi.operations import OperationError, call_operation, list_operations
from genomi.runtime import context as runtime_context


def _write_synthetic_panel(
    output_dir: Path,
    *,
    samples: list[dict[str, object]],
    markers: list[dict[str, object]],
    genotype_rows: list[list[float | None]],
    component_count: int,
    genome_build: str = "GRCh38",
    panel_id: str | None = None,
    panel_library: str | None = None,
    panel_title: str | None = None,
) -> None:
    """Write a panel artifact for projection tests.

    Production builds live in the genomi-ancestry-panel repo; this is a
    test-only fixture that produces the same on-disk shape so the projection
    code path under test sees a real artifact.
    """
    matrix = np.asarray(
        [[np.nan if value is None else float(value) for value in row] for row in genotype_rows],
        dtype=float,
    )
    means = np.nanmean(matrix, axis=1)
    scales = np.nanstd(matrix, axis=1, ddof=0)
    scales[~np.isfinite(scales) | (scales <= 0)] = 1.0
    imputed = np.where(np.isnan(matrix), means[:, None], matrix)
    standardized = ((imputed - means[:, None]) / scales[:, None]).T
    k = max(1, min(int(component_count), standardized.shape[0], standardized.shape[1]))
    u, singular, vt = np.linalg.svd(standardized, full_matrices=False)
    scores = u[:, :k] * singular[:k]
    loadings = vt[:k, :].T
    component_names = [f"PC{index + 1}" for index in range(k)]
    output_dir.mkdir(parents=True, exist_ok=True)

    def write_tsv(name: str, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
        with (output_dir / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    marker_rows = [
        {
            **marker,
            "marker_id": marker.get("marker_id") or f"{marker['chrom']}:{marker['pos']}:{marker['ref']}:{marker['alt']}",
            "mean": f"{float(means[index]):.10g}",
            "scale": f"{float(scales[index]):.10g}",
        }
        for index, marker in enumerate(markers)
    ]
    write_tsv(reference_panels.SAMPLES_NAME, ["sample_id", "population", "superpopulation", "sex"], samples)
    write_tsv(reference_panels.MARKERS_NAME, ["marker_id", "chrom", "pos", "ref", "alt", "mean", "scale"], marker_rows)
    write_tsv(
        reference_panels.LOADINGS_NAME,
        ["marker_id", *component_names],
        [
            {
                "marker_id": marker_rows[index]["marker_id"],
                **{name: f"{float(loadings[index, pc_index]):.10g}" for pc_index, name in enumerate(component_names)},
            }
            for index in range(len(marker_rows))
        ],
    )
    write_tsv(
        reference_panels.REFERENCE_SCORES_NAME,
        ["sample_id", "population", "superpopulation", *component_names],
        [
            {
                "sample_id": sample["sample_id"],
                "population": sample.get("population", ""),
                "superpopulation": sample.get("superpopulation", ""),
                **{name: f"{float(scores[index, pc_index]):.10g}" for pc_index, name in enumerate(component_names)},
            }
            for index, sample in enumerate(samples)
        ],
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    (output_dir / reference_panels.PANEL_STATS_NAME).write_text(
        json.dumps(
            {
                "schema": "genomi-ancestry-panel-stats-v1",
                "sample_count": len(samples),
                "marker_count": len(marker_rows),
                "component_count": len(component_names),
                "target_marker_count": len(marker_rows),
                "built_at": now,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / reference_panels.MANIFEST_NAME).write_text(
        json.dumps(
            {
                "schema": "genomi-ancestry-reference-panel-v1",
                "panel_id": panel_id or reference_panels.PANEL_ID,
                "title": panel_title or reference_panels.PANEL_TITLE,
                "library": panel_library or reference_panels.PANEL_LIBRARY,
                "genome_build": genome_build,
                "sample_count": len(samples),
                "marker_count": len(marker_rows),
                "component_count": len(component_names),
                "built_at": now,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


class AncestryCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self.genomi_home = Path(self._home_tmp.name) / "genomi-home"
        self._env = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_public_metadata_tools_do_not_require_personal_approval(self) -> None:
        panels = call_operation("ancestry.list_reference_panels")
        source_context = call_operation("ancestry.build_source_context")

        self.assertEqual(panels["status"], "completed")
        self.assertFalse(panels["panels"][0]["installed"])
        self.assertEqual(
            set(panels["panels"][0]),
            {
                "panel_id",
                "title",
                "library",
                "installed",
                "status",
                "genome_build",
                "method",
                "documented_source_sample_count",
                "phase3_unrelated_sample_count",
                "sample_count",
                "marker_count",
                "component_count",
                "source_urls",
                "label_definitions",
                "limitations",
                "install_command",
            },
        )
        self.assertIn("internationalgenome.org", panels["panels"][0]["source_urls"]["igsr_collection"])
        self.assertEqual(source_context["status"], "completed")
        self.assertEqual(
            [item["genome_build"] for item in source_context["supported_genome_builds"]],
            list(ancestry_policy.SUPPORTED_BUILDS),
        )
        self.assertEqual(
            [item["genome_build"] for item in source_context["reference_panels"]],
            list(ancestry_policy.SUPPORTED_BUILDS),
        )
        self.assertEqual(
            source_context["overlap_policy"],
            ancestry_policy.overlap_thresholds(),
        )
        self.assertIn("reference-panel similarity", " ".join(source_context["limitations"]))

    def test_private_tools_require_approval_for_existing_active_context(self) -> None:
        vcf = Path(self._home_tmp.name) / "sample.vcf"
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=vcf.with_suffix(".sqlite"),
            genome_build="GRCh38",
        )

        with self.assertRaises(OperationError) as raised:
            call_operation("ancestry.estimate_population_context")
        self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

    def test_private_tools_require_approval_for_unregistered_explicit_agi_path(self) -> None:
        with self.assertRaises(OperationError) as raised:
            call_operation(
                "ancestry.estimate_population_context",
                {"agi_path": str(Path(self._home_tmp.name) / "sample.sqlite")},
            )

        self.assertEqual(raised.exception.code, "active_genome_index_approval_required")

    def test_discovery_registers_all_ancestry_handlers(self) -> None:
        tools = {tool["name"]: tool for tool in list_operations(capability="ancestry")}

        self.assertEqual(
            set(tools),
            {
                "ancestry.list_reference_panels",
                "ancestry.build_source_context",
                "ancestry.check_sample_overlap",
                "ancestry.project_pca",
                "ancestry.estimate_population_context",
            },
        )
        self.assertEqual(tools["ancestry.estimate_population_context"]["annotations"]["discoveryRole"], "entry_tool")
        self.assertEqual(
            tools["ancestry.check_sample_overlap"]["annotations"]["dependencyContract"]["installedLibraries"],
            list(ancestry_policy.PANEL_LIBRARIES),
        )

    def test_synthetic_panel_overlap_projection_and_group_ordering(self) -> None:
        markers = self._install_synthetic_panel(marker_count=8)
        vcf = self._write_indexed_vcf("sample_full.vcf", markers, usable_count=8)

        with self._tiny_thresholds():
            result = call_operation(
                "ancestry.estimate_population_context",
                {"agi_path": str(default_agi_path(vcf))},
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["personal_context"]["uses_personal_dna"])
        self.assertEqual(result["sample_qc"]["usable_marker_count"], 8)
        self.assertEqual(result["sample_qc"]["missing_marker_count"], 0)
        self.assertEqual(result["sample_qc"]["marker_overlap_quality"], "high")
        self.assertIsNotNone(result["pca_projection"])
        nearest_samples = result["pca_projection"]["nearest_reference_samples"]
        self.assertEqual(nearest_samples[0]["superpopulation"], "EUR")
        nearest_labels = [group["label"] for group in result["nearest_reference_groups"][:3]]
        self.assertIn("CEU", nearest_labels)
        self.assertIn("EUR", nearest_labels)
        self.assertIn("reference cluster", result["interpretation"]["summary"])
        self.assertNotIn("ethnicity", result["interpretation"]["summary"].lower())
        self.assertNotIn("determine origin", result["interpretation"]["summary"].lower())

    def test_overlap_thresholds_block_low_overlap_projection(self) -> None:
        # 1 of 8 panel markers usable = 12.5% — below LOW_OVERLAP_FRACTION (20%),
        # so the projection is blocked.
        markers = self._install_synthetic_panel(marker_count=8)
        vcf = self._write_indexed_vcf("sample_low.vcf", markers, usable_count=1)

        with self._tiny_thresholds():
            result = call_operation("ancestry.project_pca", {"agi_path": str(default_agi_path(vcf))})

        self.assertEqual(result["status"], "insufficient_overlap")
        self.assertFalse(result["sample_qc"]["projection_allowed"])
        self.assertIsNone(result["pca_projection"])
        self.assertEqual(result["sample_qc"]["usable_marker_count"], 1)
        self.assertEqual(result["sample_qc"]["missing_marker_count"], 7)
        self.assertEqual(result["sample_qc"]["marker_overlap_quality"], "insufficient")

    def test_overlap_uses_bulk_agi_dosage_reader(self) -> None:
        markers = self._install_synthetic_panel(marker_count=20)
        vcf = self._write_indexed_vcf("sample_bulk.vcf", markers, usable_count=20)

        with self._tiny_thresholds(), mock.patch.object(
            ActiveGenomeIndexReader,
            "query_region",
            side_effect=AssertionError("ancestry overlap must not query one marker at a time"),
        ):
            result = call_operation("ancestry.check_sample_overlap", {"agi_path": str(default_agi_path(vcf))})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sample_qc"]["usable_marker_count"], 20)
        self.assertEqual(result["sample_qc"]["missing_marker_count"], 0)
        envelope = result["evidence_envelope"]
        self.assertEqual(envelope["finding_state"], "evidence_present")
        self.assertTrue(envelope["personal_context"]["uses_personal_dna"])
        self.assertEqual(envelope["coverage"]["consulted_sources"], ["active_genome_index", "ancestry-1000g-30x-grch38"])
        self.assertEqual(envelope["observations"]["usable_marker_count"], 20)

    def test_reference_block_span_uses_panel_marker_reference_allele(self) -> None:
        markers = [
            {"marker_id": "m0", "chrom": "1", "pos": 1000, "ref": "A", "alt": "C"},
            {"marker_id": "m1", "chrom": "1", "pos": 2000, "ref": "G", "alt": "C"},
        ]
        samples = [
            {"sample_id": "EUR1", "population": "CEU", "superpopulation": "EUR", "sex": ""},
            {"sample_id": "EUR2", "population": "CEU", "superpopulation": "EUR", "sex": ""},
            {"sample_id": "AFR1", "population": "YRI", "superpopulation": "AFR", "sex": ""},
            {"sample_id": "AFR2", "population": "YRI", "superpopulation": "AFR", "sex": ""},
        ]
        _write_synthetic_panel(
            reference_panels.panel_dir(),
            samples=samples,
            markers=markers,
            genotype_rows=[[0.0, 0.0, 2.0, 2.0] for _ in markers],
            component_count=2,
        )
        vcf = self._write_reference_block_vcf("sample_reference_span.vcf")

        result = call_operation("ancestry.check_sample_overlap", {"agi_path": str(default_agi_path(vcf))})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sample_qc"]["usable_marker_count"], 2)
        self.assertEqual(result["sample_qc"]["missing_marker_count"], 0)

    def test_grch37_sample_without_grch37_panel_prompts_install(self) -> None:
        # Only the GRCh38 synthetic panel is installed. A GRCh37 sample must
        # surface the GRCh37-panel install prompt rather than crashing or
        # silently using the wrong panel.
        markers = self._install_synthetic_panel(marker_count=8)
        vcf = self._write_indexed_vcf("sample_grch37.vcf", markers, usable_count=8)
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=default_agi_path(vcf),
            genome_build="GRCh37",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

        with self._tiny_thresholds():
            result = call_operation("ancestry.check_sample_overlap")

        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["missing_library"]["library"], "ancestry-1000g-30x-grch37")
        # The install command includes the prereqs (GRCh38 panel + liftover-chains)
        # alongside the GRCh37 panel so one shell invocation produces everything
        # needed for the local lift.
        install_command = result["missing_library"]["install_command"]
        self.assertIn("ancestry-1000g-30x-grch37", install_command)
        self.assertIn("liftover-chains", install_command)
        defaults = {item["parameter"]: item for item in result["defaults_applied"]}
        self.assertEqual(defaults["genome_build"]["value"], "GRCh37")
        self.assertEqual(result["reference_panel"]["panel_id"], "1000g_30x_grch37")
        self.assertEqual(result["reference_panel"]["genome_build"], "GRCh37")

    def test_grch37_sample_with_grch37_panel_runs_overlap(self) -> None:
        # Install a synthetic GRCh37 panel and verify the GRCh37 sample is
        # actually projected against it, with the envelope and sample_qc
        # pointing at the GRCh37 panel id.
        markers = self._install_synthetic_panel(marker_count=8, genome_build="GRCh37")
        vcf = self._write_indexed_vcf("sample_grch37.vcf", markers, usable_count=8)
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=default_agi_path(vcf),
            genome_build="GRCh37",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

        with self._tiny_thresholds():
            result = call_operation("ancestry.check_sample_overlap")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sample_qc"]["genome_build"], "GRCh37")
        self.assertEqual(result["sample_qc"]["usable_marker_count"], 8)
        self.assertEqual(result["sample_qc"]["marker_overlap_quality"], "high")
        self.assertEqual(result["reference_panel"]["panel_id"], "1000g_30x_grch37")
        self.assertEqual(result["reference_panel"]["genome_build"], "GRCh37")
        self.assertEqual(result["reference_panel"]["library"], "ancestry-1000g-30x-grch37")
        self.assertEqual(result["evidence_envelope"]["coverage"]["libraries"][0]["library"], "ancestry-1000g-30x-grch37")

    def test_ancestry_build_aliases_use_matching_panel_policy(self) -> None:
        markers = self._install_synthetic_panel(marker_count=8, genome_build="GRCh37")
        vcf = self._write_indexed_vcf("sample_b37_alias.vcf", markers, usable_count=8)
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=default_agi_path(vcf),
            genome_build="b37",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

        with self._tiny_thresholds():
            result = call_operation("ancestry.check_sample_overlap")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sample_qc"]["genome_build"], "GRCh37")
        self.assertEqual(result["reference_panel"]["library"], "ancestry-1000g-30x-grch37")

    def test_explicit_build_conflict_with_agi_build_is_rejected(self) -> None:
        markers = self._install_synthetic_panel(marker_count=1)
        vcf = self._write_indexed_vcf("sample_build_conflict.vcf", markers, usable_count=1)
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=default_agi_path(vcf),
            genome_build="GRCh37",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

        result = call_operation(
            "ancestry.check_sample_overlap",
            {"agi_path": str(default_agi_path(vcf)), "genome_build": "GRCh38"},
        )

        self.assertEqual(result["status"], "out_of_scope_for_input")
        self.assertEqual(result["requested_genome_build"], "GRCh38")
        self.assertEqual(result["active_genome_index_genome_build"], "GRCh37")
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_assessed")
        self.assertEqual(
            result["evidence_envelope"]["guidance"],
            ["out_of_scope_for_input:use_active_genome_index_genome_build"],
        )

    def test_consumer_array_no_call_reason_is_preserved_in_overlap_qc(self) -> None:
        markers = self._install_synthetic_panel(marker_count=2, genome_build="GRCh37")
        raw = Path(self._home_tmp.name) / "genome_Array_No_Call_v5_Full_20260101010101.txt"
        raw.write_text(
            "# This data file generated by 23andMe at: Thu Jan 01 01:01:01 2026\n"
            "# We are using reference human assembly build 37 (also known as Annotation Release 104).\n"
            "# rsid\tchromosome\tposition\tgenotype\n"
            f"rsNoCall\t{markers[0]['chrom']}\t{markers[0]['pos']}\t--\n"
            f"rsCalled\t{markers[1]['chrom']}\t{markers[1]['pos']}\tCC\n",
            encoding="utf-8",
        )
        parsed = call_operation("genomi.parse_source", {"source": str(raw)})
        runtime_context.approve_agi_access(source=str(raw), reason="test approved Active Genome Index access")

        with self._tiny_thresholds():
            result = call_operation(
                "ancestry.check_sample_overlap",
                {
                    "agi_path": parsed["outputs"]["agi_path"],
                    "genome_build": "b37",
                },
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sample_qc"]["usable_marker_count"], 1)
        self.assertEqual(result["sample_qc"]["missing_marker_count"], 1)
        self.assertEqual(result["sample_qc"]["missing_marker_reasons"], {"missing_genotype": 1})
        self.assertEqual(result["evidence_envelope"]["observations"]["usable_marker_count"], 1)
        self.assertEqual(
            result["sample_qc"]["missing_marker_examples"][0],
            {"marker_id": "m0", "reason": "missing_genotype", "detail": [{"reason": "missing_genotype", "basis": "consumer_array"}]},
        )

    def test_unsupported_ancestry_build_is_out_of_scope(self) -> None:
        markers = self._install_synthetic_panel(marker_count=8)
        vcf = self._write_indexed_vcf("sample_unsupported_build.vcf", markers, usable_count=8)

        result = call_operation(
            "ancestry.check_sample_overlap",
            {"agi_path": str(default_agi_path(vcf)), "genome_build": "CHM13"},
        )

        self.assertEqual(result["status"], "out_of_scope_for_input")
        self.assertEqual(result["supported_genome_builds"], list(ancestry_policy.SUPPORTED_BUILDS))
        envelope = result["evidence_envelope"]
        self.assertEqual(envelope["finding_state"], "not_assessed")
        self.assertEqual(envelope["observations"]["genome_build"], "CHM13")
        self.assertEqual(envelope["observations"]["supported_genome_builds"], list(ancestry_policy.SUPPORTED_BUILDS))

    def _install_synthetic_panel(
        self, *, marker_count: int, genome_build: str = "GRCh38"
    ) -> list[dict[str, object]]:
        samples = [
            {"sample_id": "EUR1", "population": "CEU", "superpopulation": "EUR", "sex": ""},
            {"sample_id": "EUR2", "population": "CEU", "superpopulation": "EUR", "sex": ""},
            {"sample_id": "AFR1", "population": "YRI", "superpopulation": "AFR", "sex": ""},
            {"sample_id": "AFR2", "population": "YRI", "superpopulation": "AFR", "sex": ""},
        ]
        markers = [
            {"marker_id": f"m{index}", "chrom": "1", "pos": 1000 + index * 1000, "ref": "A", "alt": "C"}
            for index in range(marker_count)
        ]
        genotype_rows = [[2.0, 2.0, 0.0, 0.0] for _ in markers]
        from genomi.capabilities.ancestry import source_context as ancestry_source_context

        _write_synthetic_panel(
            reference_panels.panel_dir(genome_build=genome_build),
            samples=samples,
            markers=markers,
            genotype_rows=genotype_rows,
            component_count=2,
            genome_build=genome_build,
            panel_id=ancestry_source_context.panel_id_for_build(genome_build),
            panel_library=ancestry_source_context.panel_library_for_build(genome_build),
        )
        return markers

    def _write_indexed_vcf(self, name: str, markers: list[dict[str, object]], *, usable_count: int) -> Path:
        vcf = Path(self._home_tmp.name) / name
        lines = [
            "##fileformat=VCFv4.2",
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
        ]
        for marker in markers[:usable_count]:
            lines.append(
                "\t".join(
                    [
                        str(marker["chrom"]),
                        str(marker["pos"]),
                        str(marker["marker_id"]),
                        str(marker["ref"]),
                        str(marker["alt"]),
                        ".",
                        "PASS",
                        ".",
                        "GT",
                        "1/1",
                    ]
                )
            )
        vcf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        create_active_genome_index(vcf, parallel_workers=1, reuse_existing=False)
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=default_agi_path(vcf),
            genome_build="GRCh38",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")
        return vcf

    def _write_reference_block_vcf(self, name: str) -> Path:
        vcf = Path(self._home_tmp.name) / name
        vcf.write_text(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    '##INFO=<ID=END,Number=1,Type=Integer,Description="End position">',
                    '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
                    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
                    "1\t1000\t.\tA\t.\t.\tPASS\tEND=2000\tGT\t0/0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        create_active_genome_index(vcf, parallel_workers=1, reuse_existing=False)
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=default_agi_path(vcf),
            genome_build="GRCh38",
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")
        return vcf

    def _tiny_thresholds(self):
        # Fraction-of-panel grading is panel-size-agnostic, so no patching is
        # needed for the 8-marker synthetic panel. Kept as a no-op context
        # manager to preserve the existing call sites in this file.
        from contextlib import nullcontext
        return nullcontext()


if __name__ == "__main__":
    unittest.main()
