// AUTO-GENERATED chunk 3/3 from dashboard sources by scripts/build_dashboard.py - do not edit by hand.
// source-sha256: 6b67c316a73ac2de502e8c7ea6094d3a343890b34b3b786fc33461b695712cc5
}) {
  return /*#__PURE__*/React.createElement("nav", {
    className: "mobile-nav",
    "aria-label": "Dashboard pages"
  }, AVAILABLE_NAV.map(item => /*#__PURE__*/React.createElement("button", {
    key: item.id,
    className: `mobile-nav-item ${active === item.id ? 'active' : ''}`,
    onClick: () => onNav(item.id)
  }, item.label)));
}
function App() {
  const [view, setView] = React.useState(AVAILABLE_NAV[0] && AVAILABLE_NAV[0].id || 'overview');
  const [tweaks, setTweaks] = React.useState(TWEAK_DEFAULTS);
  const mainRef = React.useRef(null);
  const accent = ACCENT_MAP[tweaks.accentColor] || ACCENT_MAP.green;
  React.useEffect(() => {
    document.documentElement.style.setProperty('--green', accent.primary);
  }, [accent.primary]);
  const navigate = nextView => {
    setView(nextView);
    window.requestAnimationFrame(() => {
      if (mainRef.current) mainRef.current.scrollTo({
        top: 0,
        behavior: 'auto'
      });
    });
  };
  const viewLabel = NAV_ITEMS.find(n => n.id === view)?.label || 'Overview';
  const renderView = () => {
    switch (view) {
      case 'overview':
        return /*#__PURE__*/React.createElement(OverviewView, {
          onNav: navigate
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
          onNav: navigate
        });
    }
  };
  const setTweak = (k, v) => setTweaks(prev => ({
    ...prev,
    [k]: v
  }));
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Sidebar, {
    active: view,
    onNav: navigate
  }), /*#__PURE__*/React.createElement("div", {
    className: "main",
    ref: mainRef
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
  }, "\u25CF"), /*#__PURE__*/React.createElement("span", {
    className: "sample-id"
  }, GENOME_SUMMARY?.sampleId || 'Select an active genome'), GENOME_SUMMARY?.genomeBuild && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#333'
    }
  }, "\xB7"), /*#__PURE__*/React.createElement("span", null, GENOME_SUMMARY.genomeBuild))))), /*#__PURE__*/React.createElement(MobileNav, {
    active: view,
    onNav: navigate
  }), renderView()), /*#__PURE__*/React.createElement("div", {
    className: "tweaks-panel",
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