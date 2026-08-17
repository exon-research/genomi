#!/usr/bin/env python3
"""Render the timestamped GenomiLab CTLA4 narration over the demo MP4."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


TIMESTAMP = re.compile(r"^##\s+(?P<minutes>\d{2}):(?P<seconds>\d{2}(?:\.\d+)?)\s*$")


@dataclass(frozen=True)
class Segment:
    start_seconds: float
    text: str


def parse_segments(path: Path) -> list[Segment]:
    segments: list[Segment] = []
    start_seconds: float | None = None
    text_lines: list[str] = []

    def finish() -> None:
        nonlocal start_seconds, text_lines
        if start_seconds is None:
            return
        text = " ".join(line.strip() for line in text_lines if line.strip())
        if not text:
            raise ValueError(f"Narration segment at {start_seconds:.1f}s has no text")
        segments.append(Segment(start_seconds=start_seconds, text=text))
        start_seconds = None
        text_lines = []

    for line in path.read_text(encoding="utf-8").splitlines():
        match = TIMESTAMP.match(line)
        if match:
            finish()
            start_seconds = int(match.group("minutes")) * 60 + float(match.group("seconds"))
        elif start_seconds is not None:
            text_lines.append(line)
    finish()
    if not segments:
        raise ValueError("Narration script contains no timestamped segments")
    return segments


def probe_duration(path: Path, ffprobe: str) -> float:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    candidates = [payload.get("format", {}).get("duration")]
    candidates.extend(stream.get("duration") for stream in payload.get("streams", []))
    for candidate in candidates:
        if candidate not in {None, "N/A"}:
            return float(candidate)
    raise ValueError(f"ffprobe did not report a duration for {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--voice", default="Samantha")
    parser.add_argument("--rate", type=int, default=190)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    source = args.source.resolve()
    script = args.script.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    segments = parse_segments(script)
    video_duration = probe_duration(source, args.ffprobe)

    with tempfile.TemporaryDirectory(prefix="genomilab-narration-") as temp_name:
        temp_dir = Path(temp_name)
        clips: list[Path] = []
        durations: list[float] = []
        for index, segment in enumerate(segments):
            clip = temp_dir / f"segment-{index:02d}.aiff"
            subprocess.run(
                ["say", "-v", args.voice, "-r", str(args.rate), "-o", str(clip), segment.text],
                check=True,
            )
            clips.append(clip)
            durations.append(probe_duration(clip, args.ffprobe))

        timing_errors: list[str] = []
        for index, (segment, duration) in enumerate(zip(segments, durations, strict=True)):
            boundary = segments[index + 1].start_seconds if index + 1 < len(segments) else video_duration
            if segment.start_seconds + duration > boundary + 0.05:
                timing_errors.append(
                    f"Segment {index + 1} ends at {segment.start_seconds + duration:.2f}s, "
                    f"past its {boundary:.2f}s boundary; increase --rate or shorten the text"
                )
        if timing_errors:
            raise ValueError("\n".join(timing_errors))

        command = [args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
        command.extend(
            ["-f", "lavfi", "-t", f"{video_duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        )
        for clip in clips:
            command.extend(["-i", str(clip)])

        filters = ["[1:a]volume=0[silence]"]
        audio_inputs = ["[silence]"]
        for index, segment in enumerate(segments):
            delay_ms = round(segment.start_seconds * 1000)
            label = f"voice{index}"
            filters.append(
                f"[{index + 2}:a]aresample=48000,adelay={delay_ms}:all=1[{label}]"
            )
            audio_inputs.append(f"[{label}]")
        filters.append(
            "".join(audio_inputs)
            + f"amix=inputs={len(audio_inputs)}:duration=longest:normalize=0,"
            + f"alimiter=limit=0.95,atrim=0:{video_duration:.3f}[narration]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "0:v:0",
                "-map",
                "[narration]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        subprocess.run(command, check=True)

    manifest = {
        "status": "completed",
        "created_at": datetime.now(UTC).isoformat(),
        "source": str(source),
        "source_sha256": sha256(source),
        "script": str(script),
        "script_sha256": sha256(script),
        "voice": args.voice,
        "rate_words_per_minute": args.rate,
        "segments": [
            {
                "start_seconds": segment.start_seconds,
                "duration_seconds": round(duration, 3),
                "text": segment.text,
            }
            for segment, duration in zip(segments, durations, strict=True)
        ],
        "output": str(output),
        "output_duration_seconds": probe_duration(output, args.ffprobe),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256(output),
    }
    manifest_path = output.with_name("narration-manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
