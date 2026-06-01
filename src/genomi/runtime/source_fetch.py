"""Conditional refresh for downloaded public reference libraries.

`genomi update` checks every installed library against its source and
re-downloads only what actually changed upstream — no version pinning, no
blind re-downloads. Freshness is decided from HTTP validators (`ETag` /
`Last-Modified`) persisted in each library's `*.genomi-manifest.json`.

The network check is opt-in (`refresh=True`): runtime code that lazily
materializes a library must NOT pay a round-trip on every query, so the
default keeps the existing "cached file is good enough" behavior.
"""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .external import file_metadata, read_manifest, utc_now, write_manifest

DEFAULT_TIMEOUT_SECONDS = 120
_HEAD_TIMEOUT_SECONDS = 30
_VALIDATOR_KEYS = ("etag", "last_modified")


def recorded_validators(manifest: dict[str, Any] | None) -> dict[str, str]:
    """The conditional-request validators stored in a library manifest."""
    if not manifest:
        return {}
    return {
        key: manifest[key]
        for key in _VALIDATOR_KEYS
        if isinstance(manifest.get(key), str) and manifest[key]
    }


def _validators_from_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    etag = headers.get("ETag")
    last_modified = headers.get("Last-Modified")
    if etag:
        out["etag"] = etag
    if last_modified:
        out["last_modified"] = last_modified
    return out


def head_validators(url: str, *, timeout: int = _HEAD_TIMEOUT_SECONDS, user_agent: str | None = None) -> dict[str, str]:
    """Cheap HEAD probe for a source's current `ETag`/`Last-Modified`."""
    request = urllib.request.Request(url, method="HEAD")
    if user_agent:
        request.add_header("User-Agent", user_agent)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _validators_from_headers(response.headers)
    except (urllib.error.URLError, OSError):
        return {}


def remote_is_current(
    url: str,
    recorded: dict[str, str] | None,
    *,
    timeout: int = _HEAD_TIMEOUT_SECONDS,
    user_agent: str | None = None,
) -> bool | None:
    """Is the source unchanged vs. what we recorded?

    True = unchanged (skip), False = changed (re-download), None = can't tell.
    For callers (like the reference FASTA) that download a compressed file and
    post-process it, so a plain ``conditional_fetch`` to the final path won't
    work — they check first, then run their own download + transform.
    """
    if not recorded:
        return None
    current = head_validators(url, timeout=timeout, user_agent=user_agent)
    if not current:
        return None
    if recorded.get("etag") and current.get("etag"):
        return recorded["etag"] == current["etag"]
    if recorded.get("last_modified") and current.get("last_modified"):
        return recorded["last_modified"] == current["last_modified"]
    return None


def conditional_fetch(
    url: str,
    dest: str | Path,
    *,
    recorded: dict[str, str] | None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Download ``url`` to ``dest`` only when upstream is newer than recorded.

    Returns ``{"status", "validators", "reason"}`` where status is one of
    ``up_to_date`` | ``downloaded``. A single conditional GET does double duty:
    a 304 means unchanged (no body transferred); a 200 means the body is the
    new content, streamed straight to ``dest``. When ``dest`` already exists
    but we have no recorded validators (first run after this ships), a HEAD
    adopts the current validators as the baseline rather than re-downloading a
    file that is almost certainly current.
    """
    dest = Path(dest)
    recorded = recorded or {}
    has_file = dest.exists()

    if has_file and not recorded:
        validators = head_validators(url, user_agent=user_agent)
        return {
            "status": "up_to_date",
            "validators": validators,
            "reason": "adopted_existing_as_baseline" if validators else "freshness_unknown",
        }

    request = urllib.request.Request(url)
    if user_agent:
        request.add_header("User-Agent", user_agent)
    if has_file and recorded.get("etag"):
        request.add_header("If-None-Match", recorded["etag"])
    if has_file and recorded.get("last_modified"):
        request.add_header("If-Modified-Since", recorded["last_modified"])

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            validators = _validators_from_headers(response.headers)
            tmp = dest.with_name(dest.name + ".genomi-fetch.tmp")
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                with tmp.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
                tmp.replace(dest)
            finally:
                if tmp.exists():
                    tmp.unlink()
            return {
                "status": "downloaded",
                "validators": validators,
                "reason": "updated" if has_file else "new",
            }
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return {"status": "up_to_date", "validators": recorded, "reason": "not_modified"}
        raise


def download(
    url: str,
    output: str | Path,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str | None = None,
) -> dict[str, str]:
    """Unconditional download to ``output``; returns the source validators."""
    output = Path(output)
    request = urllib.request.Request(url)
    if user_agent:
        request.add_header("User-Agent", user_agent)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".genomi-fetch.tmp")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            validators = _validators_from_headers(response.headers)
            with tmp.open("wb") as handle:
                shutil.copyfileobj(response, handle)
            tmp.replace(output)
    finally:
        if tmp.exists():
            tmp.unlink()
    return validators


def refresh_or_download(
    url: str,
    output: str | Path,
    manifest_path: str | Path,
    *,
    expected: dict[str, Any],
    force: bool,
    refresh: bool,
    base_payload: dict[str, Any] | None = None,
    user_agent: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Keep a "store the bytes as-is" library fresh, tracked in its manifest.

    - cached and neither force nor refresh -> ``cached`` (no network: runtime path).
    - ``refresh`` and cached -> one conditional GET; ``up_to_date`` or ``updated``.
    - ``force`` or missing/mismatched cache -> unconditional ``downloaded``.

    The manifest stores the source validators so the next ``refresh`` can ask
    "anything newer?" without transferring the body when nothing changed.
    """
    output = Path(output)
    manifest_path = Path(manifest_path)
    base_payload = base_payload or {}
    manifest = read_manifest(manifest_path)
    file_exists = output.exists()
    # A present manifest must still match (catches a source_url bump); a library
    # that never wrote one (e.g. legacy HPO/GenCC) is trusted by file presence.
    manifest_ok = manifest is None or all(manifest.get(key) == value for key, value in expected.items())

    def _result(status: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": status,
            **expected,
            **base_payload,
            "manifest_path": str(manifest_path),
            "file": file_metadata(output),
            **extra,
        }

    def _persist(validators: dict[str, str], status: str) -> dict[str, Any]:
        payload = {
            **expected,
            **base_payload,
            **validators,
            "status": "completed",
            "downloaded_at_utc": utc_now(),
            "file": file_metadata(output),
        }
        write_manifest(manifest_path, payload)
        return _result(status)

    # Runtime fast path: a present, identity-matching file is good enough — no
    # network round-trip on lazy materialization.
    if file_exists and manifest_ok and not force and not refresh:
        return _result("cached")

    if refresh and not force and file_exists and manifest_ok:
        result = conditional_fetch(
            url, output, recorded=recorded_validators(manifest), timeout=timeout, user_agent=user_agent
        )
        if result["status"] == "up_to_date":
            # Persist identity + (possibly newly-learned) validators so the next
            # refresh can ask "anything newer?" without transferring the body.
            return _persist(result["validators"], "up_to_date") | {"freshness": result["reason"]}
        return _persist(result["validators"], "updated")

    # force, a missing file, or a stale manifest identity -> (re)download.
    return _persist(download(url, output, timeout=timeout, user_agent=user_agent), "downloaded")

