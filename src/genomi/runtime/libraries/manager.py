"""The single code path for every Genomi data source.

`install`, `genomi update`, and on-demand runtime materialization all go through
this manager reading the central ``registry``. There is no per-subsystem
download code with its own lifetime any more: a capability that needs a library
calls :func:`ensure` (which never downloads — it reports availability and, when
missing, the install request to surface to the user), and the installer calls
:func:`install` / :func:`refresh` (the only download path). Freshness is tracked
uniformly through ``source_fetch`` validators in each library's manifest.

The dict shapes returned by :func:`status` and :func:`missing_request` are
load-bearing: ``evidence/envelope.py`` reads ``missing_library`` /
``install_command`` (→ blocked_missing_library) and ``status=="source_unavailable"``
(→ cannot_answer_yet).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import source_fetch
from ..external import file_metadata, read_manifest, utc_now, write_manifest
from ..paths import genomi_data_root
from . import registry
from .spec import Freshness, Kind, LibrarySpec, Transform
from . import transforms

# Re-exported registry helpers so consumers depend only on the manager.
from .registry import all_ids, all_specs, get, has, purposes, resolve_selection  # noqa: F401

_ONLINE_PROBE_TIMEOUT = 10


# --------------------------------------------------------------------------- #
# Path + identity helpers
# --------------------------------------------------------------------------- #
def _resolve(rel: Path, root: str | Path | None) -> Path:
    return genomi_data_root(root) / rel


def _required_paths(spec: LibrarySpec, root: str | Path | None) -> list[Path]:
    return [_resolve(rel, root) for rel in spec.required_paths]


def _user_agent(spec: LibrarySpec) -> str:
    return spec.source.user_agent or registry.USER_AGENT


def _install_libraries(spec: LibrarySpec) -> list[str]:
    """Library ids `genomi install` must run to materialize this spec — a derived
    panel needs its inputs installed first, everything else is just itself."""
    if spec.kind is Kind.DERIVED:
        return [*spec.source.derived_from, spec.id]
    return [spec.id]


def install_command(library_ids: list[str] | tuple[str, ...]) -> str:
    return f"genomi install --libraries {','.join(library_ids)}"


def _install_command_for_spec(spec: LibrarySpec) -> str:
    command = install_command(_install_libraries(spec))
    if spec.id == "msigdb-hallmark":
        return f"{command} --msigdb-gmt /path/to/h.all.v*.symbols.gmt"
    return command


def _manifest_path(target: Path) -> Path:
    return target.with_name(target.name + ".genomi-manifest.json")


# --------------------------------------------------------------------------- #
# status / inventory
# --------------------------------------------------------------------------- #
def status(library_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    """Installed/missing state for a library, in the shape envelope + callers read."""
    spec = registry.get(library_id)
    base = {
        "library": spec.id,
        "title": spec.title,
        "kind": spec.kind.value,
        "size_class": spec.size_class,
        "manual_source_required": spec.manual_source_required,
        "install_libraries": _install_libraries(spec),
        "install_command": _install_command_for_spec(spec),
        "helps": spec.helps,
    }
    if spec.is_online:
        return {
            **base,
            "installed": True,
            "status": "online",
            "required_paths": [],
            "existing_paths": [],
            "missing_paths": [],
        }
    required = _required_paths(spec, root)
    existing = [path for path in required if path.exists()]
    missing = [path for path in required if not path.exists()]
    return {
        **base,
        "installed": not missing,
        "status": "installed" if not missing else "not_installed",
        "required_paths": [str(path) for path in required],
        "existing_paths": [str(path) for path in existing],
        "missing_paths": [str(path) for path in missing],
    }


def _inventory_ids() -> list[str]:
    """Every registry id except the parameterized per-key template."""
    return [spec.id for spec in registry.all_specs() if spec.kind is not Kind.PARAMETERIZED]


def inventory(*, root: str | Path | None = None) -> dict[str, Any]:
    statuses = [status(library_id, root=root) for library_id in _inventory_ids()]
    return {
        "schema": "genomi-library-inventory-v1",
        "genomi_home": str(genomi_data_root(root)),
        "libraries": statuses,
        "summary": {
            "library_count": len(statuses),
            "installed_count": sum(1 for item in statuses if item["installed"]),
            "missing_count": sum(1 for item in statuses if not item["installed"]),
        },
    }


# --------------------------------------------------------------------------- #
# ensure (runtime, never downloads) + missing_request
# --------------------------------------------------------------------------- #
def _intent_help(library: str, intent: str, default_help: str) -> str:
    clean_intent = intent.strip()
    if not clean_intent:
        return default_help
    return f"For this intent ({clean_intent}), {library} {default_help}."


def missing_request(
    library_id: str,
    *,
    intent: str,
    operation: str,
    genome_build: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """The "please install" envelope a tool returns when an offline library is
    missing. Shape is load-bearing for ``evidence/envelope.py``."""
    st = status(library_id, root=root)
    return {
        "status": "requires_library_install",
        "tool_will_work": False,
        "operation": operation,
        "intent": intent,
        "genome_build": genome_build,
        "missing_library": st,
        "how_it_helps": _intent_help(st["library"], intent, st["helps"]),
        "ask_user": {
            "question": (
                f"{st['title']} is not installed. Install {', '.join(st['install_libraries'])} "
                f"so Genomi can use it for this request?"
            ),
            "install_command": st["install_command"],
            "decline_effect": "The tool should skip this evidence library and avoid interpreting missing library data as negative evidence.",
        },
    }


def ensure(
    library_id: str,
    *,
    intent: str = "",
    operation: str = "",
    genome_build: str | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Report whether a source is ready to use — never downloads.

    - Offline present → ``available`` (no network round-trip on the hot path).
    - Offline missing → :func:`missing_request` verbatim (always ask the user).
    - Online → a reachability probe → ``available`` or ``source_unavailable``.
    """
    spec = registry.get(library_id)
    if spec.is_online:
        return _probe_online(spec)
    st = status(library_id, root=root)
    if st["installed"]:
        return {**st, "status": "available"}
    return missing_request(
        library_id, intent=intent, operation=operation, genome_build=genome_build, root=root
    )


def _probe_online(spec: LibrarySpec) -> dict[str, Any]:
    api_base = spec.source.api_base or ""
    request = urllib.request.Request(api_base, method="HEAD")
    request.add_header("User-Agent", _user_agent(spec))
    try:
        urllib.request.urlopen(request, timeout=_ONLINE_PROBE_TIMEOUT).close()
        reachable, error = True, None
    except urllib.error.HTTPError:
        # An HTTP status means the host answered — the API endpoint is reachable;
        # a 4xx/5xx on a bare HEAD of the base URL is not an availability signal.
        reachable, error = True, None
    except (urllib.error.URLError, OSError) as exc:
        reachable, error = False, str(exc)
    if reachable:
        return {"status": "available", "library": spec.id, "kind": "online", "api_base": api_base}
    return {
        "status": "source_unavailable",
        "library": spec.id,
        "kind": "online",
        "source_status": {"reachable": False, "api_base": api_base, "error": error},
    }


# --------------------------------------------------------------------------- #
# refresh (the only download path) + install
# --------------------------------------------------------------------------- #
def install(
    selection_or_id: str,
    *,
    force: bool = False,
    root: str | Path | None = None,
    **overrides: Any,
) -> list[dict[str, Any]]:
    """Resolve a purpose/id selection and materialize each via :func:`refresh`."""
    results: list[dict[str, Any]] = []
    for library_id in registry.resolve_selection(selection_or_id):
        results.append(refresh(library_id, force=force, root=root, **overrides))
    return results


def refresh(
    library_id: str,
    *,
    force: bool = False,
    root: str | Path | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Materialize or update a single library. The only place that downloads.

    Returns a status dict (``cached`` | ``up_to_date`` | ``updated`` |
    ``downloaded`` | ``completed`` | ``skipped`` | ``manual_source_required``).
    """
    spec = registry.get(library_id)
    if spec.is_online:
        return {"status": "skipped", "library": spec.id, "reason": "online source; nothing to download"}
    freshness = spec.freshness
    if freshness is Freshness.HTTP_VALIDATORS and spec.transform is Transform.GUNZIP_FAIDX:
        return _refresh_gunzip_faidx(spec, force=force, root=root)
    if freshness is Freshness.HTTP_VALIDATORS and spec.transform is Transform.XLSX_TO_TSV:
        return _refresh_xlsx_tsv(spec, force=force, root=root)
    if freshness is Freshness.HTTP_VALIDATORS:
        return _refresh_http_files(spec, force=force, root=root)
    if freshness is Freshness.GITHUB_RELEASE_TAG:
        return _refresh_github_release(spec, force=force, root=root, **overrides)
    if freshness is Freshness.PINNED_SHA:
        return _refresh_pinned_sha(spec, force=force, root=root, **overrides)
    if freshness is Freshness.DERIVED:
        return _refresh_derived(spec, force=force, root=root)
    if freshness is Freshness.MANUAL:
        return _refresh_manual(spec, force=force, root=root, **overrides)
    raise ValueError(f"no refresh handler for freshness {freshness!r} on {spec.id}")


_STATUS_RANK = {"downloaded": 4, "updated": 3, "completed": 3, "up_to_date": 2, "cached": 1, "skipped": 0}


def _refresh_http_files(spec: LibrarySpec, *, force: bool, root: str | Path | None) -> dict[str, Any]:
    """Store-the-bytes-as-is libraries (clinvar, hpo, gencc, gencode, encode,
    panglaodb, liftover) — one conditional GET per (url, target)."""
    user_agent = _user_agent(spec)
    files: list[dict[str, Any]] = []
    for url, target_rel in zip(spec.source.urls, spec.targets):
        target = _resolve(target_rel, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        files.append(
            source_fetch.refresh_or_download(
                url,
                target,
                _manifest_path(target),
                expected={"library": spec.id, "source_url": url, "output": str(target)},
                base_payload={"transform": ""},
                force=force,
                refresh=True,
                user_agent=user_agent,
            )
        )
    return _aggregate(spec, files)


def _aggregate(spec: LibrarySpec, files: list[dict[str, Any]]) -> dict[str, Any]:
    if len(files) == 1:
        return {**files[0], "library": spec.id}
    best = max((f.get("status", "cached") for f in files), key=lambda s: _STATUS_RANK.get(s, 0))
    outputs = [f["output"] for f in files if f.get("output")]
    aggregate = {"status": best, "library": spec.id, "files": files}
    if outputs:
        aggregate["output"] = ", ".join(outputs)
    return aggregate


def _refresh_gunzip_faidx(spec: LibrarySpec, *, force: bool, root: str | Path | None) -> dict[str, Any]:
    """Reference FASTA: download .fa.gz, gunzip, build .fai. The multi-GB transfer
    is serialized with a file lock and skipped via a cheap HEAD when unchanged."""
    url = spec.source.urls[0]
    fasta = _resolve(spec.targets[0], root)
    fai = Path(f"{fasta}.fai")
    fasta.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(fasta)
    expected = {"library": spec.id, "source_url": url, "output": str(fasta)}
    manifest = read_manifest(manifest_path)
    manifest_ok = manifest is not None and all(manifest.get(k) == v for k, v in expected.items())
    cached = fasta.exists() and fai.exists() and manifest_ok

    if cached and not force:
        current = source_fetch.remote_is_current(url, source_fetch.recorded_validators(manifest))
        if current is not False:
            return {
                "status": "up_to_date" if current is True else "cached",
                "library": spec.id,
                "output": str(fasta),
                "fai": str(fai),
                "file": file_metadata(fasta),
            }
        # current is False: upstream changed -> re-download below.

    lock_path = fasta.with_name(fasta.name + ".lock")
    with transforms.file_lock(lock_path):
        manifest = read_manifest(manifest_path)
        manifest_ok = manifest is not None and all(manifest.get(k) == v for k, v in expected.items())
        if not force and fasta.exists() and fai.exists() and manifest_ok:
            return {
                "status": "cached",
                "library": spec.id,
                "output": str(fasta),
                "fai": str(fai),
                "file": file_metadata(fasta),
            }
        compressed = fasta.with_name(fasta.name + ".download.gz.tmp")
        try:
            validators = source_fetch.download(url, compressed, user_agent=_user_agent(spec))
            transforms.gunzip_faidx(compressed, fasta, fai)
        finally:
            if compressed.exists():
                compressed.unlink()
    write_manifest(
        manifest_path,
        {**expected, **validators, "status": "completed", "downloaded_at_utc": utc_now(), "fai": str(fai), "file": file_metadata(fasta)},
    )
    return {"status": "downloaded", "library": spec.id, "output": str(fasta), "fai": str(fai), "file": file_metadata(fasta)}


def _refresh_xlsx_tsv(spec: LibrarySpec, *, force: bool, root: str | Path | None) -> dict[str, Any]:
    """CellMarker: keep the source XLSX fresh, normalize to the marker TSV only
    when the XLSX actually changed (or the TSV is missing)."""
    url = spec.source.urls[0]
    output = _resolve(spec.targets[0], root)
    output.parent.mkdir(parents=True, exist_ok=True)
    xlsx = output.with_suffix(".source.xlsx")
    source = source_fetch.refresh_or_download(
        url,
        xlsx,
        _manifest_path(xlsx),
        expected={"library": f"{spec.id}-source", "source_url": url, "output": str(xlsx)},
        base_payload={"transform": ""},
        force=force,
        refresh=True,
        user_agent=_user_agent(spec),
    )
    if source.get("status") in {"downloaded", "updated"} or not output.is_file():
        transforms.xlsx_to_tsv(xlsx, output)
        write_manifest(
            _manifest_path(output),
            {
                "library": spec.id,
                "source_url": url,
                "output": str(output),
                "transform": "CellMarker 2.0 human XLSX normalized to Genomi marker-table TSV.",
                "downloaded_at_utc": utc_now(),
                "file": file_metadata(output),
            },
        )
        return {"status": "completed", "library": spec.id, "output": str(output)}
    return {"status": source.get("status", "cached"), "library": spec.id, "output": str(output)}


def _refresh_github_release(
    spec: LibrarySpec, *, force: bool, root: str | Path | None, **overrides: Any
) -> dict[str, Any]:
    """PharmCAT: re-download only when the latest release tag differs from the
    one recorded in the manifest."""
    output = _resolve(spec.targets[0], root)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(output)
    version = overrides.get("pharmcat_version")
    installed_tag = (read_manifest(manifest_path) or {}).get("pharmcat_version") if output.is_file() else None
    release = _fetch_github_release(spec, version)
    latest_tag = release.get("tag_name")
    if output.is_file() and not force and installed_tag and latest_tag and installed_tag == latest_tag:
        return {"status": "up_to_date", "library": spec.id, "output": str(output), "pharmcat_version": latest_tag}

    asset = _select_pharmcat_jar_asset(release)
    if asset is None:
        raise ValueError("PharmCAT release does not contain an all-in-one JAR asset.")
    source_fetch.download(asset["browser_download_url"], output, user_agent=_user_agent(spec))
    write_manifest(
        manifest_path,
        {
            "library": spec.id,
            "source_url": str(asset["browser_download_url"]),
            "output": str(output),
            "transform": f"Downloaded {asset['name']} from PharmCAT release {latest_tag or 'unknown'}.",
            "pharmcat_version": latest_tag,
            "downloaded_at_utc": utc_now(),
        },
    )
    return {
        "status": "updated" if installed_tag else "completed",
        "library": spec.id,
        "output": str(output),
        "pharmcat_version": latest_tag,
        "pharmcat_asset": asset["name"],
    }


def _fetch_github_release(spec: LibrarySpec, version: str | None) -> dict[str, Any]:
    if version:
        url = f"https://api.github.com/repos/PharmGKB/PharmCAT/releases/tags/{version}"
    else:
        url = spec.source.github_release_api or ""
    request = urllib.request.Request(
        url, headers={"User-Agent": _user_agent(spec), "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=60) as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"GitHub releases API returned an unexpected payload from {url}")
    return payload


def _select_pharmcat_jar_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return None
    candidates = [a for a in assets if isinstance(a, dict) and isinstance(a.get("name"), str)]
    for asset in candidates:
        name = str(asset.get("name") or "")
        if name.startswith("pharmcat-") and name.endswith("-all.jar"):
            return asset
    for asset in candidates:
        if str(asset.get("name") or "").endswith(".jar"):
            return asset
    return None


def _tar_compression(url: str) -> str:
    return "bz2" if url.endswith((".tar.bz2", ".tbz2")) else "gz"


def _refresh_pinned_sha(
    spec: LibrarySpec, *, force: bool, root: str | Path | None, **overrides: Any
) -> dict[str, Any]:
    """Version+sha256-pinned tarballs. A single named-binary target (aligners) is
    extracted to that path; a multi-file panel is flat-extracted into its dir."""
    url = spec.source.urls[0]
    required = _required_paths(spec, root)
    single_file = len(required) == 1 and spec.targets and required[0] == _resolve(spec.targets[0], root)

    if spec.platform_linux_x64_only and sys.platform != "linux":
        if all(path.exists() for path in required) and not force:
            return {"status": "cached", "library": spec.id, "version": spec.source.version}
        message = (
            f"Skipping {spec.id}: ships a linux x86_64 binary only "
            f"(detected sys.platform={sys.platform!r})."
        )
        return {"status": "skipped", "library": spec.id, "version": spec.source.version, "output": message}

    if single_file:
        return _refresh_pinned_binary(spec, url, required[0], force=force)
    return _refresh_pinned_panel(spec, url, force=force, root=root, **overrides)


def _refresh_pinned_binary(spec: LibrarySpec, url: str, binary: Path, *, force: bool) -> dict[str, Any]:
    install_dir = binary.parent
    manifest = install_dir / "manifest.json"
    if binary.is_file() and manifest.exists() and not force:
        return {"status": "cached", "library": spec.id, "output": str(binary), "version": spec.source.version}
    install_dir.mkdir(parents=True, exist_ok=True)
    tarball = install_dir / f"{binary.name}-{spec.source.version}.tar.{_tar_compression(url)}.partial"
    try:
        source_fetch.download(url, tarball, user_agent=_user_agent(spec))
        if spec.source.sha256:
            transforms.verify_sha256(tarball, spec.source.sha256)
        extracted = transforms.extract_named_binary(tarball, install_dir, binary.name, compression=_tar_compression(url))
    finally:
        if tarball.exists():
            tarball.unlink()
    if extracted != binary:
        binary.parent.mkdir(parents=True, exist_ok=True)
        extracted.replace(binary)
    write_manifest(
        manifest,
        {
            "library": spec.id,
            "binary": str(binary),
            "version": spec.source.version,
            "source_url": url,
            "source_sha256": spec.source.sha256,
            "downloaded_at_utc": utc_now(),
        },
    )
    return {"status": "completed", "library": spec.id, "output": str(binary), "version": spec.source.version}


def _refresh_pinned_panel(
    spec: LibrarySpec, url: str, *, force: bool, root: str | Path | None, **overrides: Any
) -> dict[str, Any]:
    target_dir = _resolve(spec.targets[0], root)
    panel_manifest = target_dir / "manifest.json"
    if panel_manifest.exists() and not force:
        return {"status": "cached", "library": spec.id, "manifest_path": str(panel_manifest)}

    # A locally-built or mirrored panel can be supplied instead of the pinned
    # release: a directory is copied verbatim; an override URL is fetched (still
    # verified against the pinned checksum unless the URL itself is overridden).
    prebuilt_dir = overrides.get("ancestry_panel_dir")
    if prebuilt_dir:
        source_dir = Path(prebuilt_dir).expanduser()
        missing = [rel.name for rel in spec.required_paths if not (source_dir / rel.name).exists()]
        if not source_dir.is_dir() or missing:
            return {"status": "manual_source_required", "library": spec.id, "reason": f"ancestry panel dir missing files: {missing or source_dir}"}
        import shutil

        target_dir.mkdir(parents=True, exist_ok=True)
        for rel in spec.required_paths:
            shutil.copyfile(source_dir / rel.name, target_dir / rel.name)
        return {"status": "completed", "library": spec.id, "manifest_path": str(panel_manifest), "source": str(source_dir)}

    override_url = overrides.get("ancestry_panel_url")
    fetch_url = override_url or url
    target_dir.mkdir(parents=True, exist_ok=True)
    tarball = target_dir.with_name(target_dir.name + ".tarball.partial")
    try:
        source_fetch.download(fetch_url, tarball, user_agent=_user_agent(spec))
        if spec.source.sha256 and not override_url:
            transforms.verify_sha256(tarball, spec.source.sha256)
        transforms.extract_flat_tarball(tarball, target_dir, compression=_tar_compression(fetch_url))
    finally:
        if tarball.exists():
            tarball.unlink()
    return {"status": "completed", "library": spec.id, "manifest_path": str(panel_manifest), "source": fetch_url}


def _refresh_derived(spec: LibrarySpec, *, force: bool, root: str | Path | None) -> dict[str, Any]:
    """A locally-built panel — ensure its inputs are installed, then build it."""
    for dependency in spec.source.derived_from:
        if not status(dependency, root=root)["installed"]:
            refresh(dependency, force=force, root=root)
    from ...capabilities.ancestry.panel_build import build_grch37_panel_from_grch38

    result = build_grch37_panel_from_grch38(force=force)
    return {**result, "library": spec.id} if isinstance(result, dict) else {"status": "completed", "library": spec.id}


def _refresh_manual(
    spec: LibrarySpec, *, force: bool, root: str | Path | None, **overrides: Any
) -> dict[str, Any]:
    """User-supplied source (MSigDB) — copy/download from an override or env, else
    report that a manual source is required (never errors in-process)."""
    output = _resolve(spec.targets[0], root)
    if output.is_file() and not force:
        return {"status": "cached", "library": spec.id, "output": str(output)}
    source_path = overrides.get("msigdb_gmt") or os.environ.get("GENOMI_MSIGDB_HALLMARK_GMT")
    source_url = overrides.get("msigdb_gmt_url") or os.environ.get("GENOMI_MSIGDB_HALLMARK_GMT_URL")
    output.parent.mkdir(parents=True, exist_ok=True)
    if source_url:
        source_fetch.download(source_url, output, user_agent=_user_agent(spec))
        _write_manual_manifest(spec, output, source_url, "Downloaded from user-supplied MSigDB export URL.")
        return {"status": "completed", "library": spec.id, "output": str(output)}
    if source_path:
        source = Path(source_path).expanduser()
        if not source.is_file():
            return {"status": "manual_source_required", "library": spec.id, "reason": f"source does not exist: {source}"}
        import shutil

        shutil.copyfile(source, output)
        _write_manual_manifest(spec, output, str(source), "Copied from user-supplied MSigDB Hallmark GMT export.")
        return {"status": "completed", "library": spec.id, "output": str(output)}
    return {
        "status": "manual_source_required",
        "library": spec.id,
        "reason": "msigdb-hallmark requires --msigdb-gmt / --msigdb-gmt-url or GENOMI_MSIGDB_HALLMARK_GMT[_URL].",
        "install_command": _install_command_for_spec(spec),
    }


def _write_manual_manifest(spec: LibrarySpec, output: Path, source: str, transform: str) -> None:
    write_manifest(
        _manifest_path(output),
        {
            "library": spec.id,
            "source_url": source,
            "output": str(output),
            "transform": transform,
            "downloaded_at_utc": utc_now(),
        },
    )
