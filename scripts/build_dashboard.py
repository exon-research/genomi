#!/usr/bin/env python3
"""Precompile the decode dashboard's JSX to plain JS so the artifact is offline.

The dashboard UI is authored in
``src/genomi/capabilities/decode/templates/dashboard.jsx`` (JSX). The rendered
``Genomi Dashboard.html`` must open with **zero** external script requests — no
unpkg, no in-browser Babel — so we transpile the JSX ahead of time, here, into
``templates/vendor/dashboard.compiled.js`` (plain ``React.createElement`` calls).
``dashboard.py`` inlines that compiled file plus the vendored React/ReactDOM
UMD builds at render time.

Run this after editing ``dashboard.jsx``::

    python3 scripts/build_dashboard.py

The compiled file carries a ``source-sha256`` of the JSX it was built from;
``tests/test_decode_offline.py`` recomputes that hash and fails if the two have
drifted, so a forgotten rebuild is caught in CI without needing a JS toolchain
at test time.

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
_OUT = _TEMPLATES / "vendor" / "dashboard.compiled.js"

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


def _transpile(jsx_path: Path) -> str:
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
        result = subprocess.run(
            ["node", "transpile.mjs", str(jsx_path)],
            cwd=tmp_dir,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
    return result.stdout


def main() -> None:
    if not _JSX.is_file():
        sys.exit(f"error: JSX source not found at {_JSX}")
    source = _JSX.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    compiled = _transpile(_JSX)

    # The compiled JS is inlined inside a <script> tag, so a literal </script>
    # would terminate it early. JSX→createElement output never emits one, but
    # fail loud if that ever changes rather than ship a broken dashboard.
    if "</script" in compiled.lower():
        sys.exit("error: compiled JS contains a literal </script>; inlining would break the HTML.")

    header = (
        "// AUTO-GENERATED from dashboard.jsx by scripts/build_dashboard.py — do not edit by hand.\n"
        f"// source-sha256: {digest}\n"
    )
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(header + compiled, encoding="utf-8")
    print(f"wrote {_OUT.relative_to(Path.cwd()) if _OUT.is_relative_to(Path.cwd()) else _OUT}")
    print(f"source-sha256: {digest}")


if __name__ == "__main__":
    main()
