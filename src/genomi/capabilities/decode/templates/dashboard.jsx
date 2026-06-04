    // All evidence comes from the decode pipeline via window.__GENOMI_DASHBOARD__.
    // Anything below this line is presentation/layout only — no genome data is
    // prefilled in the template.
    const TWEAK_DEFAULTS = { accentColor: 'green', showSupport: true, compactCards: false };

    const EV = window.__GENOMI_DASHBOARD__ || {};
    const GENOME_SUMMARY = EV.overview || null;
    const VARIANTS_DATA = Array.isArray(EV.variants) ? EV.variants : null;
    const PGX_DATA = Array.isArray(EV.pgx) ? EV.pgx : null;
    const PRS_DATA = Array.isArray(EV.risk) ? EV.risk : null;
    const ANCESTRY_DATA = EV.ancestry || null;
    const NUTRI_DATA = Array.isArray(EV.nutrigenomics) ? EV.nutrigenomics : null;
    const VARIANTS_ALL_DATA = Array.isArray(EV.variants_all) ? EV.variants_all : null;
    const JOURNAL_ENTRIES = Array.isArray(EV.journal) ? EV.journal : null;

    const PGX_IMPACT_COLORS = { normal: '#10b981', moderate: '#f59e0b', reduced: '#f59e0b', increased: '#f59e0b', elevated: '#ef4444', poor: '#ef4444' };
    function prsLevel(p) {
      if (p == null) return { label: '-', color: '#666' };
      if (p >= 80) return { label: 'Elevated', color: '#ef4444' };
      if (p >= 60) return { label: 'Moderate', color: '#f59e0b' };
      if (p >= 40) return { label: 'Average', color: '#aaaaaa' };
      return { label: 'Below Avg', color: '#10b981' };
    }
    const RENDERED_AT = EV.__renderedAt || '';

    const PANEL_OPS = {
      overview: 'active_genome_index.summarize',
      variants: 'clinvar.scan_candidates',
      pgx: 'pharmacogenomics.run_pharmcat',
      risk: 'prs.calculate_score',
      ancestry: 'ancestry.estimate_population_context',
      nutrigenomics: 'nutrigenomics.retrieve_domain_markers',
      journal: 'journal.search_entries',
    };

    const NAV_ITEMS = [
      { id: 'overview', label: 'Overview', icon: '◫', section: 'Dashboard', panel: 'overview' },
      { id: 'variants', label: 'Variants', icon: '◇', section: 'Dashboard', panel: 'variants' },
      { id: 'pharmacogenomics', label: 'Pharmacogenomics', icon: '◉', section: 'Genomics', panel: 'pgx' },
      { id: 'risk', label: 'Risk Scores', icon: '◈', section: 'Genomics', panel: 'risk' },
      { id: 'ancestry', label: 'Ancestry', icon: '◎', section: 'Genomics', panel: 'ancestry' },
      { id: 'nutrigenomics', label: 'Nutrigenomics', icon: '◆', section: 'Genomics', panel: 'nutrigenomics' },
      { id: 'journal', label: 'Journal', icon: '▤', section: 'Memory', panel: 'journal' },
    ];

    // Keep ungathered panels navigable so their EmptyPanel placeholders make
    // the dashboard state explicit after partial renders or cleared updates.
    const AVAILABLE_NAV = NAV_ITEMS;

    const ACCENT_MAP = {
      green: { primary: '#10b981', glow: '#10b98120' },
      blue: { primary: '#3b82f6', glow: '#3b82f620' },
      purple: { primary: '#8b5cf6', glow: '#8b5cf620' },
      amber: { primary: '#f59e0b', glow: '#f59e0b20' },
    };

    function EmptyPanel({ title, op }) {
      return (
        <div className="view-content">
          <div className="view-header">
            <div>
              <h2 className="view-title">{title}</h2>
              <p className="view-subtitle">No evidence rendered for this panel yet.</p>
            </div>
          </div>
          <div className="card">
            <div className="card-header"><span>{title}</span></div>
            <div className="empty-body">
              Not gathered yet. Ask the agent to run the matching <code>genomi.invoke</code> op
              {op ? <> &mdash; <code>{op}</code></> : null}.
            </div>
          </div>
        </div>
      );
    }

    function HighlightCard({ title, onNav, children }) {
      return (
        <div className="card">
          <div className="card-header">
            <span>{title}</span>
            {onNav && (
              <span className="highlight-link" onClick={onNav}>View →</span>
            )}
          </div>
          <div className="card-body">{children}</div>
        </div>
      );
    }

    function OverviewView({ onNav }) {
      if (!GENOME_SUMMARY) return <EmptyPanel title="Overview" op={PANEL_OPS.overview} />;
      const gs = GENOME_SUMMARY;
      const variantCount = gs.variantCount != null ? Number(gs.variantCount).toLocaleString() : '-';
      const gq = gs.genotypeQuality != null ? `${gs.genotypeQuality}%` : '-';
      const gqSub = gs.meanDepth != null
        ? `${gs.meanDepth}× mean depth`
        : (gs.genotypeQuality != null ? 'PASS rate' : '');
      const sources = Array.isArray(gs.sourceCoverage) ? gs.sourceCoverage : [];

      const _varHiSrc = VARIANTS_DATA || VARIANTS_ALL_DATA;
      const variantsHi = _varHiSrc && _varHiSrc.length > 0 ? _varHiSrc.slice(0, 3) : null;
      const pgxHi = PGX_DATA && PGX_DATA.length > 0 ? PGX_DATA.slice(0, 3) : null;
      const riskHi = PRS_DATA && PRS_DATA.length > 0 ? PRS_DATA.slice(0, 3) : null;
      const ancestryHi = ANCESTRY_DATA && (ANCESTRY_DATA.dominantAncestry || (Array.isArray(ANCESTRY_DATA.neighbors) && ANCESTRY_DATA.neighbors.length > 0)) ? ANCESTRY_DATA : null;
      const nutriHi = NUTRI_DATA && NUTRI_DATA.length > 0 ? NUTRI_DATA.slice(0, 3) : null;
      const journalHi = JOURNAL_ENTRIES && JOURNAL_ENTRIES.length > 0 ? JOURNAL_ENTRIES.slice(0, 3) : null;

      const anyHighlights = !!(variantsHi || pgxHi || riskHi || ancestryHi || nutriHi || journalHi);

      return (
        <div className="view-content">
          <div className="view-header">
            <div>
              <h2 className="view-title">Overview</h2>
              <p className="view-subtitle">
                Active Genome Index{gs.sampleId ? ` · ${gs.sampleId}` : ''}
                {gs.genomeBuild ? ` · ${gs.genomeBuild}` : ''}
              </p>
            </div>
            <div className="header-badge">
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#10b981' }} />
              <span style={{ color: '#10b981', fontSize: 12, fontWeight: 600 }}>Index Active</span>
            </div>
          </div>

          <div className="stats-grid">
            <div className="stat-card"><div className="stat-value" style={{ color: '#10b981' }}>{variantCount}</div><div className="stat-label">Variants Indexed</div><div className="stat-sub">{gs.genomeSource || ''}</div></div>
            <div className="stat-card"><div className="stat-value" style={{ color: '#3b82f6' }}>{gs.genomeBuild || '-'}</div><div className="stat-label">Genome Build</div><div className="stat-sub">{gs.parsedAt || ''}</div></div>
            {gs.genotypeQuality != null
              ? <div className="stat-card"><div className="stat-value" style={{ color: '#8b5cf6' }}>{gq}</div><div className="stat-label">Genotype Quality</div><div className="stat-sub">{gqSub}</div></div>
              : <div className="stat-card"><div className="stat-value" style={{ color: '#8b5cf6', fontSize: 14, paddingTop: 4 }}>{gs.pipeline || gs.genomeSource || '-'}</div><div className="stat-label">Variant Caller</div><div className="stat-sub">{gs.contig_count != null ? `${Number(gs.contig_count).toLocaleString()} contigs` : ''}</div></div>
            }
            <div className="stat-card"><div className="stat-value" style={{ color: '#f59e0b' }}>{PGX_DATA ? PGX_DATA.length : '-'}</div><div className="stat-label">PGx Markers</div><div className="stat-sub">{PGX_DATA ? `${PGX_DATA.filter(d => d.impact && d.impact !== 'normal').length} actionable` : ''}</div></div>
          </div>

          {sources.length > 0 && (
            <div className="card" style={{ marginBottom: 20 }}>
              <div className="card-header"><span>Source Coverage</span></div>
              <div className="card-body">
                <div className="source-grid">
                  {sources.map((src, i) => (
                    <div key={i} className="source-item">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ color: '#e5e5e5', fontSize: 13, fontWeight: 600 }}>{src.name || src.label || src.source || src.library || src.library_id || src.id || 'unknown source'}</span>
                        <span className="badge" style={{ background: '#10b98118', color: '#10b981', borderColor: '#10b98130' }}>{src.status || 'ok'}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, color: '#555', fontSize: 11 }}>
                        <span>{src.percent != null ? `${src.percent}%` : ''}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {anyHighlights && (
            <div className="two-col">
              {variantsHi && (
                <HighlightCard title="Top Variants" onNav={onNav ? () => onNav('variants') : null}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {variantsHi.map((v, i) => {
                      const sc = v.clinvarSignificance ? sigBadgeStyle(v.clinvarSignificance) : null;
                      return (
                        <div key={v.rsid || i} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                            <span className="mono-text" style={{ color: '#e5e5e5', fontSize: 12 }}>{v.rsid || '-'}</span>
                            {v.gene && <span style={{ color: '#3b82f6', fontWeight: 600, fontSize: 12 }}>{v.gene}</span>}
                          </div>
                          {sc && (
                            <span className="badge" style={{ alignSelf: 'flex-start', background: sc.bg, color: sc.fg, borderColor: sc.border }}>{v.clinvarSignificance.replace(/_/g, ' ')}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </HighlightCard>
              )}
              {pgxHi && (
                <HighlightCard title="Pharmacogenomics" onNav={onNav ? () => onNav('pharmacogenomics') : null}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {pgxHi.map((d, i) => {
                      const ic = PGX_IMPACT_COLORS[d.impact] || '#666';
                      return (
                        <div key={d.gene || i} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                            <span style={{ color: '#e5e5e5', fontWeight: 600, fontFamily: 'var(--mono)', fontSize: 13 }}>{d.gene || '-'}</span>
                            <span className="mono-text" style={{ fontSize: 12 }}>{d.diplotype || ''}</span>
                          </div>
                          {d.phenotype && (
                            <span className="badge" style={{ alignSelf: 'flex-start', background: ic + '18', color: ic, borderColor: ic + '30' }}>{d.phenotype}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </HighlightCard>
              )}
              {riskHi && (
                <HighlightCard title="Risk Scores" onNav={onNav ? () => onNav('risk') : null}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {riskHi.map((d, i) => {
                      const scoreNum = d.score != null ? Number(d.score) : null;
                      const scoreStr = scoreNum != null ? (scoreNum > 0 ? '+' : '') + scoreNum.toFixed(3) : '-';
                      const scoreColor = scoreNum == null ? '#666' : scoreNum > 0.5 ? '#f59e0b' : scoreNum < -0.5 ? '#3b82f6' : '#aaa';
                      return (
                        <div key={d.trait || i} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <span style={{ color: '#e5e5e5', fontSize: 13, fontWeight: 600 }}>{d.trait || '-'}</span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontFamily: 'var(--mono)', fontSize: 16, fontWeight: 700, color: scoreColor }}>{scoreStr}</span>
                            {d.percentile != null ? (
                              <span className="badge" style={{ background: prsLevel(d.percentile).color + '18', color: prsLevel(d.percentile).color, borderColor: prsLevel(d.percentile).color + '30', fontSize: 10 }}>{d.percentile}th pct</span>
                            ) : (
                              <span className="badge" style={{ background: '#66666618', color: '#888', borderColor: '#66666630', fontSize: 10 }}>raw score</span>
                            )}
                          </div>
                          {d.overlap && <span style={{ color: '#555', fontSize: 10 }}>{d.overlap}</span>}
                        </div>
                      );
                    })}
                  </div>
                </HighlightCard>
              )}
              {ancestryHi && (
                <HighlightCard title="Ancestry" onNav={onNav ? () => onNav('ancestry') : null}>
                  <div style={{ color: '#e5e5e5', fontSize: 13, marginBottom: 8 }}>
                    Closest: <span style={{ color: '#3b82f6', fontWeight: 600 }}>{ancestryHi.dominantAncestry || '-'}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {(Array.isArray(ancestryHi.neighbors) ? ancestryHi.neighbors : []).slice(0, 3).map((n, i) => (
                      <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 4, height: 4, borderRadius: '50%', background: SUPERPOP_COLORS[POP_SUPERPOP[n.population]] || '#888', display: 'inline-block' }} />
                          <span style={{ color: '#e5e5e5' }}>{POP_LABELS[n.population] || n.population || '-'}</span>
                          <span className="mono-text" style={{ color: '#555', fontSize: 10 }}>{n.population}</span>
                        </div>
                        <span className="mono-text">{n.similarity != null ? String(n.similarity) : ''}</span>
                      </div>
                    ))}
                  </div>
                </HighlightCard>
              )}
              {nutriHi && (
                <HighlightCard title="Nutrigenomics" onNav={onNav ? () => onNav('nutrigenomics') : null}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {nutriHi.map((d, i) => {
                      const ntc = { established: '#10b981', probable: '#f59e0b', emerging: '#8b5cf6' }[d.evidenceTier] || '#666';
                      return (
                        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 }}>
                            <span style={{ color: '#e5e5e5', fontWeight: 600, fontSize: 13 }}>{d.marker || '-'}</span>
                            {d.gene && <span className="mono-text" style={{ color: '#3b82f6', fontSize: 12 }}>{d.gene}</span>}
                          </div>
                          {d.evidenceTier && <span className="badge" style={{ background: ntc + '18', color: ntc, borderColor: ntc + '30', fontSize: 10, flexShrink: 0 }}>{d.evidenceTier}</span>}
                        </div>
                      );
                    })}
                  </div>
                </HighlightCard>
              )}
              {journalHi && (
                <HighlightCard title="Journal" onNav={onNav ? () => onNav('journal') : null}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {journalHi.map((entry, i) => (
                      <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, fontSize: 12 }}>
                        <span className="tag-chip">{entry.kind || '-'}</span>
                        <span style={{ color: '#e5e5e5', fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.title || ''}</span>
                        <span className="mono-text" style={{ color: '#444' }}>{entry.ts || ''}</span>
                      </div>
                    ))}
                  </div>
                </HighlightCard>
              )}
            </div>
          )}
        </div>
      );
    }

    function sigBadgeStyle(sig) {
      const s = (sig || '').toLowerCase();
      if (s.includes('conflicting'))   return { bg: '#f59e0b18', fg: '#f59e0b', border: '#f59e0b30' };
      if (s.includes('benign'))        return { bg: '#10b98118', fg: '#10b981', border: '#10b98130' };
      if (s.includes('uncertain') || s.includes('vus')) return { bg: '#66666618', fg: '#888888', border: '#66666630' };
      // LP-only: starts with "likely pathogenic"
      if (s.startsWith('likely_pathogenic') || s.startsWith('likely pathogenic'))
        return { bg: '#f59e0b18', fg: '#f59e0b', border: '#f59e0b30' };
      // P/LP combined: contains both pathogenic and likely (e.g. "Pathogenic/Likely pathogenic")
      if (s.includes('pathogenic') && s.includes('likely'))
        return { bg: '#f9731618', fg: '#f97316', border: '#f9731630' };
      // P only: red
      if (s.includes('pathogenic'))
        return { bg: '#ef444418', fg: '#ef4444', border: '#ef444430' };
      if (s.includes('risk') || s.includes('association') || s.includes('protective'))
        return { bg: '#3b82f618', fg: '#3b82f6', border: '#3b82f630' };
      return { bg: '#8b5cf618', fg: '#8b5cf6', border: '#8b5cf630' };
    }

    function VirtualVariantTable({ rows }) {
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

      return (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: COLS, padding: '10px 14px',
            borderBottom: '1px solid var(--border)',
            fontSize: 11, fontWeight: 600, color: 'var(--text4)',
            textTransform: 'uppercase', letterSpacing: '0.04em', background: 'var(--surface)',
          }}>
            <span>Variant</span><span>Gene</span><span>Location</span>
            <span>Genotype</span><span>Significance</span><span>Condition</span><span>Quality</span>
          </div>
          <div
            ref={containerRef}
            onScroll={e => setScrollTop(e.currentTarget.scrollTop)}
            style={{ overflowY: 'auto', height: containerH }}
          >
            <div style={{ height: startIdx * ROW_H }} />
            {visibleRows.map((v, i) => {
              const sc = sigBadgeStyle(v.clinvarSignificance);
              return (
                <div key={v.rsid || (startIdx + i)} style={{
                  display: 'grid', gridTemplateColumns: COLS,
                  padding: '0 14px', height: ROW_H, alignItems: 'center',
                  borderBottom: '1px solid #141414',
                }}>
                  <span className="mono-text" style={{ color: '#e5e5e5', fontSize: 12 }}>{v.rsid || '-'}</span>
                  <span style={{ color: '#3b82f6', fontWeight: 600, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.gene || '-'}</span>
                  <span className="mono-text" style={{ fontSize: 11 }}>chr{v.chrom}:{v.pos != null ? Number(v.pos).toLocaleString() : ''}</span>
                  <span className="genotype-badge">{v.ref}{'>'}{v.alt}{v.zygosity ? <span style={{ color: '#555', fontSize: 10 }}> {v.zygosity}</span> : null}</span>
                  <span className="badge" style={{ background: sc.bg, color: sc.fg, borderColor: sc.border, fontSize: 10, maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(v.clinvarSignificance || '').replace(/_/g, ' ')}</span>
                  <span style={{ color: '#aaa', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.conditionShort || ''}</span>
                  <span style={{ color: '#555', fontSize: 11 }}>{v.evidenceQuality || ''}</span>
                </div>
              );
            })}
            <div style={{ height: Math.max(0, (rows.length - endIdx) * ROW_H) }} />
          </div>
          {rows.length > 0 && (
            <div style={{ padding: '8px 14px', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text4)', display: 'flex', justifyContent: 'space-between' }}>
              <span>{rows.length.toLocaleString()} variants</span>
              <span>Scroll to explore · rendering {Math.min(endIdx - startIdx, rows.length)} rows</span>
            </div>
          )}
        </div>
      );
    }

    function VariantsView() {
      const hasPlp = VARIANTS_DATA && VARIANTS_DATA.length > 0;
      const hasAll = VARIANTS_ALL_DATA && VARIANTS_ALL_DATA.length > 0;
      if (!hasPlp && !hasAll) return <EmptyPanel title="Variants" op={PANEL_OPS.variants} />;

      const [search, setSearch] = React.useState('');
      const [sigFilter, setSigFilter] = React.useState('all');

      function matchesSearch(v) {
        if (!search) return true;
        const s = search.toLowerCase();
        return (v.rsid || '').toLowerCase().includes(s)
          || (v.gene || '').toLowerCase().includes(s)
          || (v.conditionShort || '').toLowerCase().includes(s)
          || (v.clinvarSignificance || '').toLowerCase().includes(s);
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

      const plpFiltered = React.useMemo(
        () => hasPlp ? VARIANTS_DATA.filter(matchesSearch) : [],
        [search]
      );
      const allFiltered = React.useMemo(
        () => hasAll ? VARIANTS_ALL_DATA.filter(v => matchesSearch(v) && matchesSigFilter(v)) : [],
        [search, sigFilter]
      );

      const totalCount = hasAll ? VARIANTS_ALL_DATA.length : (hasPlp ? VARIANTS_DATA.length : 0);
      const plpCount = hasPlp ? VARIANTS_DATA.length : 0;

      const SIG_TABS = [
        ['all', 'All'],
        ['plp', 'P/LP'],
        ['vus', 'VUS'],
        ['benign', 'Benign'],
        ['other', 'Other'],
      ];

      return (
        <div className="view-content">
          <div className="view-header">
            <div>
              <h2 className="view-title">Variant Explorer</h2>
              <p className="view-subtitle">ClinVar-matched variants from your Active Genome Index</p>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {plpCount > 0 && (
                <span className="badge" style={{ background: '#f9731618', color: '#f97316', borderColor: '#f9731630' }}>
                  {plpCount} P/LP
                </span>
              )}
              {totalCount > 0 && (
                <span className="badge" style={{ background: '#1a1a1a', color: '#666', borderColor: '#282828' }}>
                  {totalCount.toLocaleString()} total
                </span>
              )}
            </div>
          </div>

          <input placeholder="Search rsID, gene, condition, or significance…"
            value={search} onChange={e => setSearch(e.target.value)}
            style={{ width: '100%', padding: '8px 14px', borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)', fontFamily: 'var(--sans)', fontSize: 13, outline: 'none', marginBottom: 20 }} />

          {hasPlp && (
            <div style={{ marginBottom: 28 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#f97316', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f97316', display: 'inline-block' }} />
                Clinically Significant
              </div>
              <div className="card" style={{ overflow: 'hidden' }}>
                <table className="variant-table">
                  <thead>
                    <tr>
                      <th>Variant</th><th>Gene</th><th>Location</th>
                      <th>Genotype</th><th>Significance</th><th>Condition</th><th>Quality</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plpFiltered.map((v, i) => {
                      const sc = sigBadgeStyle(v.clinvarSignificance);
                      return (
                        <tr key={v.rsid || i}>
                          <td><span className="mono-text" style={{ color: '#e5e5e5' }}>{v.rsid}</span></td>
                          <td><span style={{ color: '#3b82f6', fontWeight: 600, fontSize: 13 }}>{v.gene}</span></td>
                          <td><span className="mono-text">chr{v.chrom}:{v.pos != null ? Number(v.pos).toLocaleString() : ''}</span></td>
                          <td>
                            <span className="genotype-badge">
                              {v.ref}{'>'}{v.alt}{v.zygosity ? <span style={{ color: '#555', fontSize: 10 }}> {v.zygosity}</span> : null}
                            </span>
                          </td>
                          <td><span className="badge" style={{ background: sc.bg, color: sc.fg, borderColor: sc.border }}>{(v.clinvarSignificance || '').replace(/_/g, ' ')}</span></td>
                          <td style={{ color: '#aaa', fontSize: 12 }}>{v.conditionShort}</td>
                          <td style={{ color: '#555', fontSize: 11 }}>{v.evidenceQuality || ''}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {plpFiltered.length === 0 && (
                  <div style={{ padding: 24, textAlign: 'center', color: '#444' }}>No P/LP variants match your search.</div>
                )}
              </div>
            </div>
          )}

          {hasAll && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  All ClinVar Variants
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {SIG_TABS.map(([key, label]) => (
                    <button key={key} onClick={() => setSigFilter(key)} style={{
                      padding: '3px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                      cursor: 'pointer', border: '1px solid',
                      background: sigFilter === key ? 'var(--surface2)' : 'transparent',
                      color: sigFilter === key ? 'var(--text)' : 'var(--text4)',
                      borderColor: sigFilter === key ? 'var(--border2)' : 'transparent',
                    }}>{label}</button>
                  ))}
                </div>
              </div>
              <div className="card" style={{ overflow: 'hidden' }}>
                {allFiltered.length > 0
                  ? <VirtualVariantTable rows={allFiltered} />
                  : <div style={{ padding: 40, textAlign: 'center', color: '#444' }}>No variants match your filter.</div>
                }
              </div>
            </div>
          )}
        </div>
      );
    }

    function PharmacogenomicsView() {
      if (!PGX_DATA) return <EmptyPanel title="Pharmacogenomics" op={PANEL_OPS.pgx} />;
      const impactColors = PGX_IMPACT_COLORS;
      return (
        <div className="view-content">
          <div className="view-header">
            <div>
              <h2 className="view-title">Pharmacogenomics</h2>
              <p className="view-subtitle">Drug–gene interactions from ClinPGx, FDA labels, and PGxDB</p>
            </div>
          </div>
          <div className="pgx-grid">
            {PGX_DATA.map((d, i) => {
              const ic = impactColors[d.impact] || '#666';
              return (
                <div key={d.gene || i} className="pgx-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: '#f5f5f5', fontWeight: 700, fontSize: 15, fontFamily: 'var(--mono)' }}>{d.gene}</span>
                        <span style={{ color: '#666', fontSize: 12, fontFamily: 'var(--mono)' }}>{d.diplotype}</span>
                      </div>
                      <div style={{ color: ic, fontSize: 13, fontWeight: 600, marginTop: 4 }}>{d.phenotype}</div>
                    </div>
                    <span className="badge" style={{ background: ic + '18', color: ic, borderColor: ic + '30' }}>{d.impact}</span>
                  </div>
                  {Array.isArray(d.drugs) && d.drugs.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 10 }}>
                      {d.drugs.map((drug, j) => {
                        const name = typeof drug === 'string' ? drug : drug.name;
                        const rec = typeof drug === 'string' ? null : drug.recommendation;
                        return (
                          <span key={j} className="drug-chip" title={rec || ''}>{name}</span>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      );
    }

    function RiskScoresView() {
      if (!PRS_DATA) return <EmptyPanel title="Risk Scores" op={PANEL_OPS.risk} />;
      return (
        <div className="view-content">
          <div className="view-header">
            <div>
              <h2 className="view-title">Polygenic Risk Scores</h2>
              <p className="view-subtitle">Published PGS Catalog scores applied to your genome</p>
            </div>
          </div>
          <div className="risk-grid">
            {PRS_DATA.map((d, i) => {
              const level = prsLevel(d.percentile);
              const scoreNum = d.score != null ? Number(d.score) : null;
              const scoreStr = scoreNum != null ? (scoreNum > 0 ? '+' : '') + scoreNum.toFixed(3) : '-';
              const scoreColor = scoreNum == null ? '#666' : scoreNum > 0.5 ? '#f59e0b' : scoreNum < -0.5 ? '#3b82f6' : '#aaa';
              return (
                <div key={d.trait || i} className="risk-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                    <div style={{ color: '#e5e5e5', fontWeight: 600, fontSize: 14 }}>{d.trait}</div>
                    {Array.isArray(d.sources) && d.sources.length > 0 && (
                      <span className="mono-text" style={{ color: '#555', fontSize: 10, whiteSpace: 'nowrap' }}>{d.sources[0]}</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 10 }}>
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 22, fontWeight: 700, color: scoreColor }}>{scoreStr}</span>
                    {d.percentile != null ? (
                      <span className="badge" style={{ background: level.color + '18', color: level.color, borderColor: level.color + '30' }}>{level.label} · {d.percentile}th pct</span>
                    ) : (
                      <span className="badge" style={{ background: '#66666618', color: '#888', borderColor: '#66666630' }}>raw score</span>
                    )}
                  </div>
                  {d.note && (
                    <div style={{ marginTop: 10, color: '#999', fontSize: 12, lineHeight: 1.6 }}>{d.note}</div>
                  )}
                  <div style={{ marginTop: 8, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    {d.overlap != null && <span style={{ color: '#555', fontSize: 11 }}>overlap: {d.overlap}</span>}
                    {d.ancestryAdjusted != null && <span style={{ color: '#555', fontSize: 11 }}>ancestry-adj: {String(d.ancestryAdjusted)}</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
    }

    const POP_LABELS = {
      EUR:'European', AFR:'African', AMR:'Admixed American', EAS:'East Asian', SAS:'South Asian',
      IBS:'Iberian (Spain)', TSI:'Toscani (Italy)', GBR:'British (England)', CEU:'Utah / NW European',
      FIN:'Finnish', NFE:'Non-Finnish European',
      PUR:'Puerto Rican', CLM:'Colombian', MXL:'Mexican', PEL:'Peruvian',
      YRI:'Yoruba (Nigeria)', LWK:'Luhya (Kenya)', GWD:'Gambian', MSL:'Mende (Sierra Leone)',
      ESN:'Esan (Nigeria)', ASW:'African American (SW)', ACB:'African Caribbean',
      CHB:'Han Chinese (Beijing)', JPT:'Japanese (Tokyo)', CHS:'Han Chinese (S)', CDX:'Chinese Dai', KHV:'Kinh Vietnamese',
      GIH:'Gujarati Indian', PJL:'Punjabi (Lahore)', BEB:'Bengali', STU:'Sri Lankan Tamil', ITU:'Indian Telugu',
    };
    const POP_SUPERPOP = {
      EUR:'EUR', IBS:'EUR', TSI:'EUR', GBR:'EUR', CEU:'EUR', FIN:'EUR', NFE:'EUR',
      AFR:'AFR', YRI:'AFR', LWK:'AFR', GWD:'AFR', MSL:'AFR', ESN:'AFR', ASW:'AFR', ACB:'AFR',
      AMR:'AMR', PUR:'AMR', CLM:'AMR', MXL:'AMR', PEL:'AMR',
      EAS:'EAS', CHB:'EAS', JPT:'EAS', CHS:'EAS', CDX:'EAS', KHV:'EAS',
      SAS:'SAS', GIH:'SAS', PJL:'SAS', BEB:'SAS', STU:'SAS', ITU:'SAS',
    };
    const SUPERPOP_COLORS = { EUR:'#3b82f6', AFR:'#10b981', AMR:'#f97316', EAS:'#f59e0b', SAS:'#8b5cf6' };

    function AncestryView() {
      if (!ANCESTRY_DATA) return <EmptyPanel title="Ancestry" op={PANEL_OPS.ancestry} />;
      const d = ANCESTRY_DATA;
      const neighbors = Array.isArray(d.neighbors) ? d.neighbors : [];
      const pts = Array.isArray(d.pcaPoints) ? d.pcaPoints : [];
      const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
      const xMin = xs.length ? Math.min(...xs) - 4 : -1, xMax = xs.length ? Math.max(...xs) + 4 : 1;
      const yMin = ys.length ? Math.min(...ys) - 4 : -1, yMax = ys.length ? Math.max(...ys) + 4 : 1;
      const W = 480, H = 320, PAD = 30;
      const sx = v => PAD + ((v - xMin) / (xMax - xMin || 1)) * (W - 2 * PAD);
      const sy = v => H - PAD - ((v - yMin) / (yMax - yMin || 1)) * (H - 2 * PAD);
      const palette = { sample: '#f5f5f5', EUR: '#3b82f6', EAS: '#f59e0b', AFR: '#10b981', SAS: '#8b5cf6', AMR: '#f97316' };

      // superpopulation distribution from neighbors
      const spCounts = {};
      neighbors.forEach(n => { const sp = POP_SUPERPOP[n.population] || 'OTH'; spCounts[sp] = (spCounts[sp] || 0) + 1; });
      const spEntries = Object.entries(spCounts).sort((a, b) => b[1] - a[1]);
      const totalN = neighbors.length || 1;
      const domSP = POP_SUPERPOP[d.dominantAncestry] || d.dominantAncestry;

      return (
        <div className="view-content">
          <div className="view-header">
            <div>
              <h2 className="view-title">Ancestry Context</h2>
              <p className="view-subtitle">Reference-panel similarity context (PCA / nearest neighbors)</p>
            </div>
            {d.overlapFraction != null && (
              <span className="badge" style={{ background: '#3b82f618', color: '#3b82f6', borderColor: '#3b82f630' }}>
                {Math.round(d.overlapFraction * 100)}% variant coverage
              </span>
            )}
          </div>

          <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
            <div className="card" style={{ flex: '1 1 160px', padding: '14px 18px' }}>
              <div style={{ fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Dominant Ancestry</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: SUPERPOP_COLORS[domSP] || '#e5e5e5' }}>{domSP || d.dominantAncestry || '–'}</div>
              <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>{POP_LABELS[d.dominantAncestry] || d.dominantAncestry}</div>
            </div>
            <div className="card" style={{ flex: '2 1 260px', padding: '14px 18px' }}>
              <div style={{ fontSize: 11, color: 'var(--text4)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Neighbor Distribution</div>
              {spEntries.map(([sp, count]) => (
                <div key={sp} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span style={{ width: 36, fontSize: 11, fontWeight: 600, color: SUPERPOP_COLORS[sp] || '#888' }}>{sp}</span>
                  <div style={{ flex: 1, height: 6, borderRadius: 3, background: '#1a1a1a', overflow: 'hidden' }}>
                    <div style={{ width: `${(count / totalN) * 100}%`, height: '100%', borderRadius: 3, background: SUPERPOP_COLORS[sp] || '#888' }} />
                  </div>
                  <span style={{ fontSize: 11, color: '#666', width: 20, textAlign: 'right' }}>{count}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="two-col">
            <div className="card">
              <div className="card-header"><span>Nearest Neighbors</span></div>
              <div className="card-body">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {neighbors.map((n, i) => {
                    const sp = POP_SUPERPOP[n.population] || 'OTH';
                    const spColor = SUPERPOP_COLORS[sp] || '#888';
                    return (
                      <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ width: 4, height: 4, borderRadius: '50%', background: spColor, display: 'inline-block', flexShrink: 0 }} />
                          <div>
                            <span style={{ color: '#e5e5e5', fontSize: 12, fontWeight: 500 }}>{POP_LABELS[n.population] || n.population}</span>
                            <span className="mono-text" style={{ color: '#555', fontSize: 10, marginLeft: 6 }}>{n.population}</span>
                          </div>
                        </div>
                        {n.similarity != null ? (
                          <span className="mono-text" style={{ fontSize: 11 }}>{Number(n.similarity).toFixed(4)}</span>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="card">
              <div className="card-header"><span>PCA Projection</span></div>
              {pts.length === 0 ? (
                <div className="empty-body" style={{ padding: '24px 16px', color: '#444', fontSize: 12 }}>
                  No PCA points in evidence. Run <code>ancestry.estimate_population_context</code> with <code>include_pca_points: true</code>.
                </div>
              ) : (
                <div className="card-body" style={{ display: 'flex', justifyContent: 'center' }}>
                  <svg width={W} height={H}>
                    {pts.map((p, i) => (
                      <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={p.cluster === 'sample' ? 6 : 3.5}
                        fill={palette[p.cluster] || '#888'} opacity={p.cluster === 'sample' ? 1 : 0.5}
                        stroke={p.cluster === 'sample' ? '#f5f5f5' : 'none'} strokeWidth={p.cluster === 'sample' ? 2 : 0} />
                    ))}
                  </svg>
                </div>
              )}
            </div>
          </div>
        </div>
      );
    }

    function NutrigenomicsView() {
      if (!NUTRI_DATA) return <EmptyPanel title="Nutrigenomics" op={PANEL_OPS.nutrigenomics} />;
      const tierColors = { established: '#10b981', probable: '#f59e0b', emerging: '#8b5cf6' };
      return (
        <div className="view-content">
          <div className="view-header">
            <div>
              <h2 className="view-title">Nutrigenomics</h2>
              <p className="view-subtitle">Gene–nutrient and gene–diet single-marker evidence</p>
            </div>
          </div>
          <div className="nutri-grid">
            {NUTRI_DATA.map((d, i) => {
              const tc = tierColors[d.evidenceTier] || '#666';
              return (
                <div key={i} className="nutri-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ color: '#e5e5e5', fontWeight: 600, fontSize: 14 }}>{d.marker}</div>
                      <div style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center' }}>
                        <span className="mono-text" style={{ color: '#3b82f6' }}>{d.gene}</span>
                        <span className="mono-text">{d.rsid}</span>
                        <span className="genotype-badge">{d.status}</span>
                      </div>
                    </div>
                    <span className="badge" style={{ background: tc + '18', color: tc, borderColor: tc + '30' }}>{d.evidenceTier}</span>
                  </div>
                  <div style={{ color: '#999', fontSize: 12, lineHeight: 1.6, marginTop: 10 }}>{d.recommendation}</div>
                </div>
              );
            })}
          </div>
        </div>
      );
    }

    function JournalView() {
      if (!JOURNAL_ENTRIES) return <EmptyPanel title="Journal" op={PANEL_OPS.journal} />;
      const typeIcons = { observation: '◎', hypothesis: '◇', decision: '◆', question: '?' };
      return (
        <div className="view-content">
          <div className="view-header">
            <div>
              <h2 className="view-title">Investigation Journal</h2>
              <p className="view-subtitle">Agent reasoning, decisions, and evidence links</p>
            </div>
          </div>
          <div className="journal-list">
            {JOURNAL_ENTRIES.map((entry, i) => (
              <div key={i} className="journal-entry">
                <div className="journal-timeline">
                  <div className="journal-icon"><span>{typeIcons[entry.kind] || '○'}</span></div>
                  <div className="journal-line" />
                </div>
                <div className="journal-body">
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#e5e5e5', fontWeight: 600, fontSize: 13 }}>{entry.title || entry.kind}</span>
                    <span style={{ color: '#444', fontSize: 11 }}>{entry.ts || ''}</span>
                  </div>
                  <div style={{ color: '#999', fontSize: 12.5, lineHeight: 1.6, marginTop: 6 }}>{entry.body}</div>
                  {Array.isArray(entry.tags) && entry.tags.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
                      {entry.tags.map((tag, j) => <span key={j} className="tag-chip">{tag}</span>)}
                    </div>
                  )}
                  {Array.isArray(entry.evidenceLinks) && entry.evidenceLinks.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      {entry.evidenceLinks.map((link, j) => (
                        <div key={j} className="mono-text" style={{ color: '#444', fontSize: 10 }}>↳ {link}</div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      );
    }

    function Sidebar({ active, onNav }) {
      let lastSection = '';
      return (
        <div className="sidebar">
          <div className="sidebar-logo">
            <img className="sidebar-logo-icon" alt="Genomi" src="__GENOMI_LOGO_DATA_URL__" />
            <span className="sidebar-logo-text">Genomi</span>
            <span className="sidebar-logo-version">v0.4</span>
          </div>
          <nav className="sidebar-nav">
            {AVAILABLE_NAV.map(item => {
              const showSection = item.section !== lastSection;
              lastSection = item.section;
              const actionable = item.id === 'pharmacogenomics' && PGX_DATA
                ? PGX_DATA.filter(d => d.impact && d.impact !== 'normal').length : 0;
              return (
                <React.Fragment key={item.id}>
                  {showSection && <div className="sidebar-section-label">{item.section}</div>}
                  <div className={`nav-item ${active === item.id ? 'active' : ''}`} onClick={() => onNav(item.id)}>
                    <span className="nav-icon">{item.icon}</span>
                    <span>{item.label}</span>
                    {actionable > 0 && <span className="nav-badge">{actionable}</span>}
                  </div>
                </React.Fragment>
              );
            })}
          </nav>
          <div className="sidebar-footer">
            Experimental · Research use only<br />
            Not for clinical diagnosis
            {RENDERED_AT && <span className="timestamp">rendered {RENDERED_AT}</span>}
          </div>
        </div>
      );
    }

    function App() {
      const [view, setView] = React.useState((AVAILABLE_NAV[0] && AVAILABLE_NAV[0].id) || 'overview');
      const [tweaks, setTweaks] = React.useState(TWEAK_DEFAULTS);
      const accent = ACCENT_MAP[tweaks.accentColor] || ACCENT_MAP.green;
      React.useEffect(() => {
        document.documentElement.style.setProperty('--green', accent.primary);
      }, [accent.primary]);
      const viewLabel = NAV_ITEMS.find(n => n.id === view)?.label || 'Overview';
      const renderView = () => {
        switch (view) {
          case 'overview': return <OverviewView onNav={setView} />;
          case 'variants': return <VariantsView />;
          case 'pharmacogenomics': return <PharmacogenomicsView />;
          case 'risk': return <RiskScoresView />;
          case 'ancestry': return <AncestryView />;
          case 'nutrigenomics': return <NutrigenomicsView />;
          case 'journal': return <JournalView />;
          default: return <OverviewView onNav={setView} />;
        }
      };
      const setTweak = (k, v) => setTweaks(prev => ({ ...prev, [k]: v }));
      return (
        <React.Fragment>
          <Sidebar active={view} onNav={setView} />
          <div className="main">
            <div className="topbar">
              <span className="topbar-title">{viewLabel}</span>
              <div className="topbar-right">
                <div className="topbar-status">
                  <span style={{ color: accent.primary }}>●</span>
                  <span>{GENOME_SUMMARY?.sampleId || 'no active sample'}</span>
                  {GENOME_SUMMARY?.genomeBuild && <><span style={{ color: '#333' }}>·</span><span>{GENOME_SUMMARY.genomeBuild}</span></>}
                </div>
              </div>
            </div>
            {renderView()}
          </div>
          <div style={{ position: 'fixed', right: 16, bottom: 16, zIndex: 100 }}>
            <details style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: '6px 10px', color: 'var(--text3)', fontSize: 11 }}>
              <summary style={{ cursor: 'pointer' }}>Genomi Tweaks</summary>
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  Accent
                  <select value={tweaks.accentColor} onChange={e => setTweak('accentColor', e.target.value)}>
                    <option value="green">green</option>
                    <option value="blue">blue</option>
                    <option value="purple">purple</option>
                    <option value="amber">amber</option>
                  </select>
                </label>
                <label style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  Show support
                  <input type="checkbox" checked={!!tweaks.showSupport} onChange={e => setTweak('showSupport', e.target.checked)} />
                </label>
                <label style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  Compact cards
                  <input type="checkbox" checked={!!tweaks.compactCards} onChange={e => setTweak('compactCards', e.target.checked)} />
                </label>
              </div>
            </details>
          </div>
        </React.Fragment>
      );
    }

    ReactDOM.createRoot(document.getElementById('root')).render(<App />);
