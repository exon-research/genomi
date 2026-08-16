    import * as api from './portal_api.js';
    import { createActiveContextClient } from './portal_active_context_client.js';
    import { conversationAttachmentModels, renderConversationAttachments } from './portal_conversation_attachments.js';
    import { createConversationReviewController } from './portal_conversation_review_controller.js';
    import { ARTIFACT_ACTIONS, isArtifactStateAction } from './portal_artifact_actions.js';
    import { artifactDisplayModel, artifactPreviewModel, artifactRecordsOutsideWorkspaceFiles, createArtifactLibraryController, renderArtifactPreview } from './portal_artifacts.js';
    import { createArtifactWorkTraceController } from './portal_artifact_work_trace_controller.js';
    import { createEvidenceLedger } from './portal_evidence_ledger.js';
    import { genomeContextViewModel, renderGenomeContext } from './portal_genome_context.js';
    import { activeGenomeHeaderModel, inquiryGenomeStateLabel, renderGenomeInventory } from './portal_genome_inventory.js';
    import { createGenomiLabController } from './portal_genomilab.js';
    import { shouldReloadFrameMessages } from './portal_message_refresh.js';
    import { createMessageSurface } from './portal_messages.js';
    import { createPromptContextController } from './portal_prompt_context.js';
    import { initializePortalSession } from './portal_session.js';
    import { watchProject } from './portal_project_stream.js';
    import { applyAssistantWorkingLabel, assistantSummaryLabel, renderAssistantChoice } from './portal_runtime_status.js';
    import { watchRun } from './portal_run_stream.js';
    import { createWorkTraceController } from './portal_work_trace_controller.js';
    import { createWorkspaceFileController, importedWorkspaceFileContextPayload } from './portal_workspace_files.js';
    import { artifactRoutePath, artifactRouteState, artifactWithSelectedVersion, frameRoutePath, parsePortalRoute, projectRoutePath, resolveArtifactRouteSelection, validateRequestedArtifactVersion } from './portal_artifact_route_model.js';
    import { renderToolCatalog, renderToolCatalogStatus, renderToolInspector, visibleTools } from './portal_tool_catalog.js';
    import { clearStarterCardState, markStarterSourceUnavailable, setStarterCardPending } from './portal_starter_cards.js';

    await initializePortalSession();

    const frameStorageKeyBase = 'genomi:portal:frameId';
    const promptContextStorageKey = 'genomi:portal:selectedEvidence:v1';
    const maxImportBytes = 4 * 1024 * 1024;
    const state = {
      agents: [],
      assistant: {},
      context: null,
      genomeInventory: null,
      project: null,
      projects: [],
      frameId: null,
      frames: [],
      artifacts: [],
      workspaceFiles: null,
      artifactDetails: {},
      tools: [],
      toolCatalogStatus: 'idle',
      toolCatalogError: '',
      toolCatalogLoadPromise: null,
      activeToolName: null,
      activeToolParams: {},
      activeArtifactId: null,
      activeArtifactVersionId: null,
      activeArtifactTabId: null,
      artifactLoadSerial: 0,
      reviewRunsInProgress: {},
      conversationReviewRunning: false,
      activeRun: null,
      liveMessageFrameId: null,
      projectWatcher: null,
      projectWatcherProjectId: null,
      refreshTimers: {},
      frameLoadSerial: 0,
      workspaceRecoveryNotice: '',
      workspaceSearchQuery: '',
      conversationSearchQuery: '',
      activeWorkspaceSection: 'research-workspace'
    };
    const $ = (id) => document.getElementById(id);
    const advancedWorkspaceSections = new Set(['evidence-ledger-pane', 'work-trace-pane', 'genome-index', 'tool-launcher']);
    const genomiLab = createGenomiLabController({
      api,
      getProjectId: () => state.project && state.project.project_id,
      getFrameId: () => state.frameId
    });
    const promptContext = createPromptContextController({
      tray: $('prompt-context'),
      prompt: $('prompt'),
      storageKey: promptContextStorageKey,
      onAskSelected: askSelectedEvidence,
      onAskNewConversation: askSelectedEvidenceInNewConversation,
      onSuggestPrompt: suggestPromptForContexts
    });
    const evidenceLedger = createEvidenceLedger({
      container: $('evidence-ledger'),
      detailContainer: $('evidence-ledger-detail'),
      onUseContext: appendPromptContext,
      onAskContext: askPromptContext,
      onAskNewContext: askPromptContextInNewConversation,
      onDraftContext: draftPromptContext,
      onAskFollowUp: askToolFollowUp
    });
    const messageSurface = createMessageSurface({
      list: $('messages'),
      onUseContext: appendPromptContext,
      onAskContext: askPromptContext,
      onAskNewContext: askPromptContextInNewConversation,
      onDraftContext: draftPromptContext,
      onAskFollowUp: askToolFollowUp,
      onToolRecord: handleToolRecord,
      onApprovePermission: approvePermissionRequest,
      onConversationStateChange: renderConversationIntake
    });
    const conversationReview = createConversationReviewController({
      container: $('conversation-review'),
      api,
      getProjectId: () => state.project && state.project.project_id,
      getFrameId: () => state.frameId,
      getAgentId: () => selectedAgent().id,
      onUseFinding: appendPromptContext,
      onJumpToMessage: (messageId) => messageSurface.focusMessage(messageId),
      onStateChange: ({ running }) => {
        state.conversationReviewRunning = running;
        renderConversationIdentity();
      }
    });
    const artifactLibrary = createArtifactLibraryController({
      container: $('artifact-list'),
      onPreview: previewArtifact,
      onUseContext: appendPromptContext,
      onArtifactAction: performArtifactAction,
      baseUrlProvider: () => window.location.href
    });
    const workspaceFileBrowser = createWorkspaceFileController({
      container: $('workspace-files'),
      onOpenArtifact: openWorkspaceFileArtifact,
      onViewContext: viewWorkspaceFileContext,
      onPreviewFile: previewWorkspaceFile,
      onAskFile: askPromptContext,
      onAskNewFile: askPromptContextInNewConversation,
      onUseFile: appendPromptContext
    });
    const artifactWorkTrace = createArtifactWorkTraceController({
      api,
      onUpdate: () => renderActiveArtifactPreview()
    });
    const activeContextClient = createActiveContextClient({
      api,
      state,
      activeArtifact,
      artifactPreviewModel
    });
    const workTrace = createWorkTraceController({
      api,
      container: () => $('frame-work-trace'),
      onStateChange: updateWorkspaceDetailNavVisibility,
      actionOptions: () => ({
        onUseContext: appendPromptContext,
        onAskContext: askPromptContext,
        onAskNewContext: askPromptContextInNewConversation,
        onDraftContext: draftPromptContext,
        onAskFollowUp: askToolFollowUp,
        baseUrl: window.location.href
      })
    });
    const scheduleActiveContextSync = () => activeContextClient.schedule();
    const syncActiveContextNow = () => activeContextClient.syncNow();
    function routeIds() {
      return parsePortalRoute(window.location.pathname, window.location.search);
    }
    function currentRoutePath() {
      return window.location.pathname + window.location.search;
    }
    function replaceRoute(nextPath) {
      if (currentRoutePath() !== nextPath || window.location.hash) window.history.replaceState(null, '', nextPath);
    }
    function setProjectRoute() {
      if (!state.project) return;
      const nextPath = projectRoutePath(state.project.project_id);
      replaceRoute(nextPath);
      scheduleActiveContextSync();
    }
    function setFrameRoute(frameId, options = {}) {
      if (!state.project || !frameId) return;
      const nextPath = frameRoutePath(state.project.project_id, frameId, options.highlightRunId, options.highlightStepId);
      replaceRoute(nextPath);
      scheduleActiveContextSync();
    }
    function setArtifactRoute(artifactId) {
      if (!state.project || !artifactId) return;
      const versionId = state.activeArtifactId === artifactId ? state.activeArtifactVersionId : null;
      const tabId = state.activeArtifactId === artifactId ? state.activeArtifactTabId : null;
      const nextPath = artifactRoutePath(state.project.project_id, artifactId, versionId, tabId);
      replaceRoute(nextPath);
      scheduleActiveContextSync();
    }
    function frameStorageKey(projectId = state.project && state.project.project_id) {
      const cleanProjectId = String(projectId || '').trim();
      return cleanProjectId ? frameStorageKeyBase + ':' + cleanProjectId : frameStorageKeyBase;
    }
    function savedFrameIdForProject(projectId = state.project && state.project.project_id) {
      return localStorage.getItem(frameStorageKey(projectId)) || localStorage.getItem(frameStorageKeyBase);
    }
    function rememberFrameId(frameId) {
      localStorage.setItem(frameStorageKey(), frameId);
      localStorage.removeItem(frameStorageKeyBase);
    }
    function clearRememberedFrameId(projectId = state.project && state.project.project_id) {
      localStorage.removeItem(frameStorageKey(projectId));
      if (!projectId) localStorage.removeItem(frameStorageKeyBase);
    }
    function workspaceName(project = state.project) {
      return project ? (String(project.name || '').trim() || 'Research workspace') : 'Loading workspace...';
    }
    function workspaceDetail(project = state.project) {
      if (!project) return 'Local project workspace';
      const conversationCount = Number(project.conversation_count || 0);
      const artifactCount = Number(project.artifact_count || 0);
      const conversations = String(conversationCount) + ' conversation' + (conversationCount === 1 ? '' : 's');
      const artifacts = String(artifactCount) + ' file' + (artifactCount === 1 ? '' : 's');
      return conversations + ' · ' + artifacts;
    }
    function updateProjectStatus() {
      renderWorkspaceSwitcher();
    }
    function renderWorkspaceSwitcher() {
      const currentName = $('workspace-name');
      const currentDetail = $('workspace-detail');
      const status = $('project-status');
      if (currentName) currentName.textContent = workspaceName();
      if (currentDetail) currentDetail.textContent = workspaceDetail();
      if (status) {
        status.textContent = state.workspaceRecoveryNotice || '';
        status.hidden = !state.workspaceRecoveryNotice;
      }
      renderWorkspaceList();
    }
    function renderWorkspaceList() {
      const list = $('workspace-list');
      if (!list) return;
      const projects = state.projects.length ? state.projects : (state.project ? [state.project] : []);
      if (!projects.length) {
        list.innerHTML = '<div class="frame-empty">No workspaces yet.</div>';
        return;
      }
      list.innerHTML = '';
      const query = String(state.workspaceSearchQuery || '').trim().toLowerCase();
      const currentProjectId = state.project ? String(state.project.project_id || '').trim() : '';
      const matches = projects.filter((project) => {
        if (!query) return true;
        const haystack = [
          workspaceName(project),
          workspaceDetail(project),
          project.project_id
        ].join(' ').toLowerCase();
        return haystack.includes(query);
      });
      const visibleProjects = matches
        .slice()
        .sort((left, right) => {
          const leftCurrent = String(left.project_id || '').trim() === currentProjectId;
          const rightCurrent = String(right.project_id || '').trim() === currentProjectId;
          if (leftCurrent !== rightCurrent) return leftCurrent ? -1 : 1;
          return 0;
        })
        .slice(0, query ? 20 : 8);
      if (!visibleProjects.length) {
        list.innerHTML = '<div class="frame-empty">No matching workspaces.</div>';
        return;
      }
      visibleProjects.forEach((project) => {
        const projectId = String(project.project_id || '').trim();
        if (!projectId) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'workspace-item' + (state.project && state.project.project_id === projectId ? ' active' : '');
        button.innerHTML = '<strong></strong><span></span>';
        button.querySelector('strong').textContent = workspaceName(project);
        button.querySelector('span').textContent = workspaceDetail(project);
        button.addEventListener('click', () => switchWorkspace(projectId).catch(showWorkspaceError));
        list.appendChild(button);
      });
      if (matches.length > visibleProjects.length) {
        const more = document.createElement('div');
        more.className = 'workspace-list-more';
        more.textContent = 'Showing ' + String(visibleProjects.length) + ' of ' + String(matches.length) + '. Search to narrow.';
        list.appendChild(more);
      }
    }
    function setWorkspaceMenuOpen(open) {
      const menu = $('workspace-menu');
      const toggle = $('workspace-menu-toggle');
      if (menu) menu.hidden = !open;
      if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) renderWorkspaceList();
    }
    function toggleWorkspaceMenu() {
      const menu = $('workspace-menu');
      setWorkspaceMenuOpen(Boolean(menu && menu.hidden));
    }
    async function refreshWorkspaceProjects() {
      try {
        const payload = await api.loadProjects();
        state.projects = Array.isArray(payload.projects) ? payload.projects : [];
      } catch {
        state.projects = state.project ? [state.project] : [];
      }
      renderWorkspaceSwitcher();
    }
    async function switchWorkspace(projectId) {
      const cleanProjectId = String(projectId || '').trim();
      if (!cleanProjectId || (state.project && state.project.project_id === cleanProjectId)) {
        setWorkspaceMenuOpen(false);
        return;
      }
      stopActiveRun();
      await api.selectProject(cleanProjectId);
      clearWorkspaceState();
      window.history.pushState(null, '', projectRoutePath(cleanProjectId));
      setWorkspaceMenuOpen(false);
      await loadWorkspace();
      activateWorkspaceSection('research-workspace', { replaceHash: false });
    }
    async function createWorkspace(event) {
      event.preventDefault();
      const input = $('workspace-name-input');
      const name = input ? String(input.value || '').trim() : '';
      const project = await api.createProject(name || 'GenomiLab Workspace');
      if (input) input.value = '';
      clearWorkspaceState();
      window.history.pushState(null, '', projectRoutePath(project.project_id));
      setWorkspaceMenuOpen(false);
      await loadWorkspace();
      activateWorkspaceSection('research-workspace', { replaceHash: false });
    }
    async function renameWorkspace() {
      if (!state.project) return;
      const input = $('workspace-name-input');
      const name = input ? String(input.value || '').trim() : '';
      if (!name) {
        if (input) {
          input.value = workspaceName();
          input.focus();
          input.select();
        }
        return;
      }
      state.project = await api.renameProject(state.project.project_id, name);
      if (input) input.value = '';
      await refreshWorkspaceProjects();
      setProjectRoute();
    }
    function showWorkspaceError(error) {
      state.workspaceRecoveryNotice = error && error.message ? error.message : 'Workspace action failed';
      renderWorkspaceSwitcher();
    }
    function updateFrameBundleAction() {
      const link = $('frame-bundle');
      if (!link) return;
      const url = state.project && state.frameId
        ? api.frameBundleUrl(state.project.project_id, state.frameId, window.location.href)
        : '';
      link.hidden = !url;
      link.href = url;
    }
    function renderActiveFrameState() {
      updateFrameBundleAction();
      renderFrames(state.frames);
      renderConversationIdentity();
    }
    function clearFrameRoute() {
      if (state.project) setProjectRoute();
      else if (window.location.pathname !== '/') window.history.replaceState(null, '', '/');
    }
    function setActiveFrame(frameId, options = {}) {
      state.frameId = frameId;
      rememberFrameId(frameId);
      setFrameRoute(frameId, { highlightRunId: options.highlightRunId, highlightStepId: options.highlightStepId });
      renderActiveFrameState();
      genomiLab.loadBoard().catch(() => undefined);
    }
    function clearActiveFrame() {
      state.frameId = null;
      clearRememberedFrameId();
      clearFrameRoute();
      renderActiveFrameState();
      genomiLab.loadBoard().catch(() => undefined);
    }
    function frameTitle(frame) {
      const title = (frame.title || frame.display_request || frame.displayRequest || frame.request || '').trim();
      return title || 'Untitled conversation';
    }
    function frameStatusLabel(status) {
      const clean = String(status || '').trim();
      if (!clean) return 'Conversation';
      if (clean === 'needs_input') return 'Needs approval';
      if (clean === 'stale_after_restart') return 'Interrupted — continue here';
      return clean.split(/[\s_-]+/).filter(Boolean).map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
    }
    function frameMessageCountLabel(count) {
      const value = Number(count || 0);
      const safeCount = Number.isFinite(value) && value > 0 ? value : 0;
      return String(safeCount) + ' message' + (safeCount === 1 ? '' : 's');
    }
    function frameDetailText(frame) {
      const details = [frameStatusLabel(frame.status), frameMessageCountLabel(frame.turn_count ?? frame.message_count)];
      const startedFrom = frame && frame.started_from && String(frame.started_from.summary || '').trim();
      if (startedFrom) details.push(startedFrom);
      return details.filter(Boolean).join(' · ');
    }
    function renderFrames(frames) {
      const list = $('frame-list');
      if (!list) return;
      if (!frames.length) {
        list.innerHTML = '<div class="frame-empty">No conversations yet.</div>';
        return;
      }
      list.innerHTML = '';
      const query = String(state.conversationSearchQuery || '').trim().toLowerCase();
      const matches = frames.filter((frame) => {
        if (!query) return true;
        return [frameTitle(frame), frame.display_request, frame.request]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(query);
      });
      const visibleFrames = matches
        .slice()
        .sort((left, right) => {
          const leftActive = left.id === state.frameId;
          const rightActive = right.id === state.frameId;
          if (leftActive !== rightActive) return leftActive ? -1 : 1;
          return 0;
        })
        .slice(0, 30);
      if (!visibleFrames.length) {
        list.innerHTML = '<div class="frame-empty">No matching conversations.</div>';
        return;
      }
      visibleFrames.forEach((frame) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'frame-item' + (frame.id === state.frameId ? ' active' : '');
        button.innerHTML = '<strong></strong><span></span>';
        button.querySelector('strong').textContent = frameTitle(frame);
        button.querySelector('span').textContent = frameDetailText(frame);
        button.addEventListener('click', () => {
          openFrame(frame.id).catch(() => {
            promptContext.setPromptText('This conversation is no longer available. Refresh the project frames and try again.');
          });
        });
        list.appendChild(button);
      });
      if (matches.length > visibleFrames.length) {
        const more = document.createElement('div');
        more.className = 'workspace-list-more';
        more.textContent = 'Showing ' + String(visibleFrames.length) + ' of ' + String(matches.length) + '. Search to narrow.';
        list.appendChild(more);
      }
    }
    async function loadFrames() {
      if (!state.project) return;
      const payload = await api.loadProjectFrames(state.project.project_id);
      state.frames = payload.frames || [];
      renderActiveFrameState();
    }
    function activeConversation() {
      return state.frames.find((frame) => frame && frame.id === state.frameId) || null;
    }
    function renderConversationIntake({ empty } = {}) {
      const intake = document.querySelector('.genomilab-intake');
      if (intake) intake.hidden = !empty;
    }
    function renderConversationIdentity() {
      const frame = activeConversation();
      const title = frame ? frameTitle(frame) : 'New conversation';
      const titleElement = $('conversation-title');
      if (titleElement) {
        titleElement.textContent = title;
        titleElement.title = title;
      }
      const rename = $('conversation-rename');
      if (rename) rename.hidden = !frame;
      const review = $('conversation-review-action');
      if (review) {
        review.hidden = !frame;
        review.disabled = !frame || frame.status === 'processing' || state.conversationReviewRunning;
        review.textContent = state.conversationReviewRunning ? 'Reviewing…' : 'Request review';
      }
      if (!frame) closeConversationRename();
    }
    function openConversationRename() {
      const frame = activeConversation();
      const form = $('conversation-rename-form');
      const input = $('conversation-title-input');
      if (!frame || !form || !input) return;
      form.hidden = false;
      input.value = frameTitle(frame);
      input.focus();
      input.select();
      const menu = $('conversation-rename').closest('details');
      if (menu) menu.open = false;
    }
    function closeConversationRename() {
      const form = $('conversation-rename-form');
      if (form) form.hidden = true;
    }
    async function renameActiveConversation(event) {
      event.preventDefault();
      const frame = activeConversation();
      const input = $('conversation-title-input');
      const title = input ? String(input.value || '').trim() : '';
      if (!frame || !state.project || !title) {
        if (input) input.focus();
        return;
      }
      const renamed = await api.renameConversation(state.project.project_id, frame.id, title);
      state.frames = state.frames.map((item) => item && item.id === renamed.id ? renamed : item);
      closeConversationRename();
      renderActiveFrameState();
      await Promise.all([loadArtifacts(), loadWorkspaceFiles()]);
    }
    async function openFrame(frameId, options = {}) {
      const prepared = await prepareFrameOpen(frameId);
      commitFrameOpen(prepared.frame.id, prepared.messages, options);
      if (options.activateResearch) activateWorkspaceSection('research-workspace');
      if (options.activateWorkTrace || options.highlightStepId) activateWorkspaceSection('work-trace-pane');
      if (options.highlightRunId) highlightFrameRun(options.highlightRunId);
    }
    async function prepareFrameOpen(frameId) {
      const cleanFrameId = String(frameId || '').trim();
      if (!cleanFrameId || !state.project) throw new Error('Frame is not available in the current project.');
      const frame = await api.loadFrame(cleanFrameId, state.project.project_id);
      if (!frame || frame.id !== cleanFrameId || frame.project_id !== state.project.project_id) {
        throw new Error('Frame is not available in the current project.');
      }
      const messages = await api.loadFrameMessages(cleanFrameId, state.project.project_id);
      if (!messages || messages.frame_id !== cleanFrameId) {
        throw new Error('Frame messages did not match the requested frame.');
      }
      return { frame, messages };
    }
    function commitFrameOpen(frameId, messagesPayload, options = {}) {
      state.frameLoadSerial += 1;
      state.liveMessageFrameId = null;
      stopActiveRun();
      if (!options.keepArtifactOpen) clearArtifactSelection();
      setActiveFrame(frameId, { highlightRunId: options.highlightRunId, highlightStepId: options.highlightStepId });
      renderFrameMessages(frameId, messagesPayload, options);
    }
    function clearArtifactSelection() {
      state.activeArtifactId = null;
      state.activeArtifactVersionId = null;
      state.activeArtifactTabId = null;
      renderArtifactLibrary();
      renderActiveArtifactPreview();
    }
    function newChat() {
      stopActiveRun();
      state.liveMessageFrameId = null;
      clearActiveFrame();
      evidenceLedger.setScope({ label: 'this new conversation' });
      messageSurface.reset();
      conversationReview.reset();
      workTrace.reset();
      activateWorkspaceSection('research-workspace', { replaceHash: false });
      $('prompt').focus();
    }
    function appendPromptContext(text) {
      const attached = promptContext.add(text);
      if (attached) activateWorkspaceSection('research-workspace', { replaceHash: false });
    }
    function includeGenomeContext(context) {
      const attached = promptContext.add(context);
      if (attached) focusGenomeQuestionComposer();
    }
    function askPromptContext(context) {
      promptContext.askWith(context)
        .then((attached) => {
          if (attached) activateWorkspaceSection('research-workspace', { replaceHash: false });
        })
        .catch(() => undefined);
    }
    function askPromptContextInNewConversation(context) {
      promptContext.askNewWith(context)
        .then((attached) => {
          if (attached) activateWorkspaceSection('research-workspace', { replaceHash: false });
        })
        .catch(() => undefined);
    }
    function draftPromptContext(context) {
      promptContext.draftWith(context)
        .then((attached) => {
          if (attached) activateWorkspaceSection('research-workspace', { replaceHash: false });
        })
        .catch(() => undefined);
    }
    function askToolFollowUp(target) {
      const contexts = followUpContexts(target);
      if (contexts.length) {
        promptContext.draftWith(contexts[0]).catch(() => undefined);
        activateWorkspaceSection('research-workspace', { replaceHash: false });
        return;
      }
      const prompt = followUpPromptText(target);
      if (prompt) promptContext.setPromptText(prompt);
    }
    function followUpContexts(target) {
      if (!target || typeof target !== 'object') return [];
      if (Array.isArray(target.selectedEvidence)) return target.selectedEvidence.filter(Boolean);
      if (target.context && typeof target.context === 'object') return [target.context];
      return [];
    }
    function followUpPromptText() {
      return 'Use the included evidence.';
    }
    function askSelectedEvidence(contexts, options = {}) {
      const selectedEvidence = Array.isArray(contexts) ? contexts : promptContext.snapshot();
      const promptText = $('prompt').value.trim();
      if (!promptText && !selectedEvidence.length) return;
      if (!promptText && isOnlyGenomeContext(selectedEvidence)) {
        focusGenomeQuestionComposer();
        return;
      }
      const message = promptText || 'Use the included evidence.';
      const clearAfterSuccess = options && typeof options.onSuccess === 'function'
        ? options.onSuccess
        : () => promptContext.clear();
      $('prompt').value = '';
      submitTurnDraft({
        message,
        selectedEvidence,
        presentationKind: promptText ? '' : 'selected_material_control',
        onSuccess: clearAfterSuccess,
        onError: () => promptContext.setPromptText(promptText || message)
      }).catch(() => undefined);
    }
    function askSelectedEvidenceInNewConversation(contexts, options = {}) {
      const selectedEvidence = Array.isArray(contexts) ? contexts : [];
      if (!selectedEvidence.length) return;
      const message = String(options.message || '').trim() || 'Use the included evidence.';
      submitTurnDraft({
        message,
        selectedEvidence,
        presentationKind: String(options.message || '').trim() ? '' : 'selected_material_control',
        forceNewFrame: true,
        onSuccess: options.onSuccess,
        onError: options.onError
      }).catch(() => undefined);
    }
    function isOnlyGenomeContext(contexts) {
      return Array.isArray(contexts)
        && contexts.length > 0
        && contexts.every((item) => item && String(item.context_kind || '').trim().toLowerCase() === 'genome_context');
    }
    function contextsWithMessagePresentationKind(contexts, presentationKind) {
      if (!Array.isArray(contexts) || !contexts.length || !presentationKind) return contexts;
      return contexts.map((item, index) => index === 0 && item && typeof item === 'object'
        ? { ...item, message_presentation_kind: presentationKind }
        : item);
    }
    function focusGenomeQuestionComposer() {
      activateWorkspaceSection('research-workspace', { replaceHash: false });
      $('prompt').placeholder = 'Ask a genetics question. Genomi will use the approved active genome only when it is relevant.';
      $('prompt').focus();
    }
    function selectedAgent() {
      const activeId = state.assistant && state.assistant.active_agent_id;
      return state.agents.find((agent) => agent.id === activeId)
        || { id: '', label: 'Assistant runtime' };
    }
    function handleToolRecord(record) {
      if (!record) evidenceLedger.reset();
      else if (!isPermissionRequestRecord(record)) evidenceLedger.upsert(record);
      updateEvidenceLedgerVisibility(evidenceLedger.count());
      if (record) {
        workTrace.trackLiveToolRecord(record, state.activeRun);
        genomiLab.refreshFromToolRecord(record).catch(() => undefined);
      }
    }
    function isPermissionRequestRecord(record) {
      return Boolean(record && record.result && record.result.permission_request);
    }
    function updateEvidenceLedgerVisibility(count) {
      const hasEvidence = Number(count || 0) > 0;
      const pane = $('evidence-ledger-pane');
      document.querySelectorAll('[data-evidence-ledger-nav]').forEach((nav) => {
        nav.hidden = !hasEvidence;
      });
      if (pane) pane.hidden = !hasEvidence || state.activeWorkspaceSection !== 'evidence-ledger-pane';
      if (!hasEvidence && state.activeWorkspaceSection === 'evidence-ledger-pane') {
        activateWorkspaceSection('research-workspace', { replaceHash: false });
      }
    }
    function updateWorkspaceDetailNavVisibility() {
      const hasWorkTrace = Boolean(workTrace && typeof workTrace.hasWork === 'function' && workTrace.hasWork());
      document.querySelectorAll('[data-mobile-work-trace-nav]').forEach((nav) => {
        nav.hidden = !hasWorkTrace && state.activeWorkspaceSection !== 'work-trace-pane';
      });
      document.querySelectorAll('[data-mobile-source-nav]').forEach((nav) => {
        nav.hidden = state.activeWorkspaceSection !== 'tool-launcher';
      });
    }
    function stopActiveRun({ resetSend = true } = {}) {
      if (state.activeRun && state.activeRun.watcher) state.activeRun.watcher.close();
      state.activeRun = null;
      if (resetSend) $('send').disabled = false;
    }
    function isCurrentRun(runId, frameId) {
      return Boolean(
        state.activeRun &&
        state.activeRun.runId === runId &&
        state.activeRun.frameId === frameId &&
        state.frameId === frameId
      );
    }
    async function loadContext() {
      const runtime = await api.loadPortalRuntime();
      applyWorkspaceAssistant(runtime);
      await loadWorkspace();
      restoreHashWorkspaceSection();
    }
    function applyWorkspaceAssistant(runtime) {
      state.agents = (runtime && runtime.agents) || [];
      state.assistant = (runtime && runtime.assistant) || {};
      $('agent-dot').className = 'status-dot ' + (state.assistant.state === 'ready' ? 'ready' : '');
      $('agent-status').textContent = assistantSummaryLabel(state.assistant, state.agents);
      applyAssistantWorkingLabel(state.assistant);
      renderAssistantChoice($('agent-list'), { agents: state.agents, assistant: state.assistant }, {
        onSelect: selectWorkspaceAssistant
      });
      if (state.assistant.state === 'choice_required') revealAssistantChoice();
    }
    function revealAssistantChoice() {
      for (let node = $('agent-list'); node; node = node.parentElement) {
        if (node.tagName === 'DETAILS') node.open = true;
      }
    }
    async function selectWorkspaceAssistant(agentId) {
      const projectId = state.project && state.project.project_id;
      if (!projectId || !agentId) return;
      try {
        const payload = await api.selectWorkspaceAssistant(projectId, agentId);
        applyWorkspaceAssistant(payload);
      } catch (error) {
        $('agent-status').textContent = 'Could not switch assistant: ' + (error.message || 'request failed');
      }
    }
    async function loadProjectGenomeContext() {
      const projectId = state.project && state.project.project_id;
      if (!projectId) return;
      const [runtime, genomeInventory] = await Promise.all([
        api.loadPortalRuntime(projectId),
        loadGenomeInventorySafe(projectId)
      ]);
      state.context = runtime.context;
      state.genomeInventory = genomeInventory;
      applyWorkspaceAssistant(runtime);
      $('context').textContent = JSON.stringify(state.context, null, 2);
      renderGenomeContext($('context-summary'), state.context, {
        onUseContext: appendPromptContext,
        onIncludeGenome: includeGenomeContext
      });
      renderGenomeInventory($('genome-inventory'), state.genomeInventory, {
        onAddGenome: openGenomeSourceTool,
        onSelectGenome: selectGenomeFromInventory
      });
      const genomeState = genomeContextViewModel(state.context);
      const genomeHeader = activeGenomeHeaderModel(state.genomeInventory, genomeState);
      const onboardingAgiState = $('onboarding-agi-state');
      if (onboardingAgiState) {
        onboardingAgiState.textContent = inquiryGenomeStateLabel(genomeHeader);
      }
      $('context-dot').className = 'status-dot ' + (genomeHeader.status === 'ready' ? 'ready' : '');
      const genomeHeaderTitle = genomeHeader.displayTitle || genomeHeader.title;
      $('context-label').textContent = genomeHeaderTitle;
      $('context-summary-action').setAttribute(
        'aria-label',
        'Open ' + genomeHeaderTitle + '. ' + (genomeHeader.actionLabel || 'Switch or add genomes') + '.'
      );
      const contextDetail = $('context-detail');
      if (contextDetail) contextDetail.textContent = genomeHeader.subtitle || 'Open Active genome';
      const switchGenome = $('context-switch-genome');
      if (switchGenome) {
        switchGenome.hidden = !genomeHeader.canSwitch;
        switchGenome.textContent = genomeHeader.switchLabel || 'Switch';
        switchGenome.setAttribute('aria-label', (genomeHeader.switchLabel || 'Switch') + ' active genome');
      }
      const addGenome = $('context-add-genome');
      if (addGenome) {
        addGenome.textContent = genomeHeader.addLabel || 'Add genome';
        addGenome.setAttribute('aria-label', 'Add a genome');
      }
    }
    async function loadGenomeInventorySafe(projectId) {
      try {
        return await api.loadGenomeInventory(projectId);
      } catch (error) {
        return { status: 'error', error: error.message || 'Genome list unavailable', genomes: [], users: [] };
      }
    }
    async function loadWorkspace() {
      const route = routeIds();
      const routeSelection = artifactRouteState(route);
      state.project = await loadRouteProject(route);
      await loadProjectGenomeContext();
      genomiLab.loadAll().catch(() => undefined);
      await refreshWorkspaceProjects();
      watchActiveProject();
      updateProjectStatus();
      renderActiveFrameState();
      state.activeArtifactId = routeSelection.artifactId;
      state.activeArtifactVersionId = routeSelection.artifactVersionId;
      state.activeArtifactTabId = routeSelection.artifactTabId;
      await loadArtifacts();
      await loadWorkspaceFiles();
      await loadFrames();
      if (routeSelection.artifactId && state.activeArtifactId === routeSelection.artifactId) {
        activateWorkspaceSection('artifact-workspace', { replaceHash: false });
      }
      scheduleActiveContextSync();
      const projectId = state.project && state.project.project_id;
      const frameIdToOpen = route.frameId || savedFrameIdForProject(projectId);
      if (!frameIdToOpen) return;
      try {
        await openFrame(frameIdToOpen, {
          activateResearch: Boolean(route.highlightRunId && !route.highlightStepId),
          activateWorkTrace: Boolean(route.highlightStepId),
          highlightRunId: route.highlightRunId,
          highlightStepId: route.highlightStepId
        });
      } catch {
        clearRememberedFrameId(projectId);
        if (route.frameId) setProjectRoute();
        return;
      }
    }
    async function loadRouteProject(route) {
      if (!route.projectId) {
        state.workspaceRecoveryNotice = '';
        return api.loadProject();
      }
      try {
        state.workspaceRecoveryNotice = '';
        const project = await api.loadProject(route.projectId);
        api.selectProject(project.project_id).catch(() => undefined);
        return project;
      } catch (error) {
        if (!api.isNotFoundError(error)) throw error;
        window.history.replaceState(null, '', '/');
        clearWorkspaceState();
        state.workspaceRecoveryNotice = 'Project no longer available; opened current workspace';
        return api.loadProject();
      }
    }
    function clearWorkspaceState() {
      const previousProjectId = state.project && state.project.project_id;
      if (state.projectWatcher) state.projectWatcher.close();
      state.projectWatcher = null;
      state.projectWatcherProjectId = null;
      state.project = null;
      state.frameId = null;
      state.frames = [];
      state.artifacts = [];
      state.workspaceFiles = null;
      workspaceFileBrowser.reset();
      state.artifactDetails = {};
      state.activeArtifactId = null;
      state.activeArtifactVersionId = null;
      state.activeArtifactTabId = null;
      state.liveMessageFrameId = null;
      state.activeWorkspaceSection = 'research-workspace';
      state.conversationSearchQuery = '';
      state.conversationReviewRunning = false;
      conversationReview.reset();
      const conversationSearch = $('conversation-search');
      if (conversationSearch) conversationSearch.value = '';
      messageSurface.reset();
      promptContext.clear();
      evidenceLedger.setScope({ label: 'this conversation' });
      evidenceLedger.reset();
      artifactWorkTrace.reset({ clearCache: true });
      workTrace.reset();
      clearRememberedFrameId(previousProjectId);
    }
    async function loadFrameMessages(frameId) {
      const loadSerial = state.frameLoadSerial + 1;
      state.frameLoadSerial = loadSerial;
      state.liveMessageFrameId = null;
      stopActiveRun();
      const payload = await api.loadFrameMessages(frameId, state.project && state.project.project_id);
      if (state.frameId !== frameId || state.frameLoadSerial !== loadSerial || payload.frame_id !== frameId) return;
      renderFrameMessages(frameId, payload);
    }
    function renderFrameMessages(frameId, payload, options = {}) {
      if (!payload || payload.frame_id !== frameId) return;
      evidenceLedger.setScope({ frameId, label: frameEvidenceScopeLabel(frameId) });
      messageSurface.reset();
      messageSurface.renderStoredMessages(payload.messages || []);
      conversationReview.render(payload.reviews || []);
      renderMessageArtifacts();
      workTrace.setFrameMessages(frameId, payload, { highlightStepId: options.highlightStepId }).catch(() => undefined);
    }
    function frameEvidenceScopeLabel(frameId) {
      const frame = state.frames.find((item) => item && item.id === frameId);
      const title = frame ? frameTitle(frame) : '';
      return title && title !== 'Untitled conversation' ? '"' + title + '"' : 'the current conversation';
    }
    function renderMessageArtifacts() {
      renderConversationAttachments(
        $('conversation-attachments'),
        conversationAttachmentModels(state.artifacts, state.frameId),
        { onOpenAttachment: openAttachedRecord }
      );
      messageSurface.renderInlineArtifacts(state.artifacts, {
        frameId: state.frameId,
        onUseContext: appendPromptContext,
        onPreview: previewArtifact,
        onArtifactAction: performArtifactAction,
        baseUrl: window.location.href
      });
    }
    function watchActiveProject() {
      const projectId = state.project && state.project.project_id;
      if (!projectId || state.projectWatcherProjectId === projectId) return;
      if (state.projectWatcher) state.projectWatcher.close();
      state.projectWatcherProjectId = projectId;
      state.projectWatcher = watchProject(projectId, {
        onProjectChanged: () => scheduleProjectReload(),
        onFrameChanged: () => scheduleFramesReload(),
        onMessagesChanged: (event) => scheduleMessagesReload(event),
        onLabInvestigationChanged: () => debounceRefresh('lab-board', genomiLab.loadBoard),
        onArtifactsChanged: () => {
          scheduleArtifactsReload();
          scheduleWorkspaceFilesReload();
        }
      });
    }
    function scheduleProjectReload() {
      debounceRefresh('project', async () => {
        if (!state.project) return;
        state.project = await api.loadProject(state.project.project_id);
        await refreshWorkspaceProjects();
        updateProjectStatus();
      });
    }
    function scheduleFramesReload() {
      debounceRefresh('frames', loadFrames);
    }
    function scheduleArtifactsReload() {
      debounceRefresh('artifacts', loadArtifacts);
    }
    function scheduleWorkspaceFilesReload() {
      debounceRefresh('workspace-files', loadWorkspaceFiles);
    }
    function scheduleMessagesReload(event) {
      if (!shouldReloadFrameMessages(event, state)) return;
      const frameId = event.frame_id;
      debounceRefresh('messages:' + frameId, () => {
        if (!shouldReloadFrameMessages(event, state)) return undefined;
        return loadFrameMessages(frameId);
      });
    }
    function debounceRefresh(key, loader, delay = 180) {
      if (state.refreshTimers[key]) window.clearTimeout(state.refreshTimers[key]);
      state.refreshTimers[key] = window.setTimeout(() => {
        delete state.refreshTimers[key];
        Promise.resolve(loader()).catch(() => undefined);
      }, delay);
    }
    async function loadArtifacts() {
      if (!state.project) return;
      const route = routeIds();
      const payload = await api.loadProjectArtifacts(state.project.project_id);
      const artifacts = payload.artifacts || [];
      state.artifacts = artifacts;
      pruneArtifactDetails(artifacts);
      const selection = resolveArtifactRouteSelection({
        route,
        projectId: state.project.project_id,
        artifacts,
        activeArtifactId: state.activeArtifactId,
        activeArtifactVersionId: state.activeArtifactVersionId,
        activeArtifactTabId: state.activeArtifactTabId,
        isPreviewableArtifact: (artifact) => artifactPreviewModel(artifact, window.location.href).previewable
      });
      state.activeArtifactId = selection.artifactId;
      state.activeArtifactVersionId = selection.artifactVersionId;
      state.activeArtifactTabId = selection.artifactTabId;
      if (selection.normalizeToProject) setProjectRoute();
      renderArtifactLibrary();
      renderWorkspaceFiles();
      renderMessageArtifacts();
      renderActiveArtifactPreview();
      hydrateActiveArtifactPreview();
      scheduleActiveContextSync();
    }
    async function loadWorkspaceFiles() {
      if (!state.project) return;
      state.workspaceFiles = await api.loadProjectWorkspaceFiles(state.project.project_id);
      renderWorkspaceFiles();
      renderArtifactLibrary();
    }
    function renderWorkspaceFiles() {
      workspaceFileBrowser.render(state.workspaceFiles || { files: [], summary: {} }, {
        projectId: state.project && state.project.project_id
      });
      renderArtifactWorkspaceMode();
    }
    function renderArtifactLibrary({ focusSearch = false } = {}) {
      const records = artifactRecordsOutsideWorkspaceFiles(state.artifacts, state.workspaceFiles);
      const workspaceFileCount = Array.isArray(state.workspaceFiles && state.workspaceFiles.files)
        ? state.workspaceFiles.files.length
        : 0;
      const list = $('artifact-list');
      if (list) list.hidden = Boolean(state.activeArtifactId) || Boolean(workspaceFileCount && !records.length);
      if (list && list.hidden) {
        list.innerHTML = '';
        return;
      }
      artifactLibrary.render(records, {
        activeArtifactId: state.activeArtifactId,
        focusSearch
      });
      renderArtifactWorkspaceMode();
    }
    function openWorkspaceFileArtifact(file) {
      const artifactId = file && file.artifactId;
      if (!artifactId) return;
      const artifact = state.artifactDetails[artifactId] || state.artifacts.find((item) => item.id === artifactId);
      if (artifact) previewArtifact(artifact);
    }
    async function viewWorkspaceFileContext(originContext) {
      const frameId = originContext && originContext.frameId;
      if (!frameId || !state.project) return;
      const highlightRunId = workspaceFileOriginHighlightRunId(originContext);
      try {
        await openFrame(frameId, { activateResearch: true, highlightRunId, keepArtifactOpen: true });
      } catch {
        promptContext.setPromptText('The conversation that produced this file is no longer available in this project. Open the generated record or artifact instead.');
      }
    }
    function workspaceFileOriginHighlightRunId(originContext) {
      const runIds = Array.isArray(originContext && originContext.runIds) ? originContext.runIds : [];
      return String(runIds[0] || '').trim();
    }
    async function previewWorkspaceFile(file) {
      if (!state.project || !file || !file.path) return null;
      return api.loadProjectWorkspaceFilePreview(state.project.project_id, file.path);
    }
    async function importArtifactFile(file, { attachToPrompt = false } = {}) {
      if (!file) return;
      if (!state.project) await loadWorkspace();
      if (file.size > maxImportBytes) {
        setFileImportStatus(attachToPrompt, 'Too large');
        return;
      }
      setFileImportStatus(attachToPrompt, attachToPrompt ? 'Attaching...' : 'Importing...');
      try {
        const contentBase64 = bytesToBase64(new Uint8Array(await file.arrayBuffer()));
        const conversationId = attachToPrompt ? String(state.frameId || '').trim() : '';
        const payload = await api.importProjectFile(state.project.project_id, {
          filename: file.name,
          contentType: file.type || 'application/octet-stream',
          contentBase64,
          ...(conversationId ? { frameId: conversationId } : {})
        });
        const artifact = payload.artifact || {};
        if (artifact.id) {
          state.artifactDetails[artifact.id] = artifact;
          state.activeArtifactId = artifact.id;
          state.activeArtifactVersionId = null;
          state.activeArtifactTabId = null;
          setArtifactRoute(artifact.id);
        }
        await loadArtifacts();
        await loadWorkspaceFiles();
        if (attachToPrompt) {
          const imported = payload.imported || {};
          const relativePath = String(imported.workspace_relative_path || '').trim();
          let preview = {};
          if (relativePath) {
            try {
              preview = await api.loadProjectWorkspaceFilePreview(state.project.project_id, relativePath);
            } catch {}
          }
          const context = importedWorkspaceFileContextPayload(payload, preview);
          if (context) appendPromptContext(context);
          activateWorkspaceSection('research-workspace', { replaceHash: false });
          setFileImportStatus(true, context ? 'Record attached' : 'Imported');
        } else {
          if (artifact.id) activateWorkspaceSection('artifact-workspace', { replaceHash: false });
          setFileImportStatus(false, 'Imported');
        }
      } catch (error) {
        setFileImportStatus(attachToPrompt, error.message || 'Import failed');
      }
    }
    function setFileImportStatus(chatAttachment, message) {
      if (chatAttachment) {
        const status = $('chat-file-attachment-status');
        if (status) status.textContent = String(message || '').trim();
        return;
      }
      setArtifactImportStatus(message);
    }
    function setArtifactImportStatus(message) {
      const status = $('artifact-import-status');
      if (!status) return;
      const text = String(message || '').trim();
      status.hidden = !text;
      status.textContent = text;
    }
    function bytesToBase64(bytes) {
      let binary = '';
      const chunkSize = 0x8000;
      for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
      }
      return window.btoa(binary);
    }
    async function loadToolCatalog() {
      if (state.toolCatalogLoadPromise) return state.toolCatalogLoadPromise;
      state.toolCatalogLoadPromise = runToolCatalogLoad();
      try {
        await state.toolCatalogLoadPromise;
      } finally {
        state.toolCatalogLoadPromise = null;
      }
    }
    async function runToolCatalogLoad() {
      state.toolCatalogStatus = 'loading';
      state.toolCatalogError = '';
      renderToolWorkspace();
      try {
        const payload = await api.loadSourceLookups();
        state.tools = visibleTools(payload.sourceLookups || payload.tools || []);
        state.toolCatalogStatus = state.tools.length ? 'ready' : 'empty';
        state.toolCatalogError = '';
        if (!state.tools.some((tool) => tool.name === state.activeToolName)) {
          state.activeToolName = null;
        }
      } catch (error) {
        state.tools = [];
        state.activeToolName = null;
        state.toolCatalogStatus = 'error';
        state.toolCatalogError = error.message || 'Evidence catalog unavailable';
      }
      renderToolWorkspace();
    }
    async function ensureToolCatalogLoaded() {
      if (state.toolCatalogStatus === 'loading' && state.toolCatalogLoadPromise) {
        await state.toolCatalogLoadPromise;
        return;
      }
      if (state.toolCatalogStatus !== 'idle') return;
      await loadToolCatalog();
    }
    function evidenceSourceOperationId(tool) {
      return String((tool && tool.sourceLookup && (tool.sourceLookup.operationId || tool.sourceLookup.name)) || (tool && tool.name) || '');
    }
    function evidenceSourceParamsKey(toolOrOperation) {
      if (typeof toolOrOperation === 'string') return toolOrOperation;
      return evidenceSourceOperationId(toolOrOperation);
    }
    function evidenceSourceParamsFor(tool) {
      return state.activeToolParams[evidenceSourceParamsKey(tool)] || {};
    }
    async function attachEvidenceSourceRequest(tool, params = {}) {
      return api.attachEvidenceSource(evidenceSourceOperationId(tool), params || {});
    }
    function attachedEvidenceSourcePackets(attached) {
      if (attached && Array.isArray(attached.selectedEvidence)) return attached.selectedEvidence.filter(Boolean);
      if (attached && attached.packet) return [attached.packet];
      return [];
    }
    async function attachEvidenceSource(tool, params = {}) {
      const attached = await attachEvidenceSourceRequest(tool, params);
      const packets = attachedEvidenceSourcePackets(attached);
      if (packets.length) promptContext.add(packets[0]);
      activateWorkspaceSection('research-workspace');
    }
    async function askToolRequest(tool, params) {
      const attached = await attachEvidenceSourceRequest(tool, params);
      const message = attached && attached.prompt || '';
      const selectedEvidence = attachedEvidenceSourcePackets(attached);
      submitTurnDraft({ message, selectedEvidence }).catch(() => undefined);
      activateWorkspaceSection('research-workspace');
    }
    function selectTool(tool, options = {}) {
      state.activeToolName = tool && tool.name;
      const key = evidenceSourceParamsKey(tool);
      if (key && options.initialParams) state.activeToolParams[key] = options.initialParams;
      else if (key && !options.preserveParams) delete state.activeToolParams[key];
      renderToolWorkspace();
    }
    function renderToolWorkspace() {
      const activeTool = state.tools.find((tool) => tool.name === state.activeToolName) || null;
      if (state.toolCatalogStatus === 'ready') {
        renderToolCatalog($('tool-launcher-list'), state.tools, {
          activeToolName: state.activeToolName,
          onSelectTool: selectTool
        });
      } else {
        renderToolCatalogStatus($('tool-launcher-list'), state.toolCatalogStatus, state.toolCatalogError);
      }
      renderToolInspector($('tool-inspector'), state.toolCatalogStatus === 'ready' ? activeTool : null, {
        initialParams: activeTool ? evidenceSourceParamsFor(activeTool) : {},
        onAttachRequest: attachEvidenceSource,
        onUseContext: appendPromptContext,
        onAskRequest: askToolRequest
      });
    }
    function previewArtifact(artifact) {
      state.activeArtifactId = artifact && artifact.id;
      state.activeArtifactVersionId = null;
      state.activeArtifactTabId = null;
      artifactWorkTrace.reset();
      if (state.activeArtifactId) setArtifactRoute(state.activeArtifactId);
      renderArtifactLibrary();
      renderActiveArtifactPreview();
      hydrateActiveArtifactPreview();
      activateWorkspaceSection('artifact-workspace', { replaceHash: false });
      scheduleActiveContextSync();
    }
    function openAttachedRecord(artifactId) {
      const artifact = (state.artifacts || []).find((item) => item && item.id === artifactId);
      if (artifact) previewArtifact(artifact);
    }
    function closeArtifactPreview() {
      state.activeArtifactId = null;
      state.activeArtifactVersionId = null;
      state.activeArtifactTabId = null;
      artifactWorkTrace.reset();
      setProjectRoute();
      renderArtifactLibrary();
      renderWorkspaceFiles();
      renderActiveArtifactPreview();
      activateWorkspaceSection('artifact-workspace');
    }
    function activateArtifactTabRoute(tabId) {
      state.activeArtifactTabId = tabId || null;
      if (state.activeArtifactId) setArtifactRoute(state.activeArtifactId);
      scheduleActiveContextSync();
    }
    function selectArtifactVersion(versionId) {
      state.activeArtifactVersionId = versionId || null;
      if (state.activeArtifactId) setArtifactRoute(state.activeArtifactId);
      renderActiveArtifactPreview();
      scheduleActiveContextSync();
    }
    async function viewArtifactContext(originContext) {
      const frameId = originContext && originContext.frameId;
      if (!frameId || !state.project) return;
      const highlightRunId = artifactOriginHighlightRunId(originContext);
      const highlightStepId = artifactOriginHighlightStepId(originContext);
      try {
        await openFrame(frameId, {
          activateResearch: Boolean(highlightRunId && !highlightStepId),
          activateWorkTrace: Boolean(highlightStepId),
          highlightRunId,
          highlightStepId,
          keepArtifactOpen: true
        });
      } catch {
        promptContext.setPromptText('The origin conversation for this artifact is no longer available in this project. Use the artifact Messages tab as the available provenance record.');
      }
    }
    function artifactOriginHighlightRunId(originContext) {
      const producingRunId = String((originContext && originContext.producingRunId) || '').trim();
      if (producingRunId) return producingRunId;
      const runIds = Array.isArray(originContext && originContext.runIds) ? originContext.runIds : [];
      return String(runIds[0] || '').trim();
    }
    function artifactOriginHighlightStepId(originContext) {
      return String((originContext && originContext.producingStepId) || '').trim();
    }
    function highlightFrameRun(runId) {
      messageSurface.focusRun(runId);
    }
    function renderActiveArtifactPreview() {
      const artifact = artifactWithPendingReviewRun(activeArtifactForPreview());
      const executionCells = artifactWorkTrace.executionCellsFor(artifact);
      renderArtifactPreview($('artifact-preview'), artifact, {
        executionCells,
        onUseContext: appendPromptContext,
        onAskContext: askPromptContext,
        onAskNewContext: askPromptContextInNewConversation,
        onDraftContext: draftPromptContext,
        onArtifactAction: performArtifactAction,
        onArtifactReviewRun: runArtifactReviewChecks,
        onViewContext: viewArtifactContext,
        onTabChange: activateArtifactTabRoute,
        onVersionChange: selectArtifactVersion,
        activeTabId: state.activeArtifactTabId,
        baseUrl: window.location.href
      });
      artifactWorkTrace.hydrate(artifact).catch(() => undefined);
      renderArtifactWorkspaceMode();
    }
    function renderArtifactWorkspaceMode() {
      const selected = Boolean(state.activeArtifactId);
      const workspaceFiles = $('workspace-files');
      const preview = $('artifact-preview');
      const back = $('artifact-back');
      const importAction = $('artifact-import-action');
      if (workspaceFiles) workspaceFiles.hidden = selected;
      if (preview) preview.hidden = !selected;
      if (back) back.hidden = !selected;
      if (importAction) importAction.hidden = selected;
      const pane = $('artifact-workspace');
      if (pane) pane.dataset.objectOpen = selected ? 'true' : 'false';
      document.body.dataset.artifactOpen = selected ? 'true' : 'false';
    }
    function activeArtifact() {
      if (!state.activeArtifactId) return null;
      return state.artifactDetails[state.activeArtifactId] || state.artifacts.find((item) => item.id === state.activeArtifactId) || null;
    }
    function activeArtifactForPreview() {
      const artifact = activeArtifact();
      return artifactWithSelectedVersion(artifact, state.activeArtifactVersionId);
    }
    async function performArtifactAction(artifact, request = {}) {
      if (!state.project || !artifact || !artifact.id) return;
      const action = String(request.action || '').trim();
      if (!action) return;
      const payload = artifactActionPayload(artifact, action);
      if (!payload) return;
      const projectId = artifact.project_id || state.project.project_id;
      await api.updateArtifact(projectId, artifact.id, payload);
      if (payload.action === ARTIFACT_ACTIONS.DELETE) {
        if (state.activeArtifactId === artifact.id) {
          state.activeArtifactId = null;
          state.activeArtifactVersionId = null;
          state.activeArtifactTabId = null;
          setProjectRoute();
        }
        delete state.artifactDetails[artifact.id];
      }
      await loadArtifacts();
    }
    async function runArtifactReviewChecks(artifact) {
      if (!state.project || !artifact || !artifact.id) return;
      const projectId = artifact.project_id || state.project.project_id;
      const display = artifactDisplayModel(artifact);
      const versionId = display.effectiveVersionId || artifactReviewVersionId(artifact);
      const pendingKey = reviewRunKey(artifact.id, versionId);
      if (state.reviewRunsInProgress[pendingKey]) return;
      state.reviewRunsInProgress[pendingKey] = pendingReviewRun(versionId);
      if (state.activeArtifactId === artifact.id) {
        state.activeArtifactTabId = 'review';
        setArtifactRoute(artifact.id);
        renderActiveArtifactPreview();
      }
      try {
        await api.runArtifactReview(projectId, artifact.id, versionId);
        const detail = await api.loadArtifactInspection(projectId, artifact.id);
        const requestedVersionId = state.activeArtifactId === artifact.id ? (state.activeArtifactVersionId || versionId) : versionId;
        const validation = validateRequestedArtifactVersion(detail, requestedVersionId);
        state.artifactDetails[artifact.id] = validation.artifact;
        if (state.activeArtifactId === artifact.id) {
          state.activeArtifactVersionId = validation.selectedVersionId;
          state.activeArtifactTabId = 'review';
          setArtifactRoute(artifact.id);
        }
        await loadArtifacts();
        delete state.reviewRunsInProgress[pendingKey];
        renderActiveArtifactPreview();
      } catch {
        delete state.reviewRunsInProgress[pendingKey];
        promptContext.setPromptText('Review checks could not run for this artifact version. Open the Review tab or refresh the artifact and try again.');
        renderActiveArtifactPreview();
      }
    }
    function artifactWithPendingReviewRun(artifact) {
      if (!artifact || !artifact.id) return artifact;
      const display = artifactDisplayModel(artifact);
      const versionId = display.effectiveVersionId || artifactReviewVersionId(artifact);
      const pending = state.reviewRunsInProgress[reviewRunKey(artifact.id, versionId)];
      if (!pending) return artifact;
      return artifactWithReviewRun(artifact, versionId, pending);
    }
    function artifactWithReviewRun(artifact, versionId, reviewRun) {
      const cleanVersionId = String(versionId || '').trim();
      const next = { ...artifact };
      if (next.review) next.review = reviewWithRun(next.review, reviewRun);
      if (next.latest_version && typeof next.latest_version === 'object') {
        const latestVersionId = String(next.latest_version.version_id || '').trim();
        if (!cleanVersionId || latestVersionId === cleanVersionId) {
          next.latest_version = {
            ...next.latest_version,
            review: reviewWithRun(next.latest_version.review || next.review, reviewRun)
          };
        }
      }
      if (Array.isArray(next.versions)) {
        next.versions = next.versions.map((version) => {
          if (!version || typeof version !== 'object') return version;
          if (cleanVersionId && String(version.version_id || '').trim() !== cleanVersionId) return version;
          return {
            ...version,
            review: reviewWithRun(version.review || next.review, reviewRun)
          };
        });
      }
      return next;
    }
    function reviewWithRun(review, reviewRun) {
      if (!review || typeof review !== 'object') return review;
      const runs = Array.isArray(review.review_runs)
        ? review.review_runs.filter((run) => run && typeof run === 'object')
        : [];
      if (runs.some((run) => run.review_run_id && run.review_run_id === reviewRun.review_run_id)) return review;
      return {
        ...review,
        review_runs: [...runs, reviewRun]
      };
    }
    function pendingReviewRun(versionId) {
      return {
        kind: 'artifact_review_run',
        review_run_id: 'pending-' + Date.now().toString(36),
        status: 'running',
        check_status: 'running',
        started_at: new Date().toISOString(),
        version_id: String(versionId || '').trim(),
        summary: 'Review checks are running for this artifact version.'
      };
    }
    function reviewRunKey(artifactId, versionId) {
      return String(artifactId || '').trim() + ':' + String(versionId || '').trim();
    }
    function artifactReviewVersionId(artifact) {
      const latest = artifact && artifact.latest_version && typeof artifact.latest_version === 'object' ? artifact.latest_version : {};
      return String(
        (state.activeArtifactId === artifact.id && state.activeArtifactVersionId)
        || artifact.selected_version_id
        || artifact.effective_version_id
        || artifact.latest_version_id
        || latest.version_id
        || ''
      ).trim();
    }
    function artifactActionPayload(artifact, action) {
      if (action === ARTIFACT_ACTIONS.RENAME) {
        const currentTitle = String(artifact.title || '').trim();
        const nextTitle = window.prompt('Rename result', currentTitle);
        if (nextTitle === null) return null;
        const title = String(nextTitle || '').trim();
        if (!title || title === currentTitle) return null;
        return { action, title };
      }
      if (action === ARTIFACT_ACTIONS.DELETE) {
        const title = String(artifact.title || 'this result').trim();
        if (!window.confirm('Delete "' + title + '" from this project?')) return null;
        return { action };
      }
      if (isArtifactStateAction(action)) return { action };
      return null;
    }
    function pruneArtifactDetails(artifacts) {
      const ids = new Set(artifacts.map((artifact) => artifact.id).filter(Boolean));
      Object.keys(state.artifactDetails).forEach((artifactId) => {
        if (!ids.has(artifactId)) delete state.artifactDetails[artifactId];
      });
    }
    async function hydrateActiveArtifactPreview() {
      const artifactId = state.activeArtifactId;
      if (!artifactId || state.artifactDetails[artifactId]?.versions_loaded) return;
      const serial = state.artifactLoadSerial + 1;
      state.artifactLoadSerial = serial;
      try {
        const detail = await api.loadArtifactInspection(state.project.project_id, artifactId);
        if (state.activeArtifactId !== artifactId || state.artifactLoadSerial !== serial) return;
        const validation = validateRequestedArtifactVersion(detail, state.activeArtifactVersionId);
        if (validation.shouldNormalizeToArtifact) {
          state.activeArtifactVersionId = null;
          setArtifactRoute(artifactId);
        } else {
          state.activeArtifactVersionId = validation.selectedVersionId;
        }
        state.artifactDetails[artifactId] = validation.artifact;
        renderActiveArtifactPreview();
      } catch {
        if (state.activeArtifactId !== artifactId || state.artifactLoadSerial !== serial) return;
        state.artifactDetails[artifactId] = {
          ...(state.artifacts.find((item) => item.id === artifactId) || { id: artifactId }),
          versions_loaded: false,
          inspection_error: 'Artifact detail unavailable'
        };
        renderActiveArtifactPreview();
      }
    }
    function initWorkspaceNavigation() {
      document.body.dataset.activeWorkspaceSection = state.activeWorkspaceSection;
      updateWorkspaceDetailNavVisibility();
      document.querySelectorAll('[data-workspace-nav]').forEach((nav) => {
        nav.addEventListener('click', (event) => {
          const button = event.target && event.target.closest ? event.target.closest('[data-nav-target]') : null;
          if (!button) return;
          event.preventDefault();
          activateWorkspaceSection(button.getAttribute('data-nav-target') || '');
        });
      });
      const initial = window.location.hash ? window.location.hash.slice(1) : '';
      if (initial) window.setTimeout(() => activateWorkspaceSection(initial, { replaceHash: false }), 0);
    }
    function restoreHashWorkspaceSection() {
      const target = window.location.hash ? window.location.hash.slice(1) : '';
      if (target && document.getElementById(target)) {
        activateWorkspaceSection(target, { replaceHash: false });
      }
    }
    function activateWorkspaceSection(target, { replaceHash = true } = {}) {
      const section = document.getElementById(target);
      if (!section) return;
      revealWorkspaceSection(target, section);
      state.activeWorkspaceSection = target;
      document.body.dataset.activeWorkspaceSection = target;
      updateWorkspaceDetailNavVisibility();
      document.querySelectorAll('[data-nav-target]').forEach((button) => {
        button.classList.toggle('active', button.getAttribute('data-nav-target') === target);
      });
      if (replaceHash && window.location.hash !== '#' + target) {
        window.history.replaceState(null, '', currentRoutePath() + '#' + target);
      }
      scheduleActiveContextSync();
      section.scrollIntoView({ block: 'start', behavior: 'smooth' });
      if (target === 'research-workspace') {
        $('prompt').focus({ preventScroll: true });
        return;
      }
      if (target === 'tool-launcher') ensureToolCatalogLoaded().catch(() => undefined);
    }
    function revealWorkspaceSection(target, section) {
      if (advancedWorkspaceSections.has(target)) {
        section.hidden = false;
        const advancedNav = document.querySelector('.advanced-nav');
        if (advancedNav) advancedNav.open = true;
        advancedWorkspaceSections.forEach((sectionId) => {
          const other = document.getElementById(sectionId);
          if (other && other !== section) other.hidden = true;
        });
        return;
      }
      advancedWorkspaceSections.forEach((sectionId) => {
        const advanced = document.getElementById(sectionId);
        if (advanced) advanced.hidden = true;
      });
    }
    async function submitTurn({ message, selectedEvidence, genomeContextMode = '', forceNewFrame = false, sourceFrameId = '', startedFromSelectedMaterial = false }) {
      if (!state.project) await loadWorkspace();
      try {
        await syncActiveContextNow();
      } catch {}
      const payload = await api.submitTurn({
        projectId: state.project.project_id,
        frameId: forceNewFrame ? null : state.frameId,
        message,
        selectedEvidence,
        genomeContextMode,
        sourceFrameId: forceNewFrame ? sourceFrameId : '',
        startedFromSelectedMaterial: Boolean(forceNewFrame && startedFromSelectedMaterial)
      });
      if (payload.frameId) {
        setActiveFrame(payload.frameId);
        await loadFrames();
      }
      return payload.runId;
    }
    async function suggestPromptForContexts(contexts) {
      const payload = await api.suggestPrompt({ selectedEvidence: Array.isArray(contexts) ? contexts : [] });
      return payload && payload.prompt;
    }
    async function submitTurnDraft({ message, selectedEvidence, presentationKind = '', forceNewFrame = false, onSuccess, onError }) {
      const requestedMessage = String(message || '').trim();
      const effectivePresentationKind = presentationKind || (!requestedMessage && Array.isArray(selectedEvidence) && selectedEvidence.length
        ? 'selected_material_control'
        : '');
      const contexts = contextsWithMessagePresentationKind(
        Array.isArray(selectedEvidence) ? selectedEvidence : [],
        effectivePresentationKind
      );
      const cleanMessage = requestedMessage || (contexts.length ? 'Use the included evidence.' : '');
      if (!cleanMessage && !contexts.length) return null;
      const sourceFrameId = forceNewFrame ? state.frameId : '';
      const startedFromSelectedMaterial = Boolean(forceNewFrame && contexts.length);
      if (forceNewFrame) newChat();
      $('send').disabled = true;
      messageSurface.addMessage('user', cleanMessage, contexts, {
        agent: selectedAgent(),
        presentationKind: effectivePresentationKind
      });
      const body = messageSurface.addMessage('assistant', '', [], {
        presentationKind: effectivePresentationKind === 'genome_context_control'
          ? 'genome_context_acknowledgement'
          : ''
      });
      try {
        const runId = await submitTurn({
          message: cleanMessage,
          selectedEvidence: contexts,
          forceNewFrame,
          sourceFrameId,
          startedFromSelectedMaterial
        });
        messageSurface.registerAssistantRun(body, runId);
        renderMessageArtifacts();
        if (typeof onSuccess === 'function') onSuccess(runId);
        attachRun(runId, body);
        return runId;
      } catch (error) {
        if (typeof onError === 'function') onError(error);
        body.textContent = error.message;
        if (error.code === 'assistant_choice_required' || error.code === 'workspace_assistant_unavailable') {
          revealAssistantChoice();
        }
        $('send').disabled = false;
        throw error;
      }
    }
    async function approvePermissionRequest(record) {
      const permission = record && record.result && record.result.permission_request;
      const runId = record && record.scope && record.scope.runId;
      if (!permission || !runId) return null;
      $('send').disabled = true;
      const body = messageSurface.addMessage('assistant', '');
      messageSurface.appendText(body, 'Access allowed. Continuing...\n\n');
      try {
        const payload = await api.approveRunPermission(runId, permission);
        if (payload.frameId) {
          setActiveFrame(payload.frameId);
          await loadFrames();
        }
        messageSurface.registerAssistantRun(body, payload.runId);
        renderMessageArtifacts();
        attachRun(payload.runId, body);
        return payload.runId;
      } catch (error) {
        messageSurface.appendText(body, error.message || 'Permission approval failed.');
        $('send').disabled = false;
        throw error;
      }
    }
    function answerBreak(body) {
      const written = String((body && body.dataset && body.dataset.rawText) || '').trim();
      return written ? '\n\n' : '';
    }
    function attachRun(runId, body) {
      const frameId = state.frameId;
      stopActiveRun({ resetSend: false });
      const assistantMessage = body.closest('.message');
      const active = { runId, frameId, watcher: null };
      state.activeRun = active;
      state.liveMessageFrameId = frameId;
      workTrace.beginLiveRun(frameId);
      active.watcher = watchRun(runId, {
        onAgent: (data) => {
          if (!isCurrentRun(runId, frameId)) return;
          if (data.type === 'text_delta') messageSurface.appendText(body, data.delta || '');
          if (data.type === 'diagnostic' || data.type === 'tool_call' || data.type === 'tool_result' || data.type === 'error') {
            messageSurface.addToolEvent(data.type, data, assistantMessage, { frameId, runId });
          }
        },
        onStdout: (data) => {
          if (!isCurrentRun(runId, frameId)) return;
        },
        onStderr: (data) => {
          if (!isCurrentRun(runId, frameId)) return;
        },
        onInterrupt: () => {
          if (!isCurrentRun(runId, frameId)) return;
          assistantMessage?.classList.remove('streaming');
          messageSurface.appendText(body, answerBreak(body) + 'The connection to the assistant dropped before this turn finished. Refresh this conversation or send the question again.');
          $('send').disabled = false;
          state.activeRun = null;
          loadFrames().catch(() => undefined);
        },
        onEnd: (data) => {
          if (!isCurrentRun(runId, frameId)) return;
          assistantMessage?.classList.remove('streaming');
          messageSurface.finishRun(runId, data.status || 'completed');
          if (data.status !== 'succeeded' && data.error) messageSurface.appendText(body, answerBreak(body) + data.error);
          loadFrames().catch(() => undefined);
          $('send').disabled = false;
          state.activeRun = null;
        }
      });
    }
    $('composer').addEventListener('submit', async (event) => {
      event.preventDefault();
      const promptText = $('prompt').value.trim();
      const contexts = promptContext.snapshot();
      if (!promptText && !contexts.length) return;
      if (!promptText && isOnlyGenomeContext(contexts)) {
        focusGenomeQuestionComposer();
        return;
      }
      const message = promptText || 'Use the included evidence.';
      $('prompt').value = '';
      try {
        await submitTurnDraft({
          message,
          selectedEvidence: contexts,
          presentationKind: promptText ? '' : 'selected_material_control',
          onSuccess: () => promptContext.clear(),
          onError: () => promptContext.setPromptText(promptText)
        });
      } catch {}
    });
    async function openSourceSuggestion(button) {
      const operation = String(button.getAttribute('data-source-operation') || '').trim();
      if (!operation) return false;
      setStarterCardPending(button);
      await ensureToolCatalogLoaded();
      const tool = state.tools.find((item) => evidenceSourceOperationId(item) === operation || item.name === operation);
      if (!tool) {
        markStarterSourceUnavailable(button, sourceSuggestionUnavailableMessage(operation));
        return false;
      }
      clearStarterCardState(button);
      selectTool(tool, { initialParams: sourceSuggestionParams(button) });
      activateWorkspaceSection('tool-launcher');
      return true;
    }
    function sourceSuggestionUnavailableMessage(operation) {
      const catalogError = state.toolCatalogStatus === 'error' ? state.toolCatalogError : '';
      if (catalogError) return catalogError;
      return operation
        ? 'That evidence source is not available in the current catalog.'
        : 'The evidence source is not available in the current catalog.';
    }
    function sourceSuggestionParams(button) {
      const raw = String(button.getAttribute('data-source-params') || '').trim();
      if (!raw) return {};
      try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
      } catch {
        return {};
      }
    }
    async function openGenomeSourceTool() {
      activateWorkspaceSection('tool-launcher');
      if (state.toolCatalogStatus !== 'ready') {
        await loadToolCatalog();
      } else {
        await ensureToolCatalogLoaded();
      }
      const tool = state.tools.find((item) => evidenceSourceOperationId(item) === 'genomi.parse_source' || item.name === 'genomi.parse_source');
      if (tool) {
        selectTool(tool);
        return true;
      }
      state.activeToolName = null;
      renderToolWorkspace();
      showEvidenceSourceUnavailable(
        'Add a genome',
        sourceSuggestionUnavailableMessage('genomi.parse_source') + ' Refresh evidence sources or add the genome from chat with a local file path.'
      );
      return false;
    }
    function startAddGenome() {
      openGenomeSourceTool().catch((error) => {
        activateWorkspaceSection('tool-launcher');
        state.activeToolName = null;
        renderToolWorkspace();
        showEvidenceSourceUnavailable(
          'Add a genome',
          (error && error.message) || 'Genome-source setup is unavailable. Refresh evidence sources or add the genome from chat with a local file path.'
        );
      });
    }
    function showEvidenceSourceUnavailable(title, detail) {
      const container = $('tool-inspector');
      if (!container) return;
      container.innerHTML = '';
      const empty = document.createElement('div');
      empty.className = 'tool-inspector-empty warning';
      empty.innerHTML = '<strong></strong><span></span>';
      empty.querySelector('strong').textContent = title || 'Evidence source unavailable';
      empty.querySelector('span').textContent = detail || 'Refresh evidence sources or try again after the local Genomi server is ready.';
      container.appendChild(empty);
    }
    async function selectGenomeFromInventory(selection) {
      if (!selection || (!selection.agiId && !selection.userId && !selection.nickname)) return;
      if (!state.project) return;
      await api.selectGenome(state.project.project_id, selection);
      await loadProjectGenomeContext();
      activateWorkspaceSection('genome-index', { replaceHash: false });
    }
    function focusGenomeInventory() {
      activateWorkspaceSection('genome-index');
      const inventory = $('genome-inventory');
      if (inventory) inventory.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    document.addEventListener('click', (event) => {
      const button = event.target && event.target.closest ? event.target.closest('[data-source-operation], [data-prompt]') : null;
      if (!button) return;
      if (button.getAttribute('data-source-operation')) {
        event.preventDefault();
        openSourceSuggestion(button).catch(() => {
          markStarterSourceUnavailable(button, 'Refresh evidence sources or check the local Genomi server.');
        });
        return;
      }
      promptContext.setPromptText(button.getAttribute('data-prompt') || '');
    });
    $('refresh').addEventListener('click', loadContext);
    $('workspace-menu-toggle').addEventListener('click', (event) => {
      event.preventDefault();
      toggleWorkspaceMenu();
    });
    $('workspace-current').addEventListener('click', (event) => {
      event.preventDefault();
      toggleWorkspaceMenu();
    });
    $('workspace-search').addEventListener('input', (event) => {
      state.workspaceSearchQuery = event.target && event.target.value ? event.target.value : '';
      renderWorkspaceList();
    });
    $('conversation-search').addEventListener('input', (event) => {
      state.conversationSearchQuery = event.target && event.target.value ? event.target.value : '';
      renderFrames(state.frames);
    });
    $('workspace-form').addEventListener('submit', (event) => createWorkspace(event).catch(showWorkspaceError));
    $('workspace-rename').addEventListener('click', (event) => {
      event.preventDefault();
      renameWorkspace().catch(showWorkspaceError);
    });
    document.addEventListener('click', (event) => {
      const card = event.target && event.target.closest ? event.target.closest('.workspace-card') : null;
      if (!card) setWorkspaceMenuOpen(false);
    });
    $('context-summary-action').addEventListener('click', () => activateWorkspaceSection('genome-index'));
    $('context-switch-genome')?.addEventListener('click', focusGenomeInventory);
    $('context-add-genome')?.addEventListener('click', startAddGenome);
    $('add-genome').addEventListener('click', startAddGenome);
    $('switch-genome').addEventListener('click', focusGenomeInventory);
    $('new-chat').addEventListener('click', newChat);
    $('conversation-new').addEventListener('click', (event) => {
      const menu = event.currentTarget.closest('details');
      if (menu) menu.open = false;
      newChat();
    });
    $('artifact-back').addEventListener('click', closeArtifactPreview);
    $('conversation-rename').addEventListener('click', openConversationRename);
    $('conversation-review-action').addEventListener('click', () => {
      const menu = $('conversation-review-action').closest('details');
      if (menu) menu.open = false;
      conversationReview.request().catch((error) => {
        promptContext.setPromptText((error && error.message) || 'Conversation review could not start.');
      });
    });
    $('conversation-rename-form').addEventListener('submit', (event) => {
      renameActiveConversation(event).catch((error) => {
        const input = $('conversation-title-input');
        if (input) {
          input.setCustomValidity((error && error.message) || 'Could not rename this conversation.');
          input.reportValidity();
          input.addEventListener('input', () => input.setCustomValidity(''), { once: true });
        }
      });
    });
    $('conversation-rename-cancel').addEventListener('click', closeConversationRename);
    $('copy-context').addEventListener('click', () => navigator.clipboard && navigator.clipboard.writeText($('context').textContent));
    $('refresh-tools').addEventListener('click', loadToolCatalog);
    $('artifact-import-file').addEventListener('change', (event) => {
      const input = event.currentTarget;
      const file = input && input.files && input.files[0];
      importArtifactFile(file).finally(() => {
        if (input) input.value = '';
      });
    });
    $('chat-file-attachment').addEventListener('change', (event) => {
      const input = event.currentTarget;
      const file = input && input.files && input.files[0];
      importArtifactFile(file, { attachToPrompt: true }).finally(() => {
        if (input) input.value = '';
      });
    });
    genomiLab.bind();
    initWorkspaceNavigation();
    workTrace.render();
    loadContext().catch((error) => {
      $('context').textContent = error.message;
      if (state.context || state.agents.length) {
        $('project-status').textContent = 'Workspace unavailable: ' + (error.message || 'request failed');
      } else {
        $('agent-status').textContent = 'GenomiLab API unavailable';
      }
    });
    $('prompt').addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      if ($('send').disabled) return;
      $('composer').requestSubmit();
    });
