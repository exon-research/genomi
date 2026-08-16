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


class PortalToolCatalogFrontendTest(unittest.TestCase):
    def test_source_lookup_model_owns_user_facing_catalog_copy(self) -> None:
        catalog_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_catalog.js").as_uri()
        script = textwrap.dedent(
            f"""
            const catalog = await import({catalog_url!r});
            const tool = {{
              name: 'genomi.parse_source',
              description: 'Raw operation description that should not drive the UI',
              sourceLookup: {{
                name: 'genomi.parse_source',
                operationId: 'genomi.parse_source',
                displayLabel: 'Add a genome',
                area: 'genomi',
                description: 'Use a local genome file for approved evidence work.',
                badges: ['Privacy: Local private', 'Updates workspace', '1 required input'],
                request: {{
                  requiredInputs: ['source'],
                  fields: [
                    {{
                      name: 'source',
                      label: 'Genome source',
                      required: true,
                      type: 'string',
                      summary: 'Choose the local genome source for this session.',
                      placeholder: '/path/to/source.vcf'
                    }},
                    {{
                      name: 'genome_build',
                      label: 'Genome build',
                      type: 'string',
                      enumValues: ['GRCh37', 'GRCh38'],
                      defaultValue: 'GRCh38',
                      defaultHint: 'GRCh38',
                      summary: 'Use when the build is known.'
                    }}
                  ]
                }},
                sections: [
                  {{
                    title: 'Inputs',
                    nodes: [
                      {{ label: 'Genome source', value: 'Choose the local genome source for this session.' }}
                    ]
                  }},
                  {{
                    title: 'Boundary',
                    nodes: [
                      {{ label: 'Privacy scope', value: 'Local private' }}
                    ]
                  }}
                ],
                technicalSections: [
                  {{
                    title: 'Operation',
                    nodes: [
                      {{ label: 'Operation ID', value: 'genomi.parse_source' }}
                    ]
                  }}
                ]
              }}
            }};
            const result = {{
              builder: catalog.toolRequestBuilderModel(tool),
              inspector: catalog.toolInspectorModel(tool),
              visible: catalog.visibleTools([tool]).map((item) => item.name),
              legacyExports: {{
                toolRequestPrompt: typeof catalog.toolRequestPrompt,
                toolRequestPayload: typeof catalog.toolRequestPayload,
                toolIntentPayload: typeof catalog.toolIntentPayload,
                toolPrompt: typeof catalog.toolPrompt
              }}
            }};
            process.stdout.write(JSON.stringify(result));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["builder"]["displayLabel"], "Add a genome")
        self.assertEqual(result["builder"]["fields"][0]["label"], "Genome source")
        self.assertEqual(result["builder"]["fields"][1]["enumValues"], ["GRCh37", "GRCh38"])
        self.assertEqual(result["inspector"]["displayLabel"], "Add a genome")
        self.assertEqual(result["inspector"]["area"], "Genomi")
        self.assertEqual(result["inspector"]["sections"][0]["title"], "Inputs")
        self.assertEqual(result["inspector"]["technicalSections"][0]["title"], "Operation")
        self.assertEqual(result["visible"], ["genomi.parse_source"])
        self.assertEqual(
            result["legacyExports"],
            {
                "toolRequestPrompt": "undefined",
                "toolRequestPayload": "undefined",
                "toolIntentPayload": "undefined",
                "toolPrompt": "undefined",
            },
        )
        _assert_public_payload(result)

    def test_tool_request_builder_models_fields_and_missing_inputs(self) -> None:
        catalog_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_catalog.js").as_uri()
        model_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_request_model.js").as_uri()
        script = textwrap.dedent(
            f"""
            const catalog = await import({catalog_url!r});
            const requestModel = await import({model_url!r});
            const tool = sourceLookupTool('variant.resolve', {{
              displayLabel: 'Variant evidence lookup',
              area: 'variant',
              description: 'Resolve a variant.',
              badges: ['Metadata only', '1 required input'],
              request: {{
                requiredInputs: ['rsid'],
                fields: [
                  {{ name: 'rsid', label: 'rsID', required: true, type: 'string', summary: 'dbSNP identifier' }},
                  {{ name: 'genome_build', label: 'Genome build', type: 'string', enumValues: ['GRCh37', 'GRCh38'], defaultValue: 'GRCh38', defaultHint: 'GRCh38', summary: 'Use when known.' }},
                  {{ name: 'limit', label: 'Limit', type: 'integer', defaultValue: 5, defaultHint: '5', summary: 'Maximum records.' }},
                  {{ name: 'include_active_genome_index', label: 'Use approved genome context', type: 'boolean', defaultValue: false, defaultHint: 'false', summary: 'Use approved genome context only when available.' }}
                ]
              }},
              sections: [
                {{ title: 'Required inputs', nodes: [{{ label: 'rsID', value: 'dbSNP identifier' }}] }},
                {{ title: 'Boundary', nodes: [{{ label: 'Privacy scope', value: 'Metadata only' }}] }}
              ],
              technicalSections: [
                {{ title: 'Operation', nodes: [{{ label: 'Operation ID', value: 'variant.resolve' }}] }},
                {{ title: 'Output shape', nodes: [
                  {{ label: 'variant_resolution', value: 'tool output' }},
                  {{ label: 'evidence_envelope', value: 'tool output' }}
                ] }}
              ]
            }});
            tool.description = 'Resolve a variant using optional context_file=/Users/matthewzmd/.genomi/private.json';
            const packetTool = sourceLookupTool('research.build_target_packet', {{
              displayLabel: 'Target evidence report',
              area: 'research',
              description: 'Build a target evidence report.',
              request: {{
                requiredInputs: ['target_type'],
                fields: [
                  {{ name: 'target_type', label: 'Target type', required: true, type: 'string', enumValues: ['gene', 'topic', 'variant'], summary: 'Choose the target kind.' }},
                  {{ name: 'gene', label: 'Gene', type: 'string', summary: 'Gene symbol.', visibleWhen: {{ parameter: 'target_type', equals: 'gene' }}, requiredWhen: {{ parameter: 'target_type', equals: 'gene' }} }},
                  {{ name: 'topic', label: 'Topic', type: 'string', summary: 'Research topic.', visibleWhen: {{ parameter: 'target_type', equals: 'topic' }}, requiredWhen: {{ parameter: 'target_type', equals: 'topic' }} }},
                  {{ name: 'chrom', label: 'Chromosome', type: 'string', summary: 'Variant chromosome.', visibleWhen: {{ parameter: 'target_type', equals: 'variant' }}, requiredWhen: {{ parameter: 'target_type', equals: 'variant' }} }}
                ],
                ui: {{
                  guidedControls: [
                    {{
                      kind: 'segmented',
                      parameter: 'target_type',
                      label: 'Review target',
                      hideField: true,
                      options: [
                        {{ value: 'condition', label: 'Condition' }},
                        {{ value: 'drug', label: 'Medication' }},
                        {{ value: 'gene', label: 'Gene' }},
                        {{ value: 'topic', label: 'Topic' }},
                        {{ value: 'variant', label: 'Variant' }}
                      ]
                    }}
                  ],
                  fieldGroups: [
                    {{
                      id: 'source_limits',
                      label: 'Source limits',
                      className: 'tool-request-source-limits',
                      bodyClassName: 'tool-request-source-limits-body',
                      collapsed: true,
                      parameters: ['genome_build', 'limit']
                    }}
                  ]
                }}
              }},
              technicalSections: [
                {{ title: 'Operation', nodes: [{{ label: 'Operation ID', value: 'research.build_target_packet' }}] }}
              ]
            }});
            const wideTool = sourceLookupTool('custom.wide', {{
              displayLabel: 'Wide evidence source',
              area: 'custom',
              request: {{
                requiredInputs: ['p01'],
                fields: Array.from({{ length: 14 }}, (_item, index) => ({{
                  name: 'p' + String(index + 1).padStart(2, '0'),
                  label: 'P' + String(index + 1).padStart(2, '0'),
                  type: 'string',
                  required: index === 0,
                  summary: 'Input ' + String(index + 1)
                }}))
              }}
            }});
            const result = {{
              builder: catalog.toolRequestBuilderModel(tool),
              packetBuilder: catalog.toolRequestBuilderModel(packetTool),
              wideBuilder: catalog.toolRequestBuilderModel(wideTool),
              cleanParams: requestModel.cleanRequestParams({{ rsid: 'rs429358', genome_build: 'GRCh38', blank: '', missing: undefined }}),
              missingInputs: requestModel.missingRequiredInputs(catalog.toolRequestBuilderModel(tool), {{ genome_build: 'GRCh38' }}),
              geneMissingInputs: requestModel.missingRequiredInputs(catalog.toolRequestBuilderModel(packetTool), {{ target_type: 'gene' }}),
              topicMissingInputs: requestModel.missingRequiredInputs(catalog.toolRequestBuilderModel(packetTool), {{ target_type: 'topic', topic: 'rs429358' }}),
              geneFieldState: requestModel.toolRequestFieldState(
                catalog.toolRequestBuilderModel(packetTool),
                catalog.toolRequestBuilderModel(packetTool).fields.find((field) => field.name === 'gene'),
                {{ target_type: 'gene' }}
              ),
              topicFieldStateForGene: requestModel.toolRequestFieldState(
                catalog.toolRequestBuilderModel(packetTool),
                catalog.toolRequestBuilderModel(packetTool).fields.find((field) => field.name === 'topic'),
                {{ target_type: 'gene' }}
              ),
              inspector: catalog.toolInspectorModel(tool),
              visibleToolNames: catalog.visibleTools([
                {{ name: 'genomi.invoke' }},
                {{ name: 'genomi.describe_portal_workspace' }},
                sourceLookupTool('genomi.search_indexes'),
                sourceLookupTool('genomi.check_libraries'),
                sourceLookupTool('genomi.parse_source'),
                {{ name: 'journal.append' }}
              ]).map((item) => item.name)
            }};
            process.stdout.write(JSON.stringify(result));

            function sourceLookupTool(name, overrides = {{}}) {{
              return {{
                name,
                sourceLookup: Object.assign({{
                  name,
                  operationId: name,
                  displayLabel: overrides.displayLabel || name,
                  area: overrides.area || 'workspace',
                  description: overrides.description || '',
                  badges: overrides.badges || [],
                  request: overrides.request || {{ requiredInputs: [], fields: [] }},
                  sections: overrides.sections || [],
                  technicalSections: overrides.technicalSections || []
                }}, overrides)
              }};
            }}
            """
        )

        result = _run_node_json(self, script)

        self.assertTrue(result["builder"]["hasFields"])
        self.assertEqual(result["builder"]["displayLabel"], "Variant evidence lookup")
        self.assertEqual(result["builder"]["fields"][0]["name"], "rsid")
        self.assertTrue(result["builder"]["fields"][0]["required"])
        self.assertIn("genome_build", [field["name"] for field in result["builder"]["fields"]])
        self.assertEqual(len(result["wideBuilder"]["fields"]), 14)
        self.assertEqual(result["wideBuilder"]["fields"][-1]["name"], "p14")
        self.assertEqual(
            next(field for field in result["packetBuilder"]["fields"] if field["name"] == "gene")["visibleWhen"],
            {"parameter": "target_type", "equals": "gene"},
        )
        self.assertEqual(
            next(field for field in result["packetBuilder"]["fields"] if field["name"] == "chrom")["requiredWhen"],
            {"parameter": "target_type", "equals": "variant"},
        )
        self.assertEqual(
            result["packetBuilder"]["ui"]["guidedControls"][0]["options"],
            [
                {"value": "condition", "label": "Condition"},
                {"value": "drug", "label": "Medication"},
                {"value": "gene", "label": "Gene"},
                {"value": "topic", "label": "Topic"},
                {"value": "variant", "label": "Variant"},
            ],
        )
        self.assertEqual(result["packetBuilder"]["ui"]["fieldGroups"][0]["parameters"], ["genome_build", "limit"])
        self.assertEqual(result["cleanParams"], {"rsid": "rs429358", "genome_build": "GRCh38"})
        self.assertEqual(result["missingInputs"], ["rsid"])
        self.assertEqual(result["geneMissingInputs"], ["gene"])
        self.assertEqual(result["topicMissingInputs"], [])
        self.assertEqual(result["geneFieldState"], {"visible": True, "required": True})
        self.assertEqual(result["topicFieldStateForGene"], {"visible": False, "required": False})
        self.assertEqual(result["inspector"]["operationId"], "variant.resolve")
        self.assertEqual(result["inspector"]["displayLabel"], "Variant evidence lookup")
        self.assertEqual(result["inspector"]["name"], "variant.resolve")
        self.assertIn("Required inputs", [section["title"] for section in result["inspector"]["sections"]])
        self.assertIn("Boundary", [section["title"] for section in result["inspector"]["sections"]])
        self.assertNotIn("Operation", [section["title"] for section in result["inspector"]["sections"]])
        self.assertIn(
            {"label": "Operation ID", "value": "variant.resolve"},
            next(section for section in result["inspector"]["technicalSections"] if section["title"] == "Operation")["nodes"],
        )
        self.assertIn("Output shape", [section["title"] for section in result["inspector"]["technicalSections"]])
        self.assertEqual(
            result["visibleToolNames"],
            ["genomi.search_indexes", "genomi.check_libraries", "genomi.parse_source"],
        )
        _assert_public_payload(result)

    def test_rendered_request_builder_omits_untouched_defaults_and_uses_condition_contract(self) -> None:
        catalog_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_catalog.js").as_uri()
        builder_url = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal_tool_request_builder.js").as_uri()
        script = textwrap.dedent(
            f"""
            const catalog = await import({catalog_url!r});
            const builder = await import({builder_url!r});
            installDom();
            const tool = sourceLookupTool('variant.resolve', {{
              displayLabel: 'Variant lookup',
              area: 'variant',
              description: 'Resolve a variant.',
              request: {{
                requiredInputs: ['rsid'],
                fields: [
                  {{ name: 'rsid', label: 'rsID', required: true, type: 'string', summary: 'dbSNP identifier' }},
                  {{ name: 'genome_build', label: 'Genome build', type: 'string', enumValues: ['GRCh37', 'GRCh38'], defaultValue: 'GRCh38', defaultHint: 'GRCh38', summary: 'Use when known.' }},
                  {{ name: 'limit', label: 'Limit', type: 'integer', defaultValue: 5, defaultHint: '5', summary: 'Maximum records.' }},
                  {{ name: 'include_active_genome_index', label: 'Use approved genome context', type: 'boolean', defaultValue: false, defaultHint: 'false', summary: 'Use approved genome context only when available.' }}
                ]
              }}
            }});
            const packetTool = sourceLookupTool('research.build_target_packet', {{
              displayLabel: 'Target evidence report',
              area: 'research',
              description: 'Build a target evidence report.',
              request: {{
                requiredInputs: ['target_type'],
                fields: [
                  {{ name: 'target_type', label: 'Target type', required: true, type: 'string', enumValues: ['gene', 'topic', 'variant'], summary: 'Choose the target kind.' }},
                  {{ name: 'gene', label: 'Gene', type: 'string', summary: 'Gene symbol.', visibleWhen: {{ parameter: 'target_type', equals: 'gene' }}, requiredWhen: {{ parameter: 'target_type', equals: 'gene' }} }},
                  {{ name: 'topic', label: 'Topic', type: 'string', summary: 'Research topic.', visibleWhen: {{ parameter: 'target_type', equals: 'topic' }}, requiredWhen: {{ parameter: 'target_type', equals: 'topic' }} }},
                  {{ name: 'chrom', label: 'Chromosome', type: 'string', summary: 'Variant chromosome.', visibleWhen: {{ parameter: 'target_type', equals: 'variant' }}, requiredWhen: {{ parameter: 'target_type', equals: 'variant' }} }},
                  {{ name: 'genome_build', label: 'Genome build', type: 'string', enumValues: ['GRCh37', 'GRCh38'], defaultValue: 'GRCh38', defaultHint: 'GRCh38', summary: 'Use when known.' }},
                  {{ name: 'limit', label: 'Limit', type: 'integer', defaultValue: 20, defaultHint: '20', summary: 'Maximum records.' }}
                ],
                ui: {{
                  guidedControls: [
                    {{
                      kind: 'segmented',
                      parameter: 'target_type',
                      label: 'Review target',
                      hideField: true,
                      options: [
                        {{ value: 'condition', label: 'Condition' }},
                        {{ value: 'drug', label: 'Medication' }},
                        {{ value: 'gene', label: 'Gene' }},
                        {{ value: 'topic', label: 'Topic' }},
                        {{ value: 'variant', label: 'Variant' }}
                      ]
                    }}
                  ],
                  fieldGroups: [
                    {{
                      id: 'source_limits',
                      label: 'Source limits',
                      className: 'tool-request-source-limits',
                      bodyClassName: 'tool-request-source-limits-body',
                      collapsed: true,
                      parameters: ['genome_build', 'limit']
                    }}
                  ]
                }}
              }}
            }});
            let attached = null;
            let asked = null;
            const section = builder.renderToolRequestBuilder(tool, {{
              onAttachRequest: (_tool, params) => {{ attached = {{ tool: _tool.name, params }}; }},
              onAskRequest: (_tool, params) => {{ asked = {{ tool: _tool.name, params }}; }}
            }});
            let prefilledAttached = null;
            const prefilledSection = builder.renderToolRequestBuilder(tool, {{
              initialParams: {{ rsid: 'rs429358', include_active_genome_index: true }},
              onAttachRequest: (_tool, params) => {{ prefilledAttached = {{ tool: _tool.name, params }}; }}
            }});
            const prefilledRsid = prefilledSection.querySelector('[data-tool-param="rsid"]');
            const prefilledAgi = prefilledSection.querySelector('[data-tool-param="include_active_genome_index"]');
            prefilledSection.querySelectorAll('button').find((button) => button.textContent === 'Include source').click();
            const genomeBuild = section.querySelector('[data-tool-param="genome_build"]');
            const limit = section.querySelector('[data-tool-param="limit"]');
            const includeAgi = section.querySelector('[data-tool-param="include_active_genome_index"]');
            const rsid = section.querySelector('[data-tool-param="rsid"]');
            rsid.value = 'rs429358';
            rsid.dispatchEvent({{ type: 'input' }});
            const builderActionLabels = section.querySelectorAll('button').map((button) => button.textContent);
            section.querySelectorAll('button').find((button) => button.textContent === 'Include source').click();
            const attachedRequest = attached;
            section.querySelectorAll('button').find((button) => button.textContent === 'Ask now').click();
            const rsidAsk = asked;

            let packetAsked = null;
            const packetSection = builder.renderToolRequestBuilder(packetTool, {{
              onAskRequest: (_tool, params) => {{ packetAsked = {{ tool: _tool.name, params }}; }}
            }});
            const targetType = packetSection.querySelector('[data-tool-param="target_type"]');
            const targetTypeRow = targetType.closest('.tool-request-field');
            const guidedTarget = packetSection.querySelector('.tool-request-guided');
            const guidedTargetLabels = packetSection.querySelectorAll('.target-type-chip').map((button) => button.textContent);
            const guidedTargetHidden = guidedTarget.hidden;
            const sourceLimitGroup = packetSection.querySelector('.tool-request-source-limits');
            const sourceLimitFieldNames = sourceLimitGroup
              .querySelectorAll('[data-tool-param]')
              .map((node) => node.getAttribute('data-tool-param'));
            const geneField = packetSection.querySelector('[data-tool-param="gene"]').closest('.tool-request-field');
            const topicField = packetSection.querySelector('[data-tool-param="topic"]').closest('.tool-request-field');
            const chromField = packetSection.querySelector('[data-tool-param="chrom"]').closest('.tool-request-field');
            const initialVisibility = {{ gene: geneField.hidden, topic: topicField.hidden, chrom: chromField.hidden }};
            packetSection.querySelectorAll('.target-type-chip').find((button) => button.textContent === 'Gene').click();
            const geneVisibility = {{ gene: geneField.hidden, topic: topicField.hidden, chrom: chromField.hidden }};
            const geneActiveTarget = packetSection.querySelectorAll('.target-type-chip.active').map((button) => button.textContent);
            packetSection.querySelectorAll('.target-type-chip').find((button) => button.textContent === 'Topic').click();
            const topicActiveTarget = packetSection.querySelectorAll('.target-type-chip.active').map((button) => button.textContent);
            const topic = packetSection.querySelector('[data-tool-param="topic"]');
            topic.value = 'rs429358';
            topic.dispatchEvent({{ type: 'input' }});
            packetSection.querySelectorAll('button').find((button) => button.textContent === 'Ask now').click();
            const topicAsk = packetAsked;
            const inspectorContainer = document.createElement('div');
            catalog.renderToolInspector(inspectorContainer, packetTool);
            const inspectorSectionTitles = inspectorContainer
              .querySelectorAll('.tool-inspector-section-title')
              .map((node) => node.textContent);
            const inspectorHasBuilder = Boolean(inspectorContainer.querySelector('.tool-request-builder'));
            const inspectorActionLabels = inspectorContainer
              .querySelectorAll('.tool-inspector-actions button')
              .map((node) => node.textContent);
            const packetConditionAttributeCount =
              packetSection.querySelectorAll('[data-tool-visible-when]').length +
              packetSection.querySelectorAll('[data-tool-required-when]').length;
            const packetFieldIdRows = packetSection
              .querySelectorAll('[data-tool-field-id]')
              .filter((node) => node.classList.contains('tool-request-field'))
              .length;

            process.stdout.write(JSON.stringify({{
              defaultValues: {{
                genomeBuild: genomeBuild.value,
                limit: limit.value,
                includeAgiChecked: includeAgi.checked,
                includeAgiIndeterminate: includeAgi.indeterminate,
                genomeBuildHint: genomeBuild.querySelector('option').textContent,
                limitPlaceholder: limit.placeholder
              }},
              prefilled: {{
                rsid: prefilledRsid.value,
                includeAgiChecked: prefilledAgi.checked,
                includeAgiIndeterminate: prefilledAgi.indeterminate,
                attached: prefilledAttached
              }},
              builderActionLabels,
              attachedRequest,
              rsidAsk,
              guidedTargetLabels,
              guidedTargetHidden,
              sourceLimitOpen: sourceLimitGroup.getAttribute('open'),
              sourceLimitFieldNames,
              targetTypeRowClass: targetTypeRow.className,
              geneActiveTarget,
              topicActiveTarget,
              initialVisibility,
              geneVisibility,
              topicAsk,
              inspectorSectionTitles,
              inspectorHasBuilder,
              inspectorActionLabels,
              packetConditionAttributeCount,
              packetFieldIdRows
            }}));

            function installDom() {{
              class ClassList {{
                constructor(element) {{ this.element = element; }}
                contains(name) {{ return String(this.element.className || '').split(/\\s+/).includes(name); }}
              }}
              class Element {{
                constructor(tagName) {{
                  this.tagName = String(tagName || '').toLowerCase();
                  this.children = [];
                  this.parentNode = null;
                  this.attributes = {{}};
                  this.dataset = {{}};
                  this.eventListeners = {{}};
                  this.className = '';
                  this.textContent = '';
                  this.hidden = false;
                  this.value = '';
                  this.checked = false;
                  this.indeterminate = false;
                  this.placeholder = '';
                  this.classList = new ClassList(this);
                }}
                appendChild(child) {{
                  child.parentNode = this;
                  this.children.push(child);
                  return child;
                }}
                setAttribute(name, value) {{
                  const text = String(value);
                  this.attributes[name] = text;
                  if (name === 'class') this.className = text;
                  if (name.startsWith('data-')) this.dataset[dataKey(name.slice(5))] = text;
                }}
                getAttribute(name) {{
                  if (name === 'class') return this.className;
                  return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
                }}
                addEventListener(type, handler) {{
                  this.eventListeners[type] = this.eventListeners[type] || [];
                  this.eventListeners[type].push(handler);
                }}
                dispatchEvent(event) {{
                  (this.eventListeners[event.type] || []).forEach((handler) => handler(event));
                }}
                click() {{
                  this.dispatchEvent({{ type: 'click', preventDefault() {{}}, stopPropagation() {{}} }});
                }}
                closest(selector) {{
                  let node = this;
                  while (node) {{
                    if (matches(node, selector)) return node;
                    node = node.parentNode;
                  }}
                  return null;
                }}
                querySelector(selector) {{ return this.querySelectorAll(selector)[0] || null; }}
                querySelectorAll(selector) {{ return querySelectorAll(this, selector); }}
                set innerHTML(value) {{
                  this.children = [];
                  this.textContent = '';
                  parseHtml(String(value || ''), this);
                }}
                get innerHTML() {{ return ''; }}
              }}
              function dataKey(name) {{
                return name.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
              }}
              function descendants(node) {{
                const found = [];
                node.children.forEach((child) => {{
                  found.push(child);
                  found.push(...descendants(child));
                }});
                return found;
              }}
              function querySelectorAll(root, selector) {{
                const parts = String(selector || '').trim().split(/\\s+/).filter(Boolean);
                let current = [root];
                parts.forEach((part) => {{
                  const next = [];
                  current.forEach((node) => {{
                    descendants(node).forEach((child) => {{
                      if (matches(child, part)) next.push(child);
                    }});
                  }});
                  current = next;
                }});
                return current;
              }}
              function matches(element, selector) {{
                const attr = String(selector || '').match(/^\\[([^=\\]]+)(?:="([^"]*)")?\\]$/);
                if (attr) {{
                  const value = element.getAttribute(attr[1]);
                  return attr[2] === undefined ? value !== null : value === attr[2];
                }}
                const pieces = String(selector || '').split('.');
                const tag = pieces[0];
                if (tag && tag !== element.tagName) return false;
                return pieces.slice(1).every((name) => element.classList.contains(name));
              }}
              function parseHtml(html, root) {{
                const tags = /<\\/?[^>]+>/g;
                const stack = [root];
                let match;
                while ((match = tags.exec(html))) {{
                  const token = match[0];
                  if (/^<\\//.test(token)) {{
                    if (stack.length > 1) stack.pop();
                    continue;
                  }}
                  const parsed = token.match(/^<([a-zA-Z0-9-]+)([^>]*)>/);
                  if (!parsed) continue;
                  const child = new Element(parsed[1]);
                  const attrs = parsed[2] || '';
                  const attrPattern = /([a-zA-Z0-9:-]+)(?:="([^"]*)")?/g;
                  let attr;
                  while ((attr = attrPattern.exec(attrs))) child.setAttribute(attr[1], attr[2] || '');
                  stack[stack.length - 1].appendChild(child);
                  if (!/\\/>$/.test(token) && !['br', 'hr', 'img', 'input', 'link', 'meta'].includes(child.tagName)) {{
                    stack.push(child);
                  }}
                }}
              }}
              globalThis.document = {{ createElement: (tagName) => new Element(tagName) }};
            }}
            function sourceLookupTool(name, overrides = {{}}) {{
              return {{
                name,
                sourceLookup: Object.assign({{
                  name,
                  operationId: name,
                  displayLabel: overrides.displayLabel || name,
                  area: overrides.area || 'workspace',
                  description: overrides.description || '',
                  badges: overrides.badges || [],
                  request: overrides.request || {{ requiredInputs: [], fields: [] }},
                  sections: overrides.sections || [],
                  technicalSections: overrides.technicalSections || []
                }}, overrides)
              }};
            }}
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["defaultValues"]["genomeBuild"], "")
        self.assertEqual(result["defaultValues"]["limit"], "")
        self.assertFalse(result["defaultValues"]["includeAgiChecked"])
        self.assertTrue(result["defaultValues"]["includeAgiIndeterminate"])
        self.assertIn("Use default (GRCh38)", result["defaultValues"]["genomeBuildHint"])
        self.assertEqual(result["defaultValues"]["limitPlaceholder"], "5")
        self.assertEqual(result["prefilled"]["rsid"], "rs429358")
        self.assertTrue(result["prefilled"]["includeAgiChecked"])
        self.assertFalse(result["prefilled"]["includeAgiIndeterminate"])
        self.assertEqual(
            result["prefilled"]["attached"],
            {
                "tool": "variant.resolve",
                "params": {"rsid": "rs429358", "include_active_genome_index": True},
            },
        )
        self.assertEqual(result["builderActionLabels"], ["Include source", "Ask now"])
        self.assertNotIn("Attach source", result["builderActionLabels"])
        self.assertNotIn("Draft question", result["builderActionLabels"])
        self.assertNotIn("Use in chat", result["builderActionLabels"])
        self.assertEqual(result["attachedRequest"], {"tool": "variant.resolve", "params": {"rsid": "rs429358"}})
        self.assertEqual(result["rsidAsk"]["params"], {"rsid": "rs429358"})
        self.assertEqual(result["rsidAsk"]["tool"], "variant.resolve")
        self.assertNotIn("GRCh38", json.dumps(result["rsidAsk"]["params"]))
        self.assertNotIn("limit", result["rsidAsk"]["params"])
        self.assertEqual(result["guidedTargetLabels"], ["Condition", "Medication", "Gene", "Topic", "Variant"])
        self.assertFalse(result["guidedTargetHidden"])
        self.assertIsNone(result["sourceLimitOpen"])
        self.assertEqual(result["sourceLimitFieldNames"], ["genome_build", "limit"])
        self.assertIn("tool-request-field-hidden-control", result["targetTypeRowClass"])
        self.assertEqual(result["initialVisibility"], {"gene": True, "topic": True, "chrom": True})
        self.assertEqual(result["geneVisibility"], {"gene": False, "topic": True, "chrom": True})
        self.assertEqual(result["geneActiveTarget"], ["Gene"])
        self.assertEqual(result["topicActiveTarget"], ["Topic"])
        self.assertEqual(result["topicAsk"]["params"], {"target_type": "topic", "topic": "rs429358"})
        self.assertEqual(result["topicAsk"]["tool"], "research.build_target_packet")
        self.assertTrue(result["inspectorHasBuilder"])
        self.assertEqual(result["inspectorActionLabels"], [])
        self.assertNotIn("Inputs", result["inspectorSectionTitles"])
        self.assertNotIn("genome_build", json.dumps(result["topicAsk"]["params"]))
        self.assertEqual(result["packetConditionAttributeCount"], 0)
        self.assertEqual(result["packetFieldIdRows"], 6)

    def test_portal_css_owns_hidden_state_once(self) -> None:
        css = (Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates/portal.css").read_text()

        self.assertIn(".app [hidden] { display: none !important; }", css)
        self.assertNotIn(".tool-request-field[hidden]", css)
        self.assertNotIn(".artifact-selection-bar[hidden]", css)


def _run_node_json(test_case: unittest.TestCase, script: str):
    if shutil.which("node") is None:
        test_case.skipTest("node is required for frontend module tests")
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _assert_public_payload(value) -> None:
    text = json.dumps(value)
    if _PRIVATE_PROMPT_RE.search(text):
        raise AssertionError(f"private prompt text leaked: {text}")
