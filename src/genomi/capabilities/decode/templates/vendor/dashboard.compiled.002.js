// AUTO-GENERATED chunk 2/2 from dashboard.jsx by scripts/build_dashboard.py - do not edit by hand.
// source-sha256: c75e08e91af8f2288daaa19f73a885e1db6e16b9928da5c0ad98d4107ca20d7e
    }, v.conditionShort), /*#__PURE__*/React.createElement("td", {
      style: {
        color: '#555',
        fontSize: 11
      }
    }, v.evidenceQuality || ''));
  }))), plpFiltered.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 24,
      textAlign: 'center',
      color: '#444'
    }
  }, "No P/LP variants match your search."))), hasAll && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.08em'
    }
  }, "All ClinVar Variants"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 4
    }
  }, SIG_TABS.map(([key, label]) => /*#__PURE__*/React.createElement("button", {
    key: key,
    onClick: () => setSigFilter(key),
    style: {
      padding: '3px 10px',
      borderRadius: 6,
      fontSize: 11,
      fontWeight: 600,
      cursor: 'pointer',
      border: '1px solid',
      background: sigFilter === key ? 'var(--surface2)' : 'transparent',
      color: sigFilter === key ? 'var(--text)' : 'var(--text4)',
      borderColor: sigFilter === key ? 'var(--border2)' : 'transparent'
    }
  }, label)))), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      overflow: 'hidden'
    }
  }, allFiltered.length > 0 ? /*#__PURE__*/React.createElement(VirtualVariantTable, {
    rows: allFiltered
  }) : /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 40,
      textAlign: 'center',
      color: '#444'
    }
  }, "No variants match your filter."))));
}
function PharmacogenomicsView() {
  if (!PGX_DATA) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Pharmacogenomics",
    panel: "pgx"
  });
  const impactColors = PGX_IMPACT_COLORS;
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Pharmacogenomics"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Drug\u2013gene interactions from ClinPGx, FDA labels, and PGxDB"))), /*#__PURE__*/React.createElement("div", {
    className: "pgx-grid"
  }, PGX_DATA.map((d, i) => {
    const ic = impactColors[d.impact] || '#666';
    return /*#__PURE__*/React.createElement("div", {
      key: d.gene || i,
      className: "pgx-card"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start'
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#f5f5f5',
        fontWeight: 700,
        fontSize: 15,
        fontFamily: 'var(--mono)'
      }
    }, d.gene), /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#666',
        fontSize: 12,
        fontFamily: 'var(--mono)'
      }
    }, d.diplotype)), /*#__PURE__*/React.createElement("div", {
      style: {
        color: ic,
        fontSize: 13,
        fontWeight: 600,
        marginTop: 4
      }
    }, d.phenotype)), /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: ic + '18',
        color: ic,
        borderColor: ic + '30'
      }
    }, d.impact)), Array.isArray(d.drugs) && d.drugs.length > 0 && /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 4,
        marginTop: 10
      }
    }, d.drugs.map((drug, j) => {
      const name = typeof drug === 'string' ? drug : drug.name;
      const rec = typeof drug === 'string' ? null : drug.recommendation;
      return /*#__PURE__*/React.createElement("span", {
        key: j,
        className: "drug-chip",
        title: rec || ''
      }, name);
    })));
  })));
}
function RiskScoresView() {
  if (!PRS_DATA) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Risk Scores",
    panel: "risk"
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Polygenic Risk Scores"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Published PGS Catalog scores applied to your genome"))), /*#__PURE__*/React.createElement("div", {
    className: "risk-grid"
  }, PRS_DATA.map((d, i) => {
    const level = prsLevel(d.percentile);
    const scoreNum = d.score != null ? Number(d.score) : null;
    const scoreStr = scoreNum != null ? (scoreNum > 0 ? '+' : '') + scoreNum.toFixed(3) : '-';
    const scoreColor = scoreNum == null ? '#666' : scoreNum > 0.5 ? '#f59e0b' : scoreNum < -0.5 ? '#3b82f6' : '#aaa';
    return /*#__PURE__*/React.createElement("div", {
      key: d.trait || i,
      className: "risk-card"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        color: '#e5e5e5',
        fontWeight: 600,
        fontSize: 14
      }
    }, d.trait), Array.isArray(d.sources) && d.sources.length > 0 && /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        color: '#555',
        fontSize: 10,
        whiteSpace: 'nowrap'
      }
    }, d.sources[0])), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 10,
        marginTop: 10
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--mono)',
        fontSize: 22,
        fontWeight: 700,
        color: scoreColor
      }
    }, scoreStr), d.percentile != null ? /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: level.color + '18',
        color: level.color,
        borderColor: level.color + '30'
      }
    }, level.label, " \xB7 ", d.percentile, "th pct") : /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: '#66666618',
        color: '#888',
        borderColor: '#66666630'
      }
    }, "raw score")), d.note && /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 10,
        color: '#999',
        fontSize: 12,
        lineHeight: 1.6
      }
    }, d.note), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 8,
        display: 'flex',
        gap: 12,
        flexWrap: 'wrap'
      }
    }, d.overlap != null && /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#555',
        fontSize: 11
      }
    }, "overlap: ", d.overlap), d.ancestryAdjusted != null && /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#555',
        fontSize: 11
      }
    }, "ancestry-adj: ", String(d.ancestryAdjusted))));
  })));
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
function AncestryView() {
  if (!ANCESTRY_DATA) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Ancestry",
    panel: "ancestry"
  });
  const d = ANCESTRY_DATA;
  const neighbors = Array.isArray(d.neighbors) ? d.neighbors : [];
  const pts = Array.isArray(d.pcaPoints) ? d.pcaPoints : [];
  const xs = pts.map(p => p.x),
    ys = pts.map(p => p.y);
  const xMin = xs.length ? Math.min(...xs) - 4 : -1,
    xMax = xs.length ? Math.max(...xs) + 4 : 1;
  const yMin = ys.length ? Math.min(...ys) - 4 : -1,
    yMax = ys.length ? Math.max(...ys) + 4 : 1;
  const W = 480,
    H = 320,
    PAD = 30;
  const sx = v => PAD + (v - xMin) / (xMax - xMin || 1) * (W - 2 * PAD);
  const sy = v => H - PAD - (v - yMin) / (yMax - yMin || 1) * (H - 2 * PAD);
  const palette = {
    sample: '#f5f5f5',
    EUR: '#3b82f6',
    EAS: '#f59e0b',
    AFR: '#10b981',
    SAS: '#8b5cf6',
    AMR: '#f97316'
  };

  // superpopulation distribution from neighbors
  const spCounts = {};
  neighbors.forEach(n => {
    const sp = POP_SUPERPOP[n.population] || 'OTH';
    spCounts[sp] = (spCounts[sp] || 0) + 1;
  });
  const spEntries = Object.entries(spCounts).sort((a, b) => b[1] - a[1]);
  const totalN = neighbors.length || 1;
  const domSP = POP_SUPERPOP[d.dominantAncestry] || d.dominantAncestry;
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Ancestry Context"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Reference-panel similarity context (PCA / nearest neighbors)")), d.overlapFraction != null && /*#__PURE__*/React.createElement("span", {
    className: "badge",
    style: {
      background: '#3b82f618',
      color: '#3b82f6',
      borderColor: '#3b82f630'
    }
  }, Math.round(d.overlapFraction * 100), "% variant coverage")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 16,
      marginBottom: 20,
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      flex: '1 1 160px',
      padding: '14px 18px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.06em',
      marginBottom: 6
    }
  }, "Dominant Ancestry"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 700,
      color: SUPERPOP_COLORS[domSP] || '#e5e5e5'
    }
  }, domSP || d.dominantAncestry || '–'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#888',
      marginTop: 2
    }
  }, POP_LABELS[d.dominantAncestry] || d.dominantAncestry)), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      flex: '2 1 260px',
      padding: '14px 18px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.06em',
      marginBottom: 10
    }
  }, "Neighbor Distribution"), spEntries.map(([sp, count]) => /*#__PURE__*/React.createElement("div", {
    key: sp,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 36,
      fontSize: 11,
      fontWeight: 600,
      color: SUPERPOP_COLORS[sp] || '#888'
    }
  }, sp), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 6,
      borderRadius: 3,
      background: '#1a1a1a',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${count / totalN * 100}%`,
      height: '100%',
      borderRadius: 3,
      background: SUPERPOP_COLORS[sp] || '#888'
    }
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: '#666',
      width: 20,
      textAlign: 'right'
    }
  }, count))))), /*#__PURE__*/React.createElement("div", {
    className: "two-col"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, "Nearest Neighbors")), /*#__PURE__*/React.createElement("div", {
    className: "card-body"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, neighbors.map((n, i) => {
    const sp = POP_SUPERPOP[n.population] || 'OTH';
    const spColor = SUPERPOP_COLORS[sp] || '#888';
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 4,
        height: 4,
        borderRadius: '50%',
        background: spColor,
        display: 'inline-block',
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#e5e5e5',
        fontSize: 12,
        fontWeight: 500
      }
    }, POP_LABELS[n.population] || n.population), /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        color: '#555',
        fontSize: 10,
        marginLeft: 6
      }
    }, n.population))), n.similarity != null ? /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        fontSize: 11
      }
    }, Number(n.similarity).toFixed(4)) : null);
  })))), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, "PCA Projection")), pts.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "empty-body",
    style: {
      padding: '24px 16px',
      color: '#444',
      fontSize: 12
    }
  }, "No PCA points in evidence. Run ", /*#__PURE__*/React.createElement("code", null, "ancestry.estimate_population_context"), " with ", /*#__PURE__*/React.createElement("code", null, "include_pca_points: true"), ".") : /*#__PURE__*/React.createElement("div", {
    className: "card-body",
    style: {
      display: 'flex',
      justifyContent: 'center'
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: W,
    height: H
  }, pts.map((p, i) => /*#__PURE__*/React.createElement("circle", {
    key: i,
    cx: sx(p.x),
    cy: sy(p.y),
    r: p.cluster === 'sample' ? 6 : 3.5,
    fill: palette[p.cluster] || '#888',
    opacity: p.cluster === 'sample' ? 1 : 0.5,
    stroke: p.cluster === 'sample' ? '#f5f5f5' : 'none',
    strokeWidth: p.cluster === 'sample' ? 2 : 0
  })))))));
}
function NutrigenomicsView() {
  if (!NUTRI_DATA) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Nutrigenomics",
    panel: "nutrigenomics"
  });
  const tierColors = {
    established: '#10b981',
    probable: '#f59e0b',
    emerging: '#8b5cf6'
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Nutrigenomics"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Gene\u2013nutrient and gene\u2013diet single-marker evidence"))), /*#__PURE__*/React.createElement("div", {
    className: "nutri-grid"
  }, NUTRI_DATA.map((d, i) => {
    const tc = tierColors[d.evidenceTier] || '#666';
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      className: "nutri-card"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start'
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        color: '#e5e5e5',
        fontWeight: 600,
        fontSize: 14
      }
    }, d.marker), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8,
        marginTop: 4,
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        color: '#3b82f6'
      }
    }, d.gene), /*#__PURE__*/React.createElement("span", {
      className: "mono-text"
    }, d.rsid), /*#__PURE__*/React.createElement("span", {
      className: "genotype-badge"
    }, d.status))), /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: tc + '18',
        color: tc,
        borderColor: tc + '30'
      }
    }, d.evidenceTier)), /*#__PURE__*/React.createElement("div", {
      style: {
        color: '#999',
        fontSize: 12,
        lineHeight: 1.6,
        marginTop: 10
      }
    }, d.recommendation));
  })));
}
function Sidebar({
  active,
  onNav
}) {
  let lastSection = '';
  return /*#__PURE__*/React.createElement("div", {
    className: "sidebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sidebar-logo"
  }, /*#__PURE__*/React.createElement("img", {
    className: "sidebar-logo-icon",
    alt: "Genomi",
    src: "__GENOMI_LOGO_DATA_URL__"
  }), /*#__PURE__*/React.createElement("span", {
    className: "sidebar-logo-text"
  }, "Genomi"), /*#__PURE__*/React.createElement("span", {
    className: "sidebar-logo-version"
  }, "v0.4")), /*#__PURE__*/React.createElement("nav", {
    className: "sidebar-nav"
  }, AVAILABLE_NAV.map(item => {
    const showSection = item.section !== lastSection;
    lastSection = item.section;
    const actionable = item.id === 'pharmacogenomics' && PGX_DATA ? PGX_DATA.filter(d => d.impact && d.impact !== 'normal').length : 0;
    return /*#__PURE__*/React.createElement(React.Fragment, {
      key: item.id
    }, showSection && /*#__PURE__*/React.createElement("div", {
      className: "sidebar-section-label"
    }, item.section), /*#__PURE__*/React.createElement("div", {
      className: `nav-item ${active === item.id ? 'active' : ''}`,
      onClick: () => onNav(item.id)
    }, /*#__PURE__*/React.createElement("span", {
      className: "nav-icon"
    }, item.icon), /*#__PURE__*/React.createElement("span", null, item.label), actionable > 0 && /*#__PURE__*/React.createElement("span", {
      className: "nav-badge"
    }, actionable)));
  })), /*#__PURE__*/React.createElement("div", {
    className: "sidebar-footer"
  }, "Experimental \xB7 Research use only", /*#__PURE__*/React.createElement("br", null), "Not for clinical diagnosis", RENDERED_AT && /*#__PURE__*/React.createElement("span", {
    className: "timestamp"
  }, "rendered ", RENDERED_AT)));
}
function App() {
  const [view, setView] = React.useState(AVAILABLE_NAV[0] && AVAILABLE_NAV[0].id || 'overview');
  const [tweaks, setTweaks] = React.useState(TWEAK_DEFAULTS);
  const accent = ACCENT_MAP[tweaks.accentColor] || ACCENT_MAP.green;
  React.useEffect(() => {
    document.documentElement.style.setProperty('--green', accent.primary);
  }, [accent.primary]);
  const viewLabel = NAV_ITEMS.find(n => n.id === view)?.label || 'Overview';
  const renderView = () => {
    switch (view) {
      case 'overview':
        return /*#__PURE__*/React.createElement(OverviewView, {
          onNav: setView
        });
      case 'variants':
        return /*#__PURE__*/React.createElement(VariantsView, null);
      case 'pharmacogenomics':
        return /*#__PURE__*/React.createElement(PharmacogenomicsView, null);
      case 'risk':
        return /*#__PURE__*/React.createElement(RiskScoresView, null);
      case 'ancestry':
        return /*#__PURE__*/React.createElement(AncestryView, null);
      case 'nutrigenomics':
        return /*#__PURE__*/React.createElement(NutrigenomicsView, null);
      default:
        return /*#__PURE__*/React.createElement(OverviewView, {
          onNav: setView
        });
    }
  };
  const setTweak = (k, v) => setTweaks(prev => ({
    ...prev,
    [k]: v
  }));
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Sidebar, {
    active: view,
    onNav: setView
  }), /*#__PURE__*/React.createElement("div", {
    className: "main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "topbar"
  }, /*#__PURE__*/React.createElement("span", {
    className: "topbar-title"
  }, viewLabel), /*#__PURE__*/React.createElement("div", {
    className: "topbar-right"
  }, /*#__PURE__*/React.createElement("div", {
    className: "topbar-status"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: accent.primary
    }
  }, "\u25CF"), /*#__PURE__*/React.createElement("span", null, GENOME_SUMMARY?.sampleId || 'no active sample'), GENOME_SUMMARY?.genomeBuild && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#333'
    }
  }, "\xB7"), /*#__PURE__*/React.createElement("span", null, GENOME_SUMMARY.genomeBuild))))), renderView()), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      right: 16,
      bottom: 16,
      zIndex: 100
    }
  }, /*#__PURE__*/React.createElement("details", {
    style: {
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      padding: '6px 10px',
      color: 'var(--text3)',
      fontSize: 11
    }
  }, /*#__PURE__*/React.createElement("summary", {
    style: {
      cursor: 'pointer'
    }
  }, "Genomi Tweaks"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8,
      display: 'flex',
      flexDirection: 'column',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      gap: 8
    }
  }, "Accent", /*#__PURE__*/React.createElement("select", {
    value: tweaks.accentColor,
    onChange: e => setTweak('accentColor', e.target.value)
  }, /*#__PURE__*/React.createElement("option", {
    value: "green"
  }, "green"), /*#__PURE__*/React.createElement("option", {
    value: "blue"
  }, "blue"), /*#__PURE__*/React.createElement("option", {
    value: "purple"
  }, "purple"), /*#__PURE__*/React.createElement("option", {
    value: "amber"
  }, "amber"))), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      gap: 8
    }
  }, "Show support", /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: !!tweaks.showSupport,
    onChange: e => setTweak('showSupport', e.target.checked)
  })), /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      gap: 8
    }
  }, "Compact cards", /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: !!tweaks.compactCards,
    onChange: e => setTweak('compactCards', e.target.checked)
  }))))));
}
ReactDOM.createRoot(document.getElementById('root')).render(/*#__PURE__*/React.createElement(App, null));