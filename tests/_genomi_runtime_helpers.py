from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.operations import call_operation
from genomi.runtime import context as runtime_context

# After the dispatcher refactor, default tools/list returns ops in the two
# base capabilities (`genomi` and `journal`) plus the genomi.invoke
# dispatcher. The journal capability owns the research.* ops. gnomad is its
# own capability now and reaches the agent only after a skill read +
# genomi.invoke. All other capabilities (clinvar, pharmacogenomics, etc.)
# are likewise hidden behind the dispatcher.
DEFAULT_TASK_ENTRY_TOOLS = {
    "genomi.check_background_job",
    "genomi.check_libraries",
    "genomi.describe_context",
    "genomi.install",
    "genomi.invoke",
    "genomi.list_resources",
    "genomi.parse_source",
    "genomi.search_indexes",
    "genomi.set_response_profile",
    "journal.append_entry",
    "journal.export_memory",
    "journal.search_entries",
    "journal.summarize",
    "research.build_target_packet",
    "research.list_sources",
    "research.query",
    "research.record",
    "research.search",
}


class GenomiRuntimeTestCase(unittest.TestCase):
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
                "GENOMI_RUNTIME_UPDATE": "",
                "GENOMI_SKIP_RUNTIME_GIT_PULL": "",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        # genomi.install now always attempts a runtime git pull. Treat the
        # runtime as "not a git checkout" by default so no test ever performs a
        # live pull against the developer's actual repo; pull-mechanism tests
        # override this with their own _runtime_git_repo patch.
        self._git_repo = mock.patch(
            "genomi.operations.registry.handlers_admin._runtime_git_repo",
            return_value=None,
        )
        self._git_repo.start()
        self.addCleanup(self._git_repo.stop)
        # genomi.install always materializes reference libraries. Stub the
        # installer subprocess so tests never download anything; tests that
        # assert install behavior override this with their own patch.
        self._install_libraries = mock.patch(
            "genomi.operations.registry.handlers_admin._install_libraries_step",
            return_value={"status": "completed", "stub": True},
        )
        self._install_libraries.start()
        self.addCleanup(self._install_libraries.stop)

    def approve_access(self) -> None:
        context = call_operation("genomi.describe_context")
        if context.get("active_agi_id"):
            call_operation(
                "active_genome_index.approve_access",
                {"approved_by_user": True, "reason": "test approved Active Genome Index access"},
            )
