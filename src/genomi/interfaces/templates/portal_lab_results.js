const LAB_PREFIX = 'lab.';

export const LAB_RESULT_OPERATIONS = Object.freeze([
  'lab.create_investigation',
  'lab.update_health_profile',
  'lab.read_investigation',
  'lab.create_cycle',
  'lab.create_hypothesis',
  'lab.revise_hypothesis',
  'lab.prepare_specialist_brief',
  'lab.create_specialist_assignment',
  'lab.transition_specialist_assignment',
  'lab.capture_evidence_result',
  'lab.capture_provider_result',
  'lab.publish_brief'
]);

export function isLabResultOperation(operation) {
  return text(operation).startsWith(LAB_PREFIX);
}

export function labResultViewModel(payload, operation) {
  if (!isLabResultOperation(operation)) return null;
  const state = object(payload);
  const investigation = object(state.investigation);
  const cycles = records(state.cycles, state.cycle);
  const hypotheses = records(state.hypothesis_versions, state.hypothesis_version);
  const snapshots = records(state.evidence_snapshots, state.evidence_snapshot);
  const assignments = records(state.specialist_assignments, state.assignment);
  const evidence = records(state.evidence_records, state.evidence_record);
  const artifacts = records(state.research_artifacts, state.research_artifact);
  const briefs = records(state.brief_versions, state.brief_version);
  const gaps = unique([
    ...hypotheses.flatMap((item) => array(object(item).unresolved_gaps).map(questionText)),
    ...array(object(state.specialist_analysis).gaps).map(questionText)
  ]);
  const questions = unique(briefs.flatMap(briefQuestions));
  const lanes = [
    lane('Investigation', record(investigation) ? [investigationNode(investigation)] : []),
    lane('Cycles', cycles.map(cycleNode)),
    lane('Hypotheses', hypotheses.map(hypothesisNode)),
    lane('Captured evidence', evidence.map(evidenceNode)),
    lane('Evidence changes', snapshots.map(snapshotNode)),
    lane('Research workstreams', assignments.map(assignmentNode)),
    lane('Research artifacts', artifacts.map(artifactNode)),
    lane('Open gaps and questions', [
      ...gaps.map((gap) => resultNode('Unresolved gap', gap, { gap })),
      ...questions.map((question) => resultNode('Question', question, { question }))
    ]),
    lane('Published briefs', briefs.map(briefNode)),
    lane('Prepared research brief', record(state.outbound_brief) ? [specialistBriefNode(state.outbound_brief)] : []),
    lane('Health profile update', operation === 'lab.update_health_profile' ? profileNodes(state) : [])
  ].filter((item) => item.nodes.length);
  const revision = positiveNumber(state.domain_revision ?? investigation.domain_revision);
  return {
    kind: 'lab_investigation',
    operation,
    kicker: 'Genomi Lab investigation',
    title: resultTitle(operation, state),
    summary: resultSummary(operation, state, lanes),
    evidenceEnvelope: {},
    notice: null,
    metrics: [
      metric('Revision', revision),
      metric('Cycles', cycles.length || null),
      metric('Hypotheses', hypotheses.length || null),
      metric('Briefs', briefs.length || null)
    ].filter(Boolean),
    lanes
  };
}

function investigationNode(item) {
  const question = text(item.question) || 'Investigation';
  return resultNode(question, join([status(item.status), text(item.disease_scope)]), {
    investigation_id: text(item.investigation_id),
    question,
    disease_scope: text(item.disease_scope),
    status: text(item.status),
    domain_revision: positiveNumber(item.domain_revision)
  });
}

function cycleNode(item) {
  const ordinal = positiveNumber(item.ordinal);
  const purpose = text(item.purpose) || 'Investigation cycle';
  return resultNode(ordinal ? `Cycle ${ordinal}` : 'Investigation cycle', purpose, {
    cycle_id: text(item.cycle_id),
    ordinal,
    purpose,
    public_only: item.public_only === true
  });
}

function hypothesisNode(item) {
  const statement = text(item.statement) || 'Hypothesis';
  const supporting = array(item.supporting_evidence_record_ids).length;
  const contradicting = array(item.contradicting_evidence_record_ids).length;
  const contextual = array(item.contextual_evidence_record_ids).length;
  const evidenceSummary = [
    supporting ? `${supporting} supporting` : '',
    contradicting ? `${contradicting} contradicting` : '',
    contextual ? `${contextual} contextual` : ''
  ].filter(Boolean).join(' · ');
  return resultNode(statement, join([status(item.status), version(item.version), evidenceSummary]), {
    logical_hypothesis_id: text(item.logical_hypothesis_id),
    hypothesis_version_id: text(item.hypothesis_version_id),
    statement,
    status: text(item.status),
    version: positiveNumber(item.version),
    revision_rationale: text(item.revision_rationale),
    supporting_evidence_count: supporting,
    contradicting_evidence_count: contradicting,
    contextual_evidence_count: contextual
  });
}

function evidenceNode(item) {
  const operation = text(item.operation) || 'Captured evidence';
  return resultNode(operation, join([text(item.source_family), text(item.created_at)]), {
    evidence_record_id: text(item.evidence_record_id),
    operation,
    source_family: text(item.source_family)
  });
}

function snapshotNode(item) {
  const diff = object(item.diff);
  const changed = object(diff.evidence_record_ids);
  const added = array(changed.added).length;
  const removed = array(changed.removed).length;
  const profileChanged = diff.patient_molecular_snapshot_changed === true;
  return resultNode(version(item.version, 'Evidence snapshot'), join([
    added ? `${added} added` : 'No evidence added',
    removed ? `${removed} removed` : '',
    profileChanged ? 'Profile context changed' : '',
    text(item.reason)
  ]), {
    evidence_snapshot_id: text(item.evidence_snapshot_id),
    version: positiveNumber(item.version),
    evidence_added: added,
    evidence_removed: removed,
    patient_molecular_snapshot_changed: profileChanged,
    reason: text(item.reason)
  });
}

function assignmentNode(item) {
  const role = humanLabel(item.specialist_role) || 'Research workstream';
  return resultNode(role, status(item.state), {
    specialist_assignment_id: text(item.specialist_assignment_id),
    specialist_role: role,
    execution_policy: text(item.execution_policy),
    state: text(item.state),
    revision: positiveNumber(item.revision)
  });
}

function artifactNode(item) {
  const kind = text(item.artifact_kind) || 'Research artifact';
  return resultNode(kind, join([text(item.provider), text(item.created_at)]), {
    research_artifact_id: text(item.research_artifact_id),
    artifact_kind: kind,
    provider: text(item.provider)
  });
}

function briefNode(item) {
  const brief = object(item.brief);
  const title = text(brief.title) || version(item.version, 'Brief');
  const evidenceDiff = object(object(object(item.diff).evidence_snapshot).evidence_record_ids);
  const added = array(evidenceDiff.added).length;
  return resultNode(title, join([text(brief.summary), version(item.version), added ? `${added} evidence added` : '']), {
    brief_version_id: text(item.brief_version_id),
    version: positiveNumber(item.version),
    title,
    summary: text(brief.summary),
    prior_brief_version_id: text(item.prior_brief_version_id)
  });
}

function specialistBriefNode(value) {
  const item = object(value);
  const role = humanLabel(item.specialist_role) || 'Research brief';
  return resultNode(role, text(item.research_question), {
    specialist_role: role,
    execution_policy: text(item.execution_policy),
    research_question: text(item.research_question)
  });
}

function profileNodes(state) {
  const observations = array(state.observations);
  const snapshot = object(state.profile_snapshot);
  return [resultNode(
    `${observations.length} health ${observations.length === 1 ? 'fact' : 'facts'} recorded`,
    snapshot.patient_molecular_snapshot_id ? 'Investigation profile snapshot refreshed' : 'Health profile updated',
    {
      observation_count: observations.length,
      profile_snapshot_id: text(snapshot.patient_molecular_snapshot_id),
      domain_revision: positiveNumber(state.domain_revision)
    }
  )];
}

function briefQuestions(item) {
  const brief = object(object(item).brief);
  return [
    ...array(brief.questions).map(questionText),
    ...array(brief.open_questions).map(questionText),
    ...array(brief.questions_for_clinician).map(questionText)
  ];
}

function questionText(value) {
  return typeof value === 'string' ? text(value) : text(object(value).question || object(value).text);
}

function resultTitle(operation, state) {
  const investigation = object(state.investigation);
  if (text(investigation.question)) return text(investigation.question);
  if (text(object(state.hypothesis_version).statement)) return text(object(state.hypothesis_version).statement);
  const brief = object(object(state.brief_version).brief);
  if (text(brief.title)) return text(brief.title);
  if (text(object(state.assignment).specialist_role)) return humanLabel(object(state.assignment).specialist_role);
  return operationLabel(operation);
}

function resultSummary(operation, state, lanes) {
  if (operation === 'lab.read_investigation') {
    const counts = lanes.map((item) => `${item.nodes.length} ${item.title.toLowerCase()}`);
    return counts.length ? `Current investigation state: ${counts.join(' · ')}.` : 'Current investigation state is ready.';
  }
  return join([status(state.status), `${operationLabel(operation)} recorded`]) || 'Lab investigation state updated.';
}

function resultNode(label, summary, value) {
  const cleanLabel = text(label) || 'Lab record';
  const cleanSummary = text(summary) || 'Recorded in the investigation';
  return {
    label: cleanLabel,
    summary: cleanSummary,
    context: `${cleanLabel}: ${cleanSummary}`,
    value: cleanObject(value)
  };
}

function lane(title, nodes) {
  return { title, nodes: array(nodes).filter(Boolean), selectable: true };
}

function metric(label, value) {
  return value === null || value === undefined || value === '' ? null : { label, value };
}

function records(plural, singular) {
  if (Array.isArray(plural)) return plural.map(object).filter(record);
  return record(singular) ? [object(singular)] : [];
}

function record(value) {
  return Object.keys(object(value)).length > 0;
}

function operationLabel(operation) {
  const value = text(operation).replace(/^lab\./, '').replaceAll('_', ' ');
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : 'Genomi Lab';
}

function version(value, prefix = 'Version') {
  const number = positiveNumber(value);
  return number ? `${prefix} ${number}` : prefix;
}

function status(value) {
  const clean = text(value).replaceAll('_', ' ');
  return clean ? clean.charAt(0).toUpperCase() + clean.slice(1) : '';
}

function humanLabel(value) {
  const clean = text(value).replace(/[_-]+/g, ' ').replace(/\bspecialist\b/gi, '').replace(/\s+/g, ' ').trim();
  return clean ? clean.charAt(0).toUpperCase() + clean.slice(1) : '';
}

function cleanObject(value) {
  return Object.fromEntries(Object.entries(object(value)).filter(([, item]) => item !== '' && item !== null && item !== undefined));
}

function unique(values) {
  return [...new Set(array(values).map(text).filter(Boolean))];
}

function join(values) {
  return array(values).map(text).filter(Boolean).join(' · ');
}

function positiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : undefined;
}

function text(value) {
  return value === null || value === undefined ? '' : String(value).trim();
}

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function array(value) {
  return Array.isArray(value) ? value : [];
}
