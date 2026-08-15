"use strict";

import { setBusy } from "./render.js";

const busyFormControlStates = new WeakMap();

export function setFormBusy(form, submitButton, busy, label = "") {
  if (busy) {
    if (busyFormControlStates.has(form)) return;
    const controls = [...form.elements].filter((control) => control !== submitButton);
    busyFormControlStates.set(
      form,
      controls.map((control) => [control, Boolean(control.disabled)])
    );
    form.setAttribute("aria-busy", "true");
    setBusy(submitButton, true, label);
    controls.forEach((control) => {
      control.disabled = true;
    });
    return;
  }
  const states = busyFormControlStates.get(form) || [];
  states.forEach(([control, wasDisabled]) => {
    control.disabled = wasDisabled;
  });
  busyFormControlStates.delete(form);
  form.removeAttribute("aria-busy");
  setBusy(submitButton, false, "");
}

export function addOptionalText(target, key, value) {
  const candidate = String(value || "").trim();
  if (candidate) target[key] = candidate;
}
