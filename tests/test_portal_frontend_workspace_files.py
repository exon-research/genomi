from __future__ import annotations

import json
import textwrap
import unittest
from pathlib import Path

from tests.test_portal_frontend_artifact_library import _dom_shim_script, _run_node_json


class PortalFrontendWorkspaceFilesTests(unittest.TestCase):
    def test_workspace_files_model_searches_and_links_artifacts(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const workspace = await import({module_url!r});
            const payload = {{
              project_id: 'proj_1',
              workspace: {{
                scope: 'project',
                owner: 'genomi_webui',
                storage: 'genomi_home_workspace',
                path_hint: '$GENOMI_HOME/workspace/proj_1'
              }},
              summary: {{ total_files: 2, linked_artifacts: 1 }},
              files: [
                {{
                  relative_path: 'reports/apoe.txt',
                  name: 'apoe.txt',
                  directory: 'reports',
                  content_type: 'text/plain',
                  file_kind: 'markdown',
                  kind_label: 'Markdown',
                  record_label: 'Generated record',
                  size_label: '12 bytes',
                  artifact_id: 'art_file'
                }},
                {{
                  relative_path: 'tables/variants.csv',
                  name: 'variants.csv',
                  directory: 'tables',
                  content_type: 'text/csv',
                  file_kind: 'table',
                  kind_label: 'Table',
                  record_label: 'Research file',
                  size_label: '22 bytes'
                }},
                {{
                  relative_path: 'notes/session.md',
                  name: 'session.md',
                  directory: 'notes',
                  content_type: 'text/markdown',
                  size_label: '34 bytes'
                }}
              ]
            }};
            const all = workspace.workspaceFilesModel(payload);
            const searched = workspace.workspaceFilesModel(payload, {{ query: 'csv' }});
            const textPreview = workspace.workspaceFilePreviewModel({{
              status: 'available',
              preview_kind: 'text',
              relative_path: 'reports/apoe.txt',
              content_type: 'text/plain',
              size_label: '12 bytes',
              text: 'APOE report'
            }});
            process.stdout.write(JSON.stringify({{
              allSummary: all.summary,
              workspace: all.workspace,
              linkedArtifacts: all.linkedArtifacts,
              allPaths: all.files.map((file) => file.path),
              allKinds: all.files.map((file) => file.fileKind),
              allKindLabels: all.files.map((file) => file.kindLabel),
              allRecordLabels: all.files.map((file) => file.recordLabel),
              allLocations: all.locations.map((location) => [location.key, location.label, location.count, location.active]),
              allGroups: all.groups.map((group) => [group.key, group.label, group.summary, group.files.map((file) => file.path)]),
              searchedPaths: searched.files.map((file) => file.path),
              searchedGroups: searched.groups.map((group) => [group.key, group.label, group.summary, group.files.map((file) => file.path)]),
              textPreview
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["allSummary"], "3 of 3 files")
        self.assertEqual(result["workspace"]["label"], "Project workspace")
        self.assertEqual(result["workspace"]["ownerLabel"], "Genomi-owned files")
        self.assertEqual(result["linkedArtifacts"], 1)
        self.assertEqual(result["allPaths"], ["reports/apoe.txt", "tables/variants.csv", "notes/session.md"])
        self.assertEqual(result["allKinds"], ["markdown", "table", "markdown"])
        self.assertEqual(result["allKindLabels"], ["Markdown", "Table", "Markdown"])
        self.assertEqual(result["allRecordLabels"], ["Generated record", "Research file", "Research file"])
        self.assertEqual(
            result["allLocations"],
            [
                ["all", "All files", 3, True],
                ["generated_records", "Generated records", 1, False],
                ["directory:notes", "notes", 1, False],
                ["directory:tables", "tables", 1, False],
            ],
        )
        self.assertEqual(
            result["allGroups"],
            [
                ["generated_records", "Generated records", "1 linked research record", ["reports/apoe.txt"]],
                ["notes", "notes", "1 file", ["notes/session.md"]],
                ["tables", "tables", "1 file", ["tables/variants.csv"]],
            ],
        )
        self.assertEqual(result["searchedPaths"], ["tables/variants.csv"])
        self.assertEqual(result["searchedGroups"], [["tables", "tables", "1 file", ["tables/variants.csv"]]])
        self.assertEqual(result["textPreview"]["previewKind"], "text")
        self.assertEqual(result["textPreview"]["title"], "reports/apoe.txt")

    def test_workspace_files_model_filters_library_locations(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const workspace = await import({module_url!r});
            const payload = {{
              files: [
                {{ relative_path: 'reports/apoe.md', directory: 'reports', content_type: 'text/markdown', artifact_id: 'art_1' }},
                {{ relative_path: 'reports/manual.md', directory: 'reports', content_type: 'text/markdown' }},
                {{ relative_path: 'tables/variants.csv', directory: 'tables', content_type: 'text/csv' }}
              ]
            }};
            const generated = workspace.workspaceFilesModel(payload, {{ locationKey: 'generated_records' }});
            const reports = workspace.workspaceFilesModel(payload, {{ locationKey: 'directory:reports' }});
            const missing = workspace.workspaceFilesModel(payload, {{ locationKey: 'directory:missing' }});
            process.stdout.write(JSON.stringify({{
              generatedSummary: generated.summary,
              generatedPaths: generated.files.map((file) => file.path),
              generatedActive: generated.locations.find((location) => location.key === 'generated_records').active,
              reportsPaths: reports.files.map((file) => file.path),
              reportsGroups: reports.groups.map((group) => [group.key, group.files.map((file) => file.path)]),
              reportsActive: reports.locations.find((location) => location.key === 'directory:reports').active,
              missingLocationKey: missing.locationKey,
              missingPaths: missing.files.map((file) => file.path)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(result["generatedSummary"], "1 of 3 files")
        self.assertEqual(result["generatedPaths"], ["reports/apoe.md"])
        self.assertTrue(result["generatedActive"])
        self.assertEqual(result["reportsPaths"], ["reports/manual.md"])
        self.assertEqual(result["reportsGroups"], [["reports", ["reports/manual.md"]]])
        self.assertTrue(result["reportsActive"])
        self.assertEqual(result["missingLocationKey"], "all")
        self.assertEqual(result["missingPaths"], ["reports/apoe.md", "reports/manual.md", "tables/variants.csv"])

    def test_workspace_files_model_separates_imported_files_from_generated_records(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const workspace = await import({module_url!r});
            const payload = {{
              summary: {{ total_files: 3, linked_artifacts: 2 }},
              files: [
                {{
                  relative_path: 'reports/apoe.md',
                  directory: 'reports',
                  content_type: 'text/markdown',
                  artifact_id: 'art_generated',
                  record_type: 'generated_record',
                  record_label: 'Generated record'
                }},
                {{
                  relative_path: 'lab-notes.csv',
                  content_type: 'text/csv',
                  artifact_id: 'art_imported',
                  record_type: 'imported_file',
                  record_label: 'Imported file'
                }},
                {{
                  relative_path: 'notes/manual.md',
                  directory: 'notes',
                  content_type: 'text/markdown',
                  record_type: 'research_file',
                  record_label: 'Research file'
                }}
              ]
            }};
            const all = workspace.workspaceFilesModel(payload);
            const imported = workspace.workspaceFilesModel(payload, {{ locationKey: 'imported_files' }});
            const generated = workspace.workspaceFilesModel(payload, {{ locationKey: 'generated_records' }});
            process.stdout.write(JSON.stringify({{
              locations: all.locations.map((location) => [location.key, location.label, location.count]),
              groups: all.groups.map((group) => [group.key, group.label, group.summary, group.files.map((file) => file.path)]),
              importedPaths: imported.files.map((file) => file.path),
              generatedPaths: generated.files.map((file) => file.path)
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(
            result["locations"],
            [
                ["all", "All files", 3],
                ["generated_records", "Generated records", 1],
                ["imported_files", "Imported files", 1],
                ["directory:notes", "notes", 1],
            ],
        )
        self.assertEqual(
            result["groups"],
            [
                ["generated_records", "Generated records", "1 linked research record", ["reports/apoe.md"]],
                ["imported_files", "Imported files", "1 imported file", ["lab-notes.csv"]],
                ["notes", "notes", "1 file", ["notes/manual.md"]],
            ],
        )
        self.assertEqual(result["importedPaths"], ["lab-notes.csv"])
        self.assertEqual(result["generatedPaths"], ["reports/apoe.md"])

    def test_workspace_files_render_open_artifact_action_and_search_input(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const opened = [];
            const previewed = [];
            const queries = [];
            workspace.renderWorkspaceFiles(container, {
              workspace: {
                scope: 'project',
                owner: 'genomi_webui',
                storage: 'genomi_home_workspace',
                path_hint: '$GENOMI_HOME/workspace/proj_1'
              },
              summary: { total_files: 1, linked_artifacts: 1 },
              files: [{
                relative_path: 'reports/apoe.txt',
                name: 'apoe.txt',
                directory: 'reports',
                content_type: 'text/plain',
                size_label: '12 bytes',
                artifact_id: 'art_file'
              }]
            }, {
              onOpenArtifact: (file) => opened.push(file.artifactId),
              onPreviewFile: (file) => previewed.push(file.path),
              onQuery: (query) => queries.push(query)
            });
            const row = container.querySelector('[data-testid="genomi-workspace-file-row"]');
            const groups = container.querySelectorAll('[data-testid="genomi-workspace-file-group"]').map((group) => ({
              key: group.dataset.groupKey,
              label: group.querySelector('.workspace-file-group-head strong').textContent,
              summary: group.querySelector('.workspace-file-group-head span').textContent
            }));
            const locations = container.querySelectorAll('[data-testid="genomi-workspace-file-location"]').map((button) => ({
              key: button.dataset.locationKey,
              text: button.textContent,
              active: button.className.includes('active')
            }));
            const button = container.querySelector('[data-testid="genomi-workspace-file-open-artifact"]');
            const preview = container.querySelector('[data-testid="genomi-workspace-file-preview"]');
            const search = container.querySelector('[data-testid="genomi-workspace-file-search"]');
            if (button) button.eventListeners.click[0]();
            if (preview) preview.eventListeners.click[0]();
            if (search) {
              search.value = 'apoe';
              search.eventListeners.input[0]();
            }
            process.stdout.write(JSON.stringify({
              testId: container.getAttribute('data-testid'),
              toolbarTitle: container.querySelector('.workspace-files-title strong').textContent,
              toolbarSummary: container.querySelector('.workspace-files-title span').textContent,
              rowPath: row ? row.dataset.filePath : '',
              rowKind: row ? row.querySelector('em').textContent : '',
              rowTitle: row ? row.querySelector('strong').textContent : '',
              rowMeta: row ? row.querySelector('span').textContent : '',
              groups,
              locations,
              previewLabel: preview ? preview.textContent : '',
              opened,
              previewed,
              queries
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["testId"], "genomi-workspace-files")
        self.assertEqual(result["toolbarTitle"], "Project workspace")
        self.assertEqual(result["toolbarSummary"], "Genomi-owned files · 1 of 1 file · 1 linked record")
        self.assertEqual(result["rowPath"], "reports/apoe.txt")
        self.assertEqual(result["rowKind"], "Text")
        self.assertEqual(result["rowTitle"], "reports/apoe.txt")
        self.assertEqual(result["rowMeta"], "text/plain · 12 bytes · Generated record")
        self.assertEqual(
            result["groups"],
            [{"key": "generated_records", "label": "Generated records", "summary": "1 linked research record"}],
        )
        self.assertEqual(
            result["locations"],
            [
                {"key": "all", "text": "All files · 1", "active": True},
                {"key": "generated_records", "text": "Generated records · 1", "active": False},
            ],
        )
        self.assertEqual(result["previewLabel"], "Preview")
        self.assertEqual(result["opened"], ["art_file"])
        self.assertEqual(result["previewed"], ["reports/apoe.txt"])
        self.assertEqual(result["queries"], ["apoe"])

    def test_workspace_file_controller_filters_by_library_location(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const controller = workspace.createWorkspaceFileController({ container });
            controller.render({
              project_id: 'proj_1',
              summary: { total_files: 3, linked_artifacts: 1 },
              files: [
                { relative_path: 'reports/apoe.md', directory: 'reports', content_type: 'text/markdown', artifact_id: 'art_1' },
                { relative_path: 'reports/manual.md', directory: 'reports', content_type: 'text/markdown' },
                { relative_path: 'tables/variants.csv', directory: 'tables', content_type: 'text/csv' }
              ]
            }, { projectId: 'proj_1' });
            const beforeRows = container.querySelectorAll('[data-testid="genomi-workspace-file-row"]').map((row) => row.dataset.filePath);
            const reportButton = container.querySelectorAll('[data-testid="genomi-workspace-file-location"]')
              .find((button) => button.dataset.locationKey === 'directory:reports');
            if (reportButton) reportButton.eventListeners.click[0]();
            const afterRows = container.querySelectorAll('[data-testid="genomi-workspace-file-row"]').map((row) => row.dataset.filePath);
            const activeLocation = container.querySelectorAll('[data-testid="genomi-workspace-file-location"]')
              .find((button) => button.className.includes('active'));
            process.stdout.write(JSON.stringify({
              beforeRows,
              afterRows,
              activeLocation: activeLocation ? [activeLocation.dataset.locationKey, activeLocation.textContent] : []
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["beforeRows"], ["reports/apoe.md", "reports/manual.md", "tables/variants.csv"])
        self.assertEqual(result["afterRows"], ["reports/manual.md"])
        self.assertEqual(result["activeLocation"], ["directory:reports", "reports · 1"])

    def test_workspace_files_group_generated_records_by_origin_conversation(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            f"""
            const workspace = await import({module_url!r});
            const model = workspace.workspaceFilesModel({{
              files: [
                {{
                  relative_path: 'reports/apoe.md',
                  name: 'apoe.md',
                  directory: 'reports',
                  content_type: 'text/markdown',
                  artifact_id: 'art_apoe',
                  origin_context: {{
                    frame_id: 'frame_1',
                    frame_title: 'Build APOE evidence record',
                    run_ids: ['run_1'],
                    producing_run_id: 'run_1'
                  }}
                }},
                {{
                  relative_path: 'tables/variant.csv',
                  name: 'variant.csv',
                  directory: 'tables',
                  content_type: 'text/csv',
                  artifact_id: 'art_variant',
                  origin_context: {{
                    frame_id: 'frame_1',
                    frame_title: 'Build APOE evidence record',
                    run_ids: ['run_2'],
                    producing_run_id: 'run_2'
                  }}
                }},
                {{
                  relative_path: 'reports/manual.md',
                  name: 'manual.md',
                  directory: 'reports',
                  content_type: 'text/markdown',
                  artifact_id: 'art_manual'
                }},
                {{
                  relative_path: 'notes/session.md',
                  name: 'session.md',
                  directory: 'notes',
                  content_type: 'text/markdown'
                }}
              ]
            }});
            process.stdout.write(JSON.stringify({{
              groups: model.groups.map((group) => [group.key, group.label, group.summary, group.files.map((file) => file.path)])
            }}));
            """
        )

        result = _run_node_json(self, script)

        self.assertEqual(
            result["groups"],
            [
                [
                    "generated_record_frame_frame_1",
                    "Created in Build APOE evidence record",
                    "2 generated records from this conversation",
                    ["reports/apoe.md", "tables/variant.csv"],
                ],
                ["generated_records", "Generated records", "1 linked research record", ["reports/manual.md"]],
                ["notes", "notes", "1 file", ["notes/session.md"]],
            ],
        )

    def test_workspace_file_generated_record_can_view_origin_chat(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const viewed = [];
            workspace.renderWorkspaceFiles(container, {
              files: [
                {
                  relative_path: 'reports/apoe.md',
                  name: 'apoe.md',
                  directory: 'reports',
                  content_type: 'text/markdown',
                  artifact_id: 'art_apoe',
                  origin_context: {
                    frame_id: 'frame_1',
                    frame_title: 'Create APOE report',
                    run_ids: ['run_1'],
                    producing_run_id: 'run_1'
                  }
                },
                {
                  relative_path: 'reports/manual.md',
                  name: 'manual.md',
                  directory: 'reports',
                  content_type: 'text/markdown',
                  artifact_id: 'art_manual'
                },
                {
                  relative_path: 'notes/session.md',
                  name: 'session.md',
                  directory: 'notes',
                  content_type: 'text/markdown'
                }
              ]
            }, {
              onViewContext: (origin, file) => viewed.push({ origin, path: file.path })
            });
            const viewButtons = container.querySelectorAll('[data-testid="genomi-workspace-file-view-context"]');
            if (viewButtons[0]) viewButtons[0].eventListeners.click[0]();
            process.stdout.write(JSON.stringify({
              viewButtonLabels: viewButtons.map((button) => button.textContent),
              viewed
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["viewButtonLabels"], ["Open origin chat"])
        self.assertEqual(result["viewed"][0]["path"], "reports/apoe.md")
        self.assertEqual(result["viewed"][0]["origin"]["frameId"], "frame_1")
        self.assertEqual(result["viewed"][0]["origin"]["frameTitle"], "Create APOE report")
        self.assertEqual(result["viewed"][0]["origin"]["runIds"], ["run_1"])

    def test_workspace_files_render_inline_preview_panel(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const closed = [];
            workspace.renderWorkspaceFiles(container, {
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{
                relative_path: 'reports/apoe.txt',
                name: 'apoe.txt',
                content_type: 'text/plain',
                size_label: '12 bytes'
              }]
            }, {
              preview: {
                status: 'available',
                preview_kind: 'text',
                relative_path: 'reports/apoe.md',
                file_kind: 'markdown',
                kind_label: 'Markdown',
                record_label: 'Research record',
                content_type: 'text/markdown',
                size_label: '12 bytes',
                text: '# APOE report\\n\\nReview `CYP2C19` with [CPIC](https://cpicpgx.org) and **public evidence**.\\n\\n| Source | Finding |\\n|---|---|\\n| dbSNP | APOE |\\n\\n- public evidence\\n- active genome boundary\\n\\n```python\\nprint("ok")\\n```'
              },
              onClosePreview: () => closed.push('closed')
            });
            const panel = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            const article = panel ? panel.querySelector('[data-testid="genomi-workspace-file-markdown-preview"]') : null;
            const close = panel ? panel.querySelector('button') : null;
            if (close) close.eventListeners.click[0]();
            process.stdout.write(JSON.stringify({
              title: panel ? panel.querySelector('strong').textContent : '',
              kind: panel ? panel.querySelector('em').textContent : '',
              meta: panel ? panel.querySelector('span').textContent : '',
              hasArticle: Boolean(article),
              heading: article ? article.querySelector('h2 span').textContent : '',
              inlineCode: article ? article.querySelector('p code').textContent : '',
              linkText: article ? article.querySelector('p a').textContent : '',
              linkHref: article ? article.querySelector('p a').href : '',
              emphasis: article ? article.querySelector('p strong').textContent : '',
              tableHeaders: article ? article.querySelectorAll('th').map((item) => item.querySelector('span').textContent) : [],
              tableCells: article ? article.querySelectorAll('td').map((item) => item.querySelector('span').textContent) : [],
              listItems: article ? article.querySelectorAll('li').map((item) => item.querySelector('span').textContent) : [],
              codeBlock: article ? article.querySelector('pre code').textContent : '',
              closed
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["title"], "reports/apoe.md")
        self.assertEqual(result["kind"], "Markdown · Research record")
        self.assertEqual(result["meta"], "text/markdown · 12 bytes")
        self.assertTrue(result["hasArticle"])
        self.assertEqual(result["heading"], "APOE report")
        self.assertEqual(result["inlineCode"], "CYP2C19")
        self.assertEqual(result["linkText"], "CPIC")
        self.assertEqual(result["linkHref"], "https://cpicpgx.org")
        self.assertEqual(result["emphasis"], "public evidence")
        self.assertEqual(result["tableHeaders"], ["Source", "Finding"])
        self.assertEqual(result["tableCells"], ["dbSNP", "APOE"])
        self.assertEqual(result["listItems"], ["public evidence", "active genome boundary"])
        self.assertEqual(result["codeBlock"], 'print("ok")')
        self.assertEqual(result["closed"], ["closed"])

    def test_workspace_file_preview_actions_build_selected_file_material(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const asked = [];
            const askedNew = [];
            const included = [];
            workspace.renderWorkspaceFiles(container, {
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{
                relative_path: 'reports/apoe.md',
                name: 'apoe.md',
                content_type: 'text/markdown',
                size_label: '12 bytes'
              }]
            }, {
              preview: {
                status: 'available',
                preview_kind: 'text',
                relative_path: 'reports/apoe.md',
                content_type: 'text/markdown',
                size_label: '12 bytes',
                text: '# APOE report\\n\\nUse public evidence first.'
              },
              onAskFile: (payload) => asked.push(payload),
              onAskNewFile: (payload) => askedNew.push(payload),
              onUseFile: (payload) => included.push(payload)
            });
            const ask = container.querySelector('[data-testid="genomi-workspace-file-ask"]');
            const askNew = container.querySelector('[data-testid="genomi-workspace-file-ask-new"]');
            const include = container.querySelector('[data-testid="genomi-workspace-file-include"]');
            if (ask) ask.eventListeners.click[0]();
            if (askNew) askNew.eventListeners.click[0]();
            if (include) include.eventListeners.click[0]();
            const direct = workspace.workspaceFileContextPayload({
              status: 'available',
              preview_kind: 'notebook',
              relative_path: 'analysis/session.ipynb',
              content_type: 'application/x-ipynb+json',
              notebook: {
                summary: '2 cells · python',
                cell_count: 2,
                shown_cell_count: 2,
                cells: [
                  { index: 1, cell_type: 'markdown', source: '# QC notes' },
                  { index: 2, cell_type: 'code', source: 'print("ok")' }
                ]
              }
            });
            process.stdout.write(JSON.stringify({ asked, askedNew, included, direct }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["asked"], [])
        self.assertEqual(result["askedNew"][0]["context_kind"], "workspace_file")
        self.assertEqual(result["askedNew"][0]["source_operation"], "genomi.portal.workspace_file")
        self.assertEqual(result["askedNew"][0]["label"], "Project file: reports/apoe.md")
        self.assertIn("Markdown · text/markdown · 12 bytes", result["askedNew"][0]["summary"])
        self.assertEqual(result["included"][0], result["askedNew"][0])
        self.assertIn("Project file / File: reports/apoe.md", [node["text"] for node in result["askedNew"][0]["selected_nodes"]])
        self.assertTrue(any(node["label"] == "Visible preview excerpt" for node in result["askedNew"][0]["selected_nodes"]))
        self.assertEqual(result["direct"]["context_kind"], "workspace_file")
        self.assertEqual(result["direct"]["label"], "Project file: analysis/session.ipynb")
        self.assertTrue(any(node["label"] == "Notebook outline" for node in result["direct"]["selected_nodes"]))
        self.assertTrue(any("markdown cell 1" in node["text"] for node in result["direct"]["selected_nodes"]))

    def test_workspace_file_preview_keeps_generated_record_origin_actions(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const opened = [];
            const viewed = [];
            const controller = workspace.createWorkspaceFileController({
              container,
              onPreviewFile: async (file) => ({
                status: 'available',
                preview_kind: 'text',
                relative_path: file.path,
                content_type: 'text/markdown',
                size_label: '24 bytes',
                text: '# Generated APOE report'
              }),
              onOpenArtifact: (file) => opened.push({ artifactId: file.artifactId, path: file.path }),
              onViewContext: (origin, file) => viewed.push({ frameId: origin.frameId, runIds: origin.runIds, path: file.path })
            });
            controller.render({
              project_id: 'proj_1',
              summary: { total_files: 1, linked_artifacts: 1 },
              files: [{
                relative_path: 'reports/apoe.md',
                name: 'apoe.md',
                content_type: 'text/markdown',
                size_label: '24 bytes',
                artifact_id: 'art_apoe',
                origin_context: {
                  frame_id: 'frame_1',
                  run_ids: ['run_1'],
                  producing_run_id: 'run_1'
                }
              }]
            }, { projectId: 'proj_1' });
            const preview = container.querySelector('[data-testid="genomi-workspace-file-preview"]');
            if (preview) await preview.eventListeners.click[0]();
            const panel = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            const open = panel ? panel.querySelector('[data-testid="genomi-workspace-preview-open-artifact"]') : null;
            const view = panel ? panel.querySelector('[data-testid="genomi-workspace-preview-view-context"]') : null;
            if (open) open.eventListeners.click[0]();
            if (view) view.eventListeners.click[0]();
            process.stdout.write(JSON.stringify({
              hasPanel: Boolean(panel),
              panelKind: panel ? panel.querySelector('em').textContent : '',
              openLabel: open ? open.textContent : '',
              viewLabel: view ? view.textContent : '',
              opened,
              viewed
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertTrue(result["hasPanel"])
        self.assertEqual(result["panelKind"], "Markdown · Generated record")
        self.assertEqual(result["openLabel"], "Open details")
        self.assertEqual(result["viewLabel"], "Open origin chat")
        self.assertEqual(result["opened"], [{"artifactId": "art_apoe", "path": "reports/apoe.md"}])
        self.assertEqual(
            result["viewed"],
            [{"frameId": "frame_1", "runIds": ["run_1"], "path": "reports/apoe.md"}],
        )

    def test_workspace_file_controller_uses_preview_record_label_for_ordinary_files(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const controller = workspace.createWorkspaceFileController({
              container,
              onPreviewFile: async (file) => ({
                status: 'available',
                preview_kind: 'text',
                relative_path: file.path,
                content_type: 'text/plain',
                file_kind: 'text',
                kind_label: 'Text',
                record_label: 'Research record',
                size_label: '18 bytes',
                text: 'APOE workspace note'
              })
            });
            controller.render({
              project_id: 'proj_1',
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{
                relative_path: 'notes/apoe.txt',
                name: 'apoe.txt',
                content_type: 'text/plain',
                file_kind: 'text',
                kind_label: 'Text',
                record_label: 'Research file',
                size_label: '18 bytes'
              }]
            }, { projectId: 'proj_1' });
            const row = container.querySelector('[data-testid="genomi-workspace-file-row"]');
            const preview = container.querySelector('[data-testid="genomi-workspace-file-preview"]');
            if (preview) await preview.eventListeners.click[0]();
            const panel = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            process.stdout.write(JSON.stringify({
              rowMeta: row ? row.querySelector('span').textContent : '',
              panelKind: panel ? panel.querySelector('em').textContent : '',
              panelText: panel ? panel.querySelector('pre').textContent : ''
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["rowMeta"], "text/plain · 18 bytes · Research file")
        self.assertEqual(result["panelKind"], "Text · Research record")
        self.assertEqual(result["panelText"], "APOE workspace note")

    def test_workspace_files_classifies_code_and_image_previews_as_research_records(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const codeContainer = document.createElement('div');
            workspace.renderWorkspaceFiles(codeContainer, {
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{
                relative_path: 'scripts/reproduce.py',
                name: 'reproduce.py',
                content_type: 'text/x-python',
                size_label: '42 bytes'
              }]
            }, {
              preview: {
                status: 'available',
                preview_kind: 'text',
                relative_path: 'scripts/reproduce.py',
                content_type: 'text/x-python',
                text: 'print("APOE")'
              }
            });
            const imageContainer = document.createElement('div');
            workspace.renderWorkspaceFiles(imageContainer, {
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{
                relative_path: 'figures/umap.png',
                name: 'umap.png',
                content_type: 'image/png',
                size_label: '80 bytes'
              }]
            }, {
              preview: {
                status: 'available',
                preview_kind: 'image',
                relative_path: 'figures/umap.png',
                content_type: 'image/png',
                data_url: 'data:image/png;base64,abc'
              }
            });
            const codePanel = codeContainer.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            const imagePanel = imageContainer.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            process.stdout.write(JSON.stringify({
              codeRowKind: codeContainer.querySelector('[data-testid="genomi-workspace-file-row"]').querySelector('em').textContent,
              codePanelKind: codePanel.querySelector('em').textContent,
              codeClass: codePanel.querySelector('pre').className,
              imageRowKind: imageContainer.querySelector('[data-testid="genomi-workspace-file-row"]').querySelector('em').textContent,
              imagePanelKind: imagePanel.querySelector('em').textContent,
              imageAlt: imagePanel.querySelector('img').alt
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["codeRowKind"], "Code")
        self.assertEqual(result["codePanelKind"], "Code · Research record")
        self.assertIn("file-kind-code", result["codeClass"])
        self.assertEqual(result["imageRowKind"], "Image")
        self.assertEqual(result["imagePanelKind"], "Image · Research record")
        self.assertEqual(result["imageAlt"], "umap.png")

    def test_workspace_files_render_table_preview_as_research_record(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            workspace.renderWorkspaceFiles(container, {
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{
                relative_path: 'tables/variants.csv',
                name: 'variants.csv',
                content_type: 'text/csv',
                size_label: '66 bytes'
              }]
            }, {
              preview: {
                status: 'available',
                preview_kind: 'text',
                relative_path: 'tables/variants.csv',
                content_type: 'text/csv',
                text: 'gene,effect,note\\nCYP2C19,poor,"needs, review"\\nAPOE,e4,public'
              }
            });
            const panel = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            const table = panel ? panel.querySelector('[data-testid="genomi-workspace-file-table-preview"]') : null;
            const firstRow = table ? table.querySelector('tbody tr') : null;
            process.stdout.write(JSON.stringify({
              kind: panel ? panel.querySelector('em').textContent : '',
              hasTable: Boolean(table),
              summary: table ? table.querySelector('.workspace-file-table-summary').textContent : '',
              headers: table ? table.querySelectorAll('th').map((cell) => cell.textContent) : [],
              firstRow: firstRow ? firstRow.querySelectorAll('td').map((cell) => cell.textContent) : [],
              preFallback: Boolean(panel && panel.querySelector('pre.file-kind-table'))
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["kind"], "Table · Research record")
        self.assertTrue(result["hasTable"])
        self.assertEqual(result["summary"], "2 data rows · 3 columns")
        self.assertEqual(result["headers"], ["gene", "effect", "note"])
        self.assertEqual(result["firstRow"], ["CYP2C19", "poor", "needs, review"])
        self.assertFalse(result["preFallback"])

    def test_workspace_files_render_pdf_document_preview_as_research_record(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            workspace.renderWorkspaceFiles(container, {
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{
                relative_path: 'papers/review.pdf',
                name: 'review.pdf',
                content_type: 'application/pdf',
                size_label: '320 KB'
              }]
            }, {
              preview: {
                status: 'available',
                preview_kind: 'document',
                relative_path: 'papers/review.pdf',
                content_type: 'application/pdf',
                size_label: '320 KB',
                document_url: '/api/projects/proj_1/workspace/file?path=papers%2Freview.pdf'
              }
            });
            const row = container.querySelector('[data-testid="genomi-workspace-file-row"]');
            const panel = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            const preview = panel ? panel.querySelector('[data-testid="genomi-workspace-file-document-preview"]') : null;
            const frame = panel ? panel.querySelector('[data-testid="genomi-workspace-file-document-frame"]') : null;
            process.stdout.write(JSON.stringify({
              rowKind: row ? row.querySelector('em').textContent : '',
              panelKind: panel ? panel.querySelector('em').textContent : '',
              hasPreview: Boolean(preview),
              frameTitle: frame ? frame.title : '',
              frameSrc: frame ? frame.src : ''
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["rowKind"], "PDF document")
        self.assertEqual(result["panelKind"], "PDF document · Research record")
        self.assertTrue(result["hasPreview"])
        self.assertEqual(result["frameTitle"], "review.pdf document preview")
        self.assertEqual(result["frameSrc"], "/api/projects/proj_1/workspace/file?path=papers%2Freview.pdf")

    def test_workspace_files_render_notebook_preview_as_cell_outline(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            workspace.renderWorkspaceFiles(container, {
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{
                relative_path: 'analysis/session.ipynb',
                name: 'session.ipynb',
                content_type: 'application/x-ipynb+json',
                size_label: '24 KB'
              }]
            }, {
              preview: {
                status: 'available',
                preview_kind: 'notebook',
                relative_path: 'analysis/session.ipynb',
                file_kind: 'notebook',
                kind_label: 'Notebook',
                record_label: 'Research record',
                content_type: 'application/x-ipynb+json',
                notebook: {
                  summary: '2 cells · 1 code · 1 markdown · python',
                  cell_count: 2,
                  shown_cell_count: 2,
                  cells: [
                    { index: 1, cell_type: 'markdown', source: '# APOE review', line_count: 1 },
                    { index: 2, cell_type: 'code', source: 'print("CYP2C19")', line_count: 1, output_count: 1 }
                  ]
                }
              }
            });
            const row = container.querySelector('[data-testid="genomi-workspace-file-row"]');
            const panel = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            const notebook = panel ? panel.querySelector('[data-testid="genomi-workspace-file-notebook-preview"]') : null;
            const cells = notebook ? notebook.querySelectorAll('[data-testid="genomi-workspace-file-notebook-cell"]') : [];
            process.stdout.write(JSON.stringify({
              rowKind: row ? row.querySelector('em').textContent : '',
              panelKind: panel ? panel.querySelector('em').textContent : '',
              summary: notebook ? notebook.querySelector('.workspace-file-notebook-summary strong').textContent : '',
              shown: notebook ? notebook.querySelector('.workspace-file-notebook-summary span').textContent : '',
              cellLabels: cells.map((cell) => cell.querySelector('header strong').textContent),
              cellMeta: cells.map((cell) => cell.querySelector('header span').textContent),
              cellSources: cells.map((cell) => cell.querySelector('pre').textContent)
            }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["rowKind"], "Notebook")
        self.assertEqual(result["panelKind"], "Notebook · Research record")
        self.assertEqual(result["summary"], "2 cells · 1 code · 1 markdown · python")
        self.assertEqual(result["shown"], "All cells shown")
        self.assertEqual(result["cellLabels"], ["Markdown cell 1", "Code cell 2"])
        self.assertEqual(result["cellMeta"], ["1 line", "1 line · 1 output"])
        self.assertEqual(result["cellSources"], ["# APOE review", 'print("CYP2C19")'])

    def test_workspace_file_controller_clears_preview_when_project_or_file_changes(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            const container = document.createElement('div');
            const controller = workspace.createWorkspaceFileController({ container });
            const payloadA = {
              project_id: 'proj_a',
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{ relative_path: 'reports/a.txt', name: 'a.txt', content_type: 'text/plain' }]
            };
            const payloadB = {
              project_id: 'proj_b',
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{ relative_path: 'reports/b.txt', name: 'b.txt', content_type: 'text/plain' }]
            };
            controller.render(payloadA, {
              preview: {
                status: 'available',
                preview_kind: 'text',
                relative_path: 'reports/a.txt',
                text: 'A'
              }
            });
            const beforeSwitch = Boolean(container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]'));
            controller.render(payloadB);
            const afterSwitch = Boolean(container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]'));
            controller.render(payloadA, {
              preview: {
                status: 'available',
                preview_kind: 'text',
                relative_path: 'reports/a.txt',
                text: 'A'
              }
            });
            controller.render({ project_id: 'proj_a', summary: { total_files: 0 }, files: [] });
            const afterReloadWithoutFile = Boolean(container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]'));
            process.stdout.write(JSON.stringify({ beforeSwitch, afterSwitch, afterReloadWithoutFile }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertTrue(result["beforeSwitch"])
        self.assertFalse(result["afterSwitch"])
        self.assertFalse(result["afterReloadWithoutFile"])

    def test_workspace_file_controller_ignores_stale_preview_response(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            function deferred() {
              let resolve;
              const promise = new Promise((done) => { resolve = done; });
              return { promise, resolve };
            }
            const container = document.createElement('div');
            const previews = {
              'reports/a.txt': deferred(),
              'reports/b.txt': deferred()
            };
            const requested = [];
            const controller = workspace.createWorkspaceFileController({
              container,
              onPreviewFile: (file) => {
                requested.push(file.path);
                return previews[file.path].promise;
              }
            });
            controller.render({
              project_id: 'proj_1',
              summary: { total_files: 2, linked_artifacts: 0 },
              files: [
                { relative_path: 'reports/a.txt', name: 'a.txt', content_type: 'text/plain' },
                { relative_path: 'reports/b.txt', name: 'b.txt', content_type: 'text/plain' }
              ]
            });
            container.querySelectorAll('[data-testid="genomi-workspace-file-preview"]')[0].eventListeners.click[0]();
            container.querySelectorAll('[data-testid="genomi-workspace-file-preview"]')[1].eventListeners.click[0]();
            previews['reports/b.txt'].resolve({
              status: 'available',
              preview_kind: 'text',
              relative_path: 'reports/b.txt',
              text: 'Preview B'
            });
            await new Promise((resolve) => setTimeout(resolve, 0));
            const afterB = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]').querySelector('pre').textContent;
            previews['reports/a.txt'].resolve({
              status: 'available',
              preview_kind: 'text',
              relative_path: 'reports/a.txt',
              text: 'Preview A'
            });
            await new Promise((resolve) => setTimeout(resolve, 0));
            const afterA = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]').querySelector('pre').textContent;
            process.stdout.write(JSON.stringify({ requested, afterB, afterA }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["requested"], ["reports/a.txt", "reports/b.txt"])
        self.assertEqual(result["afterB"], "Preview B")
        self.assertEqual(result["afterA"], "Preview B")

    def test_workspace_file_controller_ignores_preview_closed_while_loading(self) -> None:
        module_url = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_workspace_files.js"
        ).as_uri()
        script = textwrap.dedent(
            """
            const workspace = await import(__MODULE_URL__);
            __DOM_SHIM__

            globalThis.document = { createElement: (tagName) => new Element(tagName) };
            let resolvePreview;
            const pendingPreview = new Promise((resolve) => { resolvePreview = resolve; });
            const container = document.createElement('div');
            const controller = workspace.createWorkspaceFileController({
              container,
              onPreviewFile: () => pendingPreview
            });
            controller.render({
              project_id: 'proj_1',
              summary: { total_files: 1, linked_artifacts: 0 },
              files: [{ relative_path: 'reports/a.txt', name: 'a.txt', content_type: 'text/plain' }]
            });
            container.querySelector('[data-testid="genomi-workspace-file-preview"]').eventListeners.click[0]();
            const loadingPanel = container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]');
            const loadingText = loadingPanel.querySelector('.workspace-file-preview-notice').textContent;
            loadingPanel.querySelector('button').eventListeners.click[0]();
            const afterClose = Boolean(container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]'));
            resolvePreview({
              status: 'available',
              preview_kind: 'text',
              relative_path: 'reports/a.txt',
              text: 'Preview A'
            });
            await new Promise((resolve) => setTimeout(resolve, 0));
            const afterResolve = Boolean(container.querySelector('[data-testid="genomi-workspace-file-preview-panel"]'));
            process.stdout.write(JSON.stringify({ loadingText, afterClose, afterResolve }));
            """
        ).replace("__MODULE_URL__", json.dumps(module_url)).replace("__DOM_SHIM__", _dom_shim_script())

        result = _run_node_json(self, script)

        self.assertEqual(result["loadingText"], "Loading preview...")
        self.assertFalse(result["afterClose"])
        self.assertFalse(result["afterResolve"])

    def test_workspace_file_css_is_linked_from_dedicated_asset(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        html = (root / "portal.html").read_text(encoding="utf-8")
        portal_css = (root / "portal.css").read_text(encoding="utf-8")
        workspace_css = (root / "portal_workspace_files.css").read_text(encoding="utf-8")

        self.assertIn('href="/assets/portal_workspace_files.css"', html)
        self.assertIn(".workspace-file-preview", workspace_css)
        self.assertNotIn(".workspace-file-preview", portal_css)


if __name__ == "__main__":
    unittest.main()
