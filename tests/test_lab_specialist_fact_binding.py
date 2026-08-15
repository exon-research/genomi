from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.lab.store import GenomiLabStore
from genomi.runtime import context as runtime_context


class LabSpecialistFactBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_home = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_home.cleanup)
        self._environment = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(Path(self._temporary_home.name) / "home"),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "lab-specialist-fact-binding-tests",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._environment.start()
        self.addCleanup(self._environment.stop)
        self.store = GenomiLabStore()
        self.store.open_workspace("user-a", "Synthetic user")

    def test_profile_update_fact_binding_can_prepare_specialist_brief(self) -> None:
        created = self.store.create_lab_investigation(
            "user-a",
            workspace_session_id="session-a",
            question="Could the reported features have a shared explanation?",
            command_id="create-investigation",
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        updated = self.store.update_health_profile(
            "user-a",
            investigation_id,
            workspace_session_id="session-a",
            facts=[
                {
                    "modality": "phenotype",
                    "label": "Synthetic private feature",
                    "original_wording": "Synthetic private wording",
                }
            ],
            purpose="Capture the reported feature",
            command_id="update-profile",
            expected_revision=1,
        )

        self.assertEqual(
            updated["source_fact_ids"],
            updated["profile_snapshot"]["observation_revision_ids"],
        )
        cycle = self.store.create_investigation_cycle(
            investigation_id,
            purpose="Research a general mechanism",
            command_id="create-cycle",
            expected_revision=2,
        )
        brief = self.store.prepare_specialist_brief(
            investigation_id,
            cycle_id=cycle["cycle"]["cycle_id"],
            specialist_role="Public evidence reviewer",
            execution_policy="reasoning_only",
            research_question="Compare public evidence for a reference mechanism.",
            public_concepts=[],
            abstract_relations=[],
            public_evidence_record_ids=[],
            source_fact_ids=updated["source_fact_ids"],
            rationale="Research a general mechanism",
            purpose="Research a general mechanism",
            workspace_session_id="session-a",
            command_id="prepare-brief",
            expected_revision=3,
        )

        self.assertEqual(
            brief["internal_derivation"]["source_fact_ids"],
            updated["source_fact_ids"],
        )


if __name__ == "__main__":
    unittest.main()
