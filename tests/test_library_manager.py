from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from genomi.runtime.libraries import manager, registry


def _seed(root: Path, library_id: str) -> None:
    """Create empty files at every required path of a library so status() reports
    it installed under a temp GENOMI_HOME."""
    for rel in registry.get(library_id).required_paths:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("seed", encoding="utf-8")


class StatusAndInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_status_missing_offline(self) -> None:
        status = manager.status("clinvar-grch38", root=self.root)
        self.assertFalse(status["installed"])
        self.assertEqual(status["status"], "not_installed")
        self.assertIn("--libraries clinvar-grch38", status["install_command"])
        self.assertEqual(status["install_libraries"], ["clinvar-grch38"])

    def test_status_installed_offline(self) -> None:
        _seed(self.root, "gencc")
        status = manager.status("gencc", root=self.root)
        self.assertTrue(status["installed"])
        self.assertEqual(status["status"], "installed")
        self.assertEqual(status["missing_paths"], [])

    def test_status_online(self) -> None:
        status = manager.status("gnomad", root=self.root)
        self.assertEqual(status["status"], "online")
        self.assertTrue(status["installed"])
        self.assertEqual(status["kind"], "online")
        self.assertEqual(status["required_paths"], [])

    def test_msigdb_install_command_has_gmt_hint(self) -> None:
        self.assertIn("--msigdb-gmt", manager.status("msigdb-hallmark", root=self.root)["install_command"])

    def test_inventory_counts(self) -> None:
        inv = manager.inventory(root=self.root)
        self.assertEqual(inv["schema"], "genomi-library-inventory-v1")
        # 18 offline-family (incl. derived + manual) + 4 online = 22; parameterized excluded.
        self.assertEqual(inv["summary"]["library_count"], 22)
        # The 4 online sources count as installed; everything offline is missing here.
        self.assertEqual(inv["summary"]["installed_count"], 4)
        self.assertEqual(inv["summary"]["missing_count"], 18)
        ids = {item["library"] for item in inv["libraries"]}
        self.assertNotIn("prs-scoring-file", ids)
        self.assertIn("gnomad", ids)

    def test_install_command_and_resolve_selection(self) -> None:
        self.assertEqual(manager.install_command(["hpo", "gencc"]), "genomi install --libraries hpo,gencc")
        self.assertEqual(manager.resolve_selection("common-questions"), ["clinvar-grch38", "hpo", "gencc"])
        self.assertEqual(len(manager.resolve_selection("everything")), 17)
        self.assertIn("everything", manager.purposes())


class EnsureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_ensure_missing_returns_install_request(self) -> None:
        result = manager.ensure(
            "clinvar-grch38", intent="match", operation="clinvar.match_variants", root=self.root
        )
        self.assertEqual(result["status"], "requires_library_install")
        self.assertFalse(result["tool_will_work"])
        self.assertEqual(result["missing_library"]["library"], "clinvar-grch38")
        self.assertIn("--libraries clinvar-grch38", result["missing_library"]["install_command"])
        self.assertIn("install_command", result["ask_user"])

    def test_ensure_present_returns_available_without_network(self) -> None:
        _seed(self.root, "gencc")
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network on hot path")):
            result = manager.ensure("gencc", root=self.root)
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["installed"])

    def test_ensure_online_reachable(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=mock.MagicMock()):
            result = manager.ensure("gnomad", root=self.root)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["kind"], "online")

    def test_ensure_online_unreachable_is_source_unavailable(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            result = manager.ensure("pgs-catalog", root=self.root)
        self.assertEqual(result["status"], "source_unavailable")
        self.assertFalse(result["source_status"]["reachable"])


class RefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_refresh_online_is_a_noop(self) -> None:
        self.assertEqual(manager.refresh("gnomad", root=self.root)["status"], "skipped")

    def test_refresh_http_single_file_passes_through(self) -> None:
        with mock.patch.object(manager.source_fetch, "refresh_or_download", return_value={"status": "downloaded", "output": "x"}) as fetch:
            result = manager.refresh("clinvar-grch38", root=self.root)
        fetch.assert_called_once()
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["library"], "clinvar-grch38")

    def test_refresh_http_multi_file_aggregates(self) -> None:
        # HPO has two source files; the aggregate status is the strongest one.
        with mock.patch.object(
            manager.source_fetch,
            "refresh_or_download",
            side_effect=[{"status": "up_to_date"}, {"status": "downloaded"}],
        ) as fetch:
            result = manager.refresh("hpo", root=self.root)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["library"], "hpo")

    def test_refresh_manual_without_source_reports_required(self) -> None:
        result = manager.refresh("msigdb-hallmark", root=self.root)
        self.assertEqual(result["status"], "manual_source_required")
        self.assertIn("--msigdb-gmt", result["install_command"])

    def test_refresh_manual_with_source_path_copies(self) -> None:
        source = self.root / "h.all.symbols.gmt"
        source.write_text("HALLMARK_X\tdesc\tGENE1\tGENE2\n", encoding="utf-8")
        result = manager.refresh("msigdb-hallmark", root=self.root, msigdb_gmt=str(source))
        self.assertEqual(result["status"], "completed")
        installed = self.root / registry.get("msigdb-hallmark").required_paths[0]
        self.assertTrue(installed.is_file())
        self.assertIn("HALLMARK_X", installed.read_text())

    def test_refresh_pinned_binary_skipped_off_linux(self) -> None:
        with mock.patch("genomi.runtime.libraries.manager.sys.platform", "darwin"):
            result = manager.refresh("minimap2-binary", root=self.root)
        self.assertEqual(result["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
