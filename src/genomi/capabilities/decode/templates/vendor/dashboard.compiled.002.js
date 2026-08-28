// AUTO-GENERATED chunk 2/3 from dashboard sources by scripts/build_dashboard.py - do not edit by hand.
// source-sha256: 6b67c316a73ac2de502e8c7ea6094d3a343890b34b3b786fc33461b695712cc5
    if (sigFilter === 'other') return !s.includes('pathogenic') && !s.includes('uncertain') && !s.includes('benign');
    return true;
  }
  const plpFiltered = React.useMemo(() => hasPlp ? VARIANTS_DATA.filter(matchesSearch) : [], [search]);
  const allFiltered = React.useMemo(() => hasAll ? VARIANTS_ALL_DATA.filter(v => matchesSearch(v) && matchesSigFilter(v)) : [], [search, sigFilter]);
  const totalCount = hasAll ? VARIANTS_ALL_DATA.length : hasPlp ? VARIANTS_DATA.length : 0;
  const plpCount = hasPlp ? VARIANTS_DATA.length : 0;
  const SIG_TABS = [['all', 'All'], ['plp', 'Pathogenic labels'], ['vus', 'Uncertain'], ['benign', 'Benign'], ['other', 'Other']];
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Variant Explorer"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Exact allele matches against ClinVar records")), /*#__PURE__*/React.createElement("div", {
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
  }, plpCount, " pathogenic-label matches"), totalCount > 0 && /*#__PURE__*/React.createElement("span", {
    className: "badge",
    style: {
      background: '#1a1a1a',
      color: '#666',
      borderColor: '#282828'
    }
  }, totalCount.toLocaleString(), " total"))), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '14px 18px',
      marginBottom: 16,
      color: '#aaa',
      fontSize: 12,
      lineHeight: 1.6
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#e5e5e5'
    }
  }, "Start here:"), " use these database matches as review candidates. Each ClinVar label describes a specific variant\u2013condition assertion. Inheritance, zygosity, symptoms, family history, and clinical confirmation establish personal relevance."), /*#__PURE__*/React.createElement("input", {
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
  }), "Pathogenic / likely pathogenic labels to review"), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      overflow: 'hidden'
    }
  }, plpFiltered.length > 0 ? /*#__PURE__*/React.createElement(VirtualVariantTable, {
    rows: plpFiltered
  }) : /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 24,
      textAlign: 'center',
      color: '#666'
    }
  }, "Adjust your search to view pathogenic-label matches."))), hasAll && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "variant-filter-row",
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 10,
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.08em'
    }
  }, "Full ClinVar match inventory"), /*#__PURE__*/React.createElement("div", {
    className: "variant-filter-tabs",
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
      color: '#666'
    }
  }, "Adjust the search or filter to view matching variants."))));
}
function PharmacogenomicsView() {
  if (!PGX_DATA) return /*#__PURE__*/React.createElement(EmptyPanel, {
    title: "Medication Response",
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
  }, "Medication Response"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "How genetic evidence may affect specific medications"))), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '14px 18px',
      marginBottom: 20,
      color: '#aaa',
      fontSize: 12,
      lineHeight: 1.6
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#e5e5e5'
    }
  }, "Use this with a clinician or pharmacist."), " Pharmacogenomic results support medication review, while treatment changes stay guided by a qualified clinician or pharmacist."), /*#__PURE__*/React.createElement("div", {
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
  }, "Separate review candidates from calibrated risk estimates"))), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '14px 18px',
      marginBottom: 20,
      color: '#aaa',
      fontSize: 12,
      lineHeight: 1.6
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#e5e5e5'
    }
  }, "Interpretation standard:"), " calibrate each raw polygenic score to a reference population before assigning a percentile or relative-risk interpretation. Complete variant review with inheritance, genotype, phenotype, and clinical confirmation."), reviewRows.length > 0 && /*#__PURE__*/React.createElement("div", {
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
  }, "Variant and condition review targets"), /*#__PURE__*/React.createElement("div", {
    className: "risk-grid"
  }, reviewRows.map((d, i) => {
    const sig = firstCountLabel(d.clinical_significance_counts);
    const zygosity = firstCountLabel(d.zygosity_counts);
    const combinedLabel = riskReviewLabel(d);
    const labelParts = combinedLabel.split(' / ');
    const geneLabel = d.gene || (labelParts.length > 1 ? labelParts.shift() : null);
    const conditionLabel = conciseEvidenceLabel(d.condition || (labelParts.length > 0 ? labelParts.join(' / ') : combinedLabel));
    return /*#__PURE__*/React.createElement("div", {
      key: d.group_id || d.candidate_id || d.trait || i,
      className: "risk-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "risk-card-title-row",
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        minWidth: 0
      }
    }, geneLabel && /*#__PURE__*/React.createElement("div", {
      className: "mono-text",
      style: {
        color: '#3b82f6',
        fontSize: 11,
        fontWeight: 600,
        marginBottom: 5
      }
    }, geneLabel), /*#__PURE__*/React.createElement("div", {
      style: {
        color: '#e5e5e5',
        fontWeight: 600,
        fontSize: 14,
        lineHeight: 1.4
      }
    }, conditionLabel || '-')), /*#__PURE__*/React.createElement("span", {
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
        color: '#666',
        fontSize: 11
      }
    }, /*#__PURE__*/React.createElement("span", null, "Review candidate \xB7 clinical confirmation required"), Array.isArray(d.candidate_ids) && d.candidate_ids.length > 0 && /*#__PURE__*/React.createElement("span", null, d.candidate_ids.length, " linked variants")));
  }))), prsRows.length > 0 && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 700,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.08em',
      marginBottom: 10
    }
  }, "Polygenic score calculations"), /*#__PURE__*/React.createElement("div", {
    className: "risk-grid"
  }, prsRows.map((d, i) => {
    const level = prsLevel(d.percentile);
    const scoreNum = d.score != null ? Number(d.score) : null;
    const scoreStr = scoreNum != null ? (scoreNum > 0 ? '+' : '') + scoreNum.toFixed(3) : '-';
    return /*#__PURE__*/React.createElement("div", {
      key: d.score_id || d.trait || i,
      className: "risk-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "risk-card-title-row",
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
        marginTop: 10
      }
    }, d.percentile != null ? /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 20,
        fontWeight: 700,
        color: level.color
      }
    }, level.label), /*#__PURE__*/React.createElement("span", {
      className: "badge",
      style: {
        background: level.color + '18',
        color: level.color,
        borderColor: level.color + '30'
      }
    }, d.percentile, "th percentile")) : /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        color: '#e5e5e5',
        fontSize: 14,
        fontWeight: 600
      }
    }, "Score calculated"), /*#__PURE__*/React.createElement("div", {
      style: {
        color: '#777',
        fontSize: 11,
        marginTop: 3
      }
    }, "Calibration will add a percentile and absolute-risk interpretation."))), d.note && d.percentile != null && /*#__PURE__*/React.createElement("div", {
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
    }, d.ancestryAdjusted ? 'population adjustment applied' : 'population adjustment pending')), /*#__PURE__*/React.createElement("details", {
      style: {
        marginTop: 10,
        color: '#555',
        fontSize: 11
      }
    }, /*#__PURE__*/React.createElement("summary", {
      style: {
        cursor: 'pointer'
      }
    }, "Technical score details"), /*#__PURE__*/React.createElement("div", {
      className: "mono-text",
      style: {
        marginTop: 6
      }
    }, "Raw weighted score: ", scoreStr)));
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
  const distanceNote = 'PCA centroid distance · lower values indicate closer reference similarity';
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
  const rankedReferenceGroups = (rows, broad, maxRows) => {
    const plotted = rows.slice(0, maxRows || rows.length);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 8
      }
    }, plotted.map((row, i) => {
      const sp = broad ? row.label : POP_SUPERPOP[row.label] || 'OTH';
      const color = SUPERPOP_COLORS[sp] || '#888';
      return /*#__PURE__*/React.createElement("div", {
        key: `${row.label}-${i}`,
        style: {
          display: 'grid',
          gridTemplateColumns: '32px minmax(0, 1fr)',
          alignItems: 'center',
          gap: 10,
          padding: '9px 10px',
          borderRadius: 8,
          background: i === 0 ? color + '12' : '#141414'
        }
      }, /*#__PURE__*/React.createElement("div", {
        className: "mono-text",
        style: {
          width: 28,
          height: 28,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: i === 0 ? color : '#222',
          color: i === 0 ? '#0a0a0a' : '#888',
          fontWeight: 700
        }
      }, i + 1), /*#__PURE__*/React.createElement("div", {
        style: {
          minWidth: 0
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          color: i === 0 ? '#f5f5f5' : '#ccc',
          fontSize: 13,
          fontWeight: i === 0 ? 700 : 500,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis'
        }
      }, POP_LABELS[row.label] || row.label), /*#__PURE__*/React.createElement("div", {
        style: {
          color: '#666',
          fontSize: 10,
          marginTop: 2
        }
      }, /*#__PURE__*/React.createElement("span", {
        className: "mono-text"
      }, row.label), i === 0 ? ' · closest match in this comparison' : '')));
    }), plotted.length < rows.length && /*#__PURE__*/React.createElement("div", {
      style: {
        color: '#666',
        fontSize: 11,
        marginTop: 4
      }
    }, "Showing the ", plotted.length, " closest groups. The complete technical ranking is available below."));
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "view-content"
  }, /*#__PURE__*/React.createElement("div", {
    className: "view-header"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    className: "view-title"
  }, "Ancestry Context"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "How your DNA pattern compares with people in the 1000 Genomes reference dataset")), d.overlapFraction != null && /*#__PURE__*/React.createElement("span", {
    className: "badge",
    style: {
      background: '#3b82f618',
      color: '#3b82f6',
      borderColor: '#3b82f630'
    }
  }, Math.round(d.overlapFraction * 100), "% ancestry markers usable")), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '22px 24px',
      marginBottom: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: 'var(--text4)',
      textTransform: 'uppercase',
      letterSpacing: '0.06em',
      marginBottom: 8
    }
  }, "Your closest reference match"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 30,
      fontWeight: 800,
      color: SUPERPOP_COLORS[closestSuperpopulation.label] || '#e5e5e5'
    }
  }, POP_LABELS[closestSuperpopulation.label] || closestSuperpopulation.label || 'Reference match pending'), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#bbb',
      fontSize: 14,
      marginTop: 8,
      lineHeight: 1.6
    }
  }, "Your DNA pattern most closely matches the ", /*#__PURE__*/React.createElement("strong", null, POP_LABELS[closestSuperpopulation.label] || closestSuperpopulation.label || 'nearest'), " samples in this reference dataset. The closest specifically named group is ", /*#__PURE__*/React.createElement("strong", null, POP_LABELS[closestPopulation.label] || closestPopulation.label || 'pending'), "."), /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#777',
      fontSize: 11,
      marginTop: 10
    }
  }, "Use this as a reference-dataset similarity result. Ancestry percentages, ethnicity, and identity each require different evidence.")), /*#__PURE__*/React.createElement("div", {
    className: "two-col"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, "Closest named comparison groups")), /*#__PURE__*/React.createElement("div", {
    className: "card-body"
  }, rankedReferenceGroups(populationCentroids, false, 5))), /*#__PURE__*/React.createElement("div", {
    className: "card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "card-header"
  }, /*#__PURE__*/React.createElement("span", null, "How to understand the result")), /*#__PURE__*/React.createElement("div", {
    className: "card-body",
    style: {
      color: '#aaa',
      fontSize: 12,
      lineHeight: 1.7
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#e5e5e5'
    }
  }, "What it says:"), " among the people included in this public dataset, your overall DNA pattern is closest to the groups shown here."), /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#e5e5e5'
    }
  }, "Scope:"), " this result compares your overall pattern with reference groups. Ancestry composition and personal identity use additional evidence and methods."), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#e5e5e5'
    }
  }, "Data quality:"), " ", d.markerOverlapQuality || 'pending', " marker overlap", d.overlapFraction != null ? ` (${Math.round(d.overlapFraction * 100)}% of panel markers usable)` : '', ".")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("details", {
    className: "card"
  }, /*#__PURE__*/React.createElement("summary", {
    className: "card-header",
    style: {
      cursor: 'pointer'
    }
  }, "Technical PCA distances and full ranking"), /*#__PURE__*/React.createElement("div", {
    className: "card-body two-col"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#aaa',
      fontSize: 11,
      marginBottom: 12
    }
  }, "Population-label centroids"), centroidRows(populationCentroids, false)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      color: '#aaa',
      fontSize: 11,
      marginBottom: 12
    }
  }, "Broad reference clusters"), centroidRows(superpopulationCentroids, true))))));
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
  }, "Nutrition Marker Reference"), /*#__PURE__*/React.createElement("p", {
    className: "view-subtitle"
  }, "Research context for gene\u2013nutrition markers"))), /*#__PURE__*/React.createElement("div", {
    className: "card",
    style: {
      padding: '14px 18px',
      marginBottom: 20,
      color: '#aaa',
      fontSize: 12,
      lineHeight: 1.6
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: '#e5e5e5'
    }
  }, "Use these records as nutrition research background."), " Personal interpretation begins with genotype evidence at each marker. A qualified clinician or dietitian can connect confirmed results with diet or supplement decisions."), /*#__PURE__*/React.createElement("div", {
    className: "nutri-grid"
  }, NUTRI_DATA.map((d, i) => {
    const tc = tierColors[d.evidenceTier] || '#666';
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      className: "nutri-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "nutri-card-title-row",
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 10
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
    }, d.rsid), d.status && /*#__PURE__*/React.createElement("span", {
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
        color: '#666',
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        marginTop: 12
      }
    }, "What research reports"), /*#__PURE__*/React.createElement("div", {
      style: {
        color: '#999',
        fontSize: 12,
        lineHeight: 1.6,
        marginTop: 5
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
  }, "Experimental \xB7 Research use only", /*#__PURE__*/React.createElement("br", null), "Clinical confirmation supports health decisions", RENDERED_AT && /*#__PURE__*/React.createElement("span", {
    className: "timestamp"
  }, "rendered ", RENDERED_AT)));
}
function MobileNav({
  active,
  onNav
