"use strict";

/**
 * Browser state that belongs to the Research Desk as a whole.
 * Investigation request ownership lives in InvestigationSession below.
 */
export class PortalState {
  constructor() {
    this.bootstrap = null;
    this.editingObservationRevisionId = "";
    this._workspaceToken = Symbol("workspace-request");
  }

  beginWorkspaceRequest() {
    this._workspaceToken = Symbol("workspace-request");
    return this._workspaceToken;
  }

  isCurrentWorkspaceRequest(request) {
    return request === this._workspaceToken;
  }

  acceptBootstrap(request, payload) {
    if (!this.isCurrentWorkspaceRequest(request)) return false;
    this.bootstrap = payload;
    return true;
  }

  acceptWorkspace(request, payload) {
    if (!this.isCurrentWorkspaceRequest(request)) return false;
    this.bootstrap = {...(this.bootstrap || {}), ...payload};
    return true;
  }

  workspace() {
    return this.bootstrap && this.bootstrap.workspace || null;
  }

  profile() {
    const workspace = this.workspace();
    return workspace && workspace.profile || {};
  }

  profileRecords(name) {
    const records = this.profile()[name];
    return Array.isArray(records) ? records : [];
  }

  harnessManifest() {
    const capabilities = this.bootstrap && this.bootstrap.capabilities;
    const manifest = capabilities && capabilities.installed_harness;
    return manifest && typeof manifest === "object" ? manifest : {};
  }
}

/**
 * Owns the complete lifecycle of one selected investigation.
 * Tokens are opaque identities, so an old async response cannot become current
 * again through counter reuse or through an unrelated state update.
 */
export class InvestigationSession {
  constructor() {
    this.investigationId = "";
    this.investigation = null;
    this.contextCandidate = null;
    this.outboundCandidate = null;
    this.eventSequence = 0;
    this._openToken = Symbol("closed-investigation");
    this._investigationLoadToken = Symbol("investigation-load");
    this._selectionToken = Symbol("context-selection");
    this._previewToken = Symbol("context-preview");
    this._outboundPreviewToken = Symbol("outbound-preview");
    this._reconnectToken = Symbol("event-reconnect");
    this._eventStreamController = null;
  }

  beginOpen(investigationId) {
    this.disposeEventStream();
    this.investigationId = String(investigationId || "");
    this.investigation = null;
    this.contextCandidate = null;
    this.outboundCandidate = null;
    this.eventSequence = 0;
    this._openToken = Symbol("investigation-open");
    this._investigationLoadToken = Symbol("investigation-load");
    this._selectionToken = Symbol("context-selection");
    this._previewToken = Symbol("context-preview");
    this._outboundPreviewToken = Symbol("outbound-preview");
    this._reconnectToken = Symbol("event-reconnect");
    return this.openRequest();
  }

  openRequest() {
    return Object.freeze({
      investigationId: this.investigationId,
      token: this._openToken,
    });
  }

  isCurrent(request) {
    return Boolean(
      request
      && request.investigationId === this.investigationId
      && request.token === this._openToken
    );
  }

  beginInvestigationLoad(open = this.openRequest()) {
    if (!this.isCurrent(open)) return null;
    this._investigationLoadToken = Symbol("investigation-load");
    return Object.freeze({open, token: this._investigationLoadToken});
  }

  isCurrentInvestigationLoad(request) {
    return Boolean(
      request
      && this.isCurrent(request.open)
      && request.token === this._investigationLoadToken
    );
  }

  acceptInvestigationLoad(request, investigation) {
    if (!this.isCurrentInvestigationLoad(request)) return false;
    this.investigation = investigation;
    return true;
  }

  invalidateContextSelection() {
    this._selectionToken = Symbol("context-selection");
    this.discardContextCandidate();
  }

  discardContextCandidate() {
    this._previewToken = Symbol("context-preview");
    this.contextCandidate = null;
  }

  beginContextPreview() {
    this.contextCandidate = null;
    this._previewToken = Symbol("context-preview");
    return Object.freeze({
      open: this.openRequest(),
      selectionToken: this._selectionToken,
      previewToken: this._previewToken,
    });
  }

  isCurrentContextPreview(request) {
    return Boolean(
      request
      && this.isCurrent(request.open)
      && request.selectionToken === this._selectionToken
      && request.previewToken === this._previewToken
    );
  }

  acceptContextCandidate(request, candidate) {
    if (!this.isCurrentContextPreview(request)) return false;
    this.contextCandidate = candidate;
    return true;
  }

  beginOutboundPreview(open = this.openRequest()) {
    if (!this.isCurrent(open)) return null;
    this.outboundCandidate = null;
    this._outboundPreviewToken = Symbol("outbound-preview");
    return Object.freeze({
      open,
      token: this._outboundPreviewToken,
    });
  }

  isCurrentOutboundPreview(request) {
    return Boolean(
      request
      && this.isCurrent(request.open)
      && request.token === this._outboundPreviewToken
    );
  }

  acceptOutboundCandidate(request, candidate) {
    if (!this.isCurrentOutboundPreview(request)) return false;
    this.outboundCandidate = candidate;
    return true;
  }

  discardOutboundCandidate() {
    this._outboundPreviewToken = Symbol("outbound-preview");
    this.outboundCandidate = null;
  }

  beginReconnect(open = this.openRequest()) {
    this._reconnectToken = Symbol("event-reconnect");
    return Object.freeze({open, token: this._reconnectToken});
  }

  isCurrentReconnect(request) {
    return Boolean(
      request
      && this.isCurrent(request.open)
      && request.token === this._reconnectToken
    );
  }

  replaceEventStream() {
    this.disposeEventStream();
    this._eventStreamController = new AbortController();
    return Object.freeze({
      open: this.openRequest(),
      controller: this._eventStreamController,
    });
  }

  ownsEventStream(stream) {
    return Boolean(
      stream
      && this.isCurrent(stream.open)
      && stream.controller === this._eventStreamController
      && !stream.controller.signal.aborted
    );
  }

  disposeEventStream() {
    if (this._eventStreamController) this._eventStreamController.abort();
    this._eventStreamController = null;
  }

  close() {
    this.disposeEventStream();
    this.investigationId = "";
    this.investigation = null;
    this.contextCandidate = null;
    this.outboundCandidate = null;
    this.eventSequence = 0;
    this._openToken = Symbol("closed-investigation");
    this._investigationLoadToken = Symbol("investigation-load");
    this._selectionToken = Symbol("context-selection");
    this._previewToken = Symbol("context-preview");
    this._outboundPreviewToken = Symbol("outbound-preview");
    this._reconnectToken = Symbol("event-reconnect");
  }

  path(suffix = "") {
    return `/api/v1/investigations/${encodeURIComponent(this.investigationId)}${suffix}`;
  }
}
