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
        )


if __name__ == "__main__":
    unittest.main()
