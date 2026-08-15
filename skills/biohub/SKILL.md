---
name: genomi-biohub
description: Compare approved public reference or research protein sequences with Biohub ESMC for a bounded nonclinical sequence-model signal.
---

# Biohub ESMC protein comparison

Use `biohub.compare_protein_embeddings` only for public reference sequences or
approved non-patient-linked research artifacts. Both sequences are transferred
to Biohub, so `external_transfer_approved` must reflect approval for that exact
public payload and `sequence_scope` must be
`public_reference_or_approved_research_artifact`.

The result compares mean ESMC embeddings and reports the sequence changes sent.
It is a nonclinical perturbation signal. It does not diagnose disease, validate
a variant, or change a clinical classification.

Never send raw genome content, patient-derived sequences, identifiers, record
locators, or private Lab state.

### biohub.compare_protein_embeddings

Reach the operation through `genomi.invoke` after the transfer boundary is met.
