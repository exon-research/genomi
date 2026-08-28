// AUTO-GENERATED chunk 3/3 from dashboard sources by scripts/build_dashboard.py - do not edit by hand.
// source-sha256: 9955a36712623e40ca394d947be0806f7bee5504c8a62c3d7201ac325a6e5857
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