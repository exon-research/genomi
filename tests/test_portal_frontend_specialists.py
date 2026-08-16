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
    def test_redacted_native_progress_updates_spawned_lane_without_reviving_terminal_state(self) -> None:
        module_url = (TEMPLATES / "portal_specialists.js").as_uri()
        script = textwrap.dedent(
            f"""
            const specialists = await import({module_url!r});
            const records = [
              {{
                call: {{ id: 'spawn-1', name: 'spawn_agent', input: {{
                  agent_id: '/root/reviewer', task_name: '/root/reviewer',
                  assignment_id: 'assignment-1', specialist_role: 'Public evidence reviewer'
                }} }}
              }},
              {{
                call: {{ id: 'transition-1', name: 'genomi.genomi.invoke', input: {{ tool: 'lab.transition_specialist_assignment' }} }},
                result: {{ id: 'transition-1', payload: {{
                  dispatched_tool: 'lab.transition_specialist_assignment',
                  assignment: {{
                    specialist_assignment_id: 'assignment-1', native_agent_id: '/root/reviewer',
                    specialist_role: 'Public evidence reviewer', execution_policy: 'public_literature',
                    revision: 2, state: 'spawned'
                  }}
                }} }}
              }},
              {{
                result: {{ id: 'specialist-progress:search-1', name: 'specialist_progress', payload: {{
                  updates: [{{
                    agent_id: '/root/reviewer', assignment_id: 'assignment-1', status: 'running',
                    message: 'Searching public biomedical literature'
                  }}]
                }} }}
              }}
            ];
            const running = specialists.specialistLaneModel(records);
            records[1].result.payload.assignment.state = 'completed';
            records[1].result.payload.assignment.revision = 3;
            const completed = specialists.specialistLaneModel(records);
            process.stdout.write(JSON.stringify({{ running, completed }}));
            """
        )

        result = _run_node(script)
        self.assertEqual(len(result["running"]["specialists"]), 1)
        self.assertEqual(result["running"]["specialists"][0]["status"], "running")
        self.assertEqual(
            result["running"]["specialists"][0]["summary"],
            "Searching public biomedical literature",
        )
        self.assertEqual(result["completed"]["specialists"][0]["status"], "completed")

    def test_terminal_host_turn_never_leaves_spawned_assignment_running(self) -> None:
        module_url = (TEMPLATES / "portal_specialists.js").as_uri()
        script = textwrap.dedent(
            f"""
            const specialists = await import({module_url!r});
            const assignment = {{
              call: {{
                id: 'transition-1',
                name: 'genomi.genomi.invoke',
                input: {{ tool: 'lab.transition_specialist_assignment' }}
              }},
              result: {{
                id: 'transition-1',
                payload: {{
                  dispatched_tool: 'lab.transition_specialist_assignment',
                  assignment: {{
                    specialist_assignment_id: 'assignment-1',
                    native_agent_id: 'specialist-1',
                    specialist_role: 'Public evidence reviewer',
                    execution_policy: 'public_literature',
                    revision: 2,
                    state: 'spawned'
                  }}
                }}
              }}
            }};
            const live = specialists.specialistLaneModel([assignment]);
            assignment.runTerminalStatus = 'succeeded';
            const terminal = specialists.specialistLaneModel([assignment]);
            assignment.result.payload.assignment.state = 'completed';
            assignment.result.payload.assignment.revision = 3;
            const completed = specialists.specialistLaneModel([assignment]);
            process.stdout.write(JSON.stringify({{ live, terminal, completed }}));
            """
        )

        result = _run_node(script)
        self.assertEqual(result["live"]["specialists"][0]["status"], "running")
        self.assertEqual(
            result["live"]["specialists"][0]["summary"],
            "Reviewing public biomedical literature",
        )
        self.assertEqual(result["terminal"]["specialists"][0]["status"], "error")
        self.assertEqual(
            result["terminal"]["specialists"][0]["summary"],
            "This research workstream stopped before findings were saved.",
        )
        self.assertEqual(result["completed"]["specialists"][0]["status"], "completed")

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
                {{ agent_id: 'agent-lit', task_name: '/root/literature_review', status: 'completed', message: 'Literature findings ready.' }},
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
        self.assertEqual(
            completed["specialists"][0]["summary"],
            "Literature findings ready.",
        )
        self.assertEqual(
            completed["summary"], "1 findings added · 1 needs attention"
        )
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

    def test_native_and_durable_assignment_share_one_safe_identity(self) -> None:
        module_url = (TEMPLATES / "portal_specialists.js").as_uri()
        script = textwrap.dedent(
            f"""
            const specialists = await import({module_url!r});
            const records = [
              {{
                call: {{
                  id: 'spawn-1',
                  name: 'spawn_agent',
                  input: {{
                    agent_id: '/root/literature_reviewer',
                    task_name: '/root/literature_reviewer',
                    assignment_id: 'assignment-1',
                    execution_policy: 'public_literature',
                    specialist_role: 'Public-literature clinical immunology reviewer'
                  }}
                }},
                result: {{
                  id: 'spawn-1',
                  payload: {{
                    updates: [{{
                      agent_id: '/root/literature_reviewer',
                      assignment_id: 'assignment-1',
                      status: 'completed',
                      message: 'Bounded literature synthesis.'
                    }}]
                  }}
                }}
              }},
              {{
                call: {{
                  id: 'transition-1',
                  name: 'genomi.genomi.invoke',
                  input: {{ tool: 'lab.transition_specialist_assignment' }}
                }},
                result: {{
                  id: 'transition-1',
                  payload: {{
                    dispatched_tool: 'lab.transition_specialist_assignment',
                    assignment: {{
                      specialist_assignment_id: 'assignment-1',
                      native_agent_id: '[omitted_local_path]',
                      specialist_role: 'Public-literature clinical immunology reviewer',
                      execution_policy: 'public_literature',
                      revision: 3,
                      state: 'completed'
                    }},
                    specialist_analysis: {{
                      general_analysis: 'Bounded literature synthesis.'
                    }}
                  }}
                }}
              }}
            ];
            process.stdout.write(JSON.stringify(specialists.specialistLaneModel(records)));
            """
        )

        result = _run_node(script)
        self.assertEqual(len(result["specialists"]), 1)
        self.assertEqual(
            result["specialists"][0]["title"],
            "Public literature clinical immunology reviewer",
        )
        self.assertEqual(result["specialists"][0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
