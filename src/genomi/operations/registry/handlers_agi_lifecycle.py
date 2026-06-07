from __future__ import annotations

from ...runtime import context as runtime_context
from .coerce import _bool, _list_str, _optional_path, _optional_str, _str
from .errors import JsonObject, OperationError
from .handlers_admin_next_actions import read_agi_skill_next_action, with_next_action


def _genomi_describe_context(_: JsonObject) -> JsonObject:
    context = runtime_context.describe_context()
    access = context.get("active_genome_index_access") or {}
    approved = bool(access.get("approved")) if isinstance(access, dict) else False
    has_active = bool(context.get("has_active_genome_index"))
    has_genome_data = bool(context.get("users")) or bool(context.get("session_agis")) or has_active
    # Point at the AGI skill only when there is genome data to work with but it
    # is not already active + approved (so the host needs the invoke-only
    # selection/approval tools). When the default user's AGI is auto-selected
    # and approved, downstream capability tools read it directly — no pointer.
    if has_genome_data and not (has_active and approved):
        context = with_next_action(
            context,
            read_agi_skill_next_action(
                "Genome data exists for this machine but is not active and approved this "
                "session; selecting a profile or approving access for a personal-data "
                "question uses invoke-only active_genome_index.* tools."
            ),
        )
    return context


def _genomi_approve_agi_access(params: JsonObject) -> JsonObject:
    if not _bool(params, "approved_by_user"):
        raise OperationError(
            "approval_required",
            "Set approved_by_user=true only after the user explicitly approves Active Genome Index access for this chat.",
        )
    try:
        return runtime_context.approve_agi_access(
            agi_id=params.get("agi_id"),
            source=params.get("source"),
            user_id=params.get("user_id"),
            nickname=params.get("nickname"),
            reason=params.get("reason"),
        )
    except KeyError as exc:
        raise OperationError("missing_context", f"Known genomi agi not found for access target: {exc}") from exc


def _genomi_revoke_agi_access(params: JsonObject) -> JsonObject:
    return runtime_context.revoke_agi_access(agi_id=params.get("agi_id"))


def _genomi_remove_agi(params: JsonObject) -> JsonObject:
    if not _bool(params, "confirmed_by_user"):
        raise OperationError(
            "confirmation_required",
            "confirmed_by_user is required.",
        )
    agi_id = _optional_str(params, "agi_id")
    agi_ids = _list_str(params, "agi_ids")
    user_id = _optional_str(params, "user_id")
    user_ids = _list_str(params, "user_ids")
    nickname = _optional_str(params, "nickname")
    nicknames = _list_str(params, "nicknames")
    source = _optional_path(params, "source")
    sources_value = params.get("sources")
    if sources_value is None:
        sources: list[str] = []
    elif isinstance(sources_value, list) and all(isinstance(item, str) and item for item in sources_value):
        sources = list(sources_value)
    else:
        raise OperationError("invalid_params", "sources must be a string array.")
    if not agi_id and not agi_ids and not user_id and not user_ids and not nickname and not nicknames and source is None and not sources:
        raise OperationError("invalid_params", "Provide agi_id, agi_ids, user_id, user_ids, nickname, nicknames, source, or sources.")
    try:
        return runtime_context.remove_active_genome_index(
            agi_id=agi_id,
            agi_ids=agi_ids,
            source=source,
            sources=sources,
            user_id=user_id,
            user_ids=user_ids,
            nickname=nickname,
            nicknames=nicknames,
            remove_artifacts=_bool(params, "remove_artifacts", True),
        )
    except KeyError as exc:
        raise OperationError("missing_context", f"Known Active Genome Index or user not found for removal target: {exc}") from exc


def _genomi_list_agis(_: JsonObject) -> JsonObject:
    return runtime_context.list_active_genome_index_inventory()


def _genomi_select_user(params: JsonObject) -> JsonObject:
    target = _str(params, "user_id", "") or _str(params, "nickname", "")
    if not target:
        raise OperationError("invalid_params", "Provide user_id or nickname.")
    try:
        user = runtime_context.select_user(target)
    except KeyError as exc:
        raise OperationError("missing_context", f"Known user not found: {target}") from exc
    return {
        "status": "completed",
        "user": runtime_context.describe_user(user),
        "context": runtime_context.describe_context(),
    }


def _genomi_rename_user(params: JsonObject) -> JsonObject:
    target = _str(params, "user_id", "") or _str(params, "nickname", "")
    if not target:
        raise OperationError("invalid_params", "Provide user_id or current nickname.")
    try:
        user = runtime_context.rename_user(target, _str(params, "new_nickname"))
    except KeyError as exc:
        raise OperationError("missing_context", f"Known user not found: {target}") from exc
    except ValueError as exc:
        raise OperationError("invalid_params", str(exc)) from exc
    return {"status": "completed", "user": runtime_context.describe_user(user), "context": runtime_context.describe_context()}


def _genomi_assign_user_genome(params: JsonObject) -> JsonObject:
    try:
        user = runtime_context.assign_user_genome(
            user_id=params.get("user_id"),
            nickname=params.get("nickname"),
            agi_id=params.get("agi_id"),
            source=params.get("source"),
            db=_optional_path(params, "db"),
            agi_path=_optional_path(params, "agi_path"),
            matches=_optional_path(params, "matches"),
            shared_db=_optional_path(params, "shared_db"),
            reference_fasta=_optional_path(params, "reference_fasta"),
            genotype_reference_fasta=_optional_path(params, "genotype_reference_fasta"),
            genome_build=params.get("genome_build"),
            set_active=_bool(params, "set_active", True),
            set_default_user=_bool(params, "set_default_user"),
        )
    except KeyError as exc:
        raise OperationError("missing_context", f"Known genomi agi not found: {exc}") from exc
    except ValueError as exc:
        raise OperationError("invalid_params", str(exc)) from exc
    return {"status": "completed", "user": runtime_context.describe_user(user), "context": runtime_context.describe_context()}


def _genomi_set_default_user(params: JsonObject) -> JsonObject:
    target = _str(params, "user_id", "") or _str(params, "nickname", "")
    if not target:
        raise OperationError("invalid_params", "Provide user_id or nickname.")
    try:
        user = runtime_context.set_default_user(target)
    except KeyError as exc:
        raise OperationError("missing_context", f"Known user not found: {target}") from exc
    return {"status": "completed", "default_user": runtime_context.describe_user(user), "context": runtime_context.describe_context()}


def _genomi_clear_default_user(_: JsonObject) -> JsonObject:
    return runtime_context.clear_default_user()


def _genomi_clear_selection(params: JsonObject) -> JsonObject:
    return runtime_context.clear_active_genome_index(forget_active_genome_indexes=_bool(params, "forget_active_genome_indexes"))
