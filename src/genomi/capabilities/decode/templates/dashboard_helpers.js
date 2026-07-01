const PGX_IMPACT_COLORS = {
  normal: '#10b981',
  moderate: '#f59e0b',
  reduced: '#f59e0b',
  increased: '#f59e0b',
  elevated: '#ef4444',
  poor: '#ef4444',
};

function prsLevel(p) {
  if (p == null) return { label: '-', color: '#666' };
  if (p >= 80) return { label: 'Elevated', color: '#ef4444' };
  if (p >= 60) return { label: 'Moderate', color: '#f59e0b' };
  if (p >= 40) return { label: 'Average', color: '#aaaaaa' };
  return { label: 'Below Avg', color: '#10b981' };
}

function isPrsRow(row) {
  return row && (row.row_type === 'polygenic_score' || row.score_id || row.percentile != null);
}

function riskReviewLabel(row) {
  if (!row) return '-';
  const pieces = [row.gene, row.condition].filter(Boolean);
  return pieces.length ? pieces.join(' / ') : (row.trait || row.group_id || row.candidate_id || '-');
}

function reviewTypeLabel(value) {
  return String(value || 'review_target').replace(/_/g, ' ');
}

function firstCountLabel(counts) {
  if (!Array.isArray(counts) || counts.length === 0) return null;
  const first = counts[0];
  if (Array.isArray(first)) return first.filter(v => v != null).join(':');
  return String(first);
}

function pgxRowKey(row, index) {
  const drug = Array.isArray(row.drugs) && row.drugs[0]
    ? (typeof row.drugs[0] === 'string' ? row.drugs[0] : row.drugs[0].name)
    : '';
  return row.row_id || [
    drug,
    row.gene,
    row.rsid || row.variant_or_haplotype || row.diplotype || row.phenotype,
    index,
  ].filter(v => v != null && v !== '').join('|');
}

const POP_LABELS = {
  EUR: 'European',
  AFR: 'African',
  AMR: 'Admixed American',
  EAS: 'East Asian',
  SAS: 'South Asian',
  IBS: 'Iberian (Spain)',
  TSI: 'Toscani (Italy)',
  GBR: 'British (England)',
  CEU: 'Utah / NW European',
  FIN: 'Finnish',
  NFE: 'Non-Finnish European',
  PUR: 'Puerto Rican',
  CLM: 'Colombian',
  MXL: 'Mexican',
  PEL: 'Peruvian',
  YRI: 'Yoruba (Nigeria)',
  LWK: 'Luhya (Kenya)',
  GWD: 'Gambian',
  MSL: 'Mende (Sierra Leone)',
  ESN: 'Esan (Nigeria)',
  ASW: 'African American (SW)',
  ACB: 'African Caribbean',
  CHB: 'Han Chinese (Beijing)',
  JPT: 'Japanese (Tokyo)',
  CHS: 'Han Chinese (S)',
  CDX: 'Chinese Dai',
  KHV: 'Kinh Vietnamese',
  GIH: 'Gujarati Indian',
  PJL: 'Punjabi (Lahore)',
  BEB: 'Bengali',
  STU: 'Sri Lankan Tamil',
  ITU: 'Indian Telugu',
};

const POP_SUPERPOP = {
  EUR: 'EUR',
  IBS: 'EUR',
  TSI: 'EUR',
  GBR: 'EUR',
  CEU: 'EUR',
  FIN: 'EUR',
  NFE: 'EUR',
  AFR: 'AFR',
  YRI: 'AFR',
  LWK: 'AFR',
  GWD: 'AFR',
  MSL: 'AFR',
  ESN: 'AFR',
  ASW: 'AFR',
  ACB: 'AFR',
  AMR: 'AMR',
  PUR: 'AMR',
  CLM: 'AMR',
  MXL: 'AMR',
  PEL: 'AMR',
  EAS: 'EAS',
  CHB: 'EAS',
  JPT: 'EAS',
  CHS: 'EAS',
  CDX: 'EAS',
  KHV: 'EAS',
  SAS: 'SAS',
  GIH: 'SAS',
  PJL: 'SAS',
  BEB: 'SAS',
  STU: 'SAS',
  ITU: 'SAS',
};

const SUPERPOP_COLORS = {
  EUR: '#3b82f6',
  AFR: '#10b981',
  AMR: '#f97316',
  EAS: '#f59e0b',
  SAS: '#8b5cf6',
};
