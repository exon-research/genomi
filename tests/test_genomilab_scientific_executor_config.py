from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from genomi.interfaces.mcp import handle_request
from genomi.lab import agent_runtime
from genomi.lab.scientific_executor_config import (
    ESM_SCIENTIFIC_EXECUTOR_ENV,
    PROTO_SCIENTIFIC_EXECUTOR_ENV,
    SCIENTIFIC_EXECUTOR_ENTRY_POINT_GROUP,
    ScientificExecutorConfigurationError,
    load_scientific_executor_configuration,
)


def _esm_one(_request: dict[str, object]) -> dict[str, object]:
    return {}


def _esm_two(_request: dict[str, object]) -> dict[str, object]:
    return {}


def _proto(_request: dict[str, object]) -> dict[str, object]:
    return {}


class _EntryPoint:
    def __init__(
        self,
        name: str,
        value: object = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self.error = error
        self.load_count = 0

    def load(self) -> object:
        self.load_count += 1
        if self.error is not None:
            raise self.error
        return self.value


class _Service:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ScientificExecutorConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        agent_runtime.close_agent_runtime()

    def tearDown(self) -> None:
        agent_runtime.close_agent_runtime()

    def test_unset_selectors_leave_both_executors_unavailable(self) -> None:
        with mock.patch(
            "genomi.lab.scientific_executor_config.importlib_metadata.entry_points"
        ) as entry_points:
            configuration = load_scientific_executor_configuration({})

        entry_points.assert_not_called()
        self.assertIsNone(configuration.esm_executor)
        self.assertIsNone(configuration.proto_executor)

    def test_configured_installed_entry_points_are_wired_into_fresh_runtime(
        self,
    ) -> None:
        esm_entry_point = _EntryPoint("local-esm", _esm_one)
        proto_entry_point = _EntryPoint("local-proto", _proto)
        service = _Service()
        with (
            mock.patch.dict(
                os.environ,
                {
                    ESM_SCIENTIFIC_EXECUTOR_ENV: "local-esm",
                    PROTO_SCIENTIFIC_EXECUTOR_ENV: "local-proto",
                },
                clear=True,
            ),
            mock.patch(
                "genomi.lab.scientific_executor_config.importlib_metadata.entry_points",
                return_value=[esm_entry_point, proto_entry_point],
            ) as entry_points,
            mock.patch(
                "genomi.lab.agent_runtime.GenomiLabService",
                return_value=service,
            ) as service_class,
        ):
            runtime = agent_runtime.GenomiLabAgentRuntime(
                agent_runtime.AgentHostContext(agent_session_id="fresh-runtime")
            )

        self.addCleanup(runtime.close)
        entry_points.assert_called_once_with(
            group=SCIENTIFIC_EXECUTOR_ENTRY_POINT_GROUP
        )
        self.assertIs(
            service_class.call_args.kwargs["esm_scientific_executor"], _esm_one
        )
        self.assertIs(
            service_class.call_args.kwargs["proto_scientific_executor"], _proto
        )
        self.assertEqual(esm_entry_point.load_count, 1)
        self.assertEqual(proto_entry_point.load_count, 1)

    def test_invalid_selector_cannot_be_an_import_path(self) -> None:
        with (
            mock.patch(
                "genomi.lab.scientific_executor_config.importlib_metadata.entry_points"
            ) as entry_points,
            self.assertRaises(ScientificExecutorConfigurationError) as raised,
        ):
            load_scientific_executor_configuration(
                {ESM_SCIENTIFIC_EXECUTOR_ENV: "some.module:executor"}
            )

        entry_points.assert_not_called()
        self.assertEqual(
            raised.exception.code, "invalid_scientific_executor_selector"
        )
        self.assertEqual(raised.exception.system, "esm")

    def test_mcp_surfaces_typed_startup_configuration_failure(self) -> None:
        with mock.patch.dict(
            os.environ,
            {ESM_SCIENTIFIC_EXECUTOR_ENV: "some.module:executor"},
            clear=True,
        ):
            agent_runtime.configure_mcp_host(
                {"name": "Codex", "version": "test"}, transport="stdio"
            )
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "genomilab.open_workspace",
                        "arguments": {"open_portal": False},
                    },
                },
                transport="stdio",
            )

        assert response is not None
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(
            payload["error"], "invalid_scientific_executor_selector"
        )
        self.assertNotIn("some.module:executor", payload["message"])

    def test_unknown_selector_fails_closed(self) -> None:
        with (
            mock.patch(
                "genomi.lab.scientific_executor_config.importlib_metadata.entry_points",
                return_value=[],
            ),
            self.assertRaises(ScientificExecutorConfigurationError) as raised,
        ):
            load_scientific_executor_configuration(
                {PROTO_SCIENTIFIC_EXECUTOR_ENV: "missing-proto"}
            )

        self.assertEqual(raised.exception.code, "scientific_executor_not_installed")
        self.assertEqual(raised.exception.selector, "missing-proto")

    def test_ambiguous_entry_point_fails_closed_without_loading(self) -> None:
        first = _EntryPoint("duplicate-esm", _esm_one)
        second = _EntryPoint("duplicate-esm", _esm_two)
        with (
            mock.patch(
                "genomi.lab.scientific_executor_config.importlib_metadata.entry_points",
                return_value=[first, second],
            ),
            self.assertRaises(ScientificExecutorConfigurationError) as raised,
        ):
            load_scientific_executor_configuration(
                {ESM_SCIENTIFIC_EXECUTOR_ENV: "duplicate-esm"}
            )

        self.assertEqual(
            raised.exception.code,
            "ambiguous_scientific_executor_entry_point",
        )
        self.assertEqual(first.load_count, 0)
        self.assertEqual(second.load_count, 0)

    def test_non_callable_and_broken_entry_points_fail_closed(self) -> None:
        cases = (
            (
                _EntryPoint("not-callable", object()),
                "scientific_executor_not_callable",
            ),
            (
                _EntryPoint(
                    "broken-executor",
                    error=ImportError("private loader detail"),
                ),
                "scientific_executor_load_failed",
            ),
        )
        for entry_point, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with (
                    mock.patch(
                        "genomi.lab.scientific_executor_config."
                        "importlib_metadata.entry_points",
                        return_value=[entry_point],
                    ),
                    self.assertRaises(
                        ScientificExecutorConfigurationError
                    ) as raised,
                ):
                    load_scientific_executor_configuration(
                        {ESM_SCIENTIFIC_EXECUTOR_ENV: entry_point.name}
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("private loader detail", str(raised.exception))

    def test_executor_selection_is_stable_until_mcp_reinitializes(self) -> None:
        services: list[_Service] = []

        def new_service(**kwargs: object) -> _Service:
            service = _Service(**kwargs)
            services.append(service)
            return service

        entry_points = [
            _EntryPoint("esm-one", _esm_one),
            _EntryPoint("esm-two", _esm_two),
        ]
        with (
            mock.patch.dict(
                os.environ,
                {ESM_SCIENTIFIC_EXECUTOR_ENV: "esm-one"},
                clear=True,
            ),
            mock.patch(
                "genomi.lab.scientific_executor_config.importlib_metadata.entry_points",
                return_value=entry_points,
            ) as discover,
            mock.patch(
                "genomi.lab.agent_runtime.GenomiLabService",
                side_effect=new_service,
            ),
        ):
            agent_runtime.configure_mcp_host(
                {"name": "Codex", "version": "test"}, transport="stdio"
            )
            first = agent_runtime.current_agent_runtime()
            os.environ[ESM_SCIENTIFIC_EXECUTOR_ENV] = "esm-two"
            self.assertIs(agent_runtime.current_agent_runtime(), first)

            agent_runtime.configure_mcp_host(
                {"name": "Codex", "version": "test"}, transport="stdio"
            )
            second = agent_runtime.current_agent_runtime()

        self.assertIsNot(first, second)
        self.assertTrue(services[0].closed)
        self.assertIs(services[0].kwargs["esm_scientific_executor"], _esm_one)
        self.assertIs(services[1].kwargs["esm_scientific_executor"], _esm_two)
        self.assertEqual(discover.call_count, 2)


if __name__ == "__main__":
    unittest.main()
