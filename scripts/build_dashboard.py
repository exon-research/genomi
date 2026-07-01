#!/usr/bin/env python3
"""Precompile the decode dashboard's JSX to plain JS so the artifact is offline.

The dashboard UI is authored in
``src/genomi/capabilities/decode/templates/dashboard.jsx`` (JSX), with shared
plain-JS helpers in ``templates/dashboard_helpers.js``. The rendered
``Genomi Dashboard.html`` must open with **zero** external script requests — no
unpkg, no in-browser Babel — so we transpile the JSX ahead of time, here, into
ordered ``templates/vendor/dashboard.compiled.*.js`` chunks (plain
``React.createElement`` calls). ``dashboard.py`` inlines those chunks plus the
vendored React/ReactDOM UMD builds at render time.

Run this after editing ``dashboard.jsx`` or ``dashboard_helpers.js``::

    python3 scripts/build_dashboard.py

The compiled file carries a ``source-sha256`` of those dashboard sources;
``tests/test_decode_dashboard_assets.py`` recomputes that hash and fails if the
compiled chunks have drifted, so a forgotten rebuild is caught in CI without
needing a JS toolchain at test time.

Requires Node.js + npm at build time (only here, never at render or test time).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parents[1] / "src/genomi/capabilities/decode/templates"
_JSX = _TEMPLATES / "dashboard.jsx"
_HELPERS_JS = _TEMPLATES / "dashboard_helpers.js"
_OUT_DIR = _TEMPLATES / "vendor"
_OUT_PREFIX = "dashboard.compiled"
_CHUNK_MAX_LINES = 900

_BABEL_CORE = "@babel/core@7.26"
_BABEL_PRESET = "@babel/preset-react@7.26"

_TRANSPILE_JS = """
import babel from "@babel/core";
import fs from "node:fs";
const src = fs.readFileSync(process.argv[2], "utf8");
const out = babel.transformSync(src, {
  presets: ["@babel/preset-react"],
  compact: false,
  comments: true,
});
process.stdout.write(out.code);
"""


def _require(binary: str) -> None:
    if shutil.which(binary) is None:
        sys.exit(f"error: `{binary}` is required to build the dashboard but was not found on PATH.")


def _dashboard_source() -> str:
    if not _JSX.is_file():
        sys.exit(f"error: JSX source not found at {_JSX}")
    sources = []
    if _HELPERS_JS.is_file():
        sources.append(_HELPERS_JS.read_text(encoding="utf-8"))
    sources.append(_JSX.read_text(encoding="utf-8"))
    return "\n\n".join(sources)


def _transpile(source: str) -> str:
    _require("node")
    _require("npm")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        subprocess.run(["npm", "init", "-y"], cwd=tmp_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(
            ["npm", "install", "--no-fund", "--no-audit", _BABEL_CORE, _BABEL_PRESET],
            cwd=tmp_dir,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        (tmp_dir / "transpile.mjs").write_text(_TRANSPILE_JS, encoding="utf-8")
        source_path = tmp_dir / "dashboard.combined.jsx"
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            ["node", "transpile.mjs", str(source_path)],
            cwd=tmp_dir,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
    return result.stdout


def _compiled_chunks(compiled: str, header_template: str) -> list[str]:
    header_lines = header_template.format(chunk_index=1, chunk_count=1).splitlines(keepends=True)
    payload_limit = _CHUNK_MAX_LINES - len(header_lines)
    if payload_limit < 1:
        sys.exit("error: dashboard compiled chunk header exceeds the configured line budget.")
    lines = compiled.splitlines(keepends=True)
    if not lines:
        return [header_template.format(chunk_index=1, chunk_count=1)]
    payloads = ["".join(lines[i:i + payload_limit]) for i in range(0, len(lines), payload_limit)]
    chunk_count = len(payloads)
    return [
        header_template.format(chunk_index=index + 1, chunk_count=chunk_count) + payload
        for index, payload in enumerate(payloads)
    ]


def main() -> None:
    source = _dashboard_source()
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    compiled = _transpile(source)

    # The compiled JS is inlined inside a <script> tag, so a literal </script>
    # would terminate it early. JSX→createElement output never emits one, but
    # fail loud if that ever changes rather than ship a broken dashboard.
    if "</script" in compiled.lower():
        sys.exit("error: compiled JS contains a literal </script>; inlining would break the HTML.")

    header_template = (
        "// AUTO-GENERATED chunk {chunk_index}/{chunk_count} from dashboard sources "
        "by scripts/build_dashboard.py - do not edit by hand.\n"
        f"// source-sha256: {digest}\n"
    )
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in _OUT_DIR.glob(f"{_OUT_PREFIX}*.js"):
        stale.unlink()
    chunks = _compiled_chunks(compiled, header_template)
    for index, chunk in enumerate(chunks, start=1):
        out = _OUT_DIR / f"{_OUT_PREFIX}.{index:03d}.js"
        out.write_text(chunk, encoding="utf-8")
        shown = out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out
        print(f"wrote {shown}")
    print(f"source-sha256: {digest}")


if __name__ == "__main__":
    main()
