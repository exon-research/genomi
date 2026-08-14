from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RouteSpec:
    template: str
    handler: Callable[..., None]


@dataclass(frozen=True)
class RouteMatch:
    spec: RouteSpec
    params: dict[str, str]


def match_route(path: str, routes: tuple[RouteSpec, ...]) -> RouteMatch | None:
    matches: list[tuple[tuple[int, int], RouteSpec, dict[str, str]]] = []
    for spec in routes:
        params = _match_template(path, spec.template)
        if params is not None:
            matches.append((_route_rank(spec.template), spec, params))
    if not matches:
        return None
    _rank, spec, params = max(matches, key=lambda item: item[0])
    return RouteMatch(spec=spec, params=params)


def _match_template(path: str, template: str) -> dict[str, str] | None:
    if template == "/":
        return {} if path == "/" else None
    path_parts = [part for part in path.split("/") if part]
    template_parts = [part for part in template.split("/") if part]
    if len(path_parts) != len(template_parts):
        return None
    params: dict[str, str] = {}
    for actual, expected in zip(path_parts, template_parts):
        if expected.startswith("{") and expected.endswith("}"):
            if not actual:
                return None
            params[expected[1:-1]] = actual
        elif actual != expected:
            return None
    return params


def _route_rank(template: str) -> tuple[int, int]:
    parts = [part for part in template.split("/") if part]
    static_count = sum(1 for part in parts if not (part.startswith("{") and part.endswith("}")))
    return (len(parts), static_count)
