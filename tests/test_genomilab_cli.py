from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr
from unittest import mock

from genomi.interfaces import cli


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
            mock.patch("genomi.interfaces.mcp.serve_http", return_value=0) as serve_http,
        ):
            status = cli.main(
                ["lab", "--host", "localhost", "--port", "4321", "--no-open"]
            )

        self.assertEqual(status, 0)
        serve_http.assert_called_once_with(
            host="localhost",
            port=4321,
            open_browser=False,
            portal_session_auth=True,
        )

    def test_lab_setup_uses_the_normal_nested_command(self) -> None:
        payload = {"status": "ready", "mode": "check", "read_only": True}
        with mock.patch(
            "genomi.lab.setup.run_lab_setup", return_value=payload
        ) as setup:
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                status = cli.main(["lab", "setup", "--check"])

        self.assertEqual(status, 0)
        setup.assert_called_once_with(check=True, demo=False)
        self.assertIn('"mode": "check"', stdout.getvalue())

    def test_lab_setup_demo_is_forwarded_without_starting_the_portal(self) -> None:
        with (
            mock.patch(
                "genomi.lab.setup.run_lab_setup",
                return_value={"status": "completed", "mode": "demo"},
            ) as setup,
            mock.patch("genomi.interfaces.mcp.serve_http") as serve_http,
        ):
            status = cli.main(["lab", "setup", "--demo"])

        self.assertEqual(status, 0)
        setup.assert_called_once_with(check=False, demo="ctla4")
        serve_http.assert_not_called()

    def test_lab_setup_accepts_the_named_ctla4_demo(self) -> None:
        with mock.patch(
            "genomi.lab.setup.run_lab_setup",
            return_value={"status": "completed", "mode": "demo"},
        ) as setup:
            status = cli.main(["lab", "setup", "--demo", "ctla4"])

        self.assertEqual(status, 0)
        setup.assert_called_once_with(check=False, demo="ctla4")

if __name__ == "__main__":
    unittest.main()
