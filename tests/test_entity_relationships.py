from __future__ import annotations

import io
import unittest
import zipfile

from genomi.capabilities.analytical_grounding import entity_relationships


class EntityRelationshipTests(unittest.TestCase):
    def test_go_term_id_returns_goa_gene_relationship_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_id="GO:0000086",
            limit=10,
            fetch_json=_fake_entity_fetch_json,
        )

        self.assertEqual(result["schema"], "genomi-controlled-entity-relationships-v1")
        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertTrue(result["agent_decision_required"])
        self.assertNotIn("answer", result)
        self.assertEqual(result["resolved_entities"][0]["entity_type"], "go_term")
        self.assertEqual({record["gene"] for record in result["gene_relationship_records"]}, {"CDK1", "CCNB1"})
        self.assertEqual([record["gene"] for record in result["gene_relationship_records"]], ["CDK1", "CCNB1"])
        self.assertEqual(result["gene_relationship_records"][0]["relationship_type"], "involved_in")
        self.assertEqual(result["relationship_summary"]["gene_count"], 2)
        self.assertEqual(result["relationship_summary"]["genes"][0]["gene"], "CCNB1")
        self.assertIn("source_local_evidence_order", result["source_local_ordering"]["policy"])
        self.assertIn("QuickGO Gene Ontology Annotation", result["source_coverage"]["sources_consulted"])

    def test_reactome_pathway_name_returns_participant_gene_relationship_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="Urea cycle",
            entity_type="pathway",
            sources=["reactome"],
            limit=10,
            fetch_json=_fake_entity_fetch_json,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "R-HSA-70635")
        self.assertEqual({record["gene"] for record in result["gene_relationship_records"]}, {"OTC", "CPS1"})
        self.assertEqual(result["gene_relationship_records"][0]["relationship_type"], "pathway_participant")
        self.assertIn("Reactome ContentService", result["source_coverage"]["sources_consulted"])

    def test_untyped_entity_name_requires_entity_type_without_source_fanout(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="Urea cycle",
            fetch_json=_fake_entity_fetch_json,
            fetch_text=_fake_entity_fetch_text,
        )

        self.assertEqual(result["coverage_state"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "entity_type_required")
        self.assertTrue(result["resolution_candidates"])
        self.assertEqual(result["source_coverage"]["sources_consulted"], [])
        self.assertNotIn("gene_relationship_records", result)

    def test_unsupported_source_refuses_without_shape_mimicry(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="metformin",
            sources=["drugbank"],
            fetch_json=_fake_entity_fetch_json,
            fetch_text=_fake_entity_fetch_text,
        )

        self.assertEqual(result["coverage_state"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "unsupported_source")
        self.assertNotIn("gene_relationship_records", result)

    def test_kegg_chemical_name_returns_enzyme_gene_relationship_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="Pyruvate",
            entity_type="chemical",
            sources=["kegg"],
            limit=5,
            fetch_json=_fake_entity_fetch_json,
            fetch_text=_fake_entity_fetch_text,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "cpd:C00022")
        self.assertEqual({record["gene"] for record in result["gene_relationship_records"]}, {"PDHA1", "PDHB"})
        self.assertEqual(result["gene_relationship_records"][0]["relationship_type"], "enzyme_associated_with")
        self.assertIn("KEGG REST", result["source_coverage"]["sources_consulted"])
        self.assertIn("reaction direction", result["gene_relationship_records"][0]["limitations"][0])

    def test_hpa_tissue_name_returns_expression_specificity_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="liver",
            entity_type="tissue",
            sources=["hpa"],
            limit=5,
            fetch_json=_fake_entity_fetch_json,
            fetch_bytes=_fake_entity_fetch_bytes,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["resolved_entities"][0]["entity_type"], "tissue")
        self.assertEqual(result["resolved_entities"][0]["name"], "liver")
        self.assertEqual([record["gene"] for record in result["gene_relationship_records"]], ["A1BG", "A1CF"])
        self.assertEqual(result["gene_relationship_records"][0]["source"], "Human Protein Atlas")
        self.assertEqual(result["gene_relationship_records"][0]["relationship_type"], "tissue_enriched_expression")
        self.assertEqual(result["gene_relationship_records"][0]["expression"]["unit"], "nTPM")
        self.assertIn("Human Protein Atlas", result["source_coverage"]["sources_consulted"])
        self.assertNotIn("Human Protein Atlas tissue-enriched gene records", result["source_coverage"]["sources_not_integrated"])

    def test_hpa_cell_type_name_returns_single_cell_specificity_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="hepatocytes",
            entity_type="cell_type",
            sources=["hpa"],
            limit=5,
            fetch_json=_fake_entity_fetch_json,
            fetch_bytes=_fake_entity_fetch_bytes,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["resolved_entities"][0]["entity_type"], "cell_type")
        self.assertEqual({record["gene"] for record in result["gene_relationship_records"]}, {"ABCB4", "ABCC2"})
        self.assertEqual(result["gene_relationship_records"][0]["relationship_type"], "cell_type_enriched_expression")
        self.assertEqual(result["gene_relationship_records"][0]["expression"]["unit"], "nCPM")

    def test_hpa_unresolved_entity_refuses_without_gene_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="not a tissue",
            entity_type="tissue",
            sources=["hpa"],
            fetch_json=_fake_entity_fetch_json,
            fetch_bytes=_fake_entity_fetch_bytes,
        )

        self.assertEqual(result["coverage_state"], "out_of_scope_for_input")
        self.assertEqual(result["status"], "entity_not_found")
        self.assertNotIn("gene_relationship_records", result)

    def test_chembl_drug_name_returns_mechanism_target_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="aspirin",
            entity_type="drug",
            sources=["chembl"],
            limit=5,
            fetch_json=_fake_entity_fetch_json,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["resolved_entities"][0]["entity_type"], "drug")
        self.assertEqual(result["resolved_entities"][0]["entity_id"], "CHEMBL25")
        self.assertEqual({record["gene"] for record in result["gene_relationship_records"]}, {"PTGS1", "PTGS2"})
        self.assertEqual(result["gene_relationship_records"][0]["source"], "ChEMBL")
        self.assertEqual(result["gene_relationship_records"][0]["relationship_type"], "drug_target_mechanism")
        self.assertEqual(result["gene_relationship_records"][0]["mechanism"]["mechanism_of_action"], "Cyclooxygenase inhibitor")
        self.assertIn("disease-specific efficacy", result["gene_relationship_records"][0]["limitations"][0])

    def test_chembl_drug_id_returns_mechanism_target_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_id="CHEMBL25",
            entity_type="drug",
            sources=["chembl"],
            limit=5,
            fetch_json=_fake_entity_fetch_json,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual({record["gene"] for record in result["gene_relationship_records"]}, {"PTGS1", "PTGS2"})

    def test_chembl_drug_id_infers_drug_type_without_entity_type(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_id="CHEMBL25",
            sources=["chembl"],
            limit=5,
            fetch_json=_fake_entity_fetch_json,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual(result["resolved_entities"][0]["entity_type"], "drug")
        self.assertEqual({record["gene"] for record in result["gene_relationship_records"]}, {"PTGS1", "PTGS2"})

    def test_evidence_class_filter_applies_across_entity_relationship_records(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_id="GO:0000086",
            evidence_classes=["experimental"],
            limit=10,
            fetch_json=_fake_entity_fetch_json,
        )

        self.assertEqual(result["coverage_state"], "data_returned")
        self.assertEqual({record["gene"] for record in result["gene_relationship_records"]}, {"CDK1", "CCNB1"})
        self.assertEqual({record["evidence_class"] for record in result["gene_relationship_records"]}, {"experimental"})
        self.assertEqual(result["query"]["evidence_classes"], ["experimental"])

    def test_evidence_class_filter_empty_is_not_weak_ranking(self) -> None:
        result = entity_relationships.retrieve_gene_relationships(
            entity_name="Pyruvate",
            entity_type="chemical",
            sources=["kegg"],
            evidence_classes=["experimental"],
            limit=5,
            fetch_json=_fake_entity_fetch_json,
            fetch_text=_fake_entity_fetch_text,
        )

        self.assertEqual(result["coverage_state"], "in_scope_empty")
        self.assertNotIn("gene_relationship_records", result)
        self.assertNotIn("records_by_gene", result)
        self.assertNotIn("relationship_summary", result)


def _fake_entity_fetch_json(url: str):
    if "/ontology/go/terms/GO:0000086" in url:
        return {
            "results": [
                {
                    "id": "GO:0000086",
                    "name": "G2/M transition of mitotic cell cycle",
                    "aspect": "biological_process",
                    "definition": {"text": "The mitotic cell cycle transition by which a cell in G2 commits to M phase."},
                }
            ]
        }
    if "/ontology/go/search" in url:
        return {
            "results": [
                {
                    "id": "GO:0000086",
                    "name": "Urea cycle",
                    "aspect": "biological_process",
                    "definition": {"text": "Synthetic test GO candidate."},
                }
            ]
        }
    if "/annotation/search" in url:
        return {
            "results": [
                {
                    "id": "UniProtKB:P06493!1",
                    "geneProductId": "UniProtKB:P06493",
                    "qualifier": "involved_in",
                    "goId": "GO:0000086",
                    "goEvidence": "IDA",
                    "goAspect": "biological_process",
                    "symbol": "CDK1",
                    "assignedBy": "UniProt",
                    "reference": "PMID:1",
                    "taxonId": 9606,
                },
                {
                    "id": "UniProtKB:P14635!1",
                    "geneProductId": "UniProtKB:P14635",
                    "qualifier": "involved_in",
                    "goId": "GO:0000086",
                    "goEvidence": "IMP",
                    "goAspect": "biological_process",
                    "symbol": "CCNB1",
                    "assignedBy": "UniProt",
                    "reference": "PMID:2",
                    "taxonId": 9606,
                },
            ]
        }
    if "/molecule/search.json" in url:
        if "aspirin" in url.lower():
            return {
                "molecules": [
                    {
                        "molecule_chembl_id": "CHEMBL25",
                        "pref_name": "ASPIRIN",
                        "molecule_synonyms": [{"molecule_synonym": "Aspirin", "synonyms": "ASPIRIN"}],
                        "molecule_hierarchy": {"parent_chembl_id": "CHEMBL25", "active_chembl_id": "CHEMBL25"},
                        "max_phase": "4.0",
                        "first_approval": 1950,
                        "therapeutic_flag": True,
                        "molecule_type": "Small molecule",
                    }
                ]
            }
        return {"molecules": []}
    if "/molecule/CHEMBL25.json" in url:
        return {
            "molecule_chembl_id": "CHEMBL25",
            "pref_name": "ASPIRIN",
            "molecule_synonyms": [{"molecule_synonym": "Aspirin", "synonyms": "ASPIRIN"}],
            "molecule_hierarchy": {"parent_chembl_id": "CHEMBL25", "active_chembl_id": "CHEMBL25"},
            "max_phase": "4.0",
            "first_approval": 1950,
            "therapeutic_flag": True,
            "molecule_type": "Small molecule",
        }
    if "/mechanism.json" in url and "molecule_chembl_id=CHEMBL25" in url:
        return {
            "mechanisms": [
                {
                    "action_type": "INHIBITOR",
                    "direct_interaction": 1,
                    "disease_efficacy": 1,
                    "max_phase": 4,
                    "mec_id": 1187,
                    "mechanism_of_action": "Cyclooxygenase inhibitor",
                    "molecular_mechanism": 1,
                    "molecule_chembl_id": "CHEMBL25",
                    "parent_molecule_chembl_id": "CHEMBL25",
                    "target_chembl_id": "CHEMBL2094253",
                    "mechanism_refs": [{"ref_id": "17131625", "ref_type": "PubMed", "ref_url": "http://europepmc.org/abstract/MED/17131625"}],
                }
            ]
        }
    if "/target/CHEMBL2094253.json" in url:
        return {
            "organism": "Homo sapiens",
            "pref_name": "Cyclooxygenase",
            "target_chembl_id": "CHEMBL2094253",
            "target_type": "PROTEIN FAMILY",
            "target_components": [
                {
                    "accession": "P35354",
                    "component_description": "Prostaglandin G/H synthase 2",
                    "target_component_synonyms": [{"component_synonym": "PTGS2", "syn_type": "GENE_SYMBOL"}],
                },
                {
                    "accession": "P23219",
                    "component_description": "Prostaglandin G/H synthase 1",
                    "target_component_synonyms": [{"component_synonym": "PTGS1", "syn_type": "GENE_SYMBOL"}],
                },
            ],
        }
    if "/search_download.php" in url and "tissue_category_rna%3Aliver%3B" in url:
        return [
            {
                "Gene": "A1BG",
                "Gene synonym": [],
                "Ensembl": "ENSG00000121410",
                "Gene description": "Alpha-1-B glycoprotein",
                "RNA tissue specificity": "Tissue enriched",
                "RNA tissue distribution": "Detected in single",
                "RNA tissue specificity score": "736",
                "RNA tissue specific nTPM": {"liver": "565.1"},
            },
            {
                "Gene": "A1CF",
                "Gene synonym": ["ACF"],
                "Ensembl": "ENSG00000148584",
                "Gene description": "APOBEC1 complementation factor",
                "RNA tissue specificity": "Tissue enriched",
                "RNA tissue distribution": "Detected in some",
                "RNA tissue specificity score": "6",
                "RNA tissue specific nTPM": {"liver": "143.1"},
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
    if "/search/query" in url:
        return {
            "results": [
                {
                    "entries": [
                        {
                            "stId": "R-HSA-70635",
                            "name": "<span>Urea</span> cycle",
                            "type": "Pathway",
                            "exactType": "Pathway",
                            "species": ["Homo sapiens"],
                            "summation": "Urea cycle pathway.",
                        }
                    ]
                }
            ]
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
    raise AssertionError(f"Unexpected URL: {url}")


def _fake_entity_fetch_text(url: str) -> str:
    if "/find/compound/Pyruvate" in url:
        return "cpd:C00022\tPyruvate; Pyruvic acid; 2-Oxopropanoate\n"
    if "/find/compound/Urea%20cycle" in url:
        return ""
    if "/get/cpd:C00022" in url:
        return """ENTRY       C00022                      Compound
NAME        Pyruvate;
            Pyruvic acid;
FORMULA     C3H4O3
"""
    if "/link/enzyme/cpd:C00022" in url:
        return "cpd:C00022\tec:1.2.4.1\n"
    if "/link/hsa/ec%3A1.2.4.1" in url or "/link/hsa/ec:1.2.4.1" in url:
        return "ec:1.2.4.1\thsa:5160\nec:1.2.4.1\thsa:5162\n"
    if "/get/hsa:5160" in url:
        return """ENTRY       5160              CDS       T01001
SYMBOL      PDHA1, PDHA
NAME        (RefSeq) pyruvate dehydrogenase E1 subunit alpha 1
"""
    if "/get/hsa:5162" in url:
        return """ENTRY       5162              CDS       T01001
SYMBOL      PDHB
NAME        (RefSeq) pyruvate dehydrogenase E1 subunit beta
"""
    raise AssertionError(f"Unexpected URL: {url}")


def _fake_entity_fetch_bytes(url: str) -> bytes:
    if url.endswith("/rna_tissue_consensus_tissues.tsv.zip"):
        return _zip_bytes(
            "rna_tissue_consensus_tissues.tsv",
            "Tissue\tOrgan\nliver\tDigestive tract\nheart muscle\tMuscle tissue\n",
        )
    if url.endswith("/rna_single_cell_type_cell_types.tsv.zip"):
        return _zip_bytes(
            "rna_single_cell_type_cell_types.tsv",
            "Cell type\tCell type group\tCell type class\nhepatocytes\thepatocytes\tspecialized epithelial cells\npodocytes\tkidney epithelial cells\tepithelial cells\n",
        )
    raise AssertionError(f"Unexpected URL: {url}")


def _zip_bytes(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()
