from __future__ import annotations

import gzip
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from genomi.capabilities.analytical_grounding import analytical_grounding
from genomi.operations import list_operations


class AnalyticalGroundingTests(unittest.TestCase):
    def test_reactome_pathway_members_project_relationship_records(self) -> None:
        result = analytical_grounding.retrieve_pathway_member_genes(
            pathway_id_or_name="R-HSA-70635",
            source="reactome",
            fetch_json=_fake_fetch_json,
        )

        self.assertEqual(result["schema"], "genomi-pathway-member-genes-v1")
        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["pathway"]["id"], "R-HSA-70635")
        self.assertEqual({member["gene_symbol"] for member in result["members"]}, {"OTC", "CPS1"})
        self.assertNotIn("answer", result)
        self.assertTrue(result["agent_decision_required"])

    def test_kegg_pathway_members_return_human_gene_symbols(self) -> None:
        result = analytical_grounding.retrieve_pathway_member_genes(
            pathway_id_or_name="hsa00010",
            source="kegg",
            fetch_text=_fake_fetch_text,
        )

        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["pathway"]["source"], "kegg")
        self.assertEqual([member["gene_symbol"] for member in result["members"]], ["HK1", "GPI"])
        self.assertEqual(result["members"][0]["source_evidence"]["evidence_class"], "kegg_pathway_membership")

    def test_pathway_members_use_host_semantic_pathway_hint(self) -> None:
        result = analytical_grounding.retrieve_pathway_member_genes(
            pathway_id_or_name="nitrogen waste pathway",
            source="reactome",
            fetch_json=_fake_fetch_json,
            semantic_context={
                "raw_query": "genes in the nitrogen waste pathway",
                "host_expansions": ["R-HSA-70635"],
                "host_entities": [{"text": "R-HSA-70635", "type": "pathway"}],
            },
        )

        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["pathway"]["id"], "R-HSA-70635")
        accepted = {item["text"] for item in result["semantic_context"]["term_matches"]}
        self.assertIn("R-HSA-70635", accepted)

    def test_msigdb_hallmark_members_use_supplied_gmt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gmt = Path(tmp) / "hallmark.gmt"
            gmt.write_text(
                "HALLMARK_G2M_CHECKPOINT\thttps://example.test/msigdb\tCDK1\tCCNB1\n",
                encoding="utf-8",
            )

            result = analytical_grounding.retrieve_pathway_member_genes(
                pathway_id_or_name="G2M checkpoint",
                source="msigdb_hallmark",
                msigdb_gmt=gmt,
                msigdb_version="test",
            )

        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["pathway"]["id"], "HALLMARK_G2M_CHECKPOINT")
        self.assertEqual({member["gene_symbol"] for member in result["members"]}, {"CDK1", "CCNB1"})

    def test_free_text_pathway_without_source_requires_declared_source(self) -> None:
        result = analytical_grounding.retrieve_pathway_member_genes(
            pathway_id_or_name="Urea cycle",
            fetch_json=_fake_fetch_json,
        )

        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "source_required")
        self.assertNotIn("members", result)
        self.assertTrue(result["resolution_candidates"])

    def test_hpa_cell_type_markers_project_marker_records(self) -> None:
        result = analytical_grounding.retrieve_canonical_markers(
            cell_type_id_or_name="hepatocytes",
            source="hpa",
            fetch_json=_fake_fetch_json,
            fetch_bytes=_fake_fetch_bytes,
        )

        self.assertEqual(result["schema"], "genomi-cell-type-canonical-markers-v1")
        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["cell_type"]["source"], "hpa")
        self.assertEqual([marker["gene_symbol"] for marker in result["markers"]], ["ABCB4", "ABCC2"])
        self.assertEqual(result["markers"][0]["marker_strength"]["expression_unit"], "nCPM")
        self.assertNotIn("answer", result)

    def test_cell_type_markers_use_host_semantic_cell_hint(self) -> None:
        result = analytical_grounding.retrieve_canonical_markers(
            cell_type_id_or_name="liver cells",
            source="hpa",
            fetch_json=_fake_fetch_json,
            fetch_bytes=_fake_fetch_bytes,
            semantic_context={
                "raw_query": "markers for liver cells",
                "host_expansions": ["hepatocytes"],
                "host_entities": [{"text": "hepatocytes", "type": "cell_type"}],
            },
        )

        self.assertEqual(result["coverage_status"], "data_returned")
        accepted = {item["text"] for item in result["semantic_context"]["term_matches"]}
        self.assertIn("hepatocytes", accepted)

    def test_table_cell_type_markers_return_clean_empty_for_in_scope_absence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "markers.tsv"
            table.write_text(
                "cell_type\tgene_symbol\tmarker_strength\tlineage_context\n"
                "hepatocytes\tALB\tstrong\tepithelium\n",
                encoding="utf-8",
            )

            result = analytical_grounding.retrieve_canonical_markers(
                cell_type_id_or_name="podocytes",
                source="cellmarker",
                marker_table=table,
            )

        self.assertEqual(result["coverage_status"], "in_scope_empty")
        self.assertEqual(result["status"], "no_canonical_markers")
        self.assertNotIn("markers", result)

    def test_cellmarker_table_prefers_cell_name_and_gene_symbol_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "cellmarker.tsv"
            table.write_text(
                "species\tcell_type\tcell_name\tmarker\tSymbol\ttissue_type\n"
                "Human\tNormal cell\tMacrophage\tCD16\tFCGR3A\tLung\n",
                encoding="utf-8",
            )

            result = analytical_grounding.retrieve_canonical_markers(
                cell_type_id_or_name="Macrophage",
                source="cellmarker",
                marker_table=table,
            )

        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["markers"][0]["gene_symbol"], "FCGR3A")

    def test_region_feature_annotation_overlaps_gencode_and_encode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gtf = Path(tmp) / "gencode.gtf"
            bed = Path(tmp) / "ccre.bed"
            gtf.write_text(
                'chr1\tGENCODE\tgene\t1000\t1500\t.\t+\t.\tgene_id "ENSG1"; gene_name "GENE1"; gene_type "protein_coding";\n'
                'chr1\tGENCODE\texon\t1100\t1200\t.\t+\t.\tgene_id "ENSG1"; gene_name "GENE1"; transcript_id "ENST1";\n',
                encoding="utf-8",
            )
            bed.write_text("chr1\t1149\t1300\tEH38E1\t0\t.\t1150\t1300\t255,0,0\tpromoter-like\n", encoding="utf-8")

            result = analytical_grounding.retrieve_region_feature_annotation(
                region="1:1150-1175",
                assembly="GRCh38",
                gencode_gtf=gtf,
                encode_ccre_bed=bed,
            )

        self.assertEqual(result["schema"], "genomi-region-feature-annotation-v1")
        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["classification"]["distance_to_nearest_TSS"], 150)
        self.assertEqual({feature["source"] for feature in result["features"]}, {"GENCODE", "ENCODE cCRE"})
        self.assertIn("GENCODE GTF", result["source_coverage"]["sources_consulted"])
        self.assertIn("ENCODE cCRE BED", result["source_coverage"]["sources_consulted"])

    def test_region_feature_annotation_rejects_unsupported_assembly(self) -> None:
        result = analytical_grounding.retrieve_region_feature_annotation(
            region="1:100-200",
            assembly="mm10",
            gencode_gtf="unused.gtf",
        )

        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "unsupported_assembly")
        self.assertEqual(result["features"], [])

    def test_region_feature_annotation_reports_source_unavailable_for_missing_files(self) -> None:
        result = analytical_grounding.retrieve_region_feature_annotation(
            region="1:100-200",
            assembly="GRCh38",
            gencode_gtf="/definitely/not/here.gtf",
        )

        self.assertEqual(result["coverage_status"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["features"], [])
        self.assertTrue(result["source_coverage"]["sources_consulted_but_unavailable"])

    def test_region_feature_annotation_uses_installed_default_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            gtf = analytical_grounding.analytical_library_path("gencode-grch38")
            gtf.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(gtf, "wt", encoding="utf-8") as handle:
                handle.write('chr1\tGENCODE\tgene\t1000\t1500\t.\t+\t.\tgene_id "ENSG1"; gene_name "GENE1";\n')

            result = analytical_grounding.retrieve_region_feature_annotation(
                region="1:1100-1200",
                assembly="GRCh38",
            )

        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["query"]["gencode_gtf"], str(gtf))
        self.assertEqual(result["features"][0]["gene_symbol"], "GENE1")

    def test_region_feature_annotation_reports_missing_default_library_install_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            result = analytical_grounding.retrieve_region_feature_annotation(
                region="1:1100-1200",
                assembly="GRCh38",
            )

        self.assertEqual(result["status"], "requires_library_install")
        self.assertFalse(result["tool_will_work"])
        self.assertEqual(result["missing_library"]["library"], "gencode-grch38")
        self.assertIn("--libraries gencode-grch38", result["ask_user"]["install_command"])

    def test_cellmarker_uses_installed_default_marker_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            table = analytical_grounding.analytical_library_path("cellmarker-human")
            table.parent.mkdir(parents=True, exist_ok=True)
            table.write_text(
                "cell_type\tgene_symbol\tlineage_context\n"
                "Hepatocyte\tALB\tLiver\n",
                encoding="utf-8",
            )

            result = analytical_grounding.retrieve_canonical_markers(
                cell_type_id_or_name="Hepatocyte",
                source="cellmarker",
            )

        self.assertEqual(result["coverage_status"], "data_returned")
        self.assertEqual(result["markers"][0]["gene_symbol"], "ALB")

    def test_cellmarker_reports_missing_default_library_install_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            result = analytical_grounding.retrieve_canonical_markers(
                cell_type_id_or_name="Hepatocyte",
                source="cellmarker",
            )

        self.assertEqual(result["status"], "requires_library_install")
        self.assertEqual(result["missing_library"]["library"], "cellmarker-human")
        self.assertIn("CellMarker", result["how_it_helps"])

    def test_msigdb_reports_manual_library_install_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GENOMI_HOME": tmp}):
            result = analytical_grounding.retrieve_pathway_member_genes(
                pathway_id_or_name="HALLMARK_APOPTOSIS",
                source="msigdb_hallmark",
            )

        self.assertEqual(result["status"], "requires_library_install")
        self.assertTrue(result["missing_library"]["manual_source_required"])
        self.assertIn("--msigdb-gmt", result["ask_user"]["install_command"])

    def test_operation_metadata_exposes_analytical_grounding_capability(self) -> None:
        capability_tools = {tool["name"]: tool for tool in list_operations(capability="analytical-grounding")}

        self.assertIn("pathway.retrieve_members", capability_tools)
        self.assertIn("cell_type.retrieve_markers", capability_tools)
        self.assertIn("region.retrieve_features", capability_tools)
        self.assertEqual(capability_tools["pathway.retrieve_members"]["annotations"]["toolCapability"], "analytical-grounding")
        self.assertEqual(capability_tools["pathway.retrieve_members"]["annotations"]["operationScope"], "read")
        self.assertEqual(capability_tools["pathway.retrieve_members"]["annotations"]["privacyScope"], "public_metadata")
        self.assertEqual(capability_tools["region.retrieve_features"]["annotations"]["discoveryRole"], "entry_tool")


def _fake_fetch_json(url: str):
    if "/data/query/R-HSA-70635" in url:
        return {
            "stId": "R-HSA-70635",
            "displayName": "Urea cycle",
            "schemaClass": "Pathway",
            "species": {"displayName": "Homo sapiens"},
            "summation": [{"text": "Urea cycle pathway."}],
        }
    if "/data/participants/R-HSA-70635" in url:
        return [
            {
                "peDbId": 1,
                "refEntities": [
                    {
                        "stId": "uniprot:P00480",
                        "identifier": "P00480",
                        "displayName": "UniProt:P00480 OTC",
                        "url": "http://purl.uniprot.org/uniprot/P00480",
                    }
                ],
            },
            {
                "peDbId": 2,
                "refEntities": [
                    {
                        "stId": "uniprot:P31327",
                        "identifier": "P31327",
                        "displayName": "UniProt:P31327 CPS1",
                        "url": "http://purl.uniprot.org/uniprot/P31327",
                    }
                ],
            },
        ]
    if "/search_download.php" in url and "cell_type_category_rna%3Ahepatocytes%3B" in url:
        return [
            {
                "Gene": "ABCB4",
                "Gene synonym": ["MDR3"],
                "Ensembl": "ENSG00000005471",
                "Gene description": "ATP binding cassette subfamily B member 4",
                "RNA single cell type specificity": "Cell type enriched",
                "RNA single cell type distribution": "Detected in many",
                "RNA single cell type specificity score": "5",
                "RNA single cell type specific nCPM": {"Hepatocytes": "614.1"},
            },
            {
                "Gene": "ABCC2",
                "Gene synonym": ["MRP2"],
                "Ensembl": "ENSG00000023839",
                "Gene description": "ATP binding cassette subfamily C member 2",
                "RNA single cell type specificity": "Cell type enriched",
                "RNA single cell type distribution": "Detected in many",
                "RNA single cell type specificity score": "4",
                "RNA single cell type specific nCPM": {"Hepatocytes": "583.5"},
            },
        ]
    raise AssertionError(f"Unexpected URL: {url}")


def _fake_fetch_text(url: str) -> str:
    if "/get/hsa00010" in url:
        return """ENTRY       hsa00010                    Pathway
NAME        Glycolysis / Gluconeogenesis - Homo sapiens (human)
"""
    if "/link/hsa/hsa00010" in url:
        return "path:hsa00010\thsa:3098\npath:hsa00010\thsa:2821\n"
    if "/get/hsa:3098" in url:
        return """ENTRY       3098              CDS       T01001
SYMBOL      HK1, HXK1
NAME        (RefSeq) hexokinase 1
"""
    if "/get/hsa:2821" in url:
        return """ENTRY       2821              CDS       T01001
SYMBOL      GPI
NAME        (RefSeq) glucose-6-phosphate isomerase
"""
    raise AssertionError(f"Unexpected URL: {url}")


def _fake_fetch_bytes(url: str) -> bytes:
    if url.endswith("/rna_single_cell_type_cell_types.tsv.zip"):
        return _zip_bytes(
            "rna_single_cell_type_cell_types.tsv",
            "Cell type\tCell type group\tCell type class\nhepatocytes\thepatocytes\tspecialized epithelial cells\n",
        )
    raise AssertionError(f"Unexpected URL: {url}")


def _zip_bytes(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
