from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


class PortalFrontendRunStreamTests(unittest.TestCase):
    def test_run_stream_reconnects_with_last_event_id(self) -> None:
        stream_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_run_stream.js").as_uri()
        script = textwrap.dedent(
            f"""
            const stream = await import({stream_url!r});
            class FakeEventSource {{
              static instances = [];
              constructor(url) {{
                this.url = url;
                this.listeners = {{}};
                this.closed = false;
                FakeEventSource.instances.push(this);
              }}
              addEventListener(name, callback) {{
                this.listeners[name] = this.listeners[name] || [];
                this.listeners[name].push(callback);
              }}
              close() {{ this.closed = true; }}
              emit(name, data, lastEventId = '') {{
                for (const callback of this.listeners[name] || []) {{
                  callback({{ data: JSON.stringify(data || {{}}), lastEventId }});
                }}
              }}
            }}
            globalThis.EventSource = FakeEventSource;
            const received = [];
            let statusCalls = 0;
            const watcher = stream.watchRun('run 1', {{
              onAgent: (data) => received.push(['agent', data]),
              onEnd: (data) => received.push(['end', data])
            }}, {{
              reconnectDelayMs: 0,
              loadRunStatus: async () => {{
                statusCalls += 1;
                return {{ status: 'succeeded', terminal: true }};
              }}
            }});
            FakeEventSource.instances[0].emit('agent', {{ type: 'text_delta', delta: 'hello' }}, '2');
            FakeEventSource.instances[0].emit('error', {{}});
            await new Promise((resolve) => setTimeout(resolve, 5));
            FakeEventSource.instances[1].emit('agent', {{ type: 'text_delta', delta: ' again' }}, '3');
            FakeEventSource.instances[1].emit('end', {{ status: 'succeeded', error: null }}, '3');
            watcher.close();
            process.stdout.write(JSON.stringify({{
              urls: FakeEventSource.instances.map((item) => item.url),
              closed: FakeEventSource.instances.map((item) => item.closed),
              received,
              statusCalls
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["urls"], ["/api/runs/run%201/events", "/api/runs/run%201/events?after=2"])
        self.assertEqual(result["closed"], [True, True])
        self.assertEqual(result["statusCalls"], 0)
        self.assertEqual(result["received"][0], ["agent", {"type": "text_delta", "delta": "hello"}])
        self.assertEqual(result["received"][1], ["agent", {"type": "text_delta", "delta": " again"}])
        self.assertEqual(result["received"][2], ["end", {"status": "succeeded", "error": None}])

    def test_run_stream_uses_status_endpoint_only_after_reconnect_exhaustion(self) -> None:
        stream_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_run_stream.js").as_uri()
        script = textwrap.dedent(
            f"""
            const stream = await import({stream_url!r});
            class FakeEventSource {{
              static instances = [];
              constructor(url) {{
                this.url = url;
                this.listeners = {{}};
                this.closed = false;
                FakeEventSource.instances.push(this);
              }}
              addEventListener(name, callback) {{
                this.listeners[name] = this.listeners[name] || [];
                this.listeners[name].push(callback);
              }}
              close() {{ this.closed = true; }}
              emit(name, data, lastEventId = '') {{
                for (const callback of this.listeners[name] || []) {{
                  callback({{ data: JSON.stringify(data || {{}}), lastEventId }});
                }}
              }}
            }}
            globalThis.EventSource = FakeEventSource;
            const received = [];
            stream.watchRun('run 2', {{
              onEnd: (data) => received.push(['end', data]),
              onInterrupt: (data) => received.push(['interrupt', data])
            }}, {{
              reconnectDelayMs: 0,
              maxReconnectAttempts: 0,
              loadRunStatus: async () => ({{ status: 'failed', terminal: true, error: 'agent exited' }})
            }});
            FakeEventSource.instances[0].emit('error', {{}});
            await new Promise((resolve) => setTimeout(resolve, 5));
            process.stdout.write(JSON.stringify({{
              instanceCount: FakeEventSource.instances.length,
              closed: FakeEventSource.instances[0].closed,
              received
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["instanceCount"], 1)
        self.assertTrue(result["closed"])
        self.assertEqual(result["received"], [["end", {"status": "failed", "error": "agent exited"}]])

    def test_run_stream_replays_durable_event_page_before_status_fallback(self) -> None:
        stream_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_run_stream.js").as_uri()
        script = textwrap.dedent(
            f"""
            const stream = await import({stream_url!r});
            class FakeEventSource {{
              static instances = [];
              constructor(url) {{
                this.url = url;
                this.listeners = {{}};
                this.closed = false;
                FakeEventSource.instances.push(this);
              }}
              addEventListener(name, callback) {{
                this.listeners[name] = this.listeners[name] || [];
                this.listeners[name].push(callback);
              }}
              close() {{ this.closed = true; }}
              emit(name, data, lastEventId = '') {{
                for (const callback of this.listeners[name] || []) {{
                  callback({{ data: JSON.stringify(data || {{}}), lastEventId }});
                }}
              }}
            }}
            globalThis.EventSource = FakeEventSource;
            const received = [];
            const eventPageCalls = [];
            let statusCalls = 0;
            stream.watchRun('run 3', {{
              onAgent: (data) => received.push(['agent', data]),
              onArtifact: (data) => received.push(['artifact', data]),
              onEnd: (data) => received.push(['end', data]),
              onInterrupt: (data) => received.push(['interrupt', data])
            }}, {{
              reconnectDelayMs: 0,
              maxReconnectAttempts: 0,
              loadRunEventPage: async (_runId, afterEventId) => {{
                eventPageCalls.push(afterEventId);
                return {{
                  items: [
                    {{ id: 3, event: 'agent', data: {{ type: 'text_delta', delta: ' replayed' }} }},
                    {{ id: 4, event: 'artifact', data: {{ artifact_id: 'art_1' }} }},
                    {{ id: 5, event: 'end', data: {{ status: 'succeeded', error: null }} }}
                  ],
                  truncated: false,
                  next_after_event_id: 5
                }};
              }},
              loadRunStatus: async () => {{
                statusCalls += 1;
                return {{ status: 'succeeded', terminal: true }};
              }}
            }});
            FakeEventSource.instances[0].emit('agent', {{ type: 'text_delta', delta: 'before' }}, '2');
            FakeEventSource.instances[0].emit('error', {{}});
            await new Promise((resolve) => setTimeout(resolve, 5));
            process.stdout.write(JSON.stringify({{
              instanceCount: FakeEventSource.instances.length,
              closed: FakeEventSource.instances[0].closed,
              eventPageCalls,
              statusCalls,
              received
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["instanceCount"], 1)
        self.assertTrue(result["closed"])
        self.assertEqual(result["eventPageCalls"], [2])
        self.assertEqual(result["statusCalls"], 0)
        self.assertEqual(
            result["received"],
            [
                ["agent", {"type": "text_delta", "delta": "before"}],
                ["agent", {"type": "text_delta", "delta": " replayed"}],
                ["artifact", {"artifact_id": "art_1"}],
                ["end", {"status": "succeeded", "error": None}],
            ],
        )


def _run_node_json(test_case: unittest.TestCase, script: str):
    node = shutil.which("node")
    test_case.assertIsNotNone(node, "node is required for frontend run stream tests")
    completed = subprocess.run(
        [str(node), "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
