---
name: genomi-proto
description: Discover and run Proto's typed computational-biology tools on approved public research inputs for bounded nonclinical research work.
---

# Proto computational biology tools

Use `proto.search_tools` to find an executable tool by research intent, then
call `proto.describe_tool_schema` for the selected exact key before constructing its
inputs. Run it with `proto.run_tool`.

Proto runs typed computational tools; it does not itself decide a clinical
hypothesis or author a wet-lab protocol. The host agent may use a Proto result
as one nonclinical research artifact in a broader experiment-design analysis.

`proto.run_tool` transfers inputs to the configured Modal workspace. Use it only
for public or explicitly approved non-patient-linked research artifacts, with
`input_scope=public_or_approved_research_artifact` and approval for that exact
external transfer. Never send patient identifiers, raw genome data, private Lab
state, credentials, or local paths.

Large native artifacts and local materialization paths are not presented in the
Genomi result. A returned tool error is an answerability gap, not negative
biological evidence.

### proto.search_tools

Find the smallest executable Proto tool that matches the public research task.

### proto.describe_tool_schema

Inspect the selected tool's native typed input, configuration, and output shape.

### proto.run_tool

Run the selected tool only after satisfying the declared external-transfer scope.
