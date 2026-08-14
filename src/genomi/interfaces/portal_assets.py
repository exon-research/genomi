from __future__ import annotations

import html
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .. import __version__
from . import portal_starter_cards, portal_store

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_LOGO_PATH = _PACKAGE_ROOT / "assets" / "genomi-logo-transparent.png"
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_PATH = _TEMPLATE_DIR / "portal.html"
_ARTIFACT_FILE_CSP = (
    "sandbox allow-scripts allow-downloads; "
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "font-src data:; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'self'"
)


def _is_portal_template_asset(path: Path) -> bool:
    return (
        path.name == "portal.js"
        or (path.name.startswith("portal") and path.suffix == ".css")
        or (path.name.startswith("portal_") and path.suffix == ".js")
    )


def template_asset_names() -> tuple[str, ...]:
    return tuple(path.name for path in _template_asset_paths().values())


def send_portal_html(handler: BaseHTTPRequestHandler) -> None:
    token = str(getattr(handler.server, "portal_csrf_token", ""))
    try:
        body = _portal_html(token)
    except OSError:
        handler.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Portal asset unavailable")
        return
    _send_html(handler, body)


def send_logo(handler: BaseHTTPRequestHandler) -> None:
    if not _LOGO_PATH.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND, "Not Found")
        return
    raw = _LOGO_PATH.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "public, max-age=3600")
    handler.end_headers()
    handler.wfile.write(raw)


def send_template_asset(handler: BaseHTTPRequestHandler, asset_name: str) -> None:
    path = _template_asset_paths().get(f"/assets/{asset_name}")
    if path is None:
        handler.send_error(HTTPStatus.NOT_FOUND, "Not Found")
        return
    _send_file(handler, path, cache_control="no-store")


def _template_asset_paths() -> dict[str, Path]:
    return {
        f"/assets/{path.name}": path
        for path in sorted(_TEMPLATE_DIR.iterdir())
        if _is_portal_template_asset(path)
    }


def send_artifact_file(handler: BaseHTTPRequestHandler, project_id: str, artifact_id: str) -> None:
    artifact_path = portal_store.latest_project_artifact_file_path(project_id, artifact_id)
    if artifact_path is None:
        handler.send_error(HTTPStatus.NOT_FOUND, "Not Found")
        return
    _send_artifact_blob(handler, artifact_path)


def send_artifact_version_file(handler: BaseHTTPRequestHandler, project_id: str, artifact_id: str, version_id: str) -> None:
    artifact_path = portal_store.project_artifact_version_file_path(project_id, artifact_id, version_id)
    if artifact_path is None:
        handler.send_error(HTTPStatus.NOT_FOUND, "Not Found")
        return
    _send_artifact_blob(handler, artifact_path)


def _send_artifact_blob(handler: BaseHTTPRequestHandler, artifact_path: Path) -> None:
    _send_file(
        handler,
        artifact_path,
        cache_control="no-store",
        extra_headers={
            "Content-Security-Policy": _ARTIFACT_FILE_CSP,
            "X-Content-Type-Options": "nosniff",
        },
    )


def _send_html(handler: BaseHTTPRequestHandler, body: str) -> None:
    raw = body.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _send_file(
    handler: BaseHTTPRequestHandler,
    path: Path,
    *,
    cache_control: str,
    extra_headers: dict[str, str] | None = None,
) -> None:
    if not path.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND, "Not Found")
        return
    raw = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", cache_control)
    for name, value in (extra_headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(raw)


def _portal_html(token: str) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    inline_css = _portal_inline_css(template)
    version = html.escape(__version__)
    return (
        template.replace("{{GENOMI_VERSION}}", version)
        .replace("{GENOMI_VERSION}", version)
        .replace("{PORTAL_CSRF_TOKEN}", html.escape(token))
        .replace("{PORTAL_INLINE_CSS}", inline_css)
        .replace("{PORTAL_STARTER_CARDS_JSON}", portal_starter_cards.welcome_model_json())
        .replace("{PORTAL_WELCOME_MESSAGE}", portal_starter_cards.welcome_message_markup())
    )


def _portal_inline_css(template: str) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _linked_stylesheet_paths(template)).replace("</style", "<\\/style")


def _linked_stylesheet_paths(template: str) -> tuple[Path, ...]:
    assets = _template_asset_paths()
    paths: list[Path] = []
    for asset_name in re.findall(r'<link\b[^>]*\bhref="/assets/([^"]+\.css)"', template):
        path = assets.get(f"/assets/{asset_name}")
        if path is None:
            raise FileNotFoundError(asset_name)
        paths.append(path)
    return tuple(paths)
