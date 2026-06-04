from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

__all__ = ["PGxMedicationReviewTestBase"]


class PGxMedicationReviewTestBase(unittest.TestCase):
    """Shared setup for the split ``test_pgx_review_*`` test modules.

    Isolates each test from any pre-existing ``~/.genomi`` state and stubs the
    FDA PGx lookup so tests that assert "no Active Genome Index selected"
    behaviour are not polluted by an active run left over from real Genomi
    parses in this account.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._env_patch = patch.dict(
            os.environ,
            {
                "GENOMI_HOME": self._tmpdir.name,
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "",
                "GENOMI_CONTEXT_POLICY": "explicit",
            },
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self._fda_patch = patch(
            "genomi.capabilities.pharmacogenomics.fda_pgx.lookup_fda_pgx",
            return_value={
                "source": {"source_id": "fda_pgx"},
                "status": "no_matching_fda_pgx_records",
                "summary": {"biomarker_labeling_count": 0, "association_count": 0, "record_research_payload_count": 0},
                "rows": [],
                "raw_calls": [],
                "record_research_payloads": [],
            },
        )
        self._fda_lookup = self._fda_patch.start()
        self.addCleanup(self._fda_patch.stop)
