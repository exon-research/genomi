from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from genomi.interfaces import cli
from genomi.lab import server as lab_server
from genomi.operations import call_operation
from genomi.runtime import context as runtime_context


class GenomiLabCLITests(unittest.TestCase):
    def test_lab_parser_is_available_with_safe_defaults(self) -> None:
        args = cli.build_parser().parse_args(["lab"])

        self.assertEqual(args.area, "lab")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 0)
        self.assertFalse(args.no_open)
        self.assertIs(args.func, cli._cmd_lab)

    def test_lab_parser_accepts_only_explicit_loopback_hosts(self) -> None:
        for host in ("127.0.0.1", "localhost"):
            with self.subTest(host=host):
                args = cli.build_parser().parse_args(
                    ["lab", "--host", host, "--port", "4321", "--no-open"]
                )
                self.assertEqual(args.host, host)
                self.assertEqual(args.port, 4321)
                self.assertTrue(args.no_open)

        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            cli.build_parser().parse_args(["lab", "--host", "0.0.0.0"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_lab_command_is_not_hidden_behind_agent_cli_gate(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("genomi.lab.server.run_lab") as run_lab,
        ):
            status = cli.main(
                ["lab", "--host", "localhost", "--port", "4321", "--no-open"]
            )

        self.assertEqual(status, 0)
        run_lab.assert_called_once_with(
            host="localhost",
            port=4321,
            open_browser=False,
            harness_processing_destination=None,
        )

    def test_lab_command_carries_the_explicit_harness_destination(self) -> None:
        with mock.patch("genomi.lab.server.run_lab") as run_lab:
            status = cli.main(
                [
                    "lab",
                    "--no-open",
                    "--harness-processing-destination",
                    "remote: OpenAI Codex service",
                ]
            )

        self.assertEqual(status, 0)
        run_lab.assert_called_once_with(
            host="127.0.0.1",
            port=0,
            open_browser=False,
            harness_processing_destination="remote: OpenAI Codex service",
        )

    def test_launcher_hands_off_exact_user_without_reusing_agi_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            genomi_home = Path(temporary) / "genomi-home"
            vcf = Path(temporary) / "patient.vcf"
            vcf.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPatient\n"
                "1\t100\trs900000001\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            environment = {
                "GENOMI_HOME": str(genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "assistant-explicit-session",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                call_operation(
                    "genomi.parse_source",
                    {
                        "source": str(vcf),
                        "user_nickname": "Explicit non-default patient",
                    },
                )
                prior = call_operation("genomi.describe_context", {})
                user_id = str(prior["active_user_id"])
                call_operation(
                    "active_genome_index.approve_access",
                    {
                        "approved_by_user": True,
                        "user_id": user_id,
                        "reason": "Approve only in the assistant session.",
                    },
                )
                self.assertTrue(
                    call_operation("genomi.describe_context", {})[
                        "active_genome_index_access"
                    ]["approved"]
                )
                captured: dict[str, object] = {}

                class _StoppingServer:
                    launch_url = "http://127.0.0.1:1/?token=synthetic"

                    def serve_forever(self, *, poll_interval: float) -> None:
                        del poll_interval
                        current = call_operation("genomi.describe_context", {})
                        captured["context"] = current

                    def server_close(self) -> None:
                        return None

                with (
                    mock.patch(
                        "genomi.lab.server.create_lab_server",
                        return_value=_StoppingServer(),
                    ),
                    mock.patch(
                        "genomi.lab.server.GenomiLabService",
                        return_value=object(),
                    ),
                    mock.patch.object(
                        lab_server.InstalledCodexAppServerAdapter,
                        "discover",
                        return_value=mock.Mock(
                            bind_dynamic_tool_handler=lambda _handler: None
                        ),
                    ),
                ):
                    lab_server.run_lab(open_browser=False)

                launched = captured["context"]
                self.assertEqual(launched["active_user_id"], user_id)
                self.assertEqual(
                    launched["active_user"]["nickname"],
                    "Explicit non-default patient",
                )
                self.assertFalse(
                    launched["active_genome_index_access"]["approved"]
                )
                # The caller's explicit session and its private grant are
                # restored unchanged after the portal stops.
                restored = call_operation("genomi.describe_context", {})
                self.assertEqual(restored["active_user_id"], user_id)
                self.assertTrue(restored["active_genome_index_access"]["approved"])


if __name__ == "__main__":
    unittest.main()
