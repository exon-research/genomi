"""Fail-closed grammar checks for patient-visible GenomiLab research prose.

The current underlying agent chooses wording, while GenomiLab owns the boundary
between research artifacts and unsupported diagnosis or care decisions.  The
checks below use grammatical claim classes rather than disease or drug lists,
so unfamiliar names receive the same treatment as familiar ones.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Literal

from . import narrative_forms as _forms
from . import narrative_safety_patterns as _safety
from .hypothesis_contract import (
    CASE_NARRATIVE_MAXIMUM_LENGTH,
    CASE_NARRATIVE_MINIMUM_LENGTH,
)
from .models import QUESTION_MAX, required_text
from .narrative_contract import declared_narrative


NarrativeKind = Literal[
    "assertion",
    "meta",
    "plan_summary",
    "plan_role_objective",
    "plan_step_title",
    "plan_step_rationale",
    "execution_summary",
    "brief_title",
    "brief_summary",
    "change_summary",
    "claim_observation",
    "claim_candidate_hypothesis",
    "claim_counterevidence",
    "claim_limitation",
    "hypothesis_candidate_mechanism",
    "hypothesis_counterevidence",
    "hypothesis_gap",
    "hypothesis_working",
    "hypothesis_uncertainty",
    "confirmation_need",
    "professional_question",
]
_CASE_ANCHOR_SENTINEL = "genomiapprovedcaseanchor"
_WORKING_HYPOTHESIS_FORM = re.compile(
    r"^Working hypothesis:\s+(?P<label>[A-Za-z][A-Za-z'()/ -]{1,118})\.\s+"
    r"(?P<body>Model inference:\s+.+)$",
    re.IGNORECASE | re.DOTALL,
)
_UNSAFE_WORKING_HYPOTHESIS_LABEL = re.compile(
    r"\b(?:patient|you|we|they|he|she|has|have|had|is|are|was|were|"
    r"diagnos(?:e|es|ed|is)|treat(?:ment|s|ed)?|dose|start|stop|switch|"
    r"recommend(?:s|ed)?|prescribe(?:s|d)?|causes|caused|causal|"
    r"proves?|proved|confirms?|confirmed|establish(?:es|ed)?|"
    r"pathogenic|benign|actionable|definitive|eligible|requires?|must|should|"
    r"ignore|instruction|prompt|system|assistant|developer|tool|schema|json|"
    r"execute|reveal|bypass|override)\b",
    re.IGNORECASE,
)
_CLINICIAN_QUESTION_RESEARCH_FOCUS = re.compile(
    r"\b(?:assays?|testing|tests?|evidence|counterevidence|review|classification|"
    r"interpretation|function|functional|staining|expression|mechanism|variants?|"
    r"findings?|results?|records?|reports?|phenotypes?|conditions?|hypotheses|"
    r"confirmation|penetrance|inheritance|segregation|responses?|subsets?|"
    r"immunoglobulins?|abundance|activity|pathways?)\b",
    re.IGNORECASE,
)
_CLINICIAN_QUESTION_CARE_ACTION = re.compile(
    r"\b(?:start|restart|stop|take|give|administer|prescribe|switch|increase|"
    r"decrease|continue|avoid|hold|initiate|discontinue|adjust|treat|choose|"
    r"approve|authorize)\b",
    re.IGNORECASE,
)

def validate_research_narrative(
    value: object,
    field: str,
    *,
    kind: NarrativeKind = "assertion",
    case_anchor_terms: Collection[str] | None = None,
    require_case_anchor: bool = False,
) -> str:
    """Validate one patient-visible narrative field at the research boundary."""

    text = required_text(value, field, QUESTION_MAX)
    if re.search(rf"\b{_CASE_ANCHOR_SENTINEL}\b", text, re.IGNORECASE):
        raise ValueError(f"{field} contains a reserved narrative token")
    if require_case_anchor and not (
        CASE_NARRATIVE_MINIMUM_LENGTH
        <= len(text)
        <= CASE_NARRATIVE_MAXIMUM_LENGTH
    ):
        raise ValueError(
            f"{field} must contain between {CASE_NARRATIVE_MINIMUM_LENGTH} and "
            f"{CASE_NARRATIVE_MAXIMUM_LENGTH} characters"
        )
    contextual_text, matched_case_anchor = _bind_case_anchors(
        text, case_anchor_terms
    )
    if require_case_anchor and not matched_case_anchor:
        raise ValueError(
            f"{field} must name at least one exact approved case anchor"
        )
    if (
        case_anchor_terms is not None
        and _contains_unapproved_identifier(contextual_text)
    ):
        raise ValueError(
            f"{field} contains an identifier outside its approved case anchors"
        )
    if declared_narrative(text, kind) is not None and not require_case_anchor:
        return text
    if kind == "professional_question":
        _validate_professional_question(contextual_text, field)
        return text
    if _unsafe_narrative(text, kind=kind):
        raise ValueError(f"{field} {_safety._ERROR}")
    if not _uses_declared_research_form(contextual_text, kind=kind):
        if kind == "confirmation_need" and not _safety._CONFIRMATION_FORM.search(
            contextual_text
        ):
            raise ValueError(
                f"{field} must describe a confirmation or evidence need"
            )
        raise ValueError(f"{field} {_safety._FORM_ERROR}")
    return text


def validate_clinician_question(
    value: object,
    field: str,
    *,
    case_anchor_terms: Collection[str],
) -> str:
    """Validate one case-specific, evidence-anchored clinician question.

    Brief questions are deliberately separate from the historical canned
    professional-question vocabulary. They may use specialist terminology, but
    only when the question names an exact term carried by one of its cited
    records and remains a single open research question rather than a disguised
    diagnosis or care instruction.
    """

    text = required_text(value, field, QUESTION_MAX)
    if not (
        CASE_NARRATIVE_MINIMUM_LENGTH
        <= len(text)
        <= CASE_NARRATIVE_MAXIMUM_LENGTH
    ):
        raise ValueError(
            f"{field} must contain between {CASE_NARRATIVE_MINIMUM_LENGTH} and "
            f"{CASE_NARRATIVE_MAXIMUM_LENGTH} characters"
        )
    if re.search(rf"\b{_CASE_ANCHOR_SENTINEL}\b", text, re.IGNORECASE):
        raise ValueError(f"{field} contains a reserved narrative token")
    contextual_text, matched_case_anchor = _bind_case_anchors(
        text, case_anchor_terms
    )
    if not matched_case_anchor:
        raise ValueError(f"{field} must name at least one exact cited case anchor")
    if _contains_unapproved_identifier(contextual_text):
        raise ValueError(
            f"{field} contains an identifier outside its cited case anchors"
        )

    stripped = contextual_text.strip().lstrip('"\'\u201c\u2018')
    body = contextual_text.rstrip()[:-1] if contextual_text.rstrip().endswith("?") else ""
    if (
        not body
        or not _safety._INTERROGATIVE.match(stripped)
        or _safety._INTERNAL_QUESTION_UNIT.search(body)
    ):
        raise ValueError(f"{field} must contain exactly one genuine clinician question")
    if any(
        pattern.search(contextual_text)
        for pattern in (
            _safety._QUESTION_FORBIDDEN_DELIMITER,
            _safety._QUESTION_EMBEDDED_CONCLUSION,
            _safety._QUESTION_CLINICAL_PREMISE,
            _safety._QUESTION_APPENDED_ASSERTION,
            _safety._QUESTION_APPENDED_CARE_ACTION,
        )
    ):
        raise ValueError(f"{field} cannot contain an appended conclusion or care action")
    if _CLINICIAN_QUESTION_CARE_ACTION.search(contextual_text):
        raise ValueError(f"{field} cannot ask GenomiLab to direct care")
    if not _CLINICIAN_QUESTION_RESEARCH_FOCUS.search(contextual_text):
        raise ValueError(f"{field} must ask a focused evidence or mechanism question")
    return text


def _bind_case_anchors(
    text: str, case_anchor_terms: Collection[str] | None
) -> tuple[str, bool]:
    """Replace exact approved data labels before closed-vocabulary parsing."""

    if case_anchor_terms is None:
        return text, False
    normalized = text
    matched = False
    terms = sorted(
        {
            " ".join(term.strip().split())
            for term in case_anchor_terms
            if isinstance(term, str) and term.strip()
        },
        key=len,
        reverse=True,
    )
    for term in terms:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        )
        normalized, count = pattern.subn(_CASE_ANCHOR_SENTINEL, normalized)
        matched = matched or bool(count)
    return normalized, matched


def _contains_unapproved_identifier(text: str) -> bool:
    return any(
        token.casefold() != _CASE_ANCHOR_SENTINEL
        and (
            token.isdigit()
            or bool(_forms._IDENTIFIER_TOKEN.fullmatch(token))
        )
        for token in _forms._WORD_TOKEN.findall(text)
    )


def _uses_declared_research_form(text: str, *, kind: NarrativeKind) -> bool:
    if _safety._DOUBLE_NEGATED_CLINICAL.search(text):
        return False
    if kind == "hypothesis_working":
        return _working_hypothesis_form(text)
    if kind == "brief_title":
        return bool(
            _safety._SAFE_TITLE.fullmatch(text.strip())
            and _forms._tokens_are_closed(text, _forms._TITLE_WORDS)
        ) and not bool(
            _safety._UNSAFE_TITLE_TERM.search(text)
            or _safety._UNSAFE_TITLE_CLAIM.search(text)
            or (
                _safety._CLINICAL_DISEASE_TOKEN.search(text)
                and re.search(
                    r"\b(?:patient|definitive|assigned|established|confirmed|"
                    r"belongs?|lives?\s+with)\b",
                    text,
                    re.IGNORECASE,
                )
            )
        )
    units = _narrative_units(text)
    if not units:
        return False
    if kind == "claim_observation":
        return _observation_form(units[0]) and all(
            _limitation_form(unit) for unit in units[1:]
        )
    if kind == "claim_candidate_hypothesis":
        return _candidate_form(units[0]) and all(
            _limitation_form(unit) for unit in units[1:]
        )
    if kind == "claim_counterevidence":
        return _counterevidence_form(units[0]) and all(
            _limitation_form(unit) for unit in units[1:]
        )
    if kind == "claim_limitation":
        return all(_limitation_form(unit) for unit in units)
    if kind == "hypothesis_candidate_mechanism":
        return all(_candidate_form(unit) for unit in units)
    if kind == "hypothesis_counterevidence":
        return all(_counterevidence_form(unit) for unit in units)
    if kind == "hypothesis_gap":
        return all(_limitation_form(unit) for unit in units)
    if kind == "hypothesis_uncertainty":
        return all(
            _limitation_form(unit) or _candidate_form(unit) for unit in units
        )
    if kind == "confirmation_need":
        return all(_confirmation_form(unit) for unit in units)
    if kind in {"plan_role_objective", "plan_step_title"}:
        return all(_meta_form(unit) for unit in units)
    if kind in {"plan_summary", "plan_step_rationale"}:
        return all(
            _meta_form(unit) or _assertion_form(unit) for unit in units
        )
    if kind == "execution_summary":
        return all(_execution_form(unit) for unit in units)
    if kind == "brief_summary":
        return all(_research_claim_form(unit) for unit in units)
    if kind == "change_summary":
        return all(_change_form(unit) or _meta_form(unit) for unit in units)
    if kind == "meta":
        return all(_meta_form(unit) for unit in units)
    return all(_assertion_form(unit) for unit in units)


def _working_hypothesis_form(text: str) -> bool:
    """Accept one named, explicitly provisional differential hypothesis.

    The label is a short noun phrase for display, never a patient-level claim.
    The second sentence must independently satisfy the existing closed
    candidate grammar and carry an exact approved profile anchor.
    """

    match = _WORKING_HYPOTHESIS_FORM.fullmatch(text.strip())
    if match is None:
        return False
    label = " ".join(match.group("label").split())
    if (
        len(label) < 2
        or len(label) > 120
        or _UNSAFE_WORKING_HYPOTHESIS_LABEL.search(label)
        or not any(character.isalpha() for character in label)
    ):
        return False
    return _candidate_form(match.group("body"))


def _narrative_units(text: str) -> tuple[str, ...]:
    return tuple(
        unit.strip()
        for unit in _safety._NARRATIVE_UNIT_BOUNDARY.split(text.strip())
        if unit.strip()
    )


def _without_terminal_punctuation(text: str) -> str:
    return text.strip().rstrip(".?!\u201d\u2019\"'").strip()


def _typed_form(text: str) -> tuple[str, str] | None:
    match = _safety._TYPED_PREFIX.match(text.strip())
    if match is None:
        return None
    return match.group("label").casefold(), match.group("body").strip()


def _observation_form(text: str) -> bool:
    typed = _typed_form(text)
    if typed is not None:
        label, body = typed
        if label in {
            "patient record observation",
            "patient-reported observation",
            "patient observation",
            "source evidence",
        }:
            if not _forms._tokens_are_closed(body, _forms._OBSERVATION_WORDS):
                return False
            parts = _research_clauses(body)
            return _observation_core(parts[0], attributed=True) and all(
                _observation_core(part) or _limitation_form(part)
                for part in parts[1:]
            )
        return False
    plain = _without_terminal_punctuation(text)
    if not _forms._tokens_are_closed(plain, _forms._OBSERVATION_WORDS):
        return False
    if _safety._SYNTHETIC_RESEARCH_FRAGMENT.fullmatch(plain):
        return True
    parts = _research_clauses(plain)
    return _observation_core(parts[0]) and all(
        _observation_core(part) or _limitation_form(part) for part in parts[1:]
    )


def _observation_core(text: str, *, attributed: bool = False) -> bool:
    plain = _without_terminal_punctuation(text)
    if not attributed and not _safety._SOURCE_OR_OBSERVATION_SUBJECT.search(plain):
        return False
    return bool(
        _safety._REPORTING_MARKER.search(plain)
        or re.search(r"\bremains?\s+a\s+research\s+observation\b", plain, re.I)
        or re.search(r"\bsupports?\s+a\s+possible\s+research\s+observation\b", plain, re.I)
    )


def _candidate_form(text: str) -> bool:
    typed = _typed_form(text)
    body = typed[1] if typed is not None else text
    if typed is not None and typed[0] != "model inference":
        return False
    if not _forms._tokens_are_closed(body, _forms._CANDIDATE_WORDS):
        return False
    parts = _research_clauses(body)
    if not _candidate_core(parts[0], typed=typed is not None):
        return False
    return all(
        _candidate_core(part, typed=False) or _limitation_form(part)
        for part in parts[1:]
    )


def _candidate_core(text: str, *, typed: bool) -> bool:
    plain = _without_terminal_punctuation(text)
    if not _safety._CANDIDATE_MARKER.search(plain) or _safety._PATIENT_TENTATIVE_DIAGNOSIS.search(
        plain
    ):
        return False
    if typed:
        return bool(
            _safety._CANDIDATE_SUBJECT.search(plain)
            or _safety._IDENTIFIER_CANDIDATE_SUBJECT.search(plain)
            or re.match(r"^(?:this|that|it)\b", plain, re.IGNORECASE)
            or _operation_form(plain)
        )
    return bool(
        _safety._CANDIDATE_SUBJECT.search(plain)
        or _safety._IDENTIFIER_CANDIDATE_SUBJECT.search(plain)
        or re.match(r"^(?:this|that|it)\b", plain, re.IGNORECASE)
    )


def _counterevidence_form(text: str) -> bool:
    typed = _typed_form(text)
    body = typed[1] if typed is not None else text
    if typed is not None and typed[0] != "counterevidence":
        return False
    if not _forms._tokens_are_closed(body, _forms._COUNTEREVIDENCE_WORDS):
        return False
    parts = _research_clauses(body)
    if not _counterevidence_core(parts[0], typed=typed is not None):
        return False
    return all(
        _counterevidence_core(part, typed=False) or _limitation_form(part)
        for part in parts[1:]
    )


def _counterevidence_core(text: str, *, typed: bool) -> bool:
    plain = _without_terminal_punctuation(text)
    return bool(
        _safety._COUNTEREVIDENCE_MARKER.search(plain)
        and (typed or _safety._SOURCE_OR_OBSERVATION_SUBJECT.search(plain))
    )


def _limitation_form(text: str) -> bool:
    typed = _typed_form(text)
    body = typed[1] if typed is not None else text
    if typed is not None and typed[0] not in {
        "evidence limitation",
        "technical limitation",
        "conflict limitation",
        "evidence gap",
        "gap",
        "gaps",
        "uncertainty",
        "conflicts",
    }:
        return False
    if not _forms._tokens_are_closed(body, _forms._LIMITATION_WORDS):
        return False
    plain = _without_terminal_punctuation(body)
    if re.match(
        r"^(?:the\s+)?(?:approved\s+)?(?:context|evidence|finding|result|"
        r"variant|relation|source|record|report|analysis)\s+is\s+consistent\s+"
        r"with\b",
        plain,
        re.IGNORECASE,
    ) and _safety._LIMITATION_MARKER.search(plain):
        return True
    parts = _research_clauses(plain)
    if len(parts) > 1:
        return all(
            _limitation_core(part, label=typed[0] if index == 0 and typed else None)
            for index, part in enumerate(parts)
        )
    return _limitation_core(plain, label=typed[0] if typed is not None else None)


def _limitation_core(text: str, *, label: str | None = None) -> bool:
    plain = _without_terminal_punctuation(text)
    if re.match(
        r"^(?:the\s+)?(?:approved\s+)?(?:context|evidence|finding|result|"
        r"variant|relation|source|record|report|analysis)\s+is\s+consistent\s+"
        r"with\b",
        plain,
        re.IGNORECASE,
    ) and _safety._LIMITATION_MARKER.search(plain):
        return True
    if label == "conflicts":
        return bool(_safety._CONFLICT_MARKER.search(plain))
    if not _safety._LIMITATION_MARKER.search(plain):
        return False
    if _safety._LIMITATION_SUBJECT.search(plain):
        return True
    return bool(
        label in {
            "evidence limitation",
            "technical limitation",
            "conflict limitation",
            "evidence gap",
            "gap",
            "gaps",
            "uncertainty",
        }
        and re.match(r"^(?:the\s+)?(?:approved\s+)?context\b", plain, re.I)
    )


def _assertion_form(text: str) -> bool:
    typed = _typed_form(text)
    if (
        typed is not None
        and typed[0] == "source evidence"
        and _safety._LIMITATION_MARKER.search(typed[1])
    ):
        return True
    return any(
        predicate(text)
        for predicate in (
            _observation_form,
            _candidate_form,
            _counterevidence_form,
            _limitation_form,
            _change_form,
        )
    )


def _research_claim_form(text: str) -> bool:
    return any(
        predicate(text)
        for predicate in (
            _observation_form,
            _candidate_form,
            _counterevidence_form,
            _limitation_form,
        )
    )


def _research_clauses(text: str) -> tuple[str, ...]:
    return tuple(
        part.strip()
        for part in _safety._RESEARCH_CLAUSE_JOIN.split(text.strip())
        if part.strip()
    )


def _operation_form(text: str) -> bool:
    plain = _without_terminal_punctuation(text)
    if plain.casefold() == "review":
        return True
    if plain.casefold().startswith("investigate:"):
        question = plain.split(":", 1)[1].strip()
        try:
            _validate_professional_question(
                question if question.endswith("?") else f"{question}?",
                "investigation question",
            )
        except ValueError:
            return False
        return True
    words = [token.casefold() for token in _forms._WORD_TOKEN.findall(plain)]
    return bool(
        words
        and words[0] in _forms._RESEARCH_OPERATION_VERBS
        and all(word in _forms._RESEARCH_OPERATION_WORDS for word in words)
    )


def _meta_form(text: str) -> bool:
    plain = _without_terminal_punctuation(text)
    if _safety._SYNTHETIC_RESEARCH_FRAGMENT.fullmatch(plain):
        return True
    if _safety._TOOL_FREE_PLAN.search(plain) or _safety._NO_CLINICAL_CONCLUSION.search(plain):
        return True
    if _safety._INDEPENDENT_META.search(plain) and not _safety._UNSAFE_FINITE_CONCLUSION.search(
        plain
    ):
        return True
    if _safety._RESEARCH_GUARDRAIL.search(plain):
        return True
    return _operation_form(plain) or _change_form(plain) or _assertion_form(plain)


def _execution_form(text: str) -> bool:
    plain = _without_terminal_punctuation(text)
    if plain.casefold() in {
        "synthetic host-neutral execution report",
        "the exact accepted request was paused for approval",
    }:
        return True
    return bool(_safety._EXECUTION_FORM.fullmatch(plain))


def _change_form(text: str) -> bool:
    plain = _without_terminal_punctuation(text)
    if plain.casefold() == "no capability calls were made":
        return True
    words = [token.casefold() for token in _forms._WORD_TOKEN.findall(plain)]
    return bool(
        words
        and words[0]
        in {
            "added",
            "clarified",
            "created",
            "initial",
            "prepared",
            "recorded",
            "synthesized",
            "updated",
        }
        and _forms._tokens_are_closed(plain, _forms._CHANGE_WORDS)
    )


def _confirmation_form(text: str) -> bool:
    plain = _without_terminal_punctuation(text)
    if _safety._UNSAFE_FINITE_CONCLUSION.search(plain) or _safety._UNSAFE_CONFIRMATION_TARGET.search(
        plain
    ):
        return False
    return any(
        pattern.fullmatch(plain)
        for pattern in (
            _forms._CONFIRMATION_NOUN_CLOSED,
            _forms._CONFIRMATION_WHETHER_CLOSED,
            _forms._CONFIRMATION_REVIEW_CLOSED,
            _forms._CONFIRMATION_IDENTITY_CLOSED,
            _forms._CONFIRMATION_OBTAIN_CLOSED,
            _forms._CONFIRMATION_REQUIREMENT_CLOSED,
            _forms._CONFIRMATION_NONCAUSAL_CLOSED,
        )
    )


def _unsafe_narrative(text: str, *, kind: NarrativeKind) -> bool:
    if (
        _safety._NO_CONFIRMATION_REQUIRED.search(text)
        or _safety._CONFIRMATION_DISAVOWAL.search(text)
        or _safety._ASSERTION_LAUNDERING.search(text)
        or _safety._PATIENT_MODAL_ACTION.search(text)
        or _safety._PATIENT_NEEDS_PRODUCT.search(text)
        or _safety._IMPERATIVE_DIAGNOSIS_OR_TREATMENT_REVIEW.search(text)
        or _safety._LABELLED_CARE_DECISION.search(text)
        or _safety._BEST_TREATMENT.search(text)
        or _safety._PATIENT_BENEFIT.search(text)
        or _safety._ELIGIBILITY.search(text)
    ):
        return True

    for match in _safety._IMPERATIVE_CARE_ACTION.finditer(text):
        if kind in _safety._RESEARCH_PROCESS_KINDS and _safety._SAFE_RESEARCH_OBJECT.search(
            match.group("object")
        ):
            continue
        return True
    for pattern in (_safety._DIRECT_RECOMMENDATION, _safety._LABELLED_RECOMMENDATION):
        for match in pattern.finditer(text):
            if not _safety._SAFE_RECOMMENDATION_OBJECT.search(match.group("object")):
                return True
    for pattern in (_safety._PRODUCT_MODAL_ACTION, _safety._CARE_PREDICATE):
        for match in pattern.finditer(text):
            if not _safety._SAFE_PROCESS_SUBJECT.search(match.group("subject")):
                return True
    for match in _safety._DOSING_STATEMENT.finditer(text):
        if not _is_directly_source_attributed(text, match):
            return True
    for match in _safety._DECISION_TO_CARE.finditer(text):
        if _safety._CONFIRMATION_BEFORE_CARE.search(match.group(0)):
            continue
        decision_context = text[max(0, match.start() - 45) : match.end()]
        if _safety._DOUBLE_NEGATIVE_DECISION.search(decision_context):
            return True
        if not _safety._NEGATED_DECISION.search(decision_context):
            return True

    clinical_claim_patterns = (
        _safety._PATIENT_DIAGNOSIS,
        _safety._DIAGNOSIS_ASSERTION,
        _safety._DIRECT_DIAGNOSIS_REQUEST,
        _safety._EVIDENCE_ESTABLISHES,
        _safety._THIS_ESTABLISHES,
        _safety._EVIDENCE_SUPPORTS_DIAGNOSIS,
        _safety._CLINICAL_STATUS,
        _safety._NOMINAL_CLINICAL_STATUS,
        _safety._CLASSIFICATION_LABEL,
        _safety._CONFIRMED_FACT,
        _safety._MOLECULAR_CAUSALITY,
        _safety._CAUSAL_ADJECTIVE,
        _safety._REVERSED_PATIENT_DIAGNOSIS,
        _safety._ALTERNATE_CAUSALITY,
        _safety._ALTERNATE_CLINICAL_STATUS,
        _safety._ALTERNATE_CARE_DECISION,
    )
    for pattern in clinical_claim_patterns:
        for match in pattern.finditer(text):
            if _is_directly_unresolved(text, match):
                continue
            if _is_directly_source_attributed(text, match):
                continue
            if _is_scoped_to_reported_observation(text, match):
                continue
            if kind in _safety._RESEARCH_PROCESS_KINDS and _is_research_target(text, match):
                continue
            return True
    return False


def _validate_professional_question(text: str, field: str) -> None:
    stripped = text.strip().lstrip('"\'\u201c\u2018')
    if not text.rstrip().endswith("?") or not _safety._INTERROGATIVE.match(stripped):
        raise ValueError(f"{field} must be a genuine professional question")
    body = text.rstrip()[:-1]
    if _safety._INTERNAL_QUESTION_UNIT.search(body):
        raise ValueError(f"{field} must contain exactly one professional question")
    if not any(
        pattern.fullmatch(text.strip())
        for pattern in (
            _forms._QUESTION_CAN_COULD,
            _forms._QUESTION_WHAT,
            _forms._QUESTION_IS,
            _forms._QUESTION_SHOULD,
            _forms._QUESTION_DOES,
        )
    ):
        raise ValueError(f"{field} must use a declared open-question form")


def _is_directly_unresolved(text: str, claim: re.Match[str]) -> bool:
    start, end, clause = _clause_window(text, claim.start(), claim.end())
    for pattern in _safety._SAFE_UNRESOLVED_CLAIMS:
        for safe in pattern.finditer(clause):
            safe_start = start + safe.start()
            safe_end = start + safe.end()
            if safe_start <= claim.end() and safe_end >= claim.start():
                return True
    governed_prefix = clause[: claim.end() - start]
    if re.search(
        r"\bno\s+(?:causal\s+link|diagnosis|diagnostic\s+conclusion|clinical\s+"
        r"conclusion|clinical\s+claim)\b[^.!?;]{0,120}\b(?:is|are|was|were)\s+"
        r"(?:established|confirmed|proved|demonstrated)\b",
        governed_prefix,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:approved\s+)?(?:context|evidence|record|source|relation|analysis|"
        r"data)\s+(?:does|do|did|can|cannot|can't|could|couldn't|has|have|had)\s+"
        r"(?:not|n't)\s+(?:establish|confirm|prove|demonstrate|show|mean|"
        r"support|indicate|warrant|justify|require|rule\s+in)\b[^.!?;]{0,120}$",
        governed_prefix,
        re.IGNORECASE,
    ):
        return True
    return False


def _is_scoped_to_reported_observation(
    text: str, claim: re.Match[str]
) -> bool:
    """Allow an evidentiary verb only when it establishes a reported fact."""

    _, end, clause = _clause_window(text, claim.start(), claim.end())
    tail = text[claim.end() : end]
    return bool(
        re.match(r"\s+only\s+that\b", tail, re.IGNORECASE)
        and re.search(
            r"\b(?:report|record|source|study|paper|publication|database|"
            r"laboratory)\b[^.!?;]{0,80}\b(?:reports?|reported|records?|"
            r"recorded|states?|stated|lists?|listed|labels?|labelled|labeled|"
            r"documents?|documented)\b",
            clause,
            re.IGNORECASE,
        )
    )


def _is_directly_source_attributed(text: str, claim: re.Match[str]) -> bool:
    """Allow only an attribution verb immediately governing the clinical claim."""

    for source in _safety._SOURCE_ATTRIBUTION.finditer(text, 0, claim.start()):
        bridge = text[source.end() : claim.start()]
        if len(bridge) <= 24 and re.fullmatch(
            r"\s*(?:that\s+)?(?:(?:the|a|an|this|that)\s+)?", bridge, re.IGNORECASE
        ):
            return True
    return False


def _is_research_target(text: str, claim: re.Match[str]) -> bool:
    start, _, clause = _clause_window(text, claim.start(), claim.end())
    prefix = clause[: claim.start() - start]
    return bool(
        re.search(
            r"\b(?:review|assess|investigate|compare|retrieve|evaluate|examine|"
            r"verify|validate|research|question|test|determine|clarify)\b"
            r"[^.!?;]{0,80}$",
            prefix,
            re.IGNORECASE,
        )
    )


def _clause_window(text: str, start: int, end: int) -> tuple[int, int, str]:
    prior = [match.end() for match in _safety._CLAUSE_BOUNDARY.finditer(text, 0, start)]
    following = _safety._CLAUSE_BOUNDARY.search(text, end)
    clause_start = prior[-1] if prior else 0
    clause_end = following.start() if following else len(text)
    return clause_start, clause_end, text[clause_start:clause_end]
