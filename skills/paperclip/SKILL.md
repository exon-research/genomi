---
name: genomi-paperclip
description: Search focused public biomedical literature, preprints, regulatory documents, clinical trials, and protein records through Paperclip when broad web search is insufficient.
---

# Paperclip biomedical search

Use `paperclip.search_biomedical` for a bounded public evidence question. Pass
the research question as `query`; narrow `sources` only when the evidence class
matters. The defaults consult PMC and biomedical abstracts.

Treat returned records as source evidence, not as a clinical conclusion. An
`in_scope_empty` result means only that the selected Paperclip sources returned
no matching records. A `source_unavailable` result is an answerability gap.

Paperclip receives only the public search query. Do not put patient identifiers,
record text, raw genome data, or private Lab state in the query.

Reach the operation through `genomi.invoke`:

### paperclip.search_biomedical

```json
{"tool":"paperclip.search_biomedical","params":{"query":"public mechanistic question","sources":["pmc","abstracts"]}}
```
