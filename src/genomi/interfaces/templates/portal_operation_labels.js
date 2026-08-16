const FRIENDLY_OPERATION_LABELS = Object.freeze({
  bash: 'Run command',
  read_file: 'Read file',
  manage_environments: 'Environment',
  'decode.render_dashboard': 'Analysis report',
  'genomi.describe_context': 'Active genome',
  'genomi.portal.artifact_work_trail': 'Result work trail',
  'genomi.portal.conversation_review': 'Conversation reviewer',
  'genomi.portal.evidence_ledger': 'Current evidence',
  'genomi.portal.frame_work_trace': 'Conversation work trail',
  'genomi.portal.message_work_trace': 'Message work trail',
  'genomi.portal.workspace_file': 'Project file',
  'clinvar.match_variants': 'Matched your variants to ClinVar',
  'clinvar.scan_candidates': 'Scanned your genome for candidate variants',
  'lab.capture_evidence_result': 'Recorded evidence',
  'lab.capture_provider_result': 'Recorded specialist findings',
  'lab.create_cycle': 'Started a round of work',
  'lab.create_hypothesis': 'Added a possible explanation',
  'lab.create_information_gap': 'Recorded something still missing',
  'lab.create_investigation': 'Opened the investigation',
  'lab.create_specialist_assignment': 'Assigned a research specialist',
  'lab.prepare_specialist_brief': 'Prepared a de-identified research brief',
  'lab.publish_brief': 'Published the doctor brief',
  'lab.read_investigation': 'Reviewed the investigation so far',
  'lab.revise_hypothesis': 'Revised a possible explanation',
  'lab.revise_information_gap': 'Updated something still missing',
  'lab.transition_specialist_assignment': 'Updated a research workstream',
  'lab.update_health_profile': 'Recorded your health facts',
  'paperclip.retrieve_document_evidence': 'Read a source in detail',
  'paperclip.search_biomedical': 'Searched published literature',
  'pharmacogenomics.review_medication': 'Medication-response review',
  'phenotype.compare_gene_hpo_evidence': 'Compared symptoms against known genes',
  'protein.retrieve_reference_sequence': 'Fetched a reference protein sequence',
  'variant.gather_allele_context': 'Looked up a specific variant',
  'variant.gather_gene_context': 'Looked up a gene',
  'portal.import_file': 'Imported file',
  'research.build_target_packet': 'Target evidence report',
  'variant.resolve': 'Variant lookup'
});

const NAMESPACE_LABELS = Object.freeze({
  cell_type: 'Cell type',
  clinvar: 'ClinVar',
  decode: 'Reports',
  functional_genomics: 'Functional genomics',
  genomi: 'Genomi',
  lab: 'Investigation',
  gwas: 'GWAS',
  pathway: 'Pathway',
  pharmacogenomics: 'Pharmacogenomics',
  phenotype: 'Phenotype',
  portal: 'GenomiLab',
  prs: 'PRS',
  region: 'Region',
  research: 'Research',
  variant: 'Variant'
});

const OPERATION_ID_PATTERN = /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$/;

const GENERIC_FALLBACK_LABELS = Object.freeze(new Set([
  '',
  'Available operation',
  'Genomi work',
  'Genomi tool',
  'Genomi tools',
  'Research step',
  'Tool'
]));

const DEFAULT_OPERATION_LABEL = 'Research step';

export function operationDisplayLabel(name, fallback = DEFAULT_OPERATION_LABEL) {
  const raw = String(name || '').trim();
  const safeFallback = operationFallbackLabel(fallback);
  if (!raw) return safeFallback;
  if (FRIENDLY_OPERATION_LABELS[raw]) return FRIENDLY_OPERATION_LABELS[raw];
  if (!isOperationId(raw)) return safeFallback;
  const parts = raw.split('.').filter(Boolean);
  const namespace = namespaceDisplayLabel(parts[0]);
  const action = titleWords(parts.slice(1).join(' '));
  return [namespace, action].filter(Boolean).join(' ') || safeFallback;
}

export function operationListDisplayLabel(operations, fallback = DEFAULT_OPERATION_LABEL) {
  const names = (Array.isArray(operations) ? operations : [operations])
    .map((operation) => operationDisplayLabel(operation, ''))
    .filter(Boolean);
  if (!names.length) return operationFallbackLabel(fallback);
  return names.length === 1 ? names[0] : names.slice(0, 4).join(', ');
}

function namespaceDisplayLabel(namespace) {
  const raw = String(namespace || '').trim();
  return NAMESPACE_LABELS[raw] || titleWords(raw);
}

function isOperationId(value) {
  return OPERATION_ID_PATTERN.test(String(value || '').trim());
}

function operationFallbackLabel(fallback) {
  const raw = String(fallback || '').trim();
  if (!raw || GENERIC_FALLBACK_LABELS.has(raw)) return DEFAULT_OPERATION_LABEL;
  if (/^[A-Za-z][A-Za-z0-9 &+()-]{0,60}$/.test(raw)) return raw;
  return DEFAULT_OPERATION_LABEL;
}

function titleWords(value) {
  return String(value || '')
    .replace(/[_./-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean)
    .map(titlePart)
    .join(' ');
}

function titlePart(part) {
  const upper = part.toUpperCase();
  if (['AGI', 'API', 'GWAS', 'HPO', 'PRS', 'VCF'].includes(upper)) return upper;
  return part.slice(0, 1).toUpperCase() + part.slice(1);
}
