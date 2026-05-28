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
    "genomi.approve_agi_access",
    "genomi.assign_user_genome",
    "genomi.check_background_job",
    "genomi.check_libraries",
    "genomi.clear_default_user",
    "genomi.clear_selection",
    "genomi.describe_context",
    "genomi.install",
    "genomi.invoke",
    "genomi.list_resources",
    "genomi.list_users",
    "genomi.parse_source",
    "genomi.rename_user",
    "genomi.revoke_agi_access",
    "genomi.search_indexes",
    "genomi.select_user",
    "genomi.set_default_user",
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
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def approve_agi_access(self) -> None:
        context = call_operation("genomi.describe_context")
        if context.get("active_agi_id"):
            call_operation(
                "genomi.approve_agi_access",
                {"approved_by_user": True, "reason": "test approved Active Genome Index access"},
            )
