"""Deterministic, explicitly nonclinical CTLA4 longitudinal demo fixture."""

from __future__ import annotations

from ..evidence import envelope as evidence_envelope
from .artifact_validation import BRIEF_CLINICAL_BOUNDARY
from .brief_provenance import derive_brief_modality_badges
from .models import JsonObject
from .store import GenomiLabStore


DEMO_USER_ID = "genomilab-synthetic-ctla4-demo"
DEMO_DISPLAY_NAME = "Synthetic CTLA4 investigation"
DEMO_QUESTION = (
    "Could the synthetic Crohn, recurrent infection, immune thrombocytopenia, "
    "and CTLA4 Q76H records be connected?"
)
DEMO_SESSION_ID = "portal:synthetic-ctla4-demo:main-investigator"
DEMO_AGI_ID = "agi-synthetic-ctla4-q76h"
DEMO_AGI_SNAPSHOT_ID = "agi-snapshot-synthetic-ctla4-q76h-v1"


def seed_ctla4_demo(store: GenomiLabStore) -> JsonObject:
    """Create the exact three-cycle scripted demo without external execution."""

    workspace = store.open_workspace(DEMO_USER_ID, DEMO_DISPLAY_NAME)
    investigation = next(
        (
            item
            for item in store.list_investigations(DEMO_USER_ID)
            if item.get("question") == DEMO_QUESTION
        ),
        None,
    )
    if investigation is None:
        investigation = store.create_investigation(
            DEMO_USER_ID,
            question=DEMO_QUESTION,
            disease_scope="Synthetic CTLA4-associated immune dysregulation review",
        )
    investigation_id = str(investigation["investigation_id"])

    _ensure_stage_snapshot(
        store,
        investigation_id,
        stage=1,
        title="Synthetic initial history and genome record",
        facts=[
            _patient_fact(
                "condition",
                "Crohn's disease",
                "Synthetic history records Crohn's disease.",
            ),
            _patient_fact(
                "phenotype",
                "Recurrent sinus and chest infections",
                "Synthetic history records recurrent sinus and chest infections.",
            ),
            _patient_fact(
                "phenotype",
                "Very low platelets during adolescence",
                "Synthetic history records very low platelets during adolescence.",
            ),
            _patient_fact(
                "medication",
                "Possible medication contribution",
                "The synthetic patient asks whether immune-suppressing medication contributes to infection.",
            ),
            {
                "modality": "reported_germline_finding",
                "label": "CTLA4 p.Gln76His (Q76H), heterozygous VUS",
                "original_wording": "Synthetic AGI record: heterozygous CTLA4 c.228G>C, p.Gln76His (Q76H); variant of uncertain significance; clinical confirmation required.",
                "reported_variant": "CTLA4 c.228G>C (p.Gln76His; Q76H)",
                "gene": "CTLA4",
                "reported_classification": "variant of uncertain significance",
                "source_class": "issued_record",
                "verification_state": "record_confirmed",
            },
        ],
    )
    cycle_one = _cycle_one(store, investigation_id)

    _ensure_stage_snapshot(
        store,
        investigation_id,
        stage=2,
        title="Synthetic chronology and immune testing return",
        facts=[
            _record_fact(
                "condition",
                "Pneumonia before first biologic",
                "Synthetic record documents pneumonia before the first biologic.",
            ),
            _record_fact(
                "biomarker",
                "Low immunoglobulins before rituximab",
                "Synthetic record documents low immunoglobulins before rituximab.",
            ),
            _record_fact(
                "biomarker",
                "Persistently low IgG and IgA",
                "Synthetic follow-up tests record persistently low IgG and IgA.",
            ),
            _record_fact(
                "biomarker",
                "Inadequate pneumococcal antibody response",
                "Synthetic test records an inadequate pneumococcal antibody response.",
            ),
            _record_fact(
                "biomarker",
                "Abnormal B-cell maturation",
                "Synthetic flow-cytometry report records abnormal B-cell maturation.",
            ),
            _record_fact(
                "pathology",
                "Possible immune-mediated enteropathy",
                "Synthetic pathology review raises immune-mediated enteropathy as a possibility.",
            ),
        ],
    )
    cycle_two = _cycle_two(store, investigation_id)

    _ensure_stage_snapshot(
        store,
        investigation_id,
        stage=3,
        title="Synthetic staining and clinical confirmation return",
        facts=[
            _record_fact(
                "reported_germline_finding",
                "Clinical confirmation of CTLA4 Q76H as VUS",
                "Synthetic clinical laboratory confirms CTLA4 Q76H while retaining variant-of-uncertain-significance classification.",
                gene="CTLA4",
                variant="CTLA4 c.228G>C (p.Gln76His; Q76H)",
                classification="variant of uncertain significance",
            ),
            _record_fact(
                "biomarker",
                "CTLA4 staining in control range",
                "Synthetic report records CTLA4 staining in the laboratory control range.",
            ),
            _record_fact(
                "biomarker",
                "LRBA expression in control range",
                "Synthetic report records LRBA expression in the laboratory control range.",
            ),
        ],
    )
    _ensure_stage_snapshot(
        store,
        investigation_id,
        stage=4,
        title="Synthetic functional assay and carrier return",
        facts=[
            _record_fact(
                "biomarker",
                "Repeatedly reduced CTLA4 transendocytosis",
                "Synthetic reference laboratory reports reduced CTLA4 transendocytosis in two runs under the reported assay conditions.",
            ),
            _record_fact(
                "family_history",
                "Apparently healthy maternal Q76H carrier",
                "Synthetic family report records the same Q76H variant in an apparently healthy mother.",
            ),
        ],
    )
    cycle_three = _cycle_three(store, investigation_id)
    brief = _ensure_brief(store, investigation_id)

    board = store.get_investigation(investigation_id)
    return {
        "status": "ready",
        "fixture": "ctla4",
        "synthetic": True,
        "clinical_use": "prohibited",
        "user_id": DEMO_USER_ID,
        "workspace_id": workspace["workspace_id"],
        "investigation_id": investigation_id,
        "cycle_ids": [
            cycle_one["cycle_id"],
            cycle_two["cycle_id"],
            cycle_three["cycle_id"],
        ],
        "profile_snapshot_ids": [
            item["patient_molecular_snapshot_id"]
            for item in board.get("profile_snapshot_history") or []
        ],
        "brief_version_id": brief["brief_version_id"],
        "agi_fixture": {
            "agi_id": DEMO_AGI_ID,
            "agi_snapshot_id": DEMO_AGI_SNAPSHOT_ID,
            "variant": "CTLA4 c.228G>C (p.Gln76His; Q76H)",
            "classification": "variant of uncertain significance",
        },
        "live_agents_started": False,
        "external_providers_contacted": False,
    }


def _patient_fact(modality: str, label: str, wording: str) -> JsonObject:
    return {
        "modality": modality,
        "label": label,
        "original_wording": wording,
        "source_class": "patient_reported",
        "verification_state": "user_confirmed",
    }


def _record_fact(
    modality: str,
    label: str,
    wording: str,
    *,
    gene: str | None = None,
    variant: str | None = None,
    classification: str | None = None,
) -> JsonObject:
    result: JsonObject = {
        "modality": modality,
        "label": label,
        "original_wording": wording,
        "source_class": "issued_record",
        "verification_state": "record_confirmed",
    }
    if gene:
        result.update(
            {
                "gene": gene,
                "reported_variant": variant,
                "reported_classification": classification,
            }
        )
    return result


def _ensure_stage_snapshot(
    store: GenomiLabStore,
    investigation_id: str,
    *,
    stage: int,
    title: str,
    facts: list[JsonObject],
) -> JsonObject:
    investigation = store.get_investigation(investigation_id)
    history = investigation.get("profile_snapshot_history") or []
    if len(history) >= stage:
        return history[stage - 1]
    report = (title + "\nAll content is synthetic and not for clinical use.\n").encode()
    artifact = store.ingest_report(
        DEMO_USER_ID,
        content=report,
        source_type="laboratory_report",
        title=title,
        media_type="text/plain",
        source_identifier=f"SYNTHETIC-CTLA4-STAGE-{stage}",
    )
    existing = {
        str(item.get("label") or "")
        for item in store.list_profile_observations(DEMO_USER_ID, current_only=False)
    }
    for fact in facts:
        if str(fact["label"]) in existing:
            continue
        payload = dict(fact)
        if payload["source_class"] == "issued_record":
            payload["artifact_id"] = artifact["artifact_id"]
        store.add_profile_observation(DEMO_USER_ID, payload)
    current_ids = [
        str(item["observation_revision_id"])
        for item in store.list_profile_observations(DEMO_USER_ID, current_only=True)
    ]
    investigation = store.get_investigation(investigation_id)
    base = str(investigation.get("patient_molecular_snapshot_id") or "") or None
    candidate = store.profile_snapshot_candidate(
        DEMO_USER_ID,
        investigation_id=investigation_id,
        purpose=f"Synthetic CTLA4 demo stage {stage} review",
        observation_revision_ids=current_ids,
        agi_id=DEMO_AGI_ID,
        agi_snapshot_id=DEMO_AGI_SNAPSHOT_ID,
        genomic_scope={"genes": ["CTLA4"], "variant": "Q76H", "synthetic": True},
    )
    return store.create_profile_snapshot(
        DEMO_USER_ID,
        workspace_session_id=DEMO_SESSION_ID,
        investigation_id=investigation_id,
        purpose=f"Synthetic CTLA4 demo stage {stage} review",
        observation_revision_ids=current_ids,
        agi_id=DEMO_AGI_ID,
        agi_snapshot_id=DEMO_AGI_SNAPSHOT_ID,
        genomic_scope={"genes": ["CTLA4"], "variant": "Q76H", "synthetic": True},
        candidate_sha256=candidate["candidate_sha256"],
        approved=True,
        refresh=bool(base),
        expected_base_patient_molecular_snapshot_id=base,
    )


def _cycle_one(store: GenomiLabStore, investigation_id: str) -> JsonObject:
    cycle = _start_cycle(
        store,
        investigation_id,
        "cycle-1",
        "Compare medication timing, immune phenotype, focused CTLA4 evidence, literature, and alternatives.",
    )
    if cycle["status"] == "completed":
        return cycle
    q76h = _evidence(
        store,
        investigation_id,
        "cycle-1-q76h",
        "personal_genome",
        "active_genome_index.focused_variant_review",
        "Synthetic AGI surfaces heterozygous CTLA4 Q76H; classification remains uncertain and clinical confirmation is required.",
        personal=True,
    )
    literature = _evidence(
        store,
        investigation_id,
        "cycle-1-literature",
        "paperclip",
        "paperclip.synthetic_fixture",
        "Synthetic public-source fixture supports CTLA4 as an immune-dysregulation gene but does not establish Q76H causality.",
    )
    cycle = _attach_evidence(store, investigation_id, cycle, [q76h, literature])
    store.create_evidence_snapshot(investigation_id, reason="synthetic_cycle_1_basis")
    facts = _current_fact_ids(store)
    immune = _hypothesis(
        store,
        investigation_id,
        "Underlying immune dysregulation",
        "The reported finding is a candidate for further review.",
        "open",
        [literature],
        facts,
    )
    _hypothesis(
        store,
        investigation_id,
        "Medication-related immune suppression",
        "The uncertain report is a question for further evidence review.",
        "open",
        [literature],
        facts,
    )
    _hypothesis(
        store,
        investigation_id,
        "Primary antibody deficiency with another cause",
        "The reported finding is a candidate for further review.",
        "open",
        [literature],
        facts,
    )
    _hypothesis(
        store,
        investigation_id,
        "Several unrelated conditions",
        "The uncertain report is a question for further evidence review.",
        "open",
        [literature],
        facts,
    )
    _hypothesis(
        store,
        investigation_id,
        "CTLA4-related immune dysregulation",
        "The uncertain report is a question for further evidence review.",
        "unresolved",
        [q76h, literature],
        facts,
        parent=immune["logical_hypothesis_id"],
    )
    cycle = _record_questions(
        store,
        investigation_id,
        cycle,
        "cycle-1",
        [
            "Did infections begin before immune-suppressing treatment, and were immunoglobulins measured before treatment?",
            "Do current immunoglobulins, vaccine responses, and B-cell subsets show an antibody-deficiency pattern?",
            "Does the older intestinal pathology look like ordinary Crohn's disease or an immune-mediated enteropathy?",
            "Can a clinical laboratory confirm the CTLA4 variant and its current classification?",
        ],
    )
    roles = [
        ("timeline", "clinical_timeline_projection", facts, []),
        ("phenotype", "phenotype_projection", facts, []),
        (
            "gene-and-variant",
            "main_agent_genomic_summary",
            [],
            [q76h["evidence_record_id"]],
        ),
        ("literature", "public_source_result", [], [literature["evidence_record_id"]]),
        (
            "evidence-skeptic",
            "claim_and_counterevidence_projection",
            facts,
            [q76h["evidence_record_id"], literature["evidence_record_id"]],
        ),
    ]
    cycle = _seed_panel(store, investigation_id, cycle, "cycle-1", roles)
    return _complete_cycle(store, cycle, "cycle-1")


def _cycle_two(store: GenomiLabStore, investigation_id: str) -> JsonObject:
    cycle = _start_cycle(
        store,
        investigation_id,
        "cycle-2",
        "Reassess the board after pre-treatment infection, immune testing, and pathology records.",
    )
    if cycle["status"] == "completed":
        return cycle
    chronology = _evidence(
        store,
        investigation_id,
        "cycle-2-chronology",
        "patient_record",
        "lab.synthetic_clinical_record",
        "Synthetic records place pneumonia and low immunoglobulins before key immune-suppressing treatments.",
    )
    immune = _evidence(
        store,
        investigation_id,
        "cycle-2-immune",
        "patient_record",
        "lab.synthetic_immune_testing",
        "Synthetic records report persistently low IgG and IgA, inadequate pneumococcal response, abnormal B-cell maturation, and possible immune-mediated enteropathy.",
    )
    literature = _evidence(
        store,
        investigation_id,
        "cycle-2-literature",
        "paperclip",
        "paperclip.synthetic_fixture",
        "Synthetic public-source fixture supports both CTLA4-related immune dysregulation and CTLA4-independent antibody deficiency as research alternatives.",
    )
    cycle = _attach_evidence(
        store, investigation_id, cycle, [chronology, immune, literature]
    )
    store.create_evidence_snapshot(investigation_id, reason="synthetic_cycle_2_basis")
    facts = _current_fact_ids(store)
    current = _hypotheses_by_title(store, investigation_id)
    _revise(
        store,
        investigation_id,
        current,
        "Medication-related immune suppression",
        "The uncertain report is a question for further evidence review.",
        "rejected",
        [chronology],
        facts,
    )
    cycle = _record_gaps(
        store,
        investigation_id,
        cycle,
        "cycle-2",
        [
            "Independent clinical confirmation of the CTLA4 variant remains missing.",
            "CTLA4 staining under a qualified laboratory protocol remains missing.",
            "LRBA expression under a qualified laboratory protocol remains missing.",
        ],
    )
    _revise(
        store,
        investigation_id,
        current,
        "CTLA4-related immune dysregulation",
        "The reported finding is a candidate for further review.",
        "strengthened",
        [immune, literature],
        facts,
    )
    _revise(
        store,
        investigation_id,
        current,
        "Primary antibody deficiency with another cause",
        "The reported finding is a candidate for further review.",
        "strengthened",
        [immune, literature],
        facts,
    )
    _revise(
        store,
        investigation_id,
        current,
        "Several unrelated conditions",
        "The uncertain report is a question for further evidence review.",
        "weakened",
        [chronology, immune],
        facts,
    )
    roles = [
        (
            "timeline",
            "clinical_timeline_projection",
            facts,
            [chronology["evidence_record_id"]],
        ),
        ("phenotype", "phenotype_projection", facts, [immune["evidence_record_id"]]),
        (
            "evidence-skeptic",
            "claim_and_counterevidence_projection",
            facts,
            [chronology["evidence_record_id"], immune["evidence_record_id"]],
        ),
    ]
    cycle = _seed_panel(store, investigation_id, cycle, "cycle-2", roles)
    return _complete_cycle(store, cycle, "cycle-2")


def _cycle_three(store: GenomiLabStore, investigation_id: str) -> JsonObject:
    cycle = _start_cycle(
        store,
        investigation_id,
        "cycle-3",
        "Distinguish CTLA4 abundance from function and weigh functional and family evidence.",
    )
    if cycle["status"] == "completed":
        return cycle
    staining = _evidence(
        store,
        investigation_id,
        "cycle-3-staining",
        "patient_record",
        "lab.synthetic_staining_report",
        "Synthetic report records CTLA4 and LRBA measurements in control range; this does not establish normal CTLA4 function.",
    )
    functional = _evidence(
        store,
        investigation_id,
        "cycle-3-functional",
        "patient_record",
        "lab.synthetic_functional_assay",
        "Synthetic reference-laboratory report records reduced transendocytosis twice under the reported assay conditions.",
    )
    carrier = _evidence(
        store,
        investigation_id,
        "cycle-3-carrier",
        "patient_record",
        "lab.synthetic_family_report",
        "Synthetic report records Q76H in an apparently healthy mother, weighing against a simple fully penetrant explanation.",
    )
    q76h = _evidence(
        store,
        investigation_id,
        "cycle-3-q76h",
        "personal_genome",
        "active_genome_index.focused_variant_review",
        "Synthetic AGI identity remains CTLA4 Q76H; classification remains variant of uncertain significance and clinical confirmation remains required.",
        personal=True,
    )
    cycle = _attach_evidence(
        store, investigation_id, cycle, [staining, functional, carrier, q76h]
    )
    store.create_evidence_snapshot(investigation_id, reason="synthetic_cycle_3_basis")
    facts = _current_fact_ids(store)
    current = _hypotheses_by_title(store, investigation_id)
    ctla4 = _revise(
        store,
        investigation_id,
        current,
        "CTLA4-related immune dysregulation",
        "The uncertain report is a question for further evidence review.",
        "strengthened",
        [functional, carrier, q76h],
        facts,
    )
    _hypothesis(
        store,
        investigation_id,
        "Reduced CTLA4 abundance",
        "The uncertain report is a question for further evidence review.",
        "weakened",
        [staining],
        facts,
        parent=ctla4["logical_hypothesis_id"],
    )
    _hypothesis(
        store,
        investigation_id,
        "Impaired CTLA4 function despite normal staining",
        "The reported finding is a candidate for further review.",
        "strengthened",
        [staining, functional],
        facts,
        parent=ctla4["logical_hypothesis_id"],
    )
    _revise(
        store,
        investigation_id,
        current,
        "Primary antibody deficiency with another cause",
        "The reported finding is a candidate for further review.",
        "retained",
        [functional, carrier],
        facts,
    )
    _revise(
        store,
        investigation_id,
        current,
        "Medication-related immune suppression",
        "The uncertain report is a question for further evidence review.",
        "retained",
        [functional, carrier],
        facts,
    )
    _hypothesis(
        store,
        investigation_id,
        "Other immune or genetic causes",
        "The uncertain report is a question for further evidence review.",
        "open",
        [functional, carrier],
        facts,
    )
    for provider, kind, artifact in (
        (
            "biohub-esm",
            "sequence_model_signal",
            {
                "summary": "Synthetic nonclinical sequence-model perturbation signal for Q76H follow-up."
            },
        ),
        (
            "proto",
            "blinded_experiment_design",
            {
                "summary": "Synthetic blinded wild-type, Q76H, and control abundance/function experiment design."
            },
        ),
        (
            "genomi-sequence",
            "sequence_change_verification",
            {
                "summary": "Synthetic verification that the intended experiment input encodes Q76H."
            },
        ),
    ):
        cycle = store.get_cycle(str(cycle["cycle_id"]))
        store.record_research_artifact(
            DEMO_USER_ID,
            investigation_id=investigation_id,
            cycle_id=cycle["cycle_id"],
            provider=provider,
            artifact_kind=kind,
            artifact=artifact,
            source_evidence_ids=[],
            command_id=f"synthetic-ctla4:cycle-3:artifact:{provider}",
            expected_revision=int(cycle["revision"]),
        )
    cycle = store.get_cycle(str(cycle["cycle_id"]))
    cycle = _record_questions(
        store,
        investigation_id,
        cycle,
        "cycle-3",
        [
            "Would a qualified CTLA4 transendocytosis assay help distinguish normal staining from impaired function in this case?"
        ],
    )
    roles = [
        ("literature", "public_source_result", [], [staining["evidence_record_id"]]),
        (
            "mechanism",
            "claim_and_counterevidence_projection",
            facts,
            [staining["evidence_record_id"], functional["evidence_record_id"]],
        ),
        (
            "evidence-skeptic",
            "claim_and_counterevidence_projection",
            facts,
            [functional["evidence_record_id"], carrier["evidence_record_id"]],
        ),
    ]
    cycle = store.get_cycle(str(cycle["cycle_id"]))
    cycle = _seed_panel(store, investigation_id, cycle, "cycle-3", roles)
    return _complete_cycle(store, cycle, "cycle-3")


def _start_cycle(
    store: GenomiLabStore, investigation_id: str, key: str, objective: str
) -> JsonObject:
    investigation = store.get_investigation(investigation_id)
    return store.start_cycle(
        DEMO_USER_ID,
        investigation_id=investigation_id,
        objective=objective,
        command_id=f"synthetic-ctla4:{key}:start",
        expected_revision=int(investigation["domain_revision"]),
    )


def _evidence(
    store: GenomiLabStore,
    investigation_id: str,
    key: str,
    source_family: str,
    operation: str,
    summary: str,
    *,
    personal: bool = False,
) -> JsonObject:
    envelope = evidence_envelope.evidence_present(
        operation=operation,
        answer_readiness=evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
        query_scope={"synthetic_demo": True, "focus": "CTLA4 Q76H"},
        personal_context={"uses_personal_dna": personal, "approval_recorded": personal},
        coverage={
            "consulted_sources": [source_family],
            "unavailable_sources": [],
            "libraries": [],
            "materialization": [],
        },
        observations={
            "observation_count": 1,
            "summary": summary,
            "classification": "variant of uncertain significance"
            if "q76h" in summary.lower()
            else None,
            "confirmation": "required" if "q76h" in summary.lower() else None,
        },
    )
    return store.commit_evidence(
        investigation_id,
        source_family=source_family,
        operation=operation,
        evidence={"summary": summary, "synthetic": True, "evidence_envelope": envelope},
        deduplication_key=f"synthetic-ctla4:{key}",
    )


def _attach_evidence(
    store: GenomiLabStore,
    investigation_id: str,
    cycle: JsonObject,
    records: list[JsonObject],
) -> JsonObject:
    for record in records:
        cycle = store.get_cycle(str(cycle["cycle_id"]))
        store.record_evidence_reference(
            DEMO_USER_ID,
            investigation_id=investigation_id,
            cycle_id=cycle["cycle_id"],
            evidence_record_id=record["evidence_record_id"],
            relationship="context",
            command_id=f"synthetic-ctla4:{cycle['cycle_id']}:{record['evidence_record_id']}",
            expected_revision=int(cycle["revision"]),
        )
    return store.get_cycle(str(cycle["cycle_id"]))


def _hypothesis(
    store: GenomiLabStore,
    investigation_id: str,
    title: str,
    statement: str,
    status: str,
    evidence: list[JsonObject],
    facts: list[str],
    *,
    parent: str | None = None,
) -> JsonObject:
    return store.commit_hypothesis(
        investigation_id,
        kind="uncertainty",
        title=title,
        statement=statement,
        status=status,
        evidence_record_ids=[item["evidence_record_id"] for item in evidence],
        profile_revision_ids=facts,
        parent_logical_hypothesis_id=parent,
    )


def _hypotheses_by_title(
    store: GenomiLabStore, investigation_id: str
) -> list[JsonObject]:
    return list(
        store.get_investigation(investigation_id).get("current_hypotheses") or []
    )


def _revise(
    store: GenomiLabStore,
    investigation_id: str,
    current: list[JsonObject],
    title: str,
    statement: str,
    status: str,
    evidence: list[JsonObject],
    facts: list[str],
) -> JsonObject:
    prior = next(
        (item for item in current if str(item.get("title") or "") == title),
        None,
    )
    if prior is None:
        return _hypothesis(
            store,
            investigation_id,
            title,
            statement,
            status,
            evidence,
            facts,
        )
    return store.commit_hypothesis(
        investigation_id,
        kind=str(prior["kind"]),
        title=title,
        statement=statement,
        status=status,
        evidence_record_ids=[item["evidence_record_id"] for item in evidence],
        profile_revision_ids=facts,
        supersedes_hypothesis_id=prior["hypothesis_id"],
        parent_logical_hypothesis_id=prior.get("parent_logical_hypothesis_id"),
    )


def _seed_panel(
    store: GenomiLabStore,
    investigation_id: str,
    cycle: JsonObject,
    key: str,
    roles: list[tuple[str, str, list[str], list[str]]],
) -> JsonObject:
    for index, (role, projection, facts, evidence_ids) in enumerate(roles):
        cycle = store.get_cycle(str(cycle["cycle_id"]))
        packet = store.prepare_specialist_packet(
            DEMO_USER_ID,
            workspace_session_id=DEMO_SESSION_ID,
            investigation_id=investigation_id,
            cycle_id=cycle["cycle_id"],
            specialist_role=role,
            projection_kind=projection,
            objective=f"Synthetic bounded {role} review",
            selected_profile_fact_ids=facts,
            selected_evidence_ids=evidence_ids,
            allowed_provider="demo_fixture",
            purpose="Clearly labeled deterministic synthetic demonstration",
            command_id=f"synthetic-ctla4:{key}:packet:{index}",
            expected_revision=int(cycle["revision"]),
        )
        cycle = store.get_cycle(str(cycle["cycle_id"]))
        assignment = store.register_panel_assignment(
            DEMO_USER_ID,
            investigation_id=investigation_id,
            cycle_id=cycle["cycle_id"],
            packet_id=packet["packet_id"],
            specialist_role=role,
            agent_profile=f"lab-{role}",
            objective=f"Synthetic bounded {role} review",
            status="completed",
            command_id=f"synthetic-ctla4:{key}:assignment:{index}",
            expected_revision=int(cycle["revision"]),
        )
        cycle = store.get_cycle(str(cycle["cycle_id"]))
        store.record_specialist_finding(
            DEMO_USER_ID,
            investigation_id=investigation_id,
            cycle_id=cycle["cycle_id"],
            assignment_id=assignment["assignment_id"],
            finding={
                "summary": f"Synthetic {role} analysis recorded for the scripted CTLA4 demonstration.",
                "synthetic": True,
                "interpretation_boundary": "specialist analysis is not source evidence",
            },
            evidence_record_ids=evidence_ids,
            status="recorded",
            command_id=f"synthetic-ctla4:{key}:finding:{index}",
            expected_revision=int(cycle["revision"]),
        )
    return store.get_cycle(str(cycle["cycle_id"]))


def _complete_cycle(store: GenomiLabStore, cycle: JsonObject, key: str) -> JsonObject:
    cycle = store.get_cycle(str(cycle["cycle_id"]))
    return store.complete_cycle(
        DEMO_USER_ID,
        cycle_id=cycle["cycle_id"],
        command_id=f"synthetic-ctla4:{key}:complete",
        expected_revision=int(cycle["revision"]),
    )


def _record_questions(
    store: GenomiLabStore,
    investigation_id: str,
    cycle: JsonObject,
    key: str,
    questions: list[str],
) -> JsonObject:
    for index, question in enumerate(questions):
        cycle = store.get_cycle(str(cycle["cycle_id"]))
        store.record_patient_question(
            DEMO_USER_ID,
            investigation_id=investigation_id,
            cycle_id=cycle["cycle_id"],
            question=question,
            rationale="A focused question from the synthetic investigation record.",
            command_id=f"synthetic-ctla4:{key}:question:{index}",
            expected_revision=int(cycle["revision"]),
        )
    return store.get_cycle(str(cycle["cycle_id"]))


def _record_gaps(
    store: GenomiLabStore,
    investigation_id: str,
    cycle: JsonObject,
    key: str,
    gaps: list[str],
) -> JsonObject:
    for index, description in enumerate(gaps):
        cycle = store.get_cycle(str(cycle["cycle_id"]))
        store.record_information_gap(
            DEMO_USER_ID,
            investigation_id=investigation_id,
            cycle_id=cycle["cycle_id"],
            description=description,
            importance="high",
            command_id=f"synthetic-ctla4:{key}:gap:{index}",
            expected_revision=int(cycle["revision"]),
        )
    return store.get_cycle(str(cycle["cycle_id"]))


def _current_fact_ids(store: GenomiLabStore) -> list[str]:
    return [
        str(item["observation_revision_id"])
        for item in store.list_profile_observations(DEMO_USER_ID, current_only=True)
    ]


def _ensure_brief(store: GenomiLabStore, investigation_id: str) -> JsonObject:
    investigation = store.get_investigation(investigation_id)
    if investigation.get("brief_versions"):
        return investigation["brief_versions"][-1]
    evidence = list(investigation.get("current_evidence_records") or [])
    facts = store.list_profile_observations(DEMO_USER_ID, current_only=True)
    by_label = {str(item["label"]): item for item in facts}
    by_operation = {str(item["operation"]): item for item in evidence}
    claims = [
        {
            "statement": "Patient record observation: An issued laboratory record reports the finding as a research finding.",
            "claim_role": "observation",
            "evidence_record_ids": [
                by_operation["active_genome_index.focused_variant_review"][
                    "evidence_record_id"
                ]
            ],
            "profile_revision_ids": [
                by_label["Clinical confirmation of CTLA4 Q76H as VUS"][
                    "observation_revision_id"
                ]
            ],
        },
        {
            "statement": "Patient record observation: An issued laboratory record reports the finding as a research finding.",
            "claim_role": "observation",
            "evidence_record_ids": [
                by_operation["lab.synthetic_functional_assay"]["evidence_record_id"]
            ],
            "profile_revision_ids": [
                by_label["Repeatedly reduced CTLA4 transendocytosis"][
                    "observation_revision_id"
                ]
            ],
        },
        {
            "statement": "Patient record observation: An issued laboratory record reports the finding as a research finding.",
            "claim_role": "observation",
            "evidence_record_ids": [
                by_operation["lab.synthetic_family_report"]["evidence_record_id"]
            ],
            "profile_revision_ids": [
                by_label["Apparently healthy maternal Q76H carrier"][
                    "observation_revision_id"
                ]
            ],
        },
    ]
    badges = derive_brief_modality_badges(
        claims, evidence_records=evidence, profile_records=facts
    )
    current_hypotheses = investigation.get("current_hypotheses") or []
    return store.commit_brief(
        investigation_id,
        {
            "title": "Synthetic CTLA4 investigation brief",
            "summary": "The approved record remains a research observation.",
            "clinical_stage": "research_observation",
            "modality_badges": badges,
            "claims": claims,
            "hypothesis_ids": [item["hypothesis_id"] for item in current_hypotheses],
            "gap_ids": [],
            "confirmation_needs": [
                "The finding requires independent clinical confirmation."
            ],
            "professional_questions": [
                "What evidence would determine whether this is medically actionable?"
            ],
            "clinical_boundary": BRIEF_CLINICAL_BOUNDARY,
            "change_summary": "Prepared a traceable research brief.",
        },
    )


__all__ = [
    "DEMO_DISPLAY_NAME",
    "DEMO_QUESTION",
    "DEMO_USER_ID",
    "seed_ctla4_demo",
]
