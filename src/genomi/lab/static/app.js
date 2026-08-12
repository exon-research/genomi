"use strict";

import {
  PortalError,
  apiRequest,
  postJson,
  profilePath,
  setCsrfToken,
} from "./api.js";
import {
  collectElements,
  elements,
  formatBytes,
  formatDate,
  hideAlert,
  isObject,
  numberValue,
  profileIdInList,
  renderBrief,
  renderFindings,
  renderHealthFacts,
  renderInvestigations,
  renderProductMetadata,
  renderProfileOptions,
  renderReadiness,
  resetFilePicker,
  setActivity,
  setLocalStatus,
  showAlert,
  showError,
  showUploadProgress,
  stringValue,
} from "./render.js";

const state = {
  csrfToken: "",
  bootstrap: null,
  profile: null,
  activeProfileId: "",
  uploadSequence: 0,
  uploading: false,
  switchingProfile: false,
  profileLoadSequence: 0,
  loadingProfile: false,
  busyButtons: new Set(),
};

document.addEventListener("DOMContentLoaded", () => {
  void initializePortal();
});

async function initializePortal() {
  collectElements();
  bindEvents();
  setActivity("Opening the local workspace…");
  try {
    await loadBootstrap();
    setLocalStatus("Local workspace ready", "ready");
    setActivity("Ready.");
  } catch (error) {
    setLocalStatus("Local workspace unavailable", "error");
    showError(error, "GenomiLab could not open");
    setActivity("The local workspace could not be opened.");
  }
}

function bindEvents() {
  elements.alertDismiss.addEventListener("click", hideAlert);
  elements.emptyCreateButton.addEventListener("click", () => {
    elements.createProfilePanel.open = true;
    elements.profileName.focus();
  });
  elements.profileSelect.addEventListener("change", () => {
    void handleProfileSelection();
  });
  elements.createProfileForm.addEventListener("submit", (event) => {
    void handleCreateProfile(event);
  });
  elements.healthFactForm.addEventListener("submit", (event) => {
    void handleHealthFact(event);
  });
  elements.genomeFile.addEventListener("change", handleFileSelection);
  elements.genomeUploadForm.addEventListener("submit", (event) => {
    void handleGenomeUpload(event);
  });
  elements.findingForm.addEventListener("submit", (event) => {
    void handleReportedFinding(event);
  });
  elements.copyQuestionButton.addEventListener("click", copyQuestionToPurpose);
  elements.consentForm.addEventListener("submit", (event) => {
    void handleConsent(event);
  });
  elements.investigationQuestion.addEventListener("input", updateControlStates);
  elements.investigationForm.addEventListener("submit", (event) => {
    void handleInvestigation(event);
  });
}

async function loadBootstrap(preferredProfileId = "") {
  const loadSequence = ++state.profileLoadSequence;
  state.loadingProfile = true;
  updateControlStates();
  try {
    const payload = await apiRequest("/api/v1/bootstrap");
    if (loadSequence !== state.profileLoadSequence) {
      return;
    }
    state.bootstrap = payload;
    state.csrfToken = stringValue(payload.csrf_token);
    if (!state.csrfToken) {
      throw new PortalError("The local security session is incomplete. Refresh the launch page.");
    }
    setCsrfToken(state.csrfToken);

    renderProductMetadata(payload);
    const profiles = Array.isArray(payload.profiles) ? payload.profiles : [];
    renderProfileOptions(profiles, state.activeProfileId, true);

    const candidate =
      profileIdInList(preferredProfileId, profiles) ||
      profileIdInList(payload.active_profile_id, profiles) ||
      (profiles[0] ? stringValue(profiles[0].profile_id) : "");

    if (!candidate) {
      showEmptyWorkspace();
      return;
    }

    elements.profileSelect.value = candidate;
    const loadedProfile = !payload.active_profile_id
      ? await postJson(profilePath(candidate, "activate"), {})
      : await apiRequest(profilePath(candidate));
    if (loadSequence !== state.profileLoadSequence) {
      return;
    }
    state.activeProfileId = candidate;
    state.profile = loadedProfile;
    renderProfile();
  } finally {
    if (loadSequence === state.profileLoadSequence) {
      state.loadingProfile = false;
      updateControlStates();
    }
  }
}

async function handleProfileSelection() {
  const profileId = elements.profileSelect.value;
  if (
    !profileId ||
    profileId === state.activeProfileId ||
    state.uploading ||
    state.switchingProfile ||
    state.loadingProfile ||
    state.busyButtons.size > 0
  ) {
    return;
  }

  const previous = state.activeProfileId;
  state.profileLoadSequence += 1;
  state.uploadSequence += 1;
  state.switchingProfile = true;
  setActivity("Switching profiles and revoking prior session access…");
  updateControlStates();
  try {
    resetTransientInputs();
    state.profile = await postJson(profilePath(profileId, "activate"), {});
    state.activeProfileId = profileId;
    renderProfile();
    showAlert("Profile selected. Any earlier genome access approval was revoked.", "success");
    elements.workspaceTitle.focus({ preventScroll: true });
  } catch (error) {
    elements.profileSelect.value = previous;
    showError(error, "The profile could not be selected");
  } finally {
    state.switchingProfile = false;
    updateControlStates();
    setActivity("Ready.");
  }
}

async function handleCreateProfile(event) {
  event.preventDefault();
  if (
    state.uploading ||
    state.switchingProfile ||
    state.loadingProfile ||
    state.busyButtons.size > 0
  ) {
    showAlert("Finish the current workspace action before creating another workspace.", "error");
    return;
  }
  if (!elements.createProfileForm.reportValidity()) {
    return;
  }

  const displayName = elements.profileName.value.trim();
  setButtonBusy(elements.createProfileButton, true, "Creating…");
  setActivity("Creating a private local workspace…");
  try {
    const created = await postJson("/api/v1/profiles", { display_name: displayName });
    const profileId = stringValue(created.profile_id);
    if (!profileId) {
      throw new PortalError("The new profile did not return a usable identifier.");
    }
    resetTransientInputs();
    const activatedProfile = await postJson(profilePath(profileId, "activate"), {});
    state.activeProfileId = profileId;
    state.profile = activatedProfile;
    elements.createProfileForm.reset();
    elements.createProfilePanel.open = false;
    let profileListRefreshFailed = false;
    try {
      await loadBootstrap(profileId);
    } catch {
      profileListRefreshFailed = true;
      const knownProfiles =
        isObject(state.bootstrap) && Array.isArray(state.bootstrap.profiles)
          ? state.bootstrap.profiles
          : [];
      const fallbackProfiles = [
        ...knownProfiles.filter((profile) => stringValue(profile.profile_id) !== profileId),
        created,
      ];
      state.bootstrap = {
        ...(isObject(state.bootstrap) ? state.bootstrap : {}),
        active_profile_id: profileId,
        profiles: fallbackProfiles,
      };
      state.activeProfileId = profileId;
      state.profile = activatedProfile;
      renderProfileOptions(fallbackProfiles, profileId, true);
      renderProfile();
    }
    showAlert(
      profileListRefreshFailed
        ? "Workspace created and active. The workspace list could not refresh; reload the portal if needed."
        : "Workspace created. Start with the question you want to investigate.",
      profileListRefreshFailed ? "error" : "success"
    );
    elements.investigationQuestion.focus();
  } catch (error) {
    showError(error, "The workspace could not be created");
  } finally {
    setButtonBusy(elements.createProfileButton, false);
    updateControlStates();
    setActivity("Ready.");
  }
}

async function handleHealthFact(event) {
  event.preventDefault();
  if (!requireActiveProfile() || !elements.healthFactForm.reportValidity()) {
    return;
  }

  const form = new FormData(elements.healthFactForm);
  const payload = {
    kind: stringValue(form.get("kind")),
    label: stringValue(form.get("label")).trim(),
    assertion_status: stringValue(form.get("assertion_status")),
  };
  const onset = stringValue(form.get("onset")).trim();
  if (onset) {
    payload.onset = onset;
  }

  setButtonBusy(elements.healthFactButton, true, "Saving…");
  setActivity("Saving health context locally…");
  try {
    await postJson(profilePath(state.activeProfileId, "health-facts"), payload);
    elements.healthFactForm.reset();
    await refreshActiveProfile();
    showAlert("Health context added to this local profile.", "success");
  } catch (error) {
    showError(error, "The health fact could not be saved");
  } finally {
    setButtonBusy(elements.healthFactButton, false);
    setActivity("Ready.");
  }
}

function handleFileSelection() {
  const file = elements.genomeFile.files && elements.genomeFile.files[0];
  if (!file) {
    resetFilePicker();
    return;
  }

  const validation = validateGenomeFile(file);
  if (validation) {
    elements.genomeFile.setCustomValidity(validation);
    elements.filePickerTitle.textContent = "Choose a different file";
    elements.filePickerHelp.textContent = validation;
    return;
  }

  elements.genomeFile.setCustomValidity("");
  elements.filePickerTitle.textContent = file.name;
  elements.filePickerHelp.textContent = `${formatBytes(file.size)} · ready to import locally`;
}

async function handleGenomeUpload(event) {
  event.preventDefault();
  if (!requireActiveProfile()) {
    return;
  }

  const file = elements.genomeFile.files && elements.genomeFile.files[0];
  if (!file) {
    elements.genomeFile.setCustomValidity("Choose a VCF or gVCF file.");
    elements.genomeUploadForm.reportValidity();
    return;
  }
  const validation = validateGenomeFile(file);
  elements.genomeFile.setCustomValidity(validation);
  if (validation || !elements.genomeUploadForm.reportValidity()) {
    return;
  }

  state.uploading = true;
  state.uploadSequence += 1;
  const uploadSequence = state.uploadSequence;
  updateControlStates();
  setButtonBusy(elements.uploadButton, true, "Importing…");
  showUploadProgress("Uploading the file to the local GenomiLab process…", false);
  setActivity("Importing the genome locally. This may take a few minutes…");

  try {
    let job = await apiRequest(profilePath(state.activeProfileId, "genomes"), {
      method: "POST",
      body: file,
      headers: {
        "Content-Type": "application/vnd.genomilab.vcf",
        "X-GenomiLab-Filename": uploadHeaderFilename(file.name),
      },
    });
    job = await pollGenomeJob(job, uploadSequence, state.activeProfileId);
    if (!job) {
      return;
    }
    if (stringValue(job.status) !== "completed") {
      const code = stringValue(job.error_code);
      throw new PortalError(
        code ? `The genome import did not complete (${formatIdentifier(code)}).` : "The genome import did not complete.",
        code || "genome_import_failed"
      );
    }

    showUploadProgress("Genome import complete. The local index is ready.", true);
    elements.genomeUploadForm.reset();
    resetFilePicker();
    await refreshActiveProfile();
    showAlert("Genome imported and linked to this profile. Access still requires your approval.", "success");
  } catch (error) {
    showUploadProgress("Genome import stopped. Review the message above and try again.", false);
    showError(error, "The genome could not be imported");
  } finally {
    if (uploadSequence === state.uploadSequence) {
      state.uploading = false;
    }
    setButtonBusy(elements.uploadButton, false);
    updateControlStates();
    setActivity("Ready.");
  }
}

async function pollGenomeJob(initialJob, uploadSequence, profileId) {
  let job = isObject(initialJob) ? initialJob : {};
  while (uploadSequence === state.uploadSequence && profileId === state.activeProfileId) {
    const status = stringValue(job.status);
    if (status === "completed" || status === "failed") {
      return job;
    }
    const jobId = stringValue(job.portal_job_id);
    if (!jobId) {
      throw new PortalError("The local import did not return a job identifier.");
    }
    showUploadProgress("Building a private, queryable genome index on this device…", false);
    await delay(1400);
    if (uploadSequence !== state.uploadSequence || profileId !== state.activeProfileId) {
      return null;
    }
    job = await apiRequest(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
  }
  return null;
}

async function handleReportedFinding(event) {
  event.preventDefault();
  if (!requireActiveProfile() || !elements.findingForm.reportValidity()) {
    return;
  }

  const form = new FormData(elements.findingForm);
  const variant = stringValue(form.get("variant")).trim().toLowerCase();
  if (!/^rs[0-9]+$/.test(variant)) {
    const input = document.getElementById("finding-rsid");
    input.setCustomValidity("Enter an rsID beginning with rs followed by numbers.");
    input.reportValidity();
    return;
  }

  const payload = { variant };
  ["gene", "reported_classification", "source_label"].forEach((key) => {
    const value = stringValue(form.get(key)).trim();
    if (value) {
      payload[key] = value;
    }
  });

  setButtonBusy(elements.findingButton, true, "Saving…");
  setActivity("Saving the reported finding locally…");
  try {
    const finding = await postJson(profilePath(state.activeProfileId, "reported-findings"), payload);
    elements.findingForm.reset();
    document.getElementById("finding-rsid").setCustomValidity("");
    await refreshActiveProfile(stringValue(finding.finding_id));
    showAlert("Reported finding saved. Its reported classification has not been independently validated.", "success");
  } catch (error) {
    showError(error, "The reported finding could not be saved");
  } finally {
    setButtonBusy(elements.findingButton, false);
    setActivity("Ready.");
  }
}

function copyQuestionToPurpose() {
  const question = elements.investigationQuestion.value.trim();
  if (!question) {
    elements.investigationQuestion.focus();
    showAlert("Enter your investigation question first, then copy it as the access purpose.", "error");
    return;
  }
  elements.consentPurpose.value = question;
  elements.consentPurpose.focus();
  setActivity("Question copied into the access purpose.");
}

async function handleConsent(event) {
  event.preventDefault();
  if (!requireActiveProfile() || !elements.consentForm.reportValidity()) {
    return;
  }

  const profile = state.profile || {};
  if (!isObject(profile.genome)) {
    showAlert("Import a genome before approving access.", "error");
    elements.genomeStep.open = true;
    return;
  }

  setButtonBusy(elements.consentButton, true, "Approving…");
  setActivity("Recording session-only genome access approval…");
  try {
    await postJson(profilePath(state.activeProfileId, "consents/agi"), {
      approved: true,
      purpose: elements.consentPurpose.value.trim(),
    });
    elements.consentApproved.checked = false;
    await refreshActiveProfile();
    showAlert("Genome access approved for this local portal session.", "success");
  } catch (error) {
    showError(error, "Genome access could not be approved");
  } finally {
    setButtonBusy(elements.consentButton, false);
    setActivity("Ready.");
  }
}

async function handleInvestigation(event) {
  event.preventDefault();
  if (!requireActiveProfile() || !elements.investigationForm.reportValidity()) {
    return;
  }

  const question = elements.investigationQuestion.value.trim();
  const findingId = elements.investigationFinding.value;
  const profile = state.profile || {};
  if (!isObject(profile.genome) || !isObject(profile.genome_access) || !profile.genome_access.approved) {
    showAlert("Import a genome and approve session access before running the investigation.", "error");
    elements.investigateStep.open = true;
    return;
  }

  setButtonBusy(elements.investigationButton, true, "Investigating…");
  setActivity("Checking the reported finding against the approved local genome context…");
  hideAlert();
  try {
    const investigation = await postJson(profilePath(state.activeProfileId, "investigations"), {
      question,
      finding_id: findingId,
    });
    if (!isObject(investigation.brief)) {
      throw new PortalError("The investigation completed without a readable brief.");
    }
    renderBrief(investigation.brief);
    await refreshActiveProfile(findingId, false);
    elements.briefSection.hidden = false;
    elements.briefSection.focus();
    showAlert("Investigation complete. Review the result, limits, and confirmation steps together.", "success");
  } catch (error) {
    showError(error, "The investigation could not be completed");
  } finally {
    setButtonBusy(elements.investigationButton, false);
    updateControlStates();
    setActivity("Ready.");
  }
}

async function refreshActiveProfile(preferredFindingId = "", renderLatestBrief = true) {
  const profileId = state.activeProfileId;
  if (!profileId) {
    return;
  }
  const profile = await apiRequest(profilePath(profileId));
  if (profileId !== state.activeProfileId) {
    return;
  }
  state.profile = profile;
  renderProfile(preferredFindingId, renderLatestBrief);
}

function renderProfile(preferredFindingId = "", renderLatestBrief = true) {
  const profile = state.profile;
  if (!isObject(profile)) {
    showEmptyWorkspace();
    return;
  }

  elements.noProfileState.hidden = true;
  elements.profileWorkspace.hidden = false;
  elements.workspaceTitle.textContent = stringValue(profile.display_name) || "Patient workspace";
  elements.profileMeta.textContent = `Local profile · Updated ${formatDate(profile.updated_at)}`;
  elements.profileSelect.value = state.activeProfileId;

  const facts = Array.isArray(profile.health_facts) ? profile.health_facts : [];
  const findings = Array.isArray(profile.reported_findings) ? profile.reported_findings : [];
  const investigations = Array.isArray(profile.investigations) ? profile.investigations : [];
  const genomeReady = isObject(profile.genome) && Boolean(profile.genome.agi_id);
  const accessApproved = isObject(profile.genome_access) && profile.genome_access.approved === true;

  renderReadiness(
    profile,
    facts,
    findings,
    investigations,
    genomeReady,
    accessApproved,
    state.uploading
  );
  renderHealthFacts(facts);
  renderFindings(findings, preferredFindingId);
  renderInvestigations(investigations);

  if (renderLatestBrief) {
    const latest = investigations.find((item) => isObject(item) && isObject(item.brief));
    if (latest && latest.brief.status === "research_observation") {
      renderBrief(latest.brief);
    } else {
      elements.briefSection.hidden = true;
    }
  }
  updateControlStates();
}


function updateControlStates() {
  if (!elements.profileSelect) {
    return;
  }
  const profile = isObject(state.profile) ? state.profile : {};
  const genomeReady = isObject(profile.genome) && Boolean(profile.genome.agi_id);
  const accessApproved = isObject(profile.genome_access) && profile.genome_access.approved === true;
  const findings = Array.isArray(profile.reported_findings) ? profile.reported_findings : [];
  const hasQuestion = elements.investigationQuestion.value.trim().length > 0;
  const hasProfile = Boolean(state.activeProfileId);
  const interactionLocked =
    state.uploading ||
    state.switchingProfile ||
    state.loadingProfile ||
    state.busyButtons.size > 0;

  elements.profileSelect.disabled = !hasProfile || interactionLocked;
  setFormDisabled(elements.createProfileForm, interactionLocked);
  setFormDisabled(elements.healthFactForm, !hasProfile || interactionLocked);
  setFormDisabled(elements.findingForm, !hasProfile || interactionLocked);
  elements.genomeFile.disabled = !hasProfile || interactionLocked;
  elements.uploadButton.disabled = !hasProfile || interactionLocked;

  const consentLocked =
    interactionLocked || !genomeReady || accessApproved;
  elements.consentPurpose.disabled = consentLocked;
  elements.consentApproved.disabled = consentLocked;
  elements.copyQuestionButton.disabled = interactionLocked || !genomeReady || accessApproved;
  elements.consentButton.disabled = consentLocked;

  elements.investigationQuestion.disabled = interactionLocked;
  elements.investigationFinding.disabled = interactionLocked || findings.length === 0;
  const canRun =
    !interactionLocked && genomeReady && accessApproved && findings.length > 0 && hasQuestion;
  elements.investigationButton.disabled = !canRun;

  if (state.uploading) {
    elements.runReadinessTitle.textContent = "Genome import in progress";
    elements.runReadinessDetail.textContent = "Wait for the local index to finish before approving access or investigating.";
  } else if (!genomeReady) {
    elements.runReadinessTitle.textContent = "Import a genome to continue";
    elements.runReadinessDetail.textContent = "Use an uncompressed VCF or gVCF in this developer preview.";
  } else if (!findings.length) {
    elements.runReadinessTitle.textContent = "Add a reported rsID";
    elements.runReadinessDetail.textContent = "The investigation checks one existing reported finding.";
  } else if (!accessApproved) {
    elements.runReadinessTitle.textContent = "Approve session access";
    elements.runReadinessDetail.textContent = "Review and approve the local genome use above.";
  } else if (!hasQuestion) {
    elements.runReadinessTitle.textContent = "Enter your question";
    elements.runReadinessDetail.textContent = "Describe what you want to understand before running the check.";
  } else {
    elements.runReadinessTitle.textContent = "Ready to investigate";
    elements.runReadinessDetail.textContent = "The check will use the selected finding and approved local genome context.";
  }
}

function setFormDisabled(form, disabled) {
  Array.from(form.elements).forEach((control) => {
    if (control instanceof HTMLButtonElement && isButtonBusy(control)) {
      control.disabled = true;
    } else {
      control.disabled = disabled;
    }
  });
}

function showEmptyWorkspace() {
  state.profile = null;
  state.activeProfileId = "";
  elements.noProfileState.hidden = false;
  elements.profileWorkspace.hidden = true;
  elements.profileSelect.disabled = true;
  elements.briefSection.hidden = true;
}

function resetTransientInputs() {
  elements.healthFactForm.reset();
  elements.findingForm.reset();
  elements.genomeUploadForm.reset();
  elements.consentForm.reset();
  elements.investigationForm.reset();
  resetFilePicker();
  elements.uploadProgressWrap.hidden = true;
  elements.briefSection.hidden = true;
}


function validateGenomeFile(file) {
  const name = stringValue(file.name).toLowerCase();
  if (!name.endsWith(".vcf") && !name.endsWith(".gvcf")) {
    return "Choose an uncompressed .vcf, .g.vcf, or .gvcf file.";
  }
  if (file.size <= 0) {
    return "Choose a non-empty VCF or gVCF file.";
  }
  const intake = isObject(state.bootstrap) && isObject(state.bootstrap.intake) ? state.bootstrap.intake : {};
  const maximum = numberValue(intake.maximum_bytes);
  if (maximum > 0 && file.size > maximum) {
    return `This file is larger than the ${formatBytes(maximum)} preview limit.`;
  }
  return "";
}

function uploadHeaderFilename(filename) {
  const name = stringValue(filename);
  if (/^[\x20-\x7e]+$/.test(name) && !name.includes("/") && !name.includes("\\")) {
    return name;
  }
  const lower = name.toLowerCase();
  if (lower.endsWith(".g.vcf")) {
    return "genome.g.vcf";
  }
  if (lower.endsWith(".gvcf")) {
    return "genome.gvcf";
  }
  return "genome.vcf";
}


function requireActiveProfile() {
  if (state.activeProfileId) {
    return true;
  }
  showAlert("Create or choose a profile before adding information.", "error");
  elements.profileName.focus();
  return false;
}

function setButtonBusy(button, busy, busyLabel = "Working…") {
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  if (busy) {
    if (!button.dataset.defaultLabel) {
      button.dataset.defaultLabel = button.textContent;
    }
    state.busyButtons.add(button);
    button.textContent = busyLabel;
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
  } else {
    state.busyButtons.delete(button);
    button.textContent = button.dataset.defaultLabel || button.textContent;
    button.removeAttribute("aria-busy");
  }
  updateControlStates();
}

function isButtonBusy(button) {
  return state.busyButtons.has(button);
}


function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
