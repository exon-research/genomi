"""Command-line entry point for the fixture-only CTLA4 demo."""

from __future__ import annotations

import argparse
import json
import signal
import threading
from datetime import datetime
from pathlib import Path

from .runner import DemoRun


def _default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.cwd() / "demo_artifacts" / f"genomilab-ctla4-{stamp}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help=(
            "Required safety selector: this uses a synthetic one-variant "
            "recording twin, never the user's active genome profile."
        ),
    )
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--step-delay", type=float, default=2.0)
    parser.add_argument("--wait-for-viewer", action="store_true")
    parser.add_argument("--viewer-timeout", type=float, default=180.0)
    parser.add_argument(
        "--capture-handshake",
        action="store_true",
        help="Wait for one browser-capture acknowledgement after each visible timeline event.",
    )
    parser.add_argument("--capture-timeout", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--exit-after",
        type=float,
        default=None,
        help="Keep the portal live for this many seconds; default is until interrupted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.fixture_mode:
        _parser().error("--fixture-mode is required for this synthetic recording harness")
    run_dir = (args.run_dir or _default_run_dir()).expanduser().resolve()
    demo = DemoRun(
        run_dir=run_dir,
        step_delay=0.0 if args.dry_run else max(0.0, args.step_delay),
        wait_for_viewer=bool(args.wait_for_viewer),
        viewer_timeout=max(1.0, args.viewer_timeout),
        port=args.port,
        dry_run=bool(args.dry_run),
        fixture_mode=True,
        capture_handshake=bool(args.capture_handshake),
        capture_timeout=max(1.0, args.capture_timeout),
    )
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        demo.prepare()
        if not args.dry_run:
            demo.start_server()
        report = demo.run_scenario()
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)
        print(f"Run artifacts: {run_dir}", flush=True)
        if not args.dry_run:
            if args.exit_after is None:
                print("Portal remains live until Ctrl-C.", flush=True)
                while not stop.wait(0.5):
                    pass
            else:
                stop.wait(max(0.0, args.exit_after))
        return 0
    finally:
        demo.close()


__all__ = ["main"]
