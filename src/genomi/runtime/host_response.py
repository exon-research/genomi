from __future__ import annotations

import json
from importlib import resources
from typing import Any

JsonObject = dict[str, Any]
PROFILE_RESOURCE = "host_response_profiles.json"


def host_response_profiles() -> JsonObject:
    resource = resources.files(__package__).joinpath(PROFILE_RESOURCE)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{PROFILE_RESOURCE} must contain a JSON object")
    return payload


def resolve_active_response_profile(profile_id: str | None) -> JsonObject:
    """Return the full active response-profile record for `profile_id`.

    Falls back to the catalog `default_profile` when `profile_id` is None or
    does not match a profile id in the catalog. The returned dict always
    includes a `source` field: `"explicit"` when a valid id was supplied,
    `"default"` otherwise.
    """
    catalog = host_response_profiles()
    profiles = catalog.get("profiles") or []
    profile_index = {
        str(profile.get("id")): profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("id")
    }
    candidate = profile_index.get(str(profile_id)) if profile_id else None
    source = "explicit"
    if not isinstance(candidate, dict):
        candidate = profile_index.get(str(catalog.get("default_profile") or ""))
        source = "default"
    if not isinstance(candidate, dict):
        # Catalog has no usable profiles; surface an empty record rather than crash.
        return {"id": None, "label": None, "guidance": "", "source": source}
    return {
        "id": str(candidate.get("id") or ""),
        "label": str(candidate.get("label") or ""),
        "guidance": str(candidate.get("guidance") or ""),
        "source": source,
    }
