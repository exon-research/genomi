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

Search summaries are discovery evidence, not citation anchors. Before citing a
claim, call `paperclip.retrieve_document_evidence` with the `record_id` and
`collection` from a selected search record plus one to five focused public
evidence terms. Cite only the returned line-pinned excerpts using their
`citation_url`. An empty excerpt result means only that those literal terms were
not observed in that document.

`record_id` is the readable document handle and `collection` is the collection
that handle resolves in. A record may also carry `external_id`, the public
registry or application number such as an NCT, UMIN, ChiCTR, or BLA identifier.
Use `external_id` for citation and lookup outside Genomi, not as the
`retrieve_document_evidence` handle: one application number covers many
documents.

For a `proteins` or `uniprot` search, a record carries the public UniProt
`accession` and `organism`. Paperclip does not serve amino-acid sequences, so a
BioHub comparison needs its public reference sequence from the user or another
declared source, and the accession identifies which sequence that is.

Paperclip receives only the public search query. Do not put patient identifiers,
record text, raw genome data, or private Lab state in the query.

Reach the operation through `genomi.invoke`:

### paperclip.search_biomedical

```json
{"tool":"paperclip.search_biomedical","params":{"query":"public mechanistic question","sources":["pmc","abstracts"]}}
```

### paperclip.retrieve_document_evidence

```json
{"tool":"paperclip.retrieve_document_evidence","params":{"document_id":"PMC1234567","collection":"papers","patterns":["mechanism term","reported outcome"]}}
```
