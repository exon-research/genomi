from __future__ import annotations

import tempfile
import unittest

from genomi.capabilities.sequence.sequence import (
    check_primers,
    find_orfs,
    find_restriction_sites,
    kozak_context,
    match_reference_records,
    translate_sequence,
)
from genomi.operations import call_operation


class SequenceUtilityTests(unittest.TestCase):
    def test_translate_sequence(self) -> None:
        result = translate_sequence("ATGGCCATTGTAATGGGCCGCTGA", frame=1)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["translation"]["amino_acids"], "MAIVMGR*")

    def test_find_orfs_reports_coordinates(self) -> None:
        result = find_orfs("CCCATGAAATAAGGG", min_aa=2, strand="forward")

        self.assertEqual(result["summary"]["orf_count"], 1)
        self.assertEqual(result["orfs"][0]["start"], 4)
        self.assertEqual(result["orfs"][0]["end"], 12)
        self.assertEqual(result["orfs"][0]["translation"], "MK*")

    def test_find_restriction_sites_common_enzymes(self) -> None:
        result = find_restriction_sites("TTTGAATTCGGATCC", enzymes=["EcoRI", "BamHI"])

        enzymes = {item["name"]: item for item in result["enzymes"]}
        self.assertEqual(enzymes["ECORI"]["sites"][0]["start"], 4)
        self.assertEqual(enzymes["BAMHI"]["sites"][0]["start"], 10)

    def test_kozak_context_classifies_start(self) -> None:
        result = kozak_context("CCACCATGG", start_pos=6)

        self.assertEqual(result["starts"][0]["strength"], "strong")
        self.assertEqual(result["starts"][0]["minus3"], "A")
        self.assertEqual(result["starts"][0]["plus4"], "G")

    def test_check_primers_reports_amplicon(self) -> None:
        result = check_primers(
            forward_primer="ATGAAA",
            reverse_primer="CCCTTT",
            template="GGGATGAAATTTGGGAAAGGG",
        )

        self.assertEqual(result["summary"]["amplicon_count"], 1)
        self.assertEqual(result["amplicons"][0]["forward_start"], 4)

    def test_match_reference_records_returns_identity_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fasta = f"{tmp}/refs.fa"
            with open(fasta, "w", encoding="utf-8") as handle:
                handle.write(">NM_0001 gene=TEST1 product:Example\n")
                handle.write("GGGATGAAATAACCC\n")
                handle.write(">NM_0002 gene=OTHER\n")
                handle.write("TTTTTT\n")

            result = match_reference_records("ATGAAATAA", fasta)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["identity_chain"]["matched_record_ids"], ["NM_0001"])
        self.assertEqual(result["reference_matches"][0]["match_type"], "query_subsequence_of_record")
        self.assertEqual(result["reference_matches"][0]["annotations"]["gene"], "TEST1")

    def test_sequence_analyze_can_include_reference_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fasta = f"{tmp}/refs.fa"
            with open(fasta, "w", encoding="utf-8") as handle:
                handle.write(">NM_0001 gene=TEST1\nGGGATGAAATAACCC\n")

            result = call_operation("sequence.analyze", {"sequence": "ATGAAATAA", "reference_fasta": fasta})

        self.assertEqual(result["analyses"]["reference_matches"]["status"], "matched")
        self.assertEqual(result["analyses"]["reference_matches"]["identity_chain"]["matched_record_ids"], ["NM_0001"])

    def test_sequence_operations_are_registered(self) -> None:
        result = call_operation("sequence.translate", {"sequence": "ATGTAA"})

        self.assertEqual(result["translation"]["amino_acids"], "M*")


if __name__ == "__main__":
    unittest.main()
