// AUTO-GENERATED chunk 1/3 from dashboard sources by scripts/build_dashboard.py - do not edit by hand.
// source-sha256: 6b67c316a73ac2de502e8c7ea6094d3a343890b34b3b786fc33461b695712cc5
const PGX_IMPACT_COLORS = {
  normal: '#10b981',
  moderate: '#f59e0b',
  reduced: '#f59e0b',
  increased: '#f59e0b',
  elevated: '#ef4444',
  poor: '#ef4444'
};
function prsLevel(p) {
  if (p == null) return {
    label: '-',
    color: '#666'
  };
  if (p >= 80) return {
    label: 'Elevated',
    color: '#ef4444'
  };
  if (p >= 60) return {
    label: 'Moderate',
    color: '#f59e0b'
  };
  if (p >= 40) return {
    label: 'Average',
    color: '#aaaaaa'
  };
  return {
    label: 'Below Avg',
    color: '#10b981'
  };
}
function isPrsRow(row) {
  return row && (row.row_type === 'polygenic_score' || row.score_id || row.percentile != null);
}
function humanizeLabel(value) {
  return String(value || '').replace(/[|]+/g, '; ').replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
}
function conciseEvidenceLabel(value) {
  const usefulParts = humanizeLabel(value).split(';').map(part => part.trim()).filter(part => part && !['not provided', 'not specified', 'unknown'].includes(part.toLowerCase()));
  return usefulParts.join('; ') || 'Details pending';
}
function riskReviewLabel(row) {
  if (!row) return '-';
  const pieces = [row.gene, row.condition].filter(Boolean);
  return conciseEvidenceLabel(pieces.length ? pieces.join(' / ') : row.trait || row.group_id || row.candidate_id || '-');
}
function reviewTypeLabel(value) {
  const friendly = {
    phenotype_review_target: 'Needs review',
    review_target: 'Needs review',
    polygenic_score: 'Polygenic score',
    needs_clinical_confirmation: 'Clinical confirmation needed'
  };
  if (friendly[value]) return friendly[value];
  return humanizeLabel(value || 'review_target');
}
function firstCountLabel(counts) {
  if (!Array.isArray(counts) || counts.length === 0) return null;
  const first = counts[0];
  if (Array.isArray(first)) return first.filter(v => v != null).join(':');
  return String(first);
}
function pgxRowKey(row, index) {
  const drug = Array.isArray(row.drugs) && row.drugs[0] ? typeof row.drugs[0] === 'string' ? row.drugs[0] : row.drugs[0].name : '';
  return row.row_id || [drug, row.gene, row.rsid || row.variant_or_haplotype || row.diplotype || row.phenotype, index].filter(v => v != null && v !== '').join('|');
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
  ITU: 'Indian Telugu'
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
  ITU: 'SAS'
};
const SUPERPOP_COLORS = {
  EUR: '#3b82f6',
  AFR: '#10b981',
  AMR: '#f97316',
  EAS: '#f59e0b',
  SAS: '#8b5cf6'
};

// All evidence comes from the decode pipeline via window.__GENOMI_DASHBOARD__.
// Anything below this line is presentation/layout only — no genome data is
// prefilled in the template.
const TWEAK_DEFAULTS = {
  accentColor: 'green',
  showSupport: true,
  compactCards: false
};
const EV = window.__GENOMI_DASHBOARD__ || {};
const GENOME_SUMMARY = EV.overview || null;
const VARIANTS_DATA = Array.isArray(EV.variants) ? EV.variants : null;
const PGX_DATA = Array.isArray(EV.pgx) ? EV.pgx : null;
const PRS_DATA = Array.isArray(EV.risk) ? EV.risk : null;
const ANCESTRY_DATA = EV.ancestry || null;
const NUTRI_DATA = Array.isArray(EV.nutrigenomics) ? EV.nutrigenomics : null;
const VARIANTS_ALL_DATA = Array.isArray(EV.variants_all) ? EV.variants_all : null;
const DASHBOARD_META = EV.__dashboard || {};
const UNAVAILABLE_PANELS = Array.isArray(DASHBOARD_META.unavailablePanels) ? DASHBOARD_META.unavailablePanels : [];
const RENDERED_AT = DASHBOARD_META.renderedAt || '';
const NAV_ITEMS = [{
  id: 'overview',
  label: 'Overview',
  icon: '◫',
  section: 'Dashboard',
  panel: 'overview'
}, {
  id: 'variants',
  label: 'Variants',
  icon: '◇',
  section: 'Dashboard',
  panel: 'variants'
}, {
  id: 'pharmacogenomics',
  label: 'Medication Response',
  icon: '◉',
  section: 'Genomics',
  panel: 'pgx'
}, {
  id: 'risk',
  label: 'Risk Review',
  icon: '◈',
  section: 'Genomics',
  panel: 'risk'
}, {
  id: 'ancestry',
  label: 'Ancestry',
  icon: '◎',
  section: 'Genomics',
  panel: 'ancestry'
}, {
  id: 'nutrigenomics',
  label: 'Nutrigenomics',
  icon: '◆',
  section: 'Genomics',
  panel: 'nutrigenomics'
}];

// Keep unavailable panels navigable so partial renders and cleared updates
// stay visible inside the dashboard.
const AVAILABLE_NAV = NAV_ITEMS;
const ACCENT_MAP = {
  green: {
    primary: '#10b981',
    glow: '#10b98120'
  },
  blue: {
    primary: '#3b82f6',
    glow: '#3b82f620'
  },
  purple: {
    primary: '#8b5cf6',
    glow: '#8b5cf620'
  },
  amber: {
    primary: '#f59e0b',
    glow: '#f59e0b20'
  }
};
function unavailablePanel(panel) {
  return UNAVAILABLE_PANELS.find(item => item && item.panel === panel) || null;
}
function unavailableLabel(state) {
  const labels = {
    not_selected: 'Ready to add',
    blocked_position_aware_export: 'Export required',
    missing_scores: 'Score setup ready',
    insufficient_overlap: 'More markers required',
    running: 'Running',
    failed: 'Refresh required',
    blocked_setup: 'Setup required',
    source_unavailable: 'Source reconnect required',
    out_of_scope: 'Different input required',
    checked_empty: 'Review complete',
    no_pharmcat_results: 'Medication review complete',
    no_renderable_evidence: 'Assessment ready'
  };
  return labels[state] || labels.no_renderable_evidence;
}
function unavailableMessage(item) {
  const state = item && item.state;
  const messages = {
    not_selected: 'Add this category during the next dashboard refresh.',
    blocked_position_aware_export: 'Broad medication-response rendering becomes available with a position-aware Active Genome Index export that preserves reference and uncalled loci.',
    missing_scores: 'Install or import PGS Catalog scores to add calibrated polygenic results.',
    insufficient_overlap: 'A larger set of overlapping ancestry markers will support reference-neighbor context.',
    running: item && item.job_id ? `This category is still running in background job ${item.job_id}. Refresh the dashboard after the job completes.` : 'This category is still running in the background. Refresh the dashboard after it completes.',
    failed: item && item.error && item.error.message ? `Refresh this category after resolving: ${item.error.message}` : 'Refresh this category to complete its evidence display.',
    blocked_setup: 'Complete the required setup to render this category.',
    source_unavailable: 'Reconnect the category source and refresh the dashboard.',
    out_of_scope: 'Use a supported genome input to render this category.',
    checked_empty: 'Genomi completed this category review across the consulted scope with zero display rows.',
    no_pharmcat_results: 'Genomi completed the medication-response review with zero PharmCAT display rows.',
    no_renderable_evidence: 'Run or refresh this category to add display-ready evidence.'
  };
  return messages[state] || messages.no_renderable_evidence;
}
function EmptyPanel({
  title,
  panel
}) {
  const unavailable = unavailablePanel(panel);
  const isUnassessedPgx = panel === 'pgx' && (!unavailable || ['not_selected', 'no_renderable_evidence'].includes(unavailable.state));
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, title), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, isUnassessedPgx ? 'Assessment ready to run' : unavailableLabel(unavailable && unavailable.state)))), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, isUnassessedPgx ? 'What this means' : title)), /*#__PURE__*/React.createElement("div", {
    className: "empty-body"
  }, isUnassessedPgx ? 'Run the medication-response analysis to add reviewed gene–drug results to this dashboard.' : unavailableMessage(unavailable))));
}
function HighlightCard({
  title,
  onNav,
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, title), onNav && /*#__PURE__*/React.createElement("span", {
    className: "highlight-link",
    onClick: onNav
  }, "View \u2192")), /*#__PURE__*/React.createElement("div", {
    className: "card-body"
  }, children));
}
function OverviewView({
  onNav
}) {
  if (!GENOME_SUMMARY) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Overview",
    panel: "overview"
  });
  const gs = GENOME_SUMMARY;
  const variantCount = gs.variantCount != null ? Number(gs.variantCount).toLocaleString() : '-';
  const variantCountLabel = gs.variantCountLabel || 'Variants Indexed';
  const gq = gs.genotypeQuality != null ? `${gs.genotypeQuality}%` : '-';
  const gqSub = gs.meanDepth != null ? `${gs.meanDepth}× mean depth` : gs.genotypeQuality != null ? 'variants marked PASS' : '';
  const sources = Array.isArray(gs.sourceCoverage) ? gs.sourceCoverage : [];
  const sampleLabel = gs.sampleName || (gs.sampleId && !String(gs.sampleId).includes('sha256-') ? gs.sampleId : null);
  const _varHiSrc = VARIANTS_DATA || VARIANTS_ALL_DATA;
  const variantsHi = _varHiSrc && _varHiSrc.length > 0 ? _varHiSrc.slice(0, 3) : null;
  const pgxHi = PGX_DATA && PGX_DATA.length > 0 ? PGX_DATA.slice(0, 3) : null;
  const riskHi = PRS_DATA && PRS_DATA.length > 0 ? PRS_DATA.slice(0, 3) : null;
  const ancestryHi = ANCESTRY_DATA && ANCESTRY_DATA.closestSuperpopulation && ANCESTRY_DATA.closestPopulation ? ANCESTRY_DATA : null;
  const nutriHi = NUTRI_DATA && NUTRI_DATA.length > 0 ? NUTRI_DATA.slice(0, 3) : null;
  const anyHighlights = !!(variantsHi || pgxHi || riskHi || ancestryHi || nutriHi);
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Overview"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Active Genome Index", sampleLabel ? ` · ${sampleLabel}` : '', gs.genomeBuild ? ` · ${gs.genomeBuild}` : '')), /*#__PURE__*/React.createElement("div", {
    className: "header-badge"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: '#10b981'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#10b981',
      fontSize: 12,
      fontWeight: 600
    }
  }, "Index Active"))), /*#__PURE__*/React.createElement("div", {
    className: "stats-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "stat-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "stat-value",
    style: {
      color: '#10b981'
    }
  }, variantCount), /*#__PURE__*/React.createElement("div", {
    className: "stat-label"
  }, variantCountLabel), /*#__PURE__*/React.createElement("div", {
    className: "stat-sub"
  }, gs.genomeSource || '')), /*#__PURE__*/React.createElement("div", {
    className: "stat-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "stat-value",
    style: {
      color: '#3b82f6'
    }
  }, gs.genomeBuild || '-'), /*#__PURE__*/React.createElement("div", {
    className: "stat-label"
  }, "Genome Build"), /*#__PURE__*/React.createElement("div", {
    className: "stat-sub"
  }, gs.parsedAt || '')), gs.genotypeQuality != null ? /*#__PURE__*/React.createElement("div", {
    className: "stat-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "stat-value",
    style: {
      color: '#8b5cf6'
    }
  }, gq), /*#__PURE__*/React.createElement("div", {
    className: "stat-label"
  }, "Callset QC"), /*#__PURE__*/React.createElement("div", {
    className: "stat-sub"
  }, gqSub)) : /*#__PURE__*/React.createElement("div", {
    className: "stat-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "stat-value",
    style: {
      color: '#8b5cf6',
      fontSize: 14,
      paddingTop: 4
    }
  }, gs.pipeline || gs.genomeSource || '-'), /*#__PURE__*/React.createElement("div", {
    className: "stat-label"
  }, "Variant Caller"), /*#__PURE__*/React.createElement("div", {
    className: "stat-sub"
  }, gs.contig_count != null ? `${Number(gs.contig_count).toLocaleString()} contigs` : '')), /*#__PURE__*/React.createElement("div", {
    className: "stat-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "stat-value",
    style: {
      color: '#f59e0b',
      fontSize: PGX_DATA ? 26 : 14
    }
  }, PGX_DATA ? PGX_DATA.length : 'Assessment ready'), /*#__PURE__*/React.createElement("div", {
    className: "stat-label"
  }, "Medication Response"), /*#__PURE__*/React.createElement("div", {
    className: "stat-sub"
  }, PGX_DATA ? `${PGX_DATA.filter(d => d.readiness === 'needs_clinical_confirmation').length} require confirmation` : 'Run a medication-response analysis'))), sources.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      marginBottom: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, "Source Coverage")), /*#__PURE__*/React.createElement("div", {
    className: "card-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "source-grid"
  }, sources.map((src, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "source-item"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#e5e5e5',
      fontSize: 13,
      fontWeight: 600
    }
  }, src.name || 'unknown source'), /*#__PURE__*/React.createElement("span", {
    className: "badge",
    style: {
      background: '#10b98118',
      color: '#10b981',
      borderColor: '#10b98130'
    }
  }, reviewTypeLabel(src.coverageState || 'data_returned'))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      marginTop: 6,
      color: '#555',
      fontSize: 11
    }
  }, /*#__PURE__*/React.createElement("span", null, src.percent != null ? `${src.percent}%` : ''))))))), anyHighlights && /*#__PURE__*/React.createElement("div", {
    className: "two-col"
  }, variantsHi && /*#__PURE__*/React.createElement(HighlightCard, {
    title: "ClinVar matches to review",
    onNav: onNav ? () => onNav('variants') : null
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, variantsHi.map((v, i) => {
    const sc = v.clinvarSignificance ? sigBadgeStyle(v.clinvarSignificance) : null;
    return /*#__PURE__*/React.createElement("div", {
      key: v.rsid || i,
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 4
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        color: '#e5e5e5',
        fontSize: 12
      }
    }, v.rsid || '-'), v.gene && /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#3b82f6',
        fontWeight: 600,
        fontSize: 12
      }
    }, v.gene)), sc && /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        alignSelf: 'flex-start',
        background: sc.bg,
        color: sc.fg,
        borderColor: sc.border
      }
    }, v.clinvarSignificance.replace(/_/g, ' ')), v.conditionShort && /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#777',
        fontSize: 10
      }
    }, conciseEvidenceLabel(v.conditionShort)));
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#555',
      fontSize: 10,
      lineHeight: 1.5
    }
  }, "Database labels for review; clinical context establishes relevance."))), pgxHi && /*#__PURE__*/React.createElement(HighlightCard, {
    title: "Pharmacogenomics",
    onNav: onNav ? () => onNav('pharmacogenomics') : null
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, pgxHi.map((d, i) => {
    const ic = PGX_IMPACT_COLORS[d.impact] || '#666';
    return /*#__PURE__*/React.createElement("div", {
      key: pgxRowKey(d, i),
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 4
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#e5e5e5',
        fontWeight: 600,
        fontFamily: 'var(--mono)',
        fontSize: 13
      }
    }, d.gene || '-'), /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        fontSize: 12
      }
    }, d.diplotype || '')), d.phenotype && /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        alignSelf: 'flex-start',
        background: ic + '18',
        color: ic,
        borderColor: ic + '30'
      }
    }, d.phenotype));
  }))), riskHi && /*#__PURE__*/React.createElement(HighlightCard, {
    title: "Risk Review",
    onNav: onNav ? () => onNav('risk') : null
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 12
    }
  }, riskHi.map((d, i) => {
    if (!isPrsRow(d)) {
      return /*#__PURE__*/React.createElement("div", {
        key: d.group_id || d.candidate_id || d.trait || i,
        style: {
          display: 'flex',
          flexDirection: 'column',
          gap: 4
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          color: '#e5e5e5',
          fontSize: 13,
          fontWeight: 600
        }
      }, riskReviewLabel(d)), /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap'
        }
      }, /*#__PURE__*/React.createElement("span", {
        className: "badge",
        style: {
          background: '#3b82f618',
          color: '#3b82f6',
          borderColor: '#3b82f630',
          fontSize: 10
        }
      }, reviewTypeLabel(d.group_type || d.row_type)), Array.isArray(d.missing_interpretation_gates) && d.missing_interpretation_gates.length > 0 && /*#__PURE__*/React.createElement("span", {
        style: {
          color: '#555',
          fontSize: 10
        }
      }, d.missing_interpretation_gates.length, " interpretation checks pending")));
    }
    return /*#__PURE__*/React.createElement("div", {
      key: d.trait || i,
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 4
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#e5e5e5',
        fontSize: 13,
        fontWeight: 600
      }
    }, d.trait || '-'), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, d.percentile != null ? /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: prsLevel(d.percentile).color + '18',
        color: prsLevel(d.percentile).color,
        borderColor: prsLevel(d.percentile).color + '30',
        fontSize: 10
      }
    }, d.percentile, "th pct") : /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: '#66666618',
        color: '#888',
        borderColor: '#66666630',
        fontSize: 10
      }
    }, "calculated \xB7 calibration pending")), d.overlap && /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#555',
        fontSize: 10
      }
    }, d.overlap));
  }))), ancestryHi && /*#__PURE__*/React.createElement(HighlightCard, {
    title: "Ancestry",
    onNav: onNav ? () => onNav('ancestry') : null
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#666',
      fontSize: 10,
      textTransform: 'uppercase',
      letterSpacing: '0.05em'
    }
  }, "Closest reference match"), /*#__PURE__*/React.createElement("div", {
    style: {
      color: SUPERPOP_COLORS[ancestryHi.closestSuperpopulation.label] || '#e5e5e5',
      fontSize: 20,
      fontWeight: 800,
      marginTop: 3
    }
  }, POP_LABELS[ancestryHi.closestSuperpopulation.label] || ancestryHi.closestSuperpopulation.label || '-'), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#aaa',
      fontSize: 12,
      marginTop: 8
    }
  }, "Closest named group: ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#e5e5e5'
    }
  }, POP_LABELS[ancestryHi.closestPopulation.label] || ancestryHi.closestPopulation.label || '-')), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#555',
      fontSize: 10,
      marginTop: 10,
      lineHeight: 1.5
    }
  }, "Reference-dataset comparison; ancestry percentages use a different method.")), nutriHi && /*#__PURE__*/React.createElement(HighlightCard, {
    title: "Nutrition marker reference",
    onNav: onNav ? () => onNav('nutrigenomics') : null
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#e5e5e5',
      fontSize: 18,
      fontWeight: 700
    }
  }, NUTRI_DATA.length, " researched markers"), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#888',
      fontSize: 12,
      lineHeight: 1.55,
      marginTop: 8
    }
  }, "Background research is available; personal interpretation begins after matching these markers to your genotype."))));
}
function sigBadgeStyle(sig) {
  const s = (sig || '').toLowerCase();
  if (s.includes('conflicting')) return {
    bg: '#f59e0b18',
    fg: '#f59e0b',
    border: '#f59e0b30'
  };
  if (s.includes('benign')) return {
    bg: '#10b98118',
    fg: '#10b981',
    border: '#10b98130'
  };
  if (s.includes('uncertain') || s.includes('vus')) return {
    bg: '#66666618',
    fg: '#888888',
    border: '#66666630'
  };
  // LP-only: starts with "likely pathogenic"
  if (s.startsWith('likely_pathogenic') || s.startsWith('likely pathogenic')) return {
    bg: '#f59e0b18',
    fg: '#f59e0b',
    border: '#f59e0b30'
  };
  // P/LP combined: contains both pathogenic and likely (e.g. "Pathogenic/Likely pathogenic")
  if (s.includes('pathogenic') && s.includes('likely')) return {
    bg: '#f9731618',
    fg: '#f97316',
    border: '#f9731630'
  };
  // P only: red
  if (s.includes('pathogenic')) return {
    bg: '#ef444418',
    fg: '#ef4444',
    border: '#ef444430'
  };
  if (s.includes('risk') || s.includes('association') || s.includes('protective')) return {
    bg: '#3b82f618',
    fg: '#3b82f6',
    border: '#3b82f630'
  };
  return {
    bg: '#8b5cf618',
    fg: '#8b5cf6',
    border: '#8b5cf630'
  };
}
function VirtualVariantTable({
  rows
}) {
  const [compact, setCompact] = React.useState(() => window.innerWidth <= 768);
  React.useEffect(() => {
    const onResize = () => setCompact(window.innerWidth <= 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  const ROW_H = compact ? 132 : 44;
  const OVERSCAN = 8;
  const containerRef = React.useRef(null);
  const [scrollTop, setScrollTop] = React.useState(0);
  React.useEffect(() => {
    setScrollTop(0);
    if (containerRef.current) containerRef.current.scrollTop = 0;
  }, [rows]);
  const totalH = rows.length * ROW_H;
  const containerH = Math.min(totalH, ROW_H * (compact ? 5 : 15));
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const endIdx = Math.min(rows.length, Math.ceil((scrollTop + containerH) / ROW_H) + OVERSCAN);
  const visibleRows = rows.slice(startIdx, endIdx);
  const COLS = '130px 160px 150px 110px 190px 1fr 100px';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column'
    }
  }, !compact && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: COLS,
      padding: '10px 14px',
      borderBottom: '1px solid var(--border)',
      fontSize: 11,
      fontWeight: 600,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.04em',
      background: 'var(--surface)'
    }
  }, /*#__PURE__*/React.createElement("span", null, "Variant"), /*#__PURE__*/React.createElement("span", null, "Gene"), /*#__PURE__*/React.createElement("span", null, "Location"), /*#__PURE__*/React.createElement("span", null, "Genotype"), /*#__PURE__*/React.createElement("span", null, "Significance"), /*#__PURE__*/React.createElement("span", null, "Condition"), /*#__PURE__*/React.createElement("span", null, "Quality")), /*#__PURE__*/React.createElement("div", {
    ref: containerRef,
    onScroll: e => setScrollTop(e.currentTarget.scrollTop),
    style: {
      overflowY: 'auto',
      height: containerH
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: startIdx * ROW_H
    }
  }), visibleRows.map((v, i) => {
    const sc = sigBadgeStyle(v.clinvarSignificance);
    return /*#__PURE__*/React.createElement("div", {
      key: v.rsid || startIdx + i,
      style: {
        display: 'grid',
        gridTemplateColumns: compact ? 'minmax(0, 1fr) auto' : COLS,
        gridTemplateAreas: compact ? '"variant significance" "gene genotype" "condition condition" "location quality"' : 'none',
        rowGap: compact ? 7 : 0,
        columnGap: compact ? 12 : 0,
        padding: compact ? '13px 14px' : '0 14px',
        height: ROW_H,
        alignItems: 'center',
        borderBottom: '1px solid #141414'
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        gridArea: compact ? 'variant' : 'auto',
        color: '#e5e5e5',
        fontSize: 12,
        fontWeight: 600
      }
    }, v.rsid || '-'), /*#__PURE__*/React.createElement("span", {
      style: {
        gridArea: compact ? 'gene' : 'auto',
        color: '#3b82f6',
        fontWeight: 600,
        fontSize: 12,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, v.gene || '-'), /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        gridArea: compact ? 'location' : 'auto',
        fontSize: 11
      }
    }, "chr", v.chrom, ":", v.pos != null ? Number(v.pos).toLocaleString() : ''), /*#__PURE__*/React.createElement("span", {
      className: "genotype-badge",
      style: {
        gridArea: compact ? 'genotype' : 'auto',
        justifySelf: compact ? 'end' : 'auto'
      }
    }, v.ref, ' → ', v.alt, v.zygosity ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#888',
        fontSize: 10
      }
    }, " \xB7 ", v.zygosity) : null), /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        gridArea: compact ? 'significance' : 'auto',
        justifySelf: compact ? 'end' : 'auto',
        background: sc.bg,
        color: sc.fg,
        borderColor: sc.border,
        fontSize: 10,
        maxWidth: compact ? 190 : '100%',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, humanizeLabel(v.clinvarSignificance)), /*#__PURE__*/React.createElement("span", {
      style: {
        gridArea: compact ? 'condition' : 'auto',
        color: '#aaa',
        fontSize: 12,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, conciseEvidenceLabel(v.conditionShort)), /*#__PURE__*/React.createElement("span", {
      style: {
        gridArea: compact ? 'quality' : 'auto',
        justifySelf: compact ? 'end' : 'auto',
        color: '#777',
        fontSize: 11
      }
    }, v.evidenceQuality || ''));
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      height: Math.max(0, (rows.length - endIdx) * ROW_H)
    }
  })), rows.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '9px 14px',
      borderTop: '1px solid var(--border)',
      fontSize: 11,
      color: 'var(--text3)',
      display: 'flex',
      justifyContent: 'space-between',
      gap: 12,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("span", null, rows.length.toLocaleString(), " variants"), /*#__PURE__*/React.createElement("span", null, "Scroll to explore \xB7 rendering ", Math.min(endIdx - startIdx, rows.length), " rows")));
}
function VariantsView() {
  const hasPlp = VARIANTS_DATA && VARIANTS_DATA.length > 0;
  const hasAll = VARIANTS_ALL_DATA && VARIANTS_ALL_DATA.length > 0;
  if (!hasPlp && !hasAll) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Variants",
    panel: "variants"
  });
  const [search, setSearch] = React.useState('');
  const [sigFilter, setSigFilter] = React.useState('all');
  function matchesSearch(v) {
    if (!search) return true;
    const s = search.toLowerCase();
    return (v.rsid || '').toLowerCase().includes(s) || (v.gene || '').toLowerCase().includes(s) || (v.conditionShort || '').toLowerCase().includes(s) || (v.clinvarSignificance || '').toLowerCase().includes(s);
  }
  function matchesSigFilter(v) {
    if (sigFilter === 'all') return true;
    const s = (v.clinvarSignificance || '').toLowerCase();
    if (sigFilter === 'plp') return s.includes('pathogenic');
    if (sigFilter === 'vus') return s.includes('uncertain');
    if (sigFilter === 'benign') return s.includes('benign');
