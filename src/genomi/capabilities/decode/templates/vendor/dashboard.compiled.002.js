// AUTO-GENERATED chunk 2/3 from dashboard sources by scripts/build_dashboard.py - do not edit by hand.
// source-sha256: 9955a36712623e40ca394d947be0806f7bee5504c8a62c3d7201ac325a6e5857
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
  // Order by finding severity so actionable results sort to the top:
  // high-impact (poor/elevated) first, then reduced/increased/moderate,
  // then normal, then ungraded/no-call markers last.
  const PGX_SORT_RANK = {
    poor: 0,
    elevated: 0,
    reduced: 1,
    increased: 1,
    moderate: 1,
    normal: 2
  };
  const pgxRank = d => PGX_SORT_RANK[d.impact] ?? 3;
  const sortedPgx = PGX_DATA.slice().sort((a, b) => pgxRank(a) - pgxRank(b));
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Pharmacogenomics"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Medication-row PGx evidence from PharmCAT and medication review"))), /*#__PURE__*/React.createElement("div", {
    className: "pgx-grid"
  }, sortedPgx.map((d, i) => {
    const ic = impactColors[d.impact] || '#666';
    const primaryDrug = Array.isArray(d.drugs) && d.drugs[0] ? typeof d.drugs[0] === 'string' ? d.drugs[0] : d.drugs[0].name : null;
    const variantContext = d.rsid || d.variant_or_haplotype || d.diplotype || d.phenotype || '';
    return /*#__PURE__*/React.createElement("div", {
      key: pgxRowKey(d, i),
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
        fontSize: 15
      }
    }, primaryDrug || d.gene || 'PGx row'), d.gene && /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#3b82f6',
        fontSize: 12,
        fontFamily: 'var(--mono)'
      }
    }, d.gene)), /*#__PURE__*/React.createElement("div", {
      style: {
        color: ic,
        fontSize: 13,
        fontWeight: 600,
        marginTop: 4
      }
    }, variantContext)), (d.readiness || d.impact) && /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: ic + '18',
        color: ic,
        borderColor: ic + '30'
      }
    }, reviewTypeLabel(d.readiness || d.impact))), d.recommendation_text && /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 10,
        color: '#aaa',
        fontSize: 12,
        lineHeight: 1.55
      }
    }, d.recommendation_text), Array.isArray(d.drugs) && d.drugs.length > 0 && /*#__PURE__*/React.createElement("div", {
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
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 8,
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap',
        color: '#555',
        fontSize: 11
      }
    }, d.sample_relevance_state && /*#__PURE__*/React.createElement("span", null, reviewTypeLabel(d.sample_relevance_state)), d.row_type && /*#__PURE__*/React.createElement("span", null, reviewTypeLabel(d.row_type))));
  })));
}
function RiskScoresView() {
  if (!PRS_DATA) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Risk Review",
    panel: "risk"
  });
  const prsRows = PRS_DATA.filter(isPrsRow);
  const reviewRows = PRS_DATA.filter(row => !isPrsRow(row));
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Risk & Condition Review"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "PRS scores and ClinVar carrier/condition review targets"))), reviewRows.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 28
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      color: '#3b82f6',
      textTransform: 'uppercase',
      letterSpacing: '0.08em',
      marginBottom: 10
    }
  }, "Carrier / Condition Review"), /*#__PURE__*/React.createElement("div", {
    className: "risk-grid"
  }, reviewRows.map((d, i) => {
    const sig = firstCountLabel(d.clinical_significance_counts);
    const zygosity = firstCountLabel(d.zygosity_counts);
    return /*#__PURE__*/React.createElement("div", {
      key: d.group_id || d.candidate_id || d.trait || i,
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
    }, riskReviewLabel(d)), /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: '#3b82f618',
        color: '#3b82f6',
        borderColor: '#3b82f630'
      }
    }, reviewTypeLabel(d.group_type || d.row_type))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 10,
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap'
      }
    }, sig && /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: '#1a1a1a',
        color: '#aaa',
        borderColor: '#282828'
      }
    }, sig.replace(/_/g, ' ')), zygosity && /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: '#1a1a1a',
        color: '#aaa',
        borderColor: '#282828'
      }
    }, zygosity.replace(/_/g, ' ')), Array.isArray(d.missing_interpretation_gates) && d.missing_interpretation_gates.map(gate => /*#__PURE__*/React.createElement("span", {
      key: gate,
      className: "badge",
      style: {
        background: '#f59e0b18',
        color: '#f59e0b',
        borderColor: '#f59e0b30'
      }
    }, reviewTypeLabel(gate)))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 8,
        display: 'flex',
        gap: 12,
        flexWrap: 'wrap',
        color: '#555',
        fontSize: 11
      }
    }, d.score != null && /*#__PURE__*/React.createElement("span", null, "rank score: ", Number(d.score).toFixed(2)), Array.isArray(d.candidate_ids) && d.candidate_ids.length > 0 && /*#__PURE__*/React.createElement("span", null, d.candidate_ids.length, " variants")));
  }))), prsRows.length > 0 && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.08em',
      marginBottom: 10
    }
  }, "Polygenic Risk Scores"), /*#__PURE__*/React.createElement("div", {
    className: "risk-grid"
  }, prsRows.map((d, i) => {
    const level = prsLevel(d.percentile);
    const scoreNum = d.score != null ? Number(d.score) : null;
    const scoreStr = scoreNum != null ? (scoreNum > 0 ? '+' : '') + scoreNum.toFixed(3) : '-';
    const scoreColor = scoreNum == null ? '#666' : scoreNum > 0.5 ? '#f59e0b' : scoreNum < -0.5 ? '#3b82f6' : '#aaa';
    return /*#__PURE__*/React.createElement("div", {
      key: d.score_id || d.trait || i,
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
  }))));
}
function AncestryView() {
  if (!ANCESTRY_DATA) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Ancestry",
    panel: "ancestry"
  });
  const d = ANCESTRY_DATA;
  const superpopulationCentroids = Array.isArray(d.superpopulationCentroids) ? d.superpopulationCentroids : [];
  const populationCentroids = Array.isArray(d.populationCentroids) ? d.populationCentroids : [];
  const closestSuperpopulation = d.closestSuperpopulation || {};
  const closestPopulation = d.closestPopulation || {};
  const distanceNote = 'PCA centroid distance · lower is closer · not a percentage';
  const centroidRows = (rows, broad) => /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, rows.map((row, i) => {
    const sp = broad ? row.label : POP_SUPERPOP[row.label] || 'OTH';
    return /*#__PURE__*/React.createElement("div", {
      key: `${row.label}-${i}`,
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
        background: SUPERPOP_COLORS[sp] || '#888',
        display: 'inline-block',
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#e5e5e5',
        fontSize: 12,
        fontWeight: 500
      }
    }, POP_LABELS[row.label] || row.label), /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        color: '#555',
        fontSize: 10,
        marginLeft: 6
      }
    }, row.label))), /*#__PURE__*/React.createElement("span", {
      className: "mono-text",
      style: {
        fontSize: 11
      }
    }, Number(row.distance).toFixed(4)));
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#555',
      fontSize: 10
    }
  }, distanceNote));
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Ancestry Context"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Qualitative similarity to 1000 Genomes reference-group centroids")), d.overlapFraction != null && /*#__PURE__*/React.createElement("span", {
    className: "badge",
    style: {
      background: '#3b82f618',
      color: '#3b82f6',
      borderColor: '#3b82f630'
    }
  }, Math.round(d.overlapFraction * 100), "% ancestry markers usable")), /*#__PURE__*/React.createElement("div", {
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
  }, "Closest broad reference cluster"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 700,
      color: SUPERPOP_COLORS[closestSuperpopulation.label] || '#e5e5e5'
    }
  }, closestSuperpopulation.label || '–'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#888',
      marginTop: 2
    }
  }, POP_LABELS[closestSuperpopulation.label] || closestSuperpopulation.label || ''), closestSuperpopulation.distance != null && /*#__PURE__*/React.createElement("div", {
    className: "mono-text",
    style: {
      marginTop: 8
    }
  }, Number(closestSuperpopulation.distance).toFixed(4), " PCA distance")), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      flex: '1 1 220px',
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
  }, "Closest population-label centroid"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 22,
      fontWeight: 700,
      color: SUPERPOP_COLORS[POP_SUPERPOP[closestPopulation.label]] || '#e5e5e5'
    }
  }, closestPopulation.label || '–'), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: '#888',
      marginTop: 2
    }
  }, POP_LABELS[closestPopulation.label] || closestPopulation.label || ''), closestPopulation.distance != null && /*#__PURE__*/React.createElement("div", {
    className: "mono-text",
    style: {
      marginTop: 8
    }
  }, Number(closestPopulation.distance).toFixed(4), " PCA distance")), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      flex: '2 1 300px',
      padding: '14px 18px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.06em',
      marginBottom: 8
    }
  }, "How to read this"), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#aaa',
      fontSize: 12,
      lineHeight: 1.6
    }
  }, "Smaller PCA distances mean greater similarity to a reference-group centroid in this panel. Distances are arbitrary PCA units, not ancestry percentages, probabilities, or identity labels."), d.markerOverlapQuality && /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#666',
      fontSize: 11,
      marginTop: 8
    }
  }, "Marker-overlap quality: ", d.markerOverlapQuality))), /*#__PURE__*/React.createElement("div", {
    className: "two-col"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, "Population centroid distances")), /*#__PURE__*/React.createElement("div", {
    className: "card-body"
  }, centroidRows(populationCentroids, false))), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, "Broad-cluster centroid distances")), /*#__PURE__*/React.createElement("div", {
    className: "card-body"
  }, centroidRows(superpopulationCentroids, true)))));
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
    return /*#__PURE__*/React.createElement(React.Fragment, {
      key: item.id
    }, showSection && /*#__PURE__*/React.createElement("div", {
      className: "sidebar-section-label"
    }, item.section), /*#__PURE__*/React.createElement("div", {
      className: `nav-item ${active === item.id ? 'active' : ''}`,
      onClick: () => onNav(item.id)
    }, /*#__PURE__*/React.createElement("span", {
      className: "nav-icon"
    }, item.icon), /*#__PURE__*/React.createElement("span", null, item.label)));
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
