from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src/genomi/interfaces/templates"


def _run_node(script: str) -> dict[str, object]:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class PortalFrontendSpecialistTests(unittest.TestCase):
    def test_live_collaboration_records_drive_multiple_specialists_and_parent_wait(self) -> None:
        module_url = (TEMPLATES / "portal_specialists.js").as_uri()
        script = textwrap.dedent(
            f"""
            const specialists = await import({module_url!r});
            const records = [
              {{
                call: {{
                  id: 'spawn-literature',
                  name: 'spawn_agent',
                  input: {{ task_name: 'literature_review', message: 'Review the recent clinical literature independently.' }}
                }},
                result: {{
                  id: 'spawn-literature',
                  payload: {{ agent_id: 'agent-lit', task_name: '/root/literature_review' }}
                }}
              }},
              {{
                call: {{
                  id: 'spawn-protein',
                  name: 'collaboration.spawn_agent',
                  input: {{ task_name: 'protein_model', message: 'Check the protein-model evidence and limitations.' }}
                }},
                result: {{
                  id: 'spawn-protein',
                  payload: {{ agent_id: 'agent-protein', task_name: '/root/protein_model', status: 'running' }}
                }}
              }},
              {{
                call: {{ id: 'wait-1', name: 'wait_agent', input: {{ timeout_ms: 30000 }} }}
              }}
            ];
            const waiting = specialists.specialistLaneModel(records);
            records[2].result = {{
              id: 'wait-1',
              payload: {{ updates: [
                {{ agent_id: 'agent-lit', task_name: '/root/literature_review', status: 'completed' }},
                {{ agent_id: 'agent-protein', task_name: '/root/protein_model', status: 'failed' }}
              ] }}
            }};
            const completed = specialists.specialistLaneModel(records);
            process.stdout.write(JSON.stringify({{
              waiting,
              completed,
              names: [
                specialists.isSpecialistToolName('spawn_agent'),
                specialists.isSpecialistToolName('collaboration__wait_agent'),
                specialists.isSpecialistToolName('variant.resolve')
              ]
            }}));
            """
        )

        result = _run_node(script)
        waiting = result["waiting"]
        completed = result["completed"]

        self.assertTrue(waiting["visible"])
        self.assertTrue(waiting["parentWaiting"])
        self.assertEqual(waiting["parentStatus"], "waiting")
        self.assertEqual(
            [item["title"] for item in waiting["specialists"]],
            ["Literature review", "Protein model"],
        )
        self.assertEqual(
            [item["status"] for item in waiting["specialists"]],
            ["waiting", "running"],
        )
        self.assertFalse(completed["parentWaiting"])
        self.assertEqual(completed["parentStatus"], "completed")
        self.assertEqual(
            [item["status"] for item in completed["specialists"]],
            ["completed", "error"],
        )
        self.assertEqual(completed["summary"], "1 completed · 1 error")
        self.assertEqual(result["names"], [True, True, False])

    def test_message_surface_integrates_real_specialist_lane(self) -> None:
        messages = (TEMPLATES / "portal_messages.js").read_text()
        css = (TEMPLATES / "portal.css").read_text()

        self.assertIn("renderSpecialistLane", messages)
        self.assertIn("Array.from(toolCards.values())", messages)
        self.assertIn("isSpecialistToolName(name)", messages)
        self.assertIn("data-testid", (TEMPLATES / "portal_specialists.js").read_text())
        self.assertIn(".specialist-lane", css)
        self.assertIn(".specialist-card.completed", css)
        self.assertIn(".specialist-card.waiting", css)
        self.assertIn(".specialist-card.error", css)


if __name__ == "__main__":
    unittest.main()
