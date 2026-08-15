"""Direct application operations that are not Genomi evidence capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import JsonObject, OperationHandler
from .errors import OperationError


@dataclass(frozen=True)
class ApplicationOperation:
    """A direct MCP application contract kept outside the capability catalog."""

    name: str
    handler: OperationHandler
    description: str
    input_schema: JsonObject
    mutating: bool = False
    produces: tuple[str, ...] = ()
    data_access: tuple[str, ...] = ("local_encrypted_genomilab_records",)
    tool_capability: str = "lab"
    agi_need: str | None = None
    mcp_background_eligible: bool = False

    def tool_definition(self) -> JsonObject:
        action = self.name.split(".", 1)[-1].replace("_", " ")
        title = f"Using GenomiLab to {action}"
        parameter_defaults = [
            {
                "parameter": str(name),
                "value": definition["default"],
                "source": "tool_default",
                "applies_when_omitted": True,
            }
            for name, definition in (
                self.input_schema.get("properties") or {}
            ).items()
            if isinstance(definition, dict) and "default" in definition
        ]
        return {
            "name": self.name,
            "title": title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": title,
                "portalLabel": f"GenomiLab {action}",
                "skill": "skills/genomilab/SKILL.md",
                "area": "lab",
                "requires": [],
                "produces": list(self.produces),
                "contextOptional": [],
                "parameterDefaults": parameter_defaults,
                "privacyScope": "local_private",
                "operationScope": "write" if self.mutating else "read",
                "mutating": self.mutating,
                "externalIO": [],
                "dataAccess": list(self.data_access),
                "trustBoundary": "local_cli_or_stdio_mcp_host",
                "flow": "agent-composed",
                "toolCapability": self.tool_capability,
                "discoveryRole": "application_tool",
                "mcpExecution": "inline_only",
            },
        }

    def validate_params(self, params: JsonObject) -> None:
        properties = self.input_schema.get("properties") or {}
        required = self.input_schema.get("required") or []
        unexpected = set(params) - set(properties)
        if unexpected:
            raise OperationError(
                "invalid_params",
                "unsupported parameters: " + ", ".join(sorted(unexpected)),
            )
        missing = [name for name in required if params.get(name) is None]
        if missing:
            raise OperationError(
                "invalid_params",
                "missing required parameters: " + ", ".join(missing),
            )
        for name, value in params.items():
            schema = properties.get(name)
            if not isinstance(schema, dict):
                continue
            expected = schema.get("type")
            valid = (
                expected == "string"
                and isinstance(value, str)
                or expected == "integer"
                and isinstance(value, int)
                and not isinstance(value, bool)
                or expected == "boolean"
                and isinstance(value, bool)
                or expected == "object"
                and isinstance(value, dict)
                or expected == "array"
                and isinstance(value, list)
            )
            if expected and not valid:
                raise OperationError(
                    "invalid_params", f"{name} must be a {expected}"
                )
            if expected == "integer" and "minimum" in schema and value < schema["minimum"]:
                raise OperationError(
                    "invalid_params", f"{name} must be at least {schema['minimum']}"
                )
            if expected == "array" and isinstance(value, list):
                items = schema.get("items") or {}
                if items.get("type") == "string" and not all(
                    isinstance(item, str) for item in value
                ):
                    raise OperationError(
                        "invalid_params", f"{name} must contain only strings"
                    )
                if schema.get("uniqueItems") and len(value) != len(set(value)):
                    raise OperationError(
                        "invalid_params", f"{name} must not contain duplicates"
                    )


def object_schema(
    properties: JsonObject,
    *,
    required: tuple[str, ...] = (),
) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


STRING = {"type": "string"}
STRING_ARRAY = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
INTEGER = {"type": "integer", "minimum": 1}


__all__ = [
    "ApplicationOperation",
    "INTEGER",
    "STRING",
    "STRING_ARRAY",
    "object_schema",
]
