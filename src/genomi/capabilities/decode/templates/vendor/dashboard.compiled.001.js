// AUTO-GENERATED chunk 1/2 from dashboard.jsx by scripts/build_dashboard.py - do not edit by hand.
// source-sha256: c75e08e91af8f2288daaa19f73a885e1db6e16b9928da5c0ad98d4107ca20d7e
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
  label: 'Pharmacogenomics',
  icon: '◉',
  section: 'Genomics',
  panel: 'pgx'
}, {
  id: 'risk',
  label: 'Risk Scores',
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
    not_selected: 'Not selected',
    blocked_position_aware_export: 'Export required',
    missing_scores: 'Scores unavailable',
    insufficient_overlap: 'Insufficient overlap',
    running: 'Running',
    failed: 'Failed',
    blocked_setup: 'Setup required',
    source_unavailable: 'Source unavailable',
    out_of_scope: 'Out of scope',
    checked_empty: 'No records rendered',
    no_pharmcat_results: 'No PharmCAT results',
    no_renderable_evidence: 'No renderable evidence'
  };
  return labels[state] || labels.no_renderable_evidence;
}
function unavailableMessage(item) {
  const state = item && item.state;
  const messages = {
    not_selected: 'This category was not included in this dashboard render.',
    blocked_position_aware_export: 'Pharmacogenomics was checked, but broad PharmCAT rendering requires a position-aware Active Genome Index export that preserves reference and no-call loci.',
    missing_scores: 'Risk scores were checked, but no imported PGS Catalog scores were available for this dashboard.',
    insufficient_overlap: 'Ancestry context was checked, but marker overlap was too low to render reference-neighbor context.',
    running: item && item.job_id ? `This category is still running in background job ${item.job_id}. Refresh the dashboard after the job completes.` : 'This category is still running in the background. Refresh the dashboard after it completes.',
    failed: item && item.error && item.error.message ? `This category failed before renderable evidence was available: ${item.error.message}` : 'This category failed before renderable evidence was available.',
    blocked_setup: 'This category needs required setup before it can render evidence.',
    source_unavailable: 'The source needed for this category was unavailable during the dashboard build.',
    out_of_scope: 'This genome input is outside the supported scope for this category.',
    checked_empty: 'Genomi checked this category and found no renderable records in the consulted scope.',
    no_pharmcat_results: 'Pharmacogenomics was checked, but no renderable PharmCAT results were available for this dashboard.',
    no_renderable_evidence: 'This category has no renderable evidence in this dashboard.'
  };
  return messages[state] || messages.no_renderable_evidence;
}
function EmptyPanel({
  title,
  panel
}) {
  const unavailable = unavailablePanel(panel);
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, title), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, unavailableLabel(unavailable && unavailable.state)))), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, title)), /*#__PURE__*/React.createElement("div", {
    className: "empty-body"
  }, unavailableMessage(unavailable))));
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
  const gqSub = gs.meanDepth != null ? `${gs.meanDepth}× mean depth` : gs.genotypeQuality != null ? 'PASS rate' : '';
  const sources = Array.isArray(gs.sourceCoverage) ? gs.sourceCoverage : [];
  const _varHiSrc = VARIANTS_DATA || VARIANTS_ALL_DATA;
  const variantsHi = _varHiSrc && _varHiSrc.length > 0 ? _varHiSrc.slice(0, 3) : null;
  const pgxHi = PGX_DATA && PGX_DATA.length > 0 ? PGX_DATA.slice(0, 3) : null;
  const riskHi = PRS_DATA && PRS_DATA.length > 0 ? PRS_DATA.slice(0, 3) : null;
  const ancestryHi = ANCESTRY_DATA && (ANCESTRY_DATA.dominantAncestry || Array.isArray(ANCESTRY_DATA.neighbors) && ANCESTRY_DATA.neighbors.length > 0) ? ANCESTRY_DATA : null;
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
  }, "Active Genome Index", gs.sampleId ? ` · ${gs.sampleId}` : '', gs.genomeBuild ? ` · ${gs.genomeBuild}` : '')), /*#__PURE__*/React.createElement("div", {
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
  }, "Genotype Quality"), /*#__PURE__*/React.createElement("div", {
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
      color: '#f59e0b'
    }
  }, PGX_DATA ? PGX_DATA.length : '-'), /*#__PURE__*/React.createElement("div", {
    className: "stat-label"
  }, "PGx Markers"), /*#__PURE__*/React.createElement("div", {
    className: "stat-sub"
  }, PGX_DATA ? `${PGX_DATA.filter(d => d.impact && d.impact !== 'normal').length} actionable` : ''))), sources.length > 0 && /*#__PURE__*/React.createElement("div", {
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
  }, src.coverageState || 'data_returned')), /*#__PURE__*/React.createElement("div", {
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
    title: "Top Variants",
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
    }, v.clinvarSignificance.replace(/_/g, ' ')));
  }))), pgxHi && /*#__PURE__*/React.createElement(HighlightCard, {
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
      key: d.gene || i,
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
    title: "Risk Scores",
    onNav: onNav ? () => onNav('risk') : null
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 12
    }
  }, riskHi.map((d, i) => {
    const scoreNum = d.score != null ? Number(d.score) : null;
    const scoreStr = scoreNum != null ? (scoreNum > 0 ? '+' : '') + scoreNum.toFixed(3) : '-';
    const scoreColor = scoreNum == null ? '#666' : scoreNum > 0.5 ? '#f59e0b' : scoreNum < -0.5 ? '#3b82f6' : '#aaa';
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
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--mono)',
        fontSize: 16,
        fontWeight: 700,
        color: scoreColor
      }
    }, scoreStr), d.percentile != null ? /*#__PURE__*/React.createElement("span", {
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
    }, "raw score")), d.overlap && /*#__PURE__*/React.createElement("span", {
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
      color: '#e5e5e5',
      fontSize: 13,
      marginBottom: 8
    }
  }, "Closest: ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#3b82f6',
      fontWeight: 600
    }
  }, ancestryHi.dominantAncestry || '-')), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 8
    }
  }, (Array.isArray(ancestryHi.neighbors) ? ancestryHi.neighbors : []).slice(0, 3).map((n, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      fontSize: 12,
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 4,
      height: 4,
      borderRadius: '50%',
      background: SUPERPOP_COLORS[POP_SUPERPOP[n.population]] || '#888',
      display: 'inline-block'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#e5e5e5'
    }
  }, POP_LABELS[n.population] || n.population || '-'), /*#__PURE__*/React.createElement("span", {
    className: "mono-text",
    style: {
      color: '#555',
      fontSize: 10
    }
  }, n.population)), /*#__PURE__*/React.createElement("span", {
    className: "mono-text"
  }, n.similarity != null ? String(n.similarity) : ''))))), nutriHi && /*#__PURE__*/React.createElement(HighlightCard, {
    title: "Nutrigenomics",
    onNav: onNav ? () => onNav('nutrigenomics') : null
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, nutriHi.map((d, i) => {
    const ntc = {
      established: '#10b981',
      probable: '#f59e0b',
      emerging: '#8b5cf6'
    }[d.evidenceTier] || '#666';
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 8,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#e5e5e5',
        fontWeight: 600,
        fontSize: 13
      }
    }, d.marker || '-'), d.gene && /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        color: '#3b82f6',
        fontSize: 12
      }
    }, d.gene)), d.evidenceTier && /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: ntc + '18',
        color: ntc,
        borderColor: ntc + '30',
        fontSize: 10,
        flexShrink: 0
      }
    }, d.evidenceTier));
  })))));
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
  const ROW_H = 44;
  const OVERSCAN = 8;
  const containerRef = React.useRef(null);
  const [scrollTop, setScrollTop] = React.useState(0);
  React.useEffect(() => {
    setScrollTop(0);
    if (containerRef.current) containerRef.current.scrollTop = 0;
  }, [rows]);
  const totalH = rows.length * ROW_H;
  const containerH = Math.min(totalH, ROW_H * 15);
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const endIdx = Math.min(rows.length, Math.ceil((scrollTop + containerH) / ROW_H) + OVERSCAN);
  const visibleRows = rows.slice(startIdx, endIdx);
  const COLS = '130px 160px 150px 110px 190px 1fr 100px';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("div", {
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
        gridTemplateColumns: COLS,
        padding: '0 14px',
        height: ROW_H,
        alignItems: 'center',
        borderBottom: '1px solid #141414'
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        color: '#e5e5e5',
        fontSize: 12
      }
    }, v.rsid || '-'), /*#__PURE__*/React.createElement("span", {
      style: {
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
        fontSize: 11
      }
    }, "chr", v.chrom, ":", v.pos != null ? Number(v.pos).toLocaleString() : ''), /*#__PURE__*/React.createElement("span", {
      className: "genotype-badge"
    }, v.ref, '>', v.alt, v.zygosity ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#555',
        fontSize: 10
      }
    }, " ", v.zygosity) : null), /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: sc.bg,
        color: sc.fg,
        borderColor: sc.border,
        fontSize: 10,
        maxWidth: '100%',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, (v.clinvarSignificance || '').replace(/_/g, ' ')), /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#aaa',
        fontSize: 12,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap'
      }
    }, v.conditionShort || ''), /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#555',
        fontSize: 11
      }
    }, v.evidenceQuality || ''));
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      height: Math.max(0, (rows.length - endIdx) * ROW_H)
    }
  })), rows.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '8px 14px',
      borderTop: '1px solid var(--border)',
      fontSize: 11,
      color: 'var(--text4)',
      display: 'flex',
      justifyContent: 'space-between'
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
    if (sigFilter === 'other') return !s.includes('pathogenic') && !s.includes('uncertain') && !s.includes('benign');
    return true;
  }
  const plpFiltered = React.useMemo(() => hasPlp ? VARIANTS_DATA.filter(matchesSearch) : [], [search]);
  const allFiltered = React.useMemo(() => hasAll ? VARIANTS_ALL_DATA.filter(v => matchesSearch(v) && matchesSigFilter(v)) : [], [search, sigFilter]);
  const totalCount = hasAll ? VARIANTS_ALL_DATA.length : hasPlp ? VARIANTS_DATA.length : 0;
  const plpCount = hasPlp ? VARIANTS_DATA.length : 0;
  const SIG_TABS = [['all', 'All'], ['plp', 'P/LP'], ['vus', 'VUS'], ['benign', 'Benign'], ['other', 'Other']];
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Variant Explorer"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "ClinVar-matched variants from your Active Genome Index")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      alignItems: 'center'
    }
  }, plpCount > 0 && /*#__PURE__*/React.createElement("span", {
    className: "badge",
    style: {
      background: '#f9731618',
      color: '#f97316',
      borderColor: '#f9731630'
    }
  }, plpCount, " P/LP"), totalCount > 0 && /*#__PURE__*/React.createElement("span", {
    className: "badge",
    style: {
      background: '#1a1a1a',
      color: '#666',
      borderColor: '#282828'
    }
  }, totalCount.toLocaleString(), " total"))), /*#__PURE__*/React.createElement("input", {
    placeholder: "Search rsID, gene, condition, or significance\u2026",
    value: search,
    onChange: e => setSearch(e.target.value),
    style: {
      width: '100%',
      padding: '8px 14px',
      borderRadius: 8,
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      color: 'var(--text)',
      fontFamily: 'var(--sans)',
      fontSize: 13,
      outline: 'none',
      marginBottom: 20
    }
  }), hasPlp && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 28
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      color: '#f97316',
      textTransform: 'uppercase',
      letterSpacing: '0.08em',
      marginBottom: 10,
      display: 'flex',
      alignItems: 'center',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: '50%',
      background: '#f97316',
      display: 'inline-block'
    }
  }), "Clinically Significant"), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("table", {
    className: "variant-table"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "Variant"), /*#__PURE__*/React.createElement("th", null, "Gene"), /*#__PURE__*/React.createElement("th", null, "Location"), /*#__PURE__*/React.createElement("th", null, "Genotype"), /*#__PURE__*/React.createElement("th", null, "Significance"), /*#__PURE__*/React.createElement("th", null, "Condition"), /*#__PURE__*/React.createElement("th", null, "Quality"))), /*#__PURE__*/React.createElement("tbody", null, plpFiltered.map((v, i) => {
    const sc = sigBadgeStyle(v.clinvarSignificance);
    return /*#__PURE__*/React.createElement("tr", {
      key: v.rsid || i
    }, /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        color: '#e5e5e5'
      }
    }, v.rsid)), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#3b82f6',
        fontWeight: 600,
        fontSize: 13
      }
    }, v.gene)), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
      className: "mono-text"
    }, "chr", v.chrom, ":", v.pos != null ? Number(v.pos).toLocaleString() : '')), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
      className: "genotype-badge"
    }, v.ref, '>', v.alt, v.zygosity ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#555',
        fontSize: 10
      }
    }, " ", v.zygosity) : null)), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: sc.bg,
        color: sc.fg,
        borderColor: sc.border
      }
    }, (v.clinvarSignificance || '').replace(/_/g, ' '))), /*#__PURE__*/React.createElement("td", {
      style: {
        color: '#aaa',
        fontSize: 12
      }
