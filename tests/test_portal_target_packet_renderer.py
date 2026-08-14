from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

_PRIVATE_PROMPT_RE = re.compile(
    r"(?:context_file|registry_file|agi_path|/Users|/home|/tmp|/private/tmp|/var/folders|/opt/homebrew|/usr/local|/Applications|/Volumes|~)"
)


class PortalTargetPacketRendererTests(unittest.TestCase):
    def test_target_packet_chat_result_requires_server_presentation(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for frontend module tests")
        renderers_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_result_renderers.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const renderers = await import({renderers_url!r});
            const targetOperation = 'research.build_target_packet';
            const envelope = {{
              headline: 'research.build_target_packet: evidence_present · scoped_answer_only',
              finding_state: 'evidence_present',
              answer_readiness: 'scoped_answer_only',
              guidance: ['evidence_present:answer_only_within_consulted_scope']
            }};
            const targetPacket = {{
              purpose: 'Target-centric evidence report for an agent that has already inferred the user\\'s intent.',
              target: {{ target_type: 'topic', target_id: 'topic:rs429358', topic: 'rs429358' }},
              stored_research: {{ count: 0, records: [] }},
              source_catalog: {{
                summary: {{ source_count: 2 }},
                sources: [
                  {{
                    source_id: 'hpo',
                    title: 'Human Phenotype Ontology',
                    adapter_status: 'implemented_local_normalization',
                    best_for: 'Normalizing phenotype terms and HPO identifiers before disease or gene prioritization.'
                  }},
                  {{
                    source_id: 'gwas_catalog',
                    title: 'GWAS Catalog',
                    evidence_types: ['trait_association', 'variant_association']
                  }}
                ]
              }},
              available_operations: [
                {{
                  name: 'query stored reviewed research',
                  tool: 'research.query',
                  params: {{ db: '/Users/matthewzmd/.genomi/shared-evidence.sqlite', target_type: 'topic', topic: 'rs429358' }},
                  relevance: 'stored reviewed evidence for this target'
                }}
              ],
              evidence_options: [
                {{ component: 'source_scope_selection', state: 'available', inputs: ['target', 'source_catalog'] }},
                {{ component: 'stored_research', state: 'absent', available_operation: 'research.record' }}
              ],
              evidence_envelope: envelope
            }};
            const pgxLikePayload = {{
              query: {{ drug: 'clopidogrel' }},
              target: {{ target_type: 'drug', drug: 'clopidogrel' }},
              medication_review_matrix: {{ rows: [{{ drug: 'clopidogrel', gene: 'CYP2C19' }}] }},
              sample_evidence: {{ star_allele_call_count: 1 }},
              source_catalog: {{ summary: {{ source_count: 1 }}, sources: [] }},
              evidence_envelope: envelope
            }};
            const rawRecord = {{
              call: {{ id: 'call_target_packet', name: targetOperation }},
              result: {{ id: 'result_target_packet', payload: targetPacket }}
            }};
            const serverRecord = {{
              call: {{ id: 'call_target_packet', name: targetOperation }},
              result: {{
                id: 'result_target_packet',
                payload: targetPacket,
                portal_presentation: {{
                  schema: 'genomi_portal_result_presentation',
                  source: 'server',
                  operation: 'research.build_target_packet',
                  kind: 'target_packet',
                  kicker: 'Target evidence report',
                  title: 'rs429358',
                  summary: 'Server-owned target evidence report',
                  evidenceEnvelope: envelope,
                  metrics: [{{ label: 'Sources', value: 2 }}, {{ label: 'Stored findings', value: 0 }}],
                  lanes: [
                    {{
                      title: 'Target',
                      nodes: [{{
                        label: 'rs429358',
                        summary: 'topic',
                        context: 'Target / rs429358: topic',
                        value: {{ target_type: 'topic', topic: 'rs429358' }}
                      }}]
                    }},
                    {{
                      title: 'Source catalog',
                      nodes: [{{
                        label: 'hpo · Human Phenotype Ontology',
                        summary: 'implemented local normalization',
                        context: 'Source catalog / hpo: Human Phenotype Ontology',
                        value: {{ source_id: 'hpo', title: 'Human Phenotype Ontology' }}
                      }}]
                    }}
                  ]
                }}
              }}
            }};
            const result = {{
              rawView: renderers.genomiResultViewModel(rawRecord),
              rawContext: renderers.genomiResultContextPayload(rawRecord),
              view: renderers.genomiResultViewModel(serverRecord),
              context: renderers.genomiResultContextPayload(serverRecord),
              rejected: renderers.genomiResultViewModel({{
                call: {{ name: targetOperation }},
                result: {{ payload: pgxLikePayload }}
              }})
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        completed = subprocess.run(
            ["node", "--input-type=module"],
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)

        self.assertIsNone(result["rawView"])
        self.assertIsNone(result["rawContext"])
        self.assertEqual(result["view"]["kind"], "target_packet")
        self.assertEqual(result["view"]["title"], "rs429358")
        self.assertEqual(result["view"]["metrics"][0], {"label": "Sources", "value": 2})
        self.assertIn("Target", [lane["title"] for lane in result["view"]["lanes"]])
        self.assertIn("Source catalog", [lane["title"] for lane in result["view"]["lanes"]])
        self.assertNotIn("Available operations", [lane["title"] for lane in result["view"]["lanes"]])
        self.assertNotIn("Evidence options", [lane["title"] for lane in result["view"]["lanes"]])
        self.assertIn("Selected Target evidence report", result["context"]["prompt_text"])
        self.assertIn("hpo", result["context"]["prompt_text"])
        self.assertEqual(result["context"]["tool_call_id"], "call_target_packet")
        self.assertEqual(result["context"]["tool_result_id"], "result_target_packet")
        self.assertIsNone(result["rejected"])
        _assert_public_payload(result["context"])


def _assert_public_payload(value) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _assert_public_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_public_payload(child)
    elif isinstance(value, str) and _PRIVATE_PROMPT_RE.search(value):
        raise AssertionError(f"private prompt text leaked: {value}")


if __name__ == "__main__":
    unittest.main()
