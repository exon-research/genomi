from __future__ import annotations

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8768
PORTAL_ENDPOINT = "/"
MCP_ENDPOINT = "/mcp"
HEALTH_ENDPOINT = "/health"
ARTIFACT_FILE_PREFIX = "/api/artifacts"


def portal_url(host: str = DEFAULT_HTTP_HOST, port: int = DEFAULT_HTTP_PORT) -> str:
    return f"http://{host}:{port}{PORTAL_ENDPOINT}"


def mcp_url(host: str = DEFAULT_HTTP_HOST, port: int = DEFAULT_HTTP_PORT) -> str:
    return f"http://{host}:{port}{MCP_ENDPOINT}"


def runtime_routes() -> dict[str, str]:
    return {
        "portal": PORTAL_ENDPOINT,
        "mcp": MCP_ENDPOINT,
        "health": HEALTH_ENDPOINT,
    }


def artifact_file_endpoint(artifact_id: str) -> str:
    return f"{ARTIFACT_FILE_PREFIX}/{artifact_id}/file"


def artifact_endpoint(artifact_id: str) -> str:
    return f"{ARTIFACT_FILE_PREFIX}/{artifact_id}"


def artifact_versions_endpoint(artifact_id: str) -> str:
    return f"{ARTIFACT_FILE_PREFIX}/{artifact_id}/versions"


def artifact_version_endpoint(version_id: str) -> str:
    return f"{ARTIFACT_FILE_PREFIX}/versions/{version_id}"


def artifact_version_file_endpoint(version_id: str) -> str:
    return f"{ARTIFACT_FILE_PREFIX}/versions/{version_id}/file"


def project_artifact_endpoint(project_id: str, artifact_id: str) -> str:
    return f"/api/projects/{project_id}/artifacts/{artifact_id}"


def project_artifact_file_endpoint(project_id: str, artifact_id: str) -> str:
    return f"{project_artifact_endpoint(project_id, artifact_id)}/file"


def project_artifact_metadata_endpoint(project_id: str, artifact_id: str) -> str:
    return f"{project_artifact_endpoint(project_id, artifact_id)}/metadata"


def project_artifact_bundle_endpoint(project_id: str, artifact_id: str) -> str:
    return f"{project_artifact_endpoint(project_id, artifact_id)}/bundle"


def project_artifact_script_bundle_endpoint(project_id: str, artifact_id: str) -> str:
    return f"{project_artifact_endpoint(project_id, artifact_id)}/script-bundle"


def project_artifact_version_script_bundle_endpoint(project_id: str, artifact_id: str, version_id: str) -> str:
    return f"{project_artifact_version_endpoint(project_id, artifact_id, version_id)}/script-bundle"


def project_artifact_review_runs_endpoint(project_id: str, artifact_id: str) -> str:
    return f"{project_artifact_endpoint(project_id, artifact_id)}/review-runs"


def project_artifact_version_review_runs_endpoint(project_id: str, artifact_id: str, version_id: str) -> str:
    return f"{project_artifact_version_endpoint(project_id, artifact_id, version_id)}/review-runs"


def project_artifact_import_endpoint(project_id: str) -> str:
    return f"/api/projects/{project_id}/artifacts/import"


def project_frame_bundle_endpoint(project_id: str, frame_id: str) -> str:
    return f"/api/projects/{project_id}/frames/{frame_id}/bundle"


def project_frame_reviews_endpoint(project_id: str, frame_id: str) -> str:
    return f"/api/projects/{project_id}/frames/{frame_id}/reviews"


def project_artifact_versions_endpoint(project_id: str, artifact_id: str) -> str:
    return f"{project_artifact_endpoint(project_id, artifact_id)}/versions"


def project_artifact_version_endpoint(project_id: str, artifact_id: str, version_id: str) -> str:
    return f"{project_artifact_versions_endpoint(project_id, artifact_id)}/{version_id}"


def project_artifact_version_file_endpoint(project_id: str, artifact_id: str, version_id: str) -> str:
    return f"{project_artifact_version_endpoint(project_id, artifact_id, version_id)}/file"


def artifact_id_from_file_endpoint(path: str) -> str | None:
    prefix = f"{ARTIFACT_FILE_PREFIX}/"
    suffix = "/file"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return None
    artifact_id = path.removeprefix(prefix).removesuffix(suffix).strip("/")
    if "/" in artifact_id:
        return None
    return artifact_id or None
