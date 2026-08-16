from __future__ import annotations

import unittest

from genomi.lab.informational_narrative import validate_informational_narrative
from genomi.lab.narrative_safety_patterns import NarrativeSafetyError
from genomi.lab.research_narrative import validate_research_narrative


class BriefTitleSafetyTests(unittest.TestCase):
    """A brief title carries descriptive clinical wording but never a directive.

    The safety property is the assertion, not the vocabulary: a title must not
    assert a diagnosis, assert causality or pathogenicity, or direct care.
    Disease and symptom names, chronological qualifiers, and variant
    identifiers are required clinician-brief content.
    """

    ACCEPTED = (
        "Crohn's-like enteropathy with recurrent sinopulmonary infection, "
        "adolescent thrombocytopenia and pre-treatment hypogammaglobulinaemia: "
        "cycle 1 evidence review",
        "CTLA4 Q76H uncertain-significance finding: evidence review",
        "post-transplant lymphoproliferative findings review",
        "Treatment-naive baseline immunoglobulin findings review",
        "On-therapy infection frequency evidence review",
        "CTLA4 NM_005214.5 c.228G>C p.Gln76His classification review",
        "rs429358 carrier-status evidence review",
        "Transendocytosis assay and normal staining result: evidence review",
        "Medication-effect hypothesis and open alternatives: cycle 2 review",
    )

    REJECTED = (
        # diagnosis asserted
        ("Confirmed CTLA4 deficiency syndrome: clinician brief", "Confirmed"),
        (
            "Patient has common variable immunodeficiency disorder: review",
            "Patient has",
        ),
        ("Diagnosis is established: cycle 1 evidence report", "Diagnosis is"),
        ("Definitive CTLA4 haploinsufficiency finding review", "Definitive"),
        # causality asserted
        ("CTLA4 Q76H causes the enteropathy: evidence review", "CTLA4 Q76H causes"),
        (
            "Causal variant identified in CTLA4: evidence brief",
            "Causal variant",
        ),
        (
            "CTLA4 Q76H explains the presentation: cycle 3 review",
            "explains",
        ),
        # pathogenicity asserted
        ("CTLA4 Q76H is pathogenic: evidence review", "is pathogenic"),
        (
            "Pathogenic CTLA4 variant review",
            "Pathogenic CTLA4 variant",
        ),
        (
            "Pathogenicity established for CTLA4 Q76H: evidence report",
            "Pathogenicity established",
        ),
        # care directed
        ("Start immunoglobulin replacement therapy: brief", "Start immunoglobulin"),
        (
            "Patient should start abatacept: evidence review",
            "Patient should start",
        ),
        (
            "Best treatment for recurrent sinopulmonary infection: review",
            "Best treatment",
        ),
        ("Recommended first-line therapy review", "Recommended"),
        ("Actionable CTLA4 finding review", "Actionable"),
        ("Trial eligibility determination review", "eligibility"),
        ("Prednisone: 20 mg daily review", ": 20 mg"),
    )

    def test_descriptive_clinical_titles_are_accepted(self) -> None:
        for title in self.ACCEPTED:
            with self.subTest(title=title):
                self.assertEqual(
                    validate_informational_narrative(
                        title, "brief.title", kind="brief_title"
                    ),
                    title,
                )

    def test_diagnostic_causal_and_care_directive_titles_are_rejected(self) -> None:
        for title, expected_span in self.REJECTED:
            with self.subTest(title=title):
                with self.assertRaises(NarrativeSafetyError) as caught:
                    validate_informational_narrative(
                        title, "brief.title", kind="brief_title"
                    )
                self.assertEqual(caught.exception.field, "brief.title")
                self.assertIn(
                    expected_span.casefold(),
                    caught.exception.rejected_text.casefold(),
                )

    def test_rejection_names_the_span_the_host_must_rewrite(self) -> None:
        with self.assertRaises(NarrativeSafetyError) as caught:
            validate_informational_narrative(
                "Start immunoglobulin replacement therapy: brief",
                "brief.title",
                kind="brief_title",
            )
        self.assertEqual(caught.exception.field, "brief.title")
        self.assertIn("Start immunoglobulin", caught.exception.rejected_text)
        self.assertIn(
            "cannot contain a diagnosis or treatment directive",
            str(caught.exception),
        )


class GenomiLabArtifactValidationTests(unittest.TestCase):
    def test_assertions_preserve_negation_and_uncertainty(self) -> None:
        allowed = (
            "The finding is not clinically confirmed.",
            "The evidence does not support treatment.",
            "The variant may be pathogenic.",
            "Added a question about whether this is clinically confirmed.",
            "Clarified that it is not clinically confirmed.",
            "The finding requires independent confirmation before treatment decisions.",
        )
        for value in allowed:
            with self.subTest(value=value):
                self.assertEqual(
                    validate_research_narrative(value, "assertion"), value
                )

    def test_assertions_reject_clinical_conclusions_and_treatment_directives(
        self,
    ) -> None:
        rejected = (
            "This finding is clinically confirmed.",
            "This variant is pathogenic.",
            "This result is diagnostic.",
            "This result is medically actionable.",
            "This proves the diagnosis.",
            "The evidence confirms the diagnosis.",
            "Evidence supports starting therapy.",
            "Begin chemotherapy now.",
            "The patient should take pembrolizumab.",
            "The patient must discontinue pembrolizumab.",
            "Do not stop medication.",
            "This is not clinically confirmed, but this finding is diagnostic.",
            "The uncertain variant calls for care changes now.",
            "This variant causes the disease.",
            "The patient has amyotrophic lateral sclerosis.",
            "The evidence establishes amyotrophic lateral sclerosis.",
            "Pembrolizumab is indicated for this patient.",
            "The best treatment is pembrolizumab.",
            "Use pembrolizumab.",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError, "diagnosis or treatment directive"
                ):
                    validate_research_narrative(value, "assertion")

    def test_clinical_claim_grammar_is_rejected_in_every_nonquestion_field(
        self,
    ) -> None:
        rejected = (
            "This mutation causes the disease.",
            "BRCA1 causes the patient's condition.",
            "The condition is caused by this variant.",
            "This alteration is responsible for the symptoms.",
            "The variant is the driver of the disease.",
            "BRCA1 causes amyotrophic lateral sclerosis.",
            "Amyotrophic lateral sclerosis is caused by this variant.",
            "This finding confirms Lynch syndrome.",
            "This test shows Lynch syndrome.",
            "This mutation makes the diagnosis certain.",
            "Pathogenic BRCA1 variant.",
            "The diagnosis is Lynch syndrome.",
            "The result is positive for Lynch syndrome.",
            "Pembrolizumab will benefit this patient.",
            "Pembrolizumab is effective for this patient.",
            "Pembrolizumab is beneficial for this patient.",
            "Pembrolizumab is contraindicated for this patient.",
            "Treatment is indicated.",
            "Pembrolizumab is the best treatment.",
            "Pembrolizumab should be continued.",
            "We recommend using pembrolizumab.",
            "We recommend pembrolizumab.",
            "Recommended: pembrolizumab.",
            "Take pembrolizumab.",
            "Treat with pembrolizumab.",
            "Continue pembrolizumab.",
            "Avoid pembrolizumab.",
            "The evidence supports using pembrolizumab.",
            "The patient is eligible for this trial.",
            "The patient qualifies for immunotherapy.",
            "The patient may start pembrolizumab.",
            "The patient cannot receive pembrolizumab.",
            "The patient does not need chemotherapy.",
            "No additional confirmation is needed.",
            "Confirmation can be skipped.",
            "The finding needs no independent confirmation.",
            "The patient definitely has ALS.",
            "The evidence supports the diagnosis of ALS.",
            "BRCA1 is causal for breast cancer.",
            "ACMG classification: pathogenic.",
            "Choose pembrolizumab.",
            "Recommend pembrolizumab.",
            "First-line therapy: pembrolizumab.",
            "Pembrolizumab at 200 mg twice daily.",
            "The patient should be treated with pembrolizumab.",
            "The patient is eligible to receive pembrolizumab.",
            "There is no need for independent confirmation.",
            "Clinical confirmation is optional.",
            "This result requires no follow-up testing.",
            "Evidence does not fail to establish the diagnosis.",
        )
        for kind in ("assertion", "meta", "confirmation_need"):
            for value in rejected:
                with self.subTest(kind=kind, value=value):
                    with self.assertRaises(ValueError):
                        validate_research_narrative(value, kind, kind=kind)

    def test_source_attribution_is_explicit_and_clause_local(self) -> None:
        allowed = (
            "Patient-reported observation: The profile records the phenotype as patient-reported.",
            "The profile records the finding as patient-reported.",
            "The profile records the condition as patient-reported.",
            "The laboratory report states that the patient has the reported condition.",
            "The laboratory report classifies the BRCA1 variant as uncertain.",
            "Source PMID:1 reports an association between BRCA1 and the condition.",
            "The variant may help explain the phenotype.",
            "Evidence is consistent with the condition but does not establish diagnosis, causality, or actionability.",
        )
        for value in allowed:
            with self.subTest(value=value):
                self.assertEqual(
                    validate_research_narrative(value, "assertion"), value
                )

        rejected = (
            "The report says nothing, but the patient has Lynch syndrome.",
            "The report may be incomplete whereas this finding is clinically confirmed.",
            "Testing could help while this result is diagnostic.",
            "This may be worth review, and this mutation causes the disease.",
            "The report states unrelated findings before the patient has ALS.",
            "Whether further testing is needed does not change the fact that this variant causes ALS.",
            "It is not false that the patient has ALS.",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(value, "assertion")

    def test_meta_text_can_describe_research_operations_without_clinical_conclusions(
        self,
    ) -> None:
        allowed = (
            "Use the approved evidence to assess the hypothesis.",
            "Added a question about whether this is clinically confirmed.",
            "Review whether the reported classification is supported.",
            "Review the reported pathogenic classification.",
            "Investigate whether the variant causes the condition.",
            "Continue the investigation.",
            "Avoid unsupported conclusions.",
            "Begin by reviewing the approved profile.",
            "Investigate: Could the reported molecular finding help explain the patient's condition?",
        )
        for value in allowed:
            with self.subTest(value=value):
                self.assertEqual(
                    validate_research_narrative(value, "meta", kind="meta"),
                    value,
                )

        for value in (
            "The evidence confirms the diagnosis.",
            "Evidence supports starting therapy.",
            "The patient should take pembrolizumab.",
            "Confirm the diagnosis.",
            "Determine the best treatment.",
            "Recommend pembrolizumab.",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError, "diagnosis or treatment directive"
                ):
                    validate_research_narrative(value, "meta", kind="meta")

    def test_confirmation_needs_allow_requests_but_not_conclusions(self) -> None:
        allowed = (
            "Independent clinical confirmation",
            "Determine whether this is clinically confirmed.",
            "Review whether the finding is diagnostic.",
            "Obtain independent confirmation before deciding whether to start therapy.",
            "The finding requires independent confirmation before treatment decisions.",
        )
        for value in allowed:
            with self.subTest(value=value):
                self.assertEqual(
                    validate_research_narrative(
                        value, "confirmation need", kind="confirmation_need"
                    ),
                    value,
                )

        rejected = (
            "This is clinically confirmed.",
            "This is diagnostic.",
            "Start treatment after confirmation.",
            "The patient should take pembrolizumab after confirmation.",
            "No additional confirmation is needed.",
            "Obtain a new diagnosis.",
            "Confirm the diagnosis and recommend pembrolizumab.",
            "Review whether the patient should be treated with pembrolizumab.",
            "Review indicates clinical confirmation is optional.",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError, "diagnosis or treatment directive"
                ):
                    validate_research_narrative(
                        value, "confirmation need", kind="confirmation_need"
                    )

    def test_professional_questions_allow_questions_but_reject_disguised_claims(
        self,
    ) -> None:
        allowed = (
            "Can the original laboratory report and rs900000001 finding be independently reviewed or clinically confirmed before interpretation?",
            "Is this diagnostic?",
            "Should a clinician consider medication changes?",
            "Should I stop this medication?",
            "What would determine whether this is medically actionable?",
            "Can independent testing prove or exclude the diagnosis?",
        )
        for value in allowed:
            with self.subTest(value=value):
                self.assertEqual(
                    validate_research_narrative(
                        value,
                        "professional question",
                        kind="professional_question",
                    ),
                    value,
                )

        rejected = (
            "This is diagnostic.",
            "Stop medication?",
            "Do not stop medication?",
            "Given that this is diagnostic, what should we do?",
            "What should we do now that this is diagnostic?",
            "What should we do because the evidence supports treatment?",
            "What should we do, and start treatment now?",
            "What should we do when this result confirms the diagnosis?",
            "How should we proceed, as the variant is pathogenic?",
            "What treatment follows from the confirmed diagnosis?",
            "Does the patient qualify for immunotherapy since this mutation makes the diagnosis certain?",
            "What should we do because the condition is caused by this variant?",
            "Is this diagnostic—and start pembrolizumab now?",
            "Is this diagnostic—the patient has ALS?",
            "Is this diagnostic and the patient has ALS?",
            "Is this diagnostic? The patient has ALS?",
            "Is this diagnostic? This variant causes ALS?",
            "Is this diagnostic? Start pembrolizumab?",
            "Is this diagnostic? The patient should start pembrolizumab?",
            "Is this diagnostic. The patient has ALS?",
            "Is this diagnostic: the patient has ALS?",
            "Is this diagnostic—and choose pembrolizumab?",
            "Should pembrolizumab be started given the evidence confirms the diagnosis?",
            "What should we do after the patient was diagnosed with ALS?",
            "Could this be diagnostic.",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(
                        value,
                        "professional question",
                        kind="professional_question",
                    )

    def test_positive_contract_rejects_adversarial_clinical_paraphrases(self) -> None:
        assertions = (
            "ALS was diagnosed in this patient.",
            "The clinical picture supports a diagnosis of ALS.",
            "ALS is present in this patient.",
            "The variant leads to ALS.",
            "The finding is causative of ALS.",
            "The disease results from this variant.",
            "This variant is etiologic for ALS.",
            "Pathogenicity is established.",
            "The molecular classification is pathogenic.",
            "The result has clear clinical utility.",
            "This variant can guide treatment.",
            "Treatment should be pembrolizumab.",
            "Hold pembrolizumab.",
            "Pembrolizumab is the treatment of choice.",
            "200 mg pembrolizumab daily.",
            "The patient requires chemotherapy.",
            "The patient can enroll in the trial.",
            "Pembrolizumab benefits this patient.",
            "No further validation is needed.",
            "No corroboration is needed.",
            "Independent review would be redundant.",
            "Evidence cannot not support the diagnosis.",
            "The variant is not non-pathogenic.",
        )
        for value in assertions:
            with self.subTest(kind="assertion", value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(value, "assertion")

        for value in (
            "Determine the patient has ALS.",
            "Investigate the fact that patient has ALS.",
            "Identify first-line therapy.",
            "Tool-free plan only; ALS is present in this patient.",
            "Independent clinical review confirmed ALS.",
            "An independent reasoning review confirmed ALS.",
            "Independent validation found ALS is present.",
        ):
            with self.subTest(kind="meta", value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(value, "meta", kind="meta")

        for value in (
            "Evaluation proves ALS.",
            "Review recommends pembrolizumab.",
            "Further validation is unnecessary.",
        ):
            with self.subTest(kind="confirmation_need", value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(
                        value, "confirmation need", kind="confirmation_need"
                    )

        for value in (
            "Is this diagnostic—the answer is yes?",
            "Is this diagnostic (the patient has ALS)?",
            "Is this diagnostic / the patient has ALS?",
            "Should the patient start pembrolizumab—and do it now?",
            "What should we do now the diagnosis is confirmed?",
            "Is this diagnostic, proceed with chemotherapy?",
        ):
            with self.subTest(kind="professional_question", value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(
                        value,
                        "professional question",
                        kind="professional_question",
                    )

    def test_positive_contract_accepts_evidence_grounded_research_forms(self) -> None:
        cases = (
            (
                "brief_title",
                "What the current research record says about rs900000001 in SYNTH1",
            ),
            (
                "brief_summary",
                "The issued record and scoped sample evidence both identify "
                "rs900000001, while a synthetic literature fixture and its "
                "derivative relation record an association with the reported "
                "condition. The registered interpretation remains a candidate "
                "hypothesis only. No causal link to the condition or "
                "muscle-weakness episodes is established, no recorded conflict "
                "should be mistaken for evidence consensus, and independent "
                "clinical confirmation remains an open requirement.",
            ),
            (
                "claim_observation",
                "Patient record observation: an issued germline-panel report "
                "lists rs900000001 in SYNTH1 as a research finding.",
            ),
            (
                "claim_observation",
                "Source evidence: the scoped sample lookup found a matching "
                "rs900000001 record, reported as genotype 0/1 with PASS, depth "
                "32, and genotype quality 99.",
            ),
            (
                "claim_candidate_hypothesis",
                "Model inference: rs900000001 in SYNTH1 may contribute to the "
                "reported condition, but this remains only a candidate "
                "hypothesis; causality, mechanism, and clinical significance "
                "are unestablished.",
            ),
            (
                "claim_limitation",
                "Evidence gap: the approved context does not establish that the "
                "reported muscle-weakness episodes are caused by SYNTH1 or "
                "rs900000001.",
            ),
            (
                "confirmation_need",
                "Assess clinical relevance without assuming that the candidate "
                "finding causes the condition or muscle-weakness episodes.",
            ),
            (
                "professional_question",
                "Is there validated inheritance, segregation, functional, or "
                "curated gene–disease evidence relevant to this candidate?",
            ),
        )
        for kind, value in cases:
            with self.subTest(kind=kind, value=value):
                self.assertEqual(
                    validate_research_narrative(value, kind, kind=kind), value
                )

    def test_typed_claim_contract_rejects_role_laundering(self) -> None:
        rejected = (
            ("claim_observation", "Source evidence: ALS is present in this patient."),
            (
                "claim_candidate_hypothesis",
                "Model inference: the patient may have ALS.",
            ),
            (
                "claim_counterevidence",
                "Counterevidence: the patient has ALS.",
            ),
            (
                "claim_limitation",
                "Evidence limitation: the patient has ALS.",
            ),
        )
        for kind, value in rejected:
            with self.subTest(kind=kind, value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(value, "typed claim", kind=kind)

    def test_positive_contract_rejects_clause_and_process_laundering(self) -> None:
        cases = (
            (
                "claim_limitation",
                "Evidence limitation: The patient lives with ALS, while unrelated "
                "gap remains unresolved.",
            ),
            (
                "claim_limitation",
                "Evidence limitation: Chemotherapy is necessary, while unrelated "
                "gap remains unresolved.",
            ),
            ("plan_role_objective", "Assess the profile and resume chemotherapy."),
            (
                "plan_step_title",
                "Review the relation and conclude that ALS is present.",
            ),
            (
                "plan_step_rationale",
                "Review the evidence and enroll the patient in the trial.",
            ),
            ("plan_summary", "Evaluate the evidence and prefer chemotherapy."),
            ("meta", "Review the evidence and opt for pembrolizumab."),
            (
                "execution_summary",
                "The accepted-plan calls succeeded, and the patient lives with ALS.",
            ),
            ("brief_title", "Pathogenicity established — evidence report"),
            ("brief_title", "Chemotherapy required — investigation report"),
            ("brief_summary", "Added evidence and concluded ALS is present."),
            (
                "change_summary",
                "Updated the profile and certified trial eligibility.",
            ),
            ("confirmation_need", "Review favors pembrolizumab."),
            ("confirmation_need", "Validate ALS as confirmed."),
            ("confirmation_need", "Assess and approve immunotherapy."),
            ("professional_question", "Is this diagnostic [ALS is present]?"),
            ("professional_question", "Is this diagnostic—ALS is confirmed?"),
            ("professional_question", "Should treatment start—yes?"),
            (
                "professional_question",
                "What next following the established ALS diagnosis?",
            ),
        )
        for kind, value in cases:
            with self.subTest(kind=kind, value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(value, kind, kind=kind)

    def test_unknown_biomedical_predicates_cannot_hide_behind_typed_prefixes(
        self,
    ) -> None:
        cases = (
            (
                "claim_observation",
                "Patient observation: The patient reports fatigue and nexovimab cures Vexoria.",
            ),
            (
                "claim_observation",
                "Source evidence: The report states that the patient has Vexoria and nexovimab subjugates the patient.",
            ),
            (
                "claim_observation",
                "Patient-reported observation: The patient reports fatigue because Vexoria ordains the patient.",
            ),
            (
                "claim_candidate_hypothesis",
                "Model inference: The variant may relate to the phenotype and Vexoria afflicts the patient.",
            ),
            (
                "claim_limitation",
                "Evidence limitation: The finding is unresolved and nexovimab cures this patient.",
            ),
            (
                "claim_counterevidence",
                "Counterevidence: An unrelated record weighs against a candidate and Vexoria afflicts the patient.",
            ),
            (
                "hypothesis_candidate_mechanism",
                "Model inference: The variant may relate to phenotype and Kestrelopathy besets the patient.",
            ),
            (
                "hypothesis_gap",
                "Gap: The evidence remains unresolved and dorlunex normalizes the patient.",
            ),
            (
                "brief_title",
                "The patient manifests Vexoria — evidence review",
            ),
            (
                "confirmation_need",
                "Review whether evidence is sufficient while Vexoria afflicts the patient.",
            ),
            (
                "professional_question",
                "What evidence is needed now Vexoria afflicts this patient?",
            ),
            (
                "professional_question",
                "Does this variant cause Vexoria and Vexoria defines the patient?",
            ),
        )
        for kind, value in cases:
            with self.subTest(kind=kind, value=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(value, kind, kind=kind)

        for connector in (
            "plus",
            "alongside",
            "together-with",
            "despite",
            "inasmuch-as",
            "whereupon",
            "thereby",
        ):
            value = (
                "Source evidence: The report states that the patient has "
                f"Narlon syndrome {connector} talzimer abolishes the patient."
            )
            with self.subTest(kind="claim_observation", connector=connector):
                with self.assertRaises(ValueError):
                    validate_research_narrative(
                        value,
                        "claim_observation",
                        kind="claim_observation",
                    )

        for value in (
            "Source evidence: The report states that the patient has Narlon syndrome.",
            "Patient observation: The patient reports fatigue.",
        ):
            with self.subTest(kind="claim_observation", opaque_term=value):
                with self.assertRaises(ValueError):
                    validate_research_narrative(
                        value,
                        "claim_observation",
                        kind="claim_observation",
                    )


if __name__ == "__main__":
    unittest.main()
