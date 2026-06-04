from __future__ import annotations

import unittest

from genomi.active_genome_index import dosage as agi_dosage

from _prs_contract_helpers import (
    insert_array_prs_record,
    insert_prs_record,
    memory_prs_index,
    score_variant,
)


class PrsDosageContractTests(unittest.TestCase):
    def test_harmonization_does_not_count_third_allele_as_reference_homozygous(self) -> None:
        connection = memory_prs_index()
        insert_prs_record(connection, pos=100, ref="A", alt="G", genotype="0/1")
        variant = score_variant(pos=100, effect_allele="C", other_allele="A")

        result = agi_dosage.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "genotype_allele_outside_score_alleles")

    def test_harmonization_allows_reference_block_zero_dosage(self) -> None:
        connection = memory_prs_index()
        insert_prs_record(connection, pos=100, ref="A", alt=".", genotype="0/0")
        variant = score_variant(pos=100, effect_allele="C", other_allele="A")

        result = agi_dosage.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["effect_allele_dosage"], 0.0)
        self.assertEqual(result["match_type"], "reference_homozygous_inferred")

    def test_harmonization_counts_exact_gvcf_reference_block_effect_dosage(self) -> None:
        connection = memory_prs_index()
        insert_prs_record(connection, pos=100, ref="A", alt="<NON_REF>", genotype="0/0")
        variant = score_variant(pos=100, effect_allele="A", other_allele="G")

        result = agi_dosage.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["effect_allele_dosage"], 2.0)
        self.assertEqual(result["match_type"], "reference_homozygous_inferred")

    def test_array_harmonization_counts_effect_without_other_allele(self) -> None:
        connection = memory_prs_index()
        insert_array_prs_record(connection, pos=100, genotype="AG")
        variant = score_variant(pos=100, effect_allele="G", other_allele="")

        result = agi_dosage.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["effect_allele_dosage"], 1.0)
        self.assertEqual(result["match_type"], "consumer_array_letter_count")

    def test_array_harmonization_counts_zero_without_other_allele(self) -> None:
        connection = memory_prs_index()
        insert_array_prs_record(connection, pos=100, genotype="AA")
        variant = score_variant(pos=100, effect_allele="G", other_allele="")

        result = agi_dosage.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["effect_allele_dosage"], 0.0)
        self.assertEqual(result["match_type"], "consumer_array_letter_count")

    def test_array_harmonization_rejects_third_allele_with_complete_score_model(self) -> None:
        connection = memory_prs_index()
        insert_array_prs_record(connection, pos=100, genotype="AG")
        variant = score_variant(pos=100, effect_allele="G", other_allele="T")

        result = agi_dosage.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "genotype_allele_outside_score_alleles")

    def test_array_harmonization_treats_no_call_as_missing_not_filter_exclusion(self) -> None:
        connection = memory_prs_index()
        insert_array_prs_record(connection, pos=100, genotype="--", filter_value="NO_CALL")
        variant = score_variant(pos=100, effect_allele="G", other_allele="A")

        result = agi_dosage.dosage_for_variant(connection, variant)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "no_call")


if __name__ == "__main__":
    unittest.main()
