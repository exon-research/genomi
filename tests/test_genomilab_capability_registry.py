from __future__ import annotations

import unittest

from genomi.lab.capability_registry import (
    BackgroundJobOwner,
    CAPABILITY_ALLOWLIST,
    CAPABILITY_DEFINITIONS,
    CapabilityFamily,
    GENOMI_VARIANT_FIND_GENE_VARIANTS,
    GENOMI_VARIANT_RESOLVE,
    PROFILE_PROJECT,
    PUBLIC_EVIDENCE_RETRIEVE,
    capability_definition,
)
from genomi.lab.disease_evidence_catalog import LOCAL_DISEASE_EVIDENCE_CAPABILITIES
from genomi.lab.disease_evidence_external import (
    EXTERNAL_DISEASE_EVIDENCE_CAPABILITIES,
)
from genomi.lab.agent_artifacts import BRIEF_SCHEMA, PLAN_SCHEMA
from genomi.lab.narrative_contract import (
    NarrativeStatementId,
    declared_narrative,
    narrative_text,
)


class CapabilityRegistryTests(unittest.TestCase):
    def test_registry_is_the_complete_allowlist(self) -> None:
        self.assertEqual(CAPABILITY_ALLOWLIST, frozenset(CAPABILITY_DEFINITIONS))
        self.assertTrue(
            LOCAL_DISEASE_EVIDENCE_CAPABILITIES.issubset(CAPABILITY_ALLOWLIST)
        )
        self.assertTrue(
            EXTERNAL_DISEASE_EVIDENCE_CAPABILITIES.issubset(CAPABILITY_ALLOWLIST)
        )

    def test_registry_owns_execution_approval_and_resume_policy(self) -> None:
        self.assertEqual(
            capability_definition(PROFILE_PROJECT).family,
            CapabilityFamily.PROFILE_PROJECTION,
        )
        self.assertEqual(
            capability_definition(GENOMI_VARIANT_RESOLVE).background_job_owner,
            BackgroundJobOwner.GENOMI,
        )
        candidate_scan = capability_definition(GENOMI_VARIANT_FIND_GENE_VARIANTS)
        self.assertEqual(candidate_scan.family, CapabilityFamily.GENOMI_VARIANT)
        self.assertEqual(candidate_scan.background_job_owner, BackgroundJobOwner.NONE)
        self.assertEqual(
            candidate_scan.privacy,
            "bounded_candidate_gene_genomi_authorization_required",
        )
        public = capability_definition(PUBLIC_EVIDENCE_RETRIEVE)
        self.assertTrue(public.requires_exact_egress_approval)
        self.assertEqual(
            public.background_job_owner, BackgroundJobOwner.PUBLIC_EVIDENCE
        )
        for capability in EXTERNAL_DISEASE_EVIDENCE_CAPABILITIES:
            definition = capability_definition(capability)
            self.assertEqual(
                definition.family, CapabilityFamily.SOURCE_PUBLIC_EVIDENCE
            )
            self.assertTrue(definition.requires_exact_egress_approval)

    def test_unknown_capability_fails_at_the_registry_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported investigation capability"):
            capability_definition("unknown.capability")

    def test_plan_is_declared_and_brief_accepts_bounded_host_synthesis(self) -> None:
        plan_summary = narrative_text(NarrativeStatementId.PLAN_SUMMARY)
        self.assertEqual(PLAN_SCHEMA["properties"]["summary"]["enum"], [plan_summary])
        self.assertIsNotNone(declared_narrative(plan_summary, "plan_summary"))
        claim_statement = BRIEF_SCHEMA["properties"]["claims"]["items"][
            "properties"
        ]["statement"]
        self.assertEqual(claim_statement["type"], "string")
        self.assertGreaterEqual(claim_statement["minLength"], 1)
        self.assertGreater(
            claim_statement["maxLength"], claim_statement["minLength"]
        )
        self.assertNotIn("enum", claim_statement)


if __name__ == "__main__":
    unittest.main()
