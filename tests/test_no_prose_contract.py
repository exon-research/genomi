"""No-prose contract tests.

Asserts evidence-producing operation results never carry removed policy-prose
fields, and that envelope.guidance is always typed codes.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from genomi import operations as ops
from genomi.evidence import envelope as env

FORBIDDEN_TOP_LEVEL_KEYS = {
    "agent_guidance",
    "interpretation_boundary",
    "recommended_agent_action",
    "answer_affordance",
}


def _walk(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    """Yield (path, key) for every dict key found anywhere in value."""

    hits: list[tuple[tuple[str, ...], str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            hits.append((path, str(key)))
            hits.extend(_walk(item, (*path, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_walk(item, (*path, f"[{index}]")))
    return hits


def _stub_dispatch(name: str, stub_result: dict[str, Any]) -> dict[str, Any]:
    operation = ops.get_operation(name)
    original = operation.handler
    replaced = ops.Operation(
        name=operation.name,
        description=operation.description,
        input_schema=operation.input_schema,
        handler=lambda _params, _stub=stub_result: dict(_stub),
        skill=operation.skill,
        area=operation.area,
        requires=operation.requires,
        produces=operation.produces,
        context_optional=operation.context_optional,
        privacy_scope=operation.privacy_scope,
        operation_scope=operation.operation_scope,
        mutating=operation.mutating,
        external_io=operation.external_io,
        data_access=operation.data_access,
    )
    ops._OPERATION_BY_NAME[name] = replaced
    try:
        return ops.call_operation(name, {})
    finally:
        ops._OPERATION_BY_NAME[name] = ops.Operation(
            name=operation.name,
            description=operation.description,
            input_schema=operation.input_schema,
            handler=original,
            skill=operation.skill,
            area=operation.area,
            requires=operation.requires,
            produces=operation.produces,
            context_optional=operation.context_optional,
            privacy_scope=operation.privacy_scope,
            operation_scope=operation.operation_scope,
            mutating=operation.mutating,
            external_io=operation.external_io,
            data_access=operation.data_access,
        )


class NoProseContractTests(unittest.TestCase):
    def test_dispatched_results_have_no_removed_top_level_prose(self) -> None:
        # For every evidence-producing op, the dispatched result must not
        # carry agent_guidance / interpretation_boundary /
        # recommended_agent_action / answer_affordance at the top level.
        for name in sorted(ops.EVIDENCE_PRODUCING_OPERATIONS):
            with self.subTest(op=name):
                result = _stub_dispatch(
                    name,
                    {"status": "completed", "ok": True, "summary": {"record_count": 1}},
                )
                top_level_keys = set(result.keys()) if isinstance(result, dict) else set()
                forbidden = top_level_keys & FORBIDDEN_TOP_LEVEL_KEYS
                self.assertFalse(
                    forbidden,
                    f"{name} result has forbidden top-level keys: {sorted(forbidden)}",
                )

    def test_envelope_guidance_is_typed_codes_only(self) -> None:
        # Each guidance entry must be a short code (no spaces, no prose).
        envelopes = [
            env.evidence_present(operation="x", observations={"observation_count": 1}),
            env.empty_consulted_scope(operation="x"),
            env.not_assessed(operation="x", reason="missing inputs"),
            env.materialization_pending(operation="x", library="clinvar-grch38", materialization={"status": "running"}),
            env.missing_library(
                operation="x",
                library="clinvar-grch38",
                library_status_payload={"install_command": "x", "title": "y", "helps": "z"},
            ),
        ]
        for e in envelopes:
            for g in e["guidance"]:
                self.assertNotIn(" ", g, f"guidance entry should be a code, got prose: {g!r}")

    def test_operation_metadata_does_not_advertise_forbidden_outputs(self) -> None:
        offenders: list[str] = []
        for operation in ops.all_operations():
            forbidden = set(operation["annotations"].get("produces") or []) & FORBIDDEN_TOP_LEVEL_KEYS
            if forbidden:
                offenders.append(f"{operation['name']}: {sorted(forbidden)}")
        self.assertEqual(offenders, [], "found forbidden operation produces metadata:\n" + "\n".join(offenders))

    def test_source_modules_dont_assign_forbidden_output_keys(self) -> None:
        # Grep-style guard. No module may write these removed prose keys into
        # dict literal or assignment outputs.
        src_dir = Path(__file__).resolve().parents[1] / "src" / "genomi"
        dict_literal_pattern = re.compile(
            r'^\s*"(agent_guidance|interpretation_boundary|recommended_agent_action|answer_affordance)"\s*:'
        )
        assignment_pattern = re.compile(
            r'\[\s*"(agent_guidance|interpretation_boundary|recommended_agent_action|answer_affordance)"\s*\]\s*='
        )
        offenders: list[str] = []
        for path in sorted(src_dir.glob("*.py")):
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if dict_literal_pattern.match(line) or assignment_pattern.search(line):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [], "found removed prose key assignments:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
