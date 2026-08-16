from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from ...evidence import envelope as evidence_envelope
from ...runtime.external_credentials import resolve_external_credentials


BIOHUB_URL = "https://biohub.ai"
DEFAULT_MODEL = "esmc-600m-2024-12"
PUBLIC_SEQUENCE_SCOPE = "public_reference_or_approved_research_artifact"
PROTEIN_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO")
Transport = Callable[[str, dict[str, Any], str], dict[str, Any]]


def compare_protein_embeddings(
    *,
    reference_sequence: str,
    alternate_sequence: str,
    sequence_scope: str,
    external_transfer_approved: bool,
    model: str = DEFAULT_MODEL,
    transport: Transport | None = None,
) -> dict[str, Any]:
    if sequence_scope != PUBLIC_SEQUENCE_SCOPE or external_transfer_approved is not True:
        raise ValueError("Biohub requires approved external transfer of public research sequences")
    reference = _sequence(reference_sequence)
    alternate = _sequence(alternate_sequence)
    if model != DEFAULT_MODEL:
        raise ValueError(f"unsupported Biohub model: {model}")
    credentials = resolve_external_credentials("biohub")
    query_scope = {
        "model": model,
        "sequence_scope": sequence_scope,
        "reference_length": len(reference),
        "alternate_length": len(alternate),
    }
    if not credentials.configured:
        return _unavailable(query_scope, "credential_missing")

    call = transport or _post
    try:
        reference_embedding = _mean_embedding(call, reference, model, credentials.values["api_key"])
        alternate_embedding = _mean_embedding(call, alternate, model, credentials.values["api_key"])
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        return _unavailable(query_scope, "request_failed")
    if len(reference_embedding) != len(alternate_embedding) or not reference_embedding:
        return _unavailable(query_scope, "invalid_response")

    cosine_similarity = _cosine(reference_embedding, alternate_embedding)
    l2_distance = math.sqrt(
        sum((left - right) ** 2 for left, right in zip(reference_embedding, alternate_embedding))
    )
    changes = _changed_positions(reference, alternate)
    return {
        "status": "completed",
        "provider": "biohub",
        "model": model,
        "comparison": {
            "reference_length": len(reference),
            "alternate_length": len(alternate),
            "changed_positions": changes,
            "embedding_dimension": len(reference_embedding),
            "cosine_similarity": cosine_similarity,
            "cosine_distance": 1.0 - cosine_similarity,
            "l2_distance": l2_distance,
        },
        "interpretation_scope": "nonclinical_sequence_model_signal",
        "classification_effect": "none",
        "evidence_envelope": evidence_envelope.evidence_present(
            operation="biohub.compare_protein_embeddings",
            query_scope=query_scope,
            coverage={"consulted_sources": ["biohub:esmc"], "source_status": "consulted"},
            observations={"observation_count": 1, "changed_position_count": len(changes)},
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
            guidance=["evidence_present:use_only_as_nonclinical_protein_model_signal"],
        ),
    }


def _sequence(value: str) -> str:
    sequence = "".join(value.split()).upper()
    if not sequence:
        raise ValueError("protein sequence must not be empty")
    if len(sequence) > 4096:
        raise ValueError("protein sequence exceeds 4096 residues")
    invalid = sorted(set(sequence) - PROTEIN_ALPHABET)
    if invalid:
        raise ValueError(f"protein sequence contains unsupported residues: {''.join(invalid)}")
    return sequence


def _mean_embedding(call: Transport, sequence: str, model: str, token: str) -> list[float]:
    encoded = _unwrap(call("/api/v1/encode", {"inputs": {"sequence": sequence}, "model": model}, token))
    outputs = encoded.get("outputs")
    token_ids = outputs.get("sequence") if isinstance(outputs, dict) else None
    token_ids = token_ids or encoded.get("sequence") or encoded.get("tokens")
    if not isinstance(token_ids, list):
        raise ValueError("Biohub encode response did not contain tokens")
    result = _unwrap(
        call(
            "/api/v1/logits",
            {
                "model": model,
                "inputs": {"sequence": token_ids},
                "logits_config": {
                    "sequence": False,
                    "return_embeddings": False,
                    "return_mean_embedding": True,
                    "return_mean_hidden_states": False,
                    "return_hidden_states": False,
                },
            },
            token,
        )
    )
    vector = result.get("mean_embedding")
    while isinstance(vector, list) and len(vector) == 1 and isinstance(vector[0], list):
        vector = vector[0]
    if not isinstance(vector, list):
        raise ValueError("Biohub logits response did not contain a mean embedding")
    return [float(value) for value in vector]


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _post(path: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{BIOHUB_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise urllib.error.URLError("Biohub request failed")
        body = response.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("Biohub response exceeded size limit")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("Biohub response must be an object")
    return value


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    if not denominator:
        raise ValueError("Biohub returned a zero embedding")
    return max(-1.0, min(1.0, numerator / denominator))


def _changed_positions(reference: str, alternate: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for index in range(max(len(reference), len(alternate))):
        ref = reference[index] if index < len(reference) else None
        alt = alternate[index] if index < len(alternate) else None
        if ref != alt:
            changes.append({"position": index + 1, "reference": ref, "alternate": alt})
    return changes


def _unavailable(query_scope: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        "status": "source_unavailable",
        "provider": "biohub",
        "reason_code": reason_code,
        "evidence_envelope": evidence_envelope.not_assessed(
            operation="biohub.compare_protein_embeddings",
            reason=reason_code,
            query_scope=query_scope,
            coverage={"consulted_sources": [], "source_status": "unavailable"},
            guidance=["not_assessed:retry_external_source_or_use_another_source"],
        ),
    }
