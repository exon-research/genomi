"use strict";

import { postJson } from "./api.js";
import { addOptionalText, setFormBusy } from "./form-controls.js";
import {
  elements,
  hideObservationEditor,
  renderObservationEditor,
  setActivity,
  showAlert,
} from "./render.js";

const MOLECULAR_MODALITIES = new Set([
  "reported_germline_finding",
  "reported_somatic_finding",
  "biomarker",
]);
const SOURCE_RECORD_FILE_EXTENSIONS = new Set([
  ".pdf", ".txt", ".rtf", ".doc", ".docx", ".png", ".jpg", ".jpeg",
]);
const SOURCE_RECORD_MIME_TYPES = new Set([
  "application/pdf", "text/plain", "application/rtf", "text/rtf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "image/png", "image/jpeg",
]);
const GENOME_SOURCE_FILE_EXTENSIONS = new Set([
  ".vcf", ".vcf.gz", ".gvcf", ".gvcf.gz", ".bcf", ".bam", ".cram",
  ".fastq", ".fastq.gz", ".fq", ".fq.gz", ".bed", ".ped", ".bgen",
]);

export function createProfileController({state, refresh}) {
  function bind() {
    elements.manageGenomeButton.addEventListener("click", handleManageGenomeHandoff);
    elements.sourceArtifactForm.addEventListener("submit", handleSourceArtifact);
    elements.specimenForm.addEventListener("submit", handleSpecimen);
    elements.assayForm.addEventListener("submit", handleAssay);
    elements.observationForm.addEventListener("submit", handleObservation);
    elements.observationList.addEventListener("click", handleObservationReviewSelection);
    elements.observationEditForm.addEventListener("submit", handleObservationCorrection);
    elements.observationEditCancel.addEventListener("click", closeObservationEditor);
    elements.assaySpecimen.addEventListener("change", synchronizeAssayFormLinks);
    addObservationLinkListeners("observation");
    addObservationLinkListeners("observationEdit");
    elements.observationForm.elements.modality.addEventListener(
      "change", () => updateObservationLinkHelp("observation")
    );
    elements.observationForm.elements.assertion_status.addEventListener(
      "change", () => updateObservationLinkHelp("observation")
    );
    elements.observationEditAssertionStatus.addEventListener(
      "change", () => updateObservationLinkHelp("observationEdit")
    );
  }

  async function handleSourceArtifact(event) {
    event.preventDefault();
    if (!elements.sourceArtifactForm.reportValidity()) return;
    const file = elements.sourceArtifactFile.files && elements.sourceArtifactFile.files[0];
    if (!file) {
      showAlert("Choose the local report you want to fingerprint.");
      return;
    }
    if (!isSupportedSourceRecordFile(file)) {
      showAlert("Choose a PDF, text, Word, or image report. Genome source files stay in Genomi's existing genome setup.");
      return;
    }
    setFormBusy(elements.sourceArtifactForm, elements.sourceArtifactSubmit, true, "Fingerprinting locally…");
    setActivity("Computing a local report fingerprint. The report itself is not being uploaded…");
    try {
      const digest = await localFileSha256(file);
      const form = new FormData(elements.sourceArtifactForm);
      const payload = {
        content_sha256: digest,
        source_type: String(form.get("source_type") || "issued_report"),
        title: String(form.get("title") || "").trim(),
      };
      addOptionalText(payload, "source_identifier", form.get("source_identifier"));
      addOptionalText(payload, "issued_at", form.get("issued_at"));
      await postJson("/api/v1/molecular-profile/source-artifacts", payload);
      elements.sourceArtifactForm.reset();
      showAlert("Source record registered. Only the fingerprint and entered record details were saved.", "success");
      await refresh();
    } catch (error) {
      showAlert(error.message || "The source record could not be registered.");
    } finally {
      setFormBusy(elements.sourceArtifactForm, elements.sourceArtifactSubmit, false);
    }
  }

  async function handleSpecimen(event) {
    event.preventDefault();
    if (!elements.specimenForm.reportValidity()) return;
    const form = new FormData(elements.specimenForm);
    const payload = {
      specimen_type: String(form.get("specimen_type") || ""),
      tumor_normal_role: String(form.get("tumor_normal_role") || "unknown"),
    };
    addOptionalText(payload, "artifact_id", form.get("artifact_id"));
    addOptionalText(payload, "body_site", form.get("body_site"));
    addOptionalText(payload, "collected_at", form.get("collected_at"));
    addOptionalText(payload, "disease_state", form.get("disease_state"));
    setFormBusy(elements.specimenForm, elements.specimenSubmit, true, "Saving…");
    setActivity("Saving the specimen description locally…");
    try {
      await postJson("/api/v1/molecular-profile/specimens", payload);
      elements.specimenForm.reset();
      showAlert("Specimen saved.", "success");
      await refresh();
    } catch (error) {
      showAlert(error.message || "The specimen could not be saved.");
    } finally {
      setFormBusy(elements.specimenForm, elements.specimenSubmit, false);
    }
  }

  async function handleAssay(event) {
    event.preventDefault();
    if (!elements.assayForm.reportValidity()) return;
    try {
      assertEntityLinkCoherence({
        artifactId: elements.assayArtifact.value,
        specimenId: elements.assaySpecimen.value,
        assayId: "",
      });
    } catch (error) {
      showAlert(error.message);
      return;
    }
    const form = new FormData(elements.assayForm);
    const assayScope = String(form.get("assay_scope") || "").trim();
    const detectionLimits = String(form.get("detection_limits") || "").trim();
    if (!assayScope || !detectionLimits) {
      showAlert("Describe both what the test covered and what it could detect.");
      return;
    }
    const payload = {
      assay_type: String(form.get("assay_type") || ""),
      assay_scope: {reported_description: assayScope},
      detection_limits: {reported_description: detectionLimits},
    };
    addOptionalText(payload, "artifact_id", elements.assayArtifact.value);
    addOptionalText(payload, "specimen_id", elements.assaySpecimen.value);
    addOptionalText(payload, "laboratory", form.get("laboratory"));
    addOptionalText(payload, "platform", form.get("platform"));
    addOptionalText(payload, "genome_build", form.get("genome_build"));
    setFormBusy(elements.assayForm, elements.assaySubmit, true, "Saving…");
    setActivity("Saving the assay scope and detection limits locally…");
    try {
      await postJson("/api/v1/molecular-profile/assays", payload);
      elements.assayForm.reset();
      synchronizeAssayFormLinks();
      showAlert("Assay saved. Its declared scope can now support correctly bounded negative findings.", "success");
      await refresh();
    } catch (error) {
      showAlert(error.message || "The assay could not be saved.");
    } finally {
      setFormBusy(elements.assayForm, elements.assaySubmit, false);
      synchronizeAssayFormLinks();
    }
  }

  async function handleObservation(event) {
    event.preventDefault();
    if (!elements.observationForm.reportValidity()) return;
    let payload;
    try {
      const modality = String(new FormData(elements.observationForm).get("modality") || "");
      payload = observationPayload(elements.observationForm, modality, {revision: false});
    } catch (error) {
      showAlert(error.message);
      return;
    }
    setFormBusy(elements.observationForm, elements.observationSubmit, true, "Saving…");
    setActivity("Saving this profile observation locally…");
    try {
      await postJson("/api/v1/molecular-profile/observations", payload);
      elements.observationForm.reset();
      synchronizeObservationLinks("observation", "reset");
      showAlert("Profile observation saved.", "success");
      await refresh();
    } catch (error) {
      showAlert(error.message || "The observation could not be saved.");
    } finally {
      setFormBusy(elements.observationForm, elements.observationSubmit, false);
    }
  }

  function handleObservationReviewSelection(event) {
    const button = event.target.closest("button[data-observation-revision-id]");
    if (!button || !elements.observationList.contains(button)) return;
    const revisionId = String(button.dataset.observationRevisionId || "");
    const observation = profileObservations().find(
      (item) => String(item.observation_revision_id || "") === revisionId
    );
    if (!observation) {
      showAlert("That observation is no longer the current revision. Refresh and try again.");
      return;
    }
    state.editingObservationRevisionId = revisionId;
    renderObservationEditor(observation);
    synchronizeObservationLinks("observationEdit", "assay");
    elements.observationEditor.scrollIntoView({block: "nearest"});
    setActivity("Reviewing an observation. Saving will create a new immutable revision.");
  }

  async function handleObservationCorrection(event) {
    event.preventDefault();
    const revisionId = state.editingObservationRevisionId;
    if (!revisionId || !elements.observationEditForm.reportValidity()) return;
    const observation = profileObservations().find(
      (item) => String(item.observation_revision_id || "") === revisionId
    );
    if (!observation) {
      showAlert("That observation is no longer the current revision. Refresh and review the latest version.");
      return;
    }
    let payload;
    try {
      payload = observationPayload(
        elements.observationEditForm,
        String(observation.modality || ""),
        {revision: true, prior: observation}
      );
    } catch (error) {
      showAlert(error.message);
      return;
    }
    setFormBusy(elements.observationEditForm, elements.observationEditSubmit, true, "Saving revision…");
    setActivity("Saving a corrected immutable observation revision…");
    try {
      await postJson(
        `/api/v1/molecular-profile/observations/${encodeURIComponent(revisionId)}/supersede`,
        payload
      );
      state.editingObservationRevisionId = "";
      hideObservationEditor();
      showAlert("Correction saved. The superseded revision remains visible in version history.", "success");
      await refresh();
    } catch (error) {
      showAlert(error.message || "The corrected revision could not be saved.");
    } finally {
      setFormBusy(elements.observationEditForm, elements.observationEditSubmit, false);
    }
  }

  function closeObservationEditor() {
    state.editingObservationRevisionId = "";
    hideObservationEditor();
    setActivity("Correction cancelled. No profile revision was created.");
  }

  function observationPayload(formElement, modality, {revision, prior = null}) {
    const form = new FormData(formElement);
    const label = String(form.get("label") || "").trim();
    const assertionStatus = String(form.get("assertion_status") || "present");
    const artifactId = String(form.get("artifact_id") || "");
    const specimenId = String(form.get("specimen_id") || "");
    const assayId = String(form.get("assay_id") || "");
    const recordAssertion = form.get("record_assertion") === "on";
    assertEntityLinkCoherence({artifactId, specimenId, assayId});
    if (assertionStatus === "absent" && MOLECULAR_MODALITIES.has(modality) && !assayId) {
      throw new Error("Link the assay that defines what was tested before saving a molecular finding as not detected.");
    }
    if (recordAssertion && !artifactId) {
      throw new Error("Select the issued medical record that states this observation.");
    }
    if (recordAssertion && !isIssuedMedicalRecord(artifactId)) {
      throw new Error("Only an issued report, laboratory report, pathology report, or clinical note can state a record-derived observation.");
    }
    const payload = {
      label,
      assertion_status: assertionStatus,
      source_class: recordAssertion ? "issued_record" : "patient_reported",
      verification_state: "user_confirmed",
    };
    if (!revision) {
      payload.modality = modality;
      payload.original_wording = label;
      payload.coverage_state = assertionStatus === "absent" && MOLECULAR_MODALITIES.has(modality)
        ? "explicitly_not_detected_within_declared_assay_scope"
        : "observed";
    } else if (MOLECULAR_MODALITIES.has(modality) && assertionStatus === "absent") {
      payload.coverage_state = "explicitly_not_detected_within_declared_assay_scope";
    } else if (MOLECULAR_MODALITIES.has(modality) && assertionStatus === "present") {
      payload.coverage_state = "observed";
    } else if (
      MOLECULAR_MODALITIES.has(modality)
      && assertionStatus === "unknown"
      && prior
      && prior.coverage_state === "explicitly_not_detected_within_declared_assay_scope"
    ) {
      payload.coverage_state = "not_provided";
    }
    if (revision) {
      payload.artifact_id = artifactId;
      payload.specimen_id = specimenId;
      payload.assay_id = assayId;
      payload.reported_variant = String(form.get("reported_variant") || "").trim();
      payload.gene = String(form.get("gene") || "").trim();
    } else {
      addOptionalText(payload, "artifact_id", artifactId);
      addOptionalText(payload, "specimen_id", specimenId);
      addOptionalText(payload, "assay_id", assayId);
      addOptionalText(payload, "reported_variant", form.get("reported_variant"));
      addOptionalText(payload, "gene", form.get("gene"));
    }
    return payload;
  }

  function isIssuedMedicalRecord(artifactId) {
    const artifact = profileSourceArtifacts().find(
      (item) => String(item.artifact_id || "") === artifactId
    );
    return Boolean(artifact && new Set([
      "issued_report", "laboratory_report", "pathology_report", "clinical_note",
    ]).has(String(artifact.source_type || "")));
  }

  function addObservationLinkListeners(prefix) {
    const artifact = elements[`${prefix}Artifact`];
    const specimen = elements[`${prefix}Specimen`];
    const assay = elements[`${prefix}Assay`];
    artifact.addEventListener("change", () => synchronizeObservationLinks(prefix, "artifact"));
    specimen.addEventListener("change", () => synchronizeObservationLinks(prefix, "specimen"));
    assay.addEventListener("change", () => synchronizeObservationLinks(prefix, "assay"));
    elements[`${prefix}RecordAssertion`].addEventListener(
      "change", () => updateObservationLinkHelp(prefix)
    );
  }

  function synchronizeObservationLinks(prefix, changed) {
    const artifactSelect = elements[`${prefix}Artifact`];
    const specimenSelect = elements[`${prefix}Specimen`];
    const assaySelect = elements[`${prefix}Assay`];
    if (changed === "reset") {
      artifactSelect.value = "";
      specimenSelect.value = "";
      assaySelect.value = "";
      updateObservationLinkHelp(prefix);
      return;
    }
    if (changed === "assay" && assaySelect.value) {
      const assay = profileAssays().find((item) => String(item.assay_id || "") === assaySelect.value);
      if (assay) {
        const specimen = profileSpecimens().find(
          (item) => String(item.specimen_id || "") === String(assay.specimen_id || "")
        );
        if (assay.specimen_id) specimenSelect.value = String(assay.specimen_id);
        const artifactId = String(assay.artifact_id || specimen && specimen.artifact_id || "");
        if (artifactId) artifactSelect.value = artifactId;
      }
    }
    if (changed === "specimen") {
      const specimen = profileSpecimens().find((item) => String(item.specimen_id || "") === specimenSelect.value);
      if (specimen && specimen.artifact_id) artifactSelect.value = String(specimen.artifact_id);
      const assay = profileAssays().find((item) => String(item.assay_id || "") === assaySelect.value);
      if (assay && String(assay.specimen_id || "") !== specimenSelect.value) assaySelect.value = "";
    }
    if (changed === "artifact") {
      const specimen = profileSpecimens().find((item) => String(item.specimen_id || "") === specimenSelect.value);
      if (specimen && specimen.artifact_id && String(specimen.artifact_id) !== artifactSelect.value) {
        specimenSelect.value = "";
        assaySelect.value = "";
      } else {
        const assay = profileAssays().find((item) => String(item.assay_id || "") === assaySelect.value);
        if (assay && assay.artifact_id && String(assay.artifact_id) !== artifactSelect.value) assaySelect.value = "";
      }
    }
    updateObservationLinkHelp(prefix);
  }

  function synchronizeAssayFormLinks() {
    const specimen = profileSpecimens().find(
      (item) => String(item.specimen_id || "") === elements.assaySpecimen.value
    );
    const linkedArtifactId = String(specimen && specimen.artifact_id || "");
    if (linkedArtifactId) elements.assayArtifact.value = linkedArtifactId;
    elements.assayArtifact.disabled = Boolean(linkedArtifactId);
    elements.assayLinkHelp.textContent = linkedArtifactId
      ? "The specimen's source record is locked here so the assay links remain coherent."
      : "When a specimen has a source record, that record is selected automatically.";
  }

  function updateObservationLinkHelp(prefix) {
    const isEditor = prefix === "observationEdit";
    const artifact = elements[`${prefix}Artifact`];
    const assay = elements[`${prefix}Assay`];
    const recordAssertion = elements[`${prefix}RecordAssertion`].checked;
    const help = isEditor ? elements.observationEditLinkHelp : elements.observationSourceNote;
    const assertionStatus = isEditor
      ? elements.observationEditAssertionStatus.value
      : String(elements.observationForm.elements.assertion_status.value || "present");
    const modality = isEditor
      ? String(profileObservations().find(
        (item) => String(item.observation_revision_id || "") === state.editingObservationRevisionId
      )?.modality || "")
      : String(elements.observationForm.elements.modality.value || "");
    if (assertionStatus === "absent" && MOLECULAR_MODALITIES.has(modality) && !assay.value) {
      help.textContent = "A molecular not-detected result requires the assay that defines its tested scope and detection limits.";
    } else if (artifact.value && recordAssertion) {
      help.textContent = "This observation will be saved as stated by the selected issued medical record.";
    } else if (artifact.value) {
      help.textContent = "The selected record supports this patient-reported observation; a link alone does not make it record-stated.";
    } else {
      help.textContent = "This is saved as patient-reported context.";
    }
  }

  function assertEntityLinkCoherence({artifactId, specimenId, assayId}) {
    const specimen = profileSpecimens().find((item) => String(item.specimen_id || "") === specimenId);
    if (specimen && specimen.artifact_id && String(specimen.artifact_id) !== artifactId) {
      throw new Error("The selected specimen must stay linked to its own source record.");
    }
    const assay = profileAssays().find((item) => String(item.assay_id || "") === assayId);
    if (!assay) return;
    if (assay.specimen_id && String(assay.specimen_id) !== specimenId) {
      throw new Error("The selected assay must stay linked to its own specimen.");
    }
    const expectedArtifactId = String(assay.artifact_id || specimen && specimen.artifact_id || "");
    if (expectedArtifactId && expectedArtifactId !== artifactId) {
      throw new Error("The selected assay must stay linked to its own source record.");
    }
  }

  async function localFileSha256(file) {
    if (!globalThis.crypto || !globalThis.crypto.subtle) {
      throw new Error("This browser cannot compute the required local SHA-256 fingerprint.");
    }
    const fileBytes = await file.arrayBuffer();
    const digestBytes = await globalThis.crypto.subtle.digest("SHA-256", fileBytes);
    return [...new Uint8Array(digestBytes)]
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
  }

  function isSupportedSourceRecordFile(file) {
    const fileName = String(file && file.name || "").toLowerCase();
    if ([...GENOME_SOURCE_FILE_EXTENSIONS].some((candidate) => fileName.endsWith(candidate))) return false;
    const extension = [...SOURCE_RECORD_FILE_EXTENSIONS].find((candidate) => fileName.endsWith(candidate));
    const mimeType = String(file && file.type || "").toLowerCase();
    return Boolean(extension && (!mimeType || SOURCE_RECORD_MIME_TYPES.has(mimeType)));
  }

  function handleManageGenomeHandoff() {
    showAlert(
      "Genomi owns genome setup and updates. In your installed assistant, ask: “Manage the current Genomi user’s genome.” Return here afterward and use Compare latest profile in any affected investigation.",
      "success"
    );
    setActivity("Genome management stays in Genomi; GenomiLab will reuse its updated Active Genome Index.");
  }

  function profileObservations() {
    return state.profileRecords("observations");
  }

  function profileSourceArtifacts() {
    return state.profileRecords("source_artifacts");
  }

  function profileSpecimens() {
    return state.profileRecords("specimens");
  }

  function profileAssays() {
    return state.profileRecords("assays");
  }

  function synchronizeFormState() {
    synchronizeAssayFormLinks();
    updateObservationLinkHelp("observation");
    if (state.editingObservationRevisionId) updateObservationLinkHelp("observationEdit");
  }

  return Object.freeze({bind, synchronizeFormState});
}
