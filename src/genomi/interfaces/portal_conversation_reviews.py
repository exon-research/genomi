from __future__ import annotations

import json
import re
from typing import Any

from . import portal_turns

JsonObject = dict[str, Any]

REVIEW_KIND = "conversation_review"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATE_VERIFYING = "verifying"
STATE_CLEAR = "clear"
STATE_FINDINGS = "findings"
STATE_INCONCLUSIVE = "inconclusive"
PUBLIC_STATUSES = {STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED}
PUBLIC_STATES = {STATE_VERIFYING, STATE_CLEAR, STATE_FINDINGS, STATE_INCONCLUSIVE}
PUBLIC_VERDICTS = {"pass", "warning", "error", "inconclusive"}


def source_messages(messages: Any, *, max_messages: int = 24) -> list[JsonObject]:
    items = messages if isinstance(messages, list) else []
    records: list[JsonObject] = []
    for message in items:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        if role not in {"user", "assistant", "tool"}:
            continue
        message_id = _safe_text(message.get("id"))
        if not message_id:
            continue
        if role == "tool":
            text = _tool_summary(message.get("event"))
            source_role = "work_step"
        else:
            text = portal_turns.prompt_safe_text(str(message.get("text") or "")).strip()[:4000]
            source_role = role
        if not text:
            continue
        record: JsonObject = {
            "message_id": message_id,
            "role": source_role,
            "text": text,
        }
        attachments = _attachment_summaries(message.get("selected_evidence"))
        if attachments:
            record["attached_material"] = attachments
        records.append(record)
    limit = max(1, int(max_messages))
    return records[-limit:]


def review_prompt(messages: list[JsonObject]) -> str:
    transcript = "\n\n".join(_prompt_message(item) for item in messages)
    return (
        "You are the independent reviewer for a Genomi research conversation.\n"
        "Audit the work against the user's stated task and the evidence visible in the transcript. "
        "Check factual consistency, citation or source traceability, numerical claims, task-boundary adherence, "
        "genomics evidence limits, privacy boundaries, and whether conclusions overstate the available evidence.\n"
        "Do not continue the research task and do not invent missing evidence. Review only the supplied transcript.\n"
        "Write findings in ordinary research language. Do not expose tool names, operation names, internal field names, "
        "message ids, run ids, tool-call ids, or transport terminology in claim, evidence, recommendation, or summary text. "
        "Use source_message_id only in its dedicated JSON field.\n"
        "Return exactly one JSON object and no Markdown or commentary. Use this schema:\n"
        '{"state":"clear|findings|inconclusive","summary":"short user-facing summary",'
        '"findings":[{"verdict":"pass|warning|error|inconclusive","claim":"claim or step reviewed",'
        '"evidence":"why the verdict follows from the transcript","recommendation":"specific correction or next check",'
        '"source_message_id":"one supplied message_id or empty"}]}\n'
        "Use state=clear only when no warning or error remains. Omit pass findings unless they clarify an important boundary. "
        "Keep findings distinct and return at most 12.\n\n"
        "# Conversation under review\n"
        f"{transcript}\n"
    )


def pending_review(*, review_run_id: str, source_message_ids: list[str], started_at: str) -> JsonObject:
    return {
        "kind": REVIEW_KIND,
        "review_run_id": _safe_text(review_run_id),
        "status": STATUS_RUNNING,
        "state": STATE_VERIFYING,
        "started_at": _safe_text(started_at),
        "source_message_ids": _safe_id_list(source_message_ids),
        "summary": "Reviewer is checking this conversation.",
        "findings": [],
    }


def completed_review(
    *,
    review_run_id: str,
    output: str,
    source_message_ids: list[str],
    started_at: str,
    completed_at: str,
) -> JsonObject:
    parsed = _parse_review_output(output, allowed_message_ids=set(_safe_id_list(source_message_ids)))
    return {
        "kind": REVIEW_KIND,
        "review_run_id": _safe_text(review_run_id),
        "status": STATUS_COMPLETED,
        "state": parsed["state"],
        "started_at": _safe_text(started_at),
        "completed_at": _safe_text(completed_at),
        "source_message_ids": _safe_id_list(source_message_ids),
        "summary": parsed["summary"],
        "check_count": len(parsed["findings"]),
        "findings": parsed["findings"],
        "limitations": [
            "This reviewer checks the supplied conversation and evidence boundaries; it is not clinical validation.",
        ],
    }


def failed_review(
    *,
    review_run_id: str,
    source_message_ids: list[str],
    started_at: str,
    completed_at: str,
    error: str,
) -> JsonObject:
    return {
        "kind": REVIEW_KIND,
        "review_run_id": _safe_text(review_run_id),
        "status": STATUS_FAILED,
        "state": STATE_INCONCLUSIVE,
        "started_at": _safe_text(started_at),
        "completed_at": _safe_text(completed_at),
        "source_message_ids": _safe_id_list(source_message_ids),
        "summary": "Reviewer could not complete this check.",
        "error": portal_turns.prompt_safe_text(str(error or "Review failed."))[:500],
        "findings": [],
    }


def public_review(value: Any) -> JsonObject | None:
    source = value if isinstance(value, dict) else {}
    status = _safe_text(source.get("status"))
    state = _safe_text(source.get("state"))
    if status not in PUBLIC_STATUSES or state not in PUBLIC_STATES:
        return None
    findings = [_public_finding(item) for item in source.get("findings", [])] if isinstance(source.get("findings"), list) else []
    findings = [item for item in findings if item is not None][:12]
    result: JsonObject = {
        "kind": REVIEW_KIND,
        "review_run_id": _safe_text(source.get("review_run_id")),
        "status": status,
        "state": state,
        "started_at": _safe_text(source.get("started_at")),
        "completed_at": _safe_text(source.get("completed_at")),
        "summary": _review_text(source.get("summary"), limit=500),
        "check_count": len(findings),
        "findings": findings,
        "limitations": _safe_text_list(source.get("limitations")),
    }
    error = portal_turns.prompt_safe_text(str(source.get("error") or "")).strip()[:500]
    if error:
        result["error"] = error
    return _compact(result)


def public_reviews(value: Any) -> list[JsonObject]:
    items = value if isinstance(value, list) else []
    reviews = [public_review(item) for item in items]
    return [item for item in reviews if item is not None][-8:]


def _parse_review_output(output: str, *, allowed_message_ids: set[str]) -> JsonObject:
    payload = _json_object(output)
    if payload is None:
        return {
            "state": STATE_INCONCLUSIVE,
            "summary": "Reviewer returned an unreadable result.",
            "findings": [],
        }
    findings = [
        item
        for item in (_finding(value, index, allowed_message_ids) for index, value in enumerate(payload.get("findings", [])))
        if item is not None
    ][:12]
    requested_state = _safe_text(payload.get("state"))
    has_issue = any(item["verdict"] in {"warning", "error"} for item in findings)
    has_inconclusive = any(item["verdict"] == "inconclusive" for item in findings)
    if has_issue:
        state = STATE_FINDINGS
    elif requested_state == STATE_INCONCLUSIVE or has_inconclusive:
        state = STATE_INCONCLUSIVE
    else:
        state = STATE_CLEAR
    summary = _review_text(payload.get("summary"), limit=500)
    if not summary:
        summary = {
            STATE_CLEAR: "No issues found in the reviewed conversation.",
            STATE_FINDINGS: f"Reviewer found {sum(item['verdict'] in {'warning', 'error'} for item in findings)} issue(s).",
            STATE_INCONCLUSIVE: "Reviewer could not verify all reviewed claims.",
        }[state]
    return {"state": state, "summary": summary, "findings": findings}


def _finding(value: Any, index: int, allowed_message_ids: set[str]) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    verdict = _safe_text(value.get("verdict"))
    if verdict not in PUBLIC_VERDICTS:
        return None
    claim = _review_text(value.get("claim"), limit=600)
    evidence = _review_text(value.get("evidence"), limit=1200)
    recommendation = _review_text(value.get("recommendation"), limit=800)
    if not claim and not evidence:
        return None
    source_message_id = _safe_text(value.get("source_message_id"))
    finding: JsonObject = {
        "finding_id": f"finding_{index + 1}",
        "verdict": verdict,
        "claim": claim or "Reviewed claim",
        "evidence": evidence,
        "recommendation": recommendation,
    }
    if source_message_id in allowed_message_ids:
        finding["source_ref"] = {"kind": "message", "message_id": source_message_id}
    return _compact(finding)


def _public_finding(value: Any) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    verdict = _safe_text(value.get("verdict"))
    if verdict not in PUBLIC_VERDICTS:
        return None
    source_ref = value.get("source_ref") if isinstance(value.get("source_ref"), dict) else {}
    result: JsonObject = {
        "finding_id": _safe_text(value.get("finding_id")),
        "verdict": verdict,
        "claim": _review_text(value.get("claim"), limit=600),
        "evidence": _review_text(value.get("evidence"), limit=1200),
        "recommendation": _review_text(value.get("recommendation"), limit=800),
    }
    message_id = _safe_text(source_ref.get("message_id"))
    if source_ref.get("kind") == "message" and message_id:
        result["source_ref"] = {"kind": "message", "message_id": message_id}
    return _compact(result)


def _prompt_message(item: JsonObject) -> str:
    attached = item.get("attached_material") if isinstance(item.get("attached_material"), list) else []
    attachment_text = ""
    if attached:
        attachment_text = "\nAttached material: " + "; ".join(
            f"{entry.get('label')}: {entry.get('summary', '')}" for entry in attached if isinstance(entry, dict)
        )
    return (
        f"[message_id={item.get('message_id')}] {str(item.get('role') or '').upper()}\n"
        f"{item.get('text')}{attachment_text}"
    )


def _tool_summary(value: Any) -> str:
    event = value if isinstance(value, dict) else {}
    event_type = _safe_text(event.get("type"))
    name = portal_turns.prompt_safe_text(str(event.get("name") or "Research step")).strip()[:160]
    if event_type == "tool_call":
        return f"Started research step: {name}"
    if event_type == "tool_result":
        status = "failed" if bool(event.get("isError")) else "completed"
        content = portal_turns.prompt_safe_text(str(event.get("content") or "")).strip()[:900]
        return f"Research step {status}: {name}" + (f"\n{content}" if content else "")
    if event_type == "error":
        message = portal_turns.prompt_safe_text(str(event.get("message") or event.get("content") or "")).strip()[:900]
        return f"Research step failed: {name}" + (f"\n{message}" if message else "")
    return ""


def _attachment_summaries(value: Any) -> list[JsonObject]:
    summaries: list[JsonObject] = []
    for item in portal_turns.clean_selected_evidence(value)[:4]:
        label = portal_turns.prompt_safe_text(str(item.get("label") or "Attached material")).strip()[:160]
        summary = portal_turns.prompt_safe_text(str(item.get("summary") or "")).strip()[:320]
        entry: JsonObject = {"label": label or "Attached material"}
        if summary:
            entry["summary"] = summary
        summaries.append(entry)
    return summaries


def _json_object(text: str) -> JsonObject | None:
    clean = str(text or "").strip()
    candidates = [clean]
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", clean, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1))
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        candidates.append(clean[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _safe_id_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    result: list[str] = []
    for item in items:
        clean = _safe_text(item)
        if clean and clean not in result:
            result.append(clean)
    return result[:32]


def _safe_text_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    return [portal_turns.prompt_safe_text(str(item)).strip()[:500] for item in items if str(item).strip()][:8]


def _safe_text(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()[:240]


def _review_text(value: Any, *, limit: int) -> str:
    text = portal_turns.prompt_safe_text(str(value or "")).strip()
    replacements = {
        "genomi_describe_context": "active-genome context result",
        "active_genome_index": "active genome",
        "active_agi_id": "active genome identifier",
        "agi_id": "genome identifier",
        "agi_source_format": "source format",
        "agi_source_kind": "source type",
        "source_format": "source format",
        "genome_build": "genome build",
        "variants_ready": "variant data ready",
        "consumer_genotype_array": "consumer genotype array",
    }
    for internal, label in replacements.items():
        text = re.sub(rf"\b{re.escape(internal)}\b", label, text, flags=re.IGNORECASE)
    text = re.sub(r"\bmcp__[A-Za-z0-9_.-]+\b", "research source", text)
    text = re.sub(r"\s*\([0-9a-f]{8,}\)", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _compact(value: JsonObject) -> JsonObject:
    return {
        key: child
        for key, child in value.items()
        if child not in (None, "", [], {})
    }
