from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POSTPROCESSOR = REPOSITORY_ROOT / "scripts" / "record_genomilab_ctla4_demo.cjs"


class GenomiLabRecordingPostprocessorTests(unittest.TestCase):
    def test_same_document_tab_goto_is_recorded_as_scroll_provenance(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.skipTest("ffmpeg is required for the recording postprocessor")
        with tempfile.TemporaryDirectory(
            prefix=".genomilab-recording-test-", dir=REPOSITORY_ROOT
        ) as root:
            run_dir = Path(root)
            frames_dir = run_dir / "recording-frames"
            frames_dir.mkdir()
            (run_dir / "viewer-ready").write_text("ready\n", encoding="utf-8")

            completed_at = datetime.now(UTC)
            self._write_jsonl(
                run_dir / "timeline.jsonl",
                [{
                    "stage": "demo_complete",
                    "scroll_target": "#doctor-brief",
                    "at": completed_at.isoformat(),
                }],
            )
            (frames_dir / "frame-000001.png").write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
                    "2mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
            )
            self._write_jsonl(
                frames_dir / "capture-provenance.jsonl",
                [
                    {
                        "type": "session",
                        "browser_surface": "in_app_browser",
                        "viewer_ready_at": completed_at.isoformat(),
                    },
                    {
                        "type": "scroll",
                        "timeline_event_index": 1,
                        "stage": "demo_complete",
                        "scroll_target": "#doctor-brief",
                        "acted_at": completed_at.isoformat(),
                        "browser_api": "tab.goto",
                    },
                    {
                        "type": "frame",
                        "file": "frame-000001.png",
                        "captured_at": (completed_at + timedelta(seconds=1)).isoformat(),
                        "capture_api": "tab.screenshot",
                        "media_type": "image/png",
                    },
                ],
            )

            completed = subprocess.run(
                [
                    "node",
                    str(POSTPROCESSOR),
                    "--run-dir",
                    str(run_dir),
                    "--hold-seconds",
                    "0",
                    "--ffmpeg-path",
                    ffmpeg,
                ],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            manifest = json.loads(
                (run_dir / "recording-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["capture"]["browser_scroll_apis"], ["tab.goto"]
            )

    def test_setup_events_before_viewer_ready_do_not_require_fake_scrolls(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.skipTest("ffmpeg is required for the recording postprocessor")
        with tempfile.TemporaryDirectory(
            prefix=".genomilab-recording-test-", dir=REPOSITORY_ROOT
        ) as root:
            run_dir = Path(root)
            frames_dir = run_dir / "recording-frames"
            frames_dir.mkdir()
            (run_dir / "viewer-ready").write_text("ready\n", encoding="utf-8")

            viewer_ready_at = datetime.now(UTC)
            completed_at = viewer_ready_at + timedelta(seconds=1)
            self._write_jsonl(
                run_dir / "timeline.jsonl",
                [
                    {
                        "stage": "portal_ready",
                        "scroll_target": "#investigation-detail",
                        "at": (viewer_ready_at - timedelta(seconds=1)).isoformat(),
                    },
                    {
                        "stage": "demo_complete",
                        "scroll_target": "#doctor-brief",
                        "at": completed_at.isoformat(),
                    },
                ],
            )
            (frames_dir / "frame-000001.jpg").write_bytes(
                base64.b64decode(
                    "/9j/4AAQSkZJRgABAgAAAQABAAD//gAQTGF2YzYyLjI4LjEwMAD/2wBDAAgEBAQEBAUFBQUFBQYGBgYGBgYGBgYGBgYHBwcICAgHBwcGBgcHCAgICAkJCQgICAgJCQoKCgwMCwsODg4RERT/xABLAAEBAAAAAAAAAAAAAAAAAAAABwEBAAAAAAAAAAAAAAAAAAAAABABAAAAAAAAAAAAAAAAAAAAABEBAAAAAAAAAAAAAAAAAAAAAP/AABEIAAIAAgMBIgACEQADEQD/2gAMAwEAAhEDEQA/AL+AD//Z"
                )
            )
            self._write_jsonl(
                frames_dir / "capture-provenance.jsonl",
                [
                    {
                        "type": "session",
                        "browser_surface": "in_app_browser",
                        "viewer_ready_at": viewer_ready_at.isoformat(),
                    },
                    {
                        "type": "scroll",
                        "timeline_event_index": 2,
                        "stage": "demo_complete",
                        "scroll_target": "#doctor-brief",
                        "acted_at": completed_at.isoformat(),
                        "browser_api": "tab.goto",
                    },
                    {
                        "type": "frame",
                        "file": "frame-000001.jpg",
                        "captured_at": (completed_at + timedelta(seconds=1)).isoformat(),
                        "capture_api": "tab.screenshot",
                        "media_type": "image/jpeg",
                    },
                ],
            )

            completed = subprocess.run(
                [
                    "node",
                    str(POSTPROCESSOR),
                    "--run-dir",
                    str(run_dir),
                    "--hold-seconds",
                    "0",
                    "--ffmpeg-path",
                    ffmpeg,
                ],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            manifest = json.loads(
                (run_dir / "recording-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["coordination"]["pre_viewer_timeline_events"], 1)
            self.assertEqual(manifest["coordination"]["scroll_targets_verified"], 1)
            self.assertEqual(
                manifest["capture"]["source_frames"]["media_type"], "image/jpeg"
            )

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
        path.write_text(
            "".join(f"{json.dumps(record, sort_keys=True)}\n" for record in records),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
