// AUTO-GENERATED chunk 3/3 from dashboard sources by scripts/build_dashboard.py - do not edit by hand.
// source-sha256: 4ea0a1b359efa3c0c9deb5689df547ff947205d39259c0feaf0f1176e29dc038
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