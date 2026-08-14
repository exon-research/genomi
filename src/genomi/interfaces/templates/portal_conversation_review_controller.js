import { renderConversationReview } from './portal_conversation_reviews.js';
import { watchRun } from './portal_run_stream.js';

export function createConversationReviewController({
  container,
  api,
  getProjectId,
  getFrameId,
  getAgentId,
  onUseFinding,
  onJumpToMessage,
  onStateChange
} = {}) {
  let reviews = [];
  let watcher = null;

  function render(nextReviews = reviews) {
    reviews = Array.isArray(nextReviews) ? nextReviews : [];
    renderConversationReview(container, reviews, {
      onRequestReview: request,
      onUseFinding,
      onJumpToMessage
    });
    notify();
  }

  async function request() {
    const projectId = value(getProjectId);
    const frameId = value(getFrameId);
    if (!projectId || !frameId || !api || typeof api.requestConversationReview !== 'function') return null;
    stopWatcher();
    const payload = await api.requestConversationReview(projectId, frameId, value(getAgentId));
    if (payload && payload.review) render([...reviews, payload.review]);
    if (payload && payload.runId) {
      watcher = watchRun(payload.runId, {
        onReview: (event) => {
          if (event && event.review) replaceReview(event.review);
        },
        onEnd: () => refresh().catch(() => undefined),
        onInterrupt: () => refresh().catch(() => undefined)
      });
    }
    return payload;
  }

  async function refresh() {
    const projectId = value(getProjectId);
    const frameId = value(getFrameId);
    if (!projectId || !frameId || !api || typeof api.loadFrameMessages !== 'function') return;
    const payload = await api.loadFrameMessages(frameId, projectId);
    if (value(getFrameId) !== frameId) return;
    render(payload && payload.reviews);
  }

  function replaceReview(review) {
    const id = String(review && review.review_run_id || '').trim();
    const next = reviews.filter((item) => String(item && item.review_run_id || '').trim() !== id);
    render([...next, review]);
  }

  function reset() {
    stopWatcher();
    reviews = [];
    render([]);
  }

  function stopWatcher() {
    if (watcher && typeof watcher.close === 'function') watcher.close();
    watcher = null;
  }

  function notify() {
    if (typeof onStateChange === 'function') {
      onStateChange({ reviews: [...reviews], hasReview: reviews.length > 0, running: latestRunning(reviews) });
    }
  }

  return { refresh, render, request, reset };
}

function latestRunning(reviews) {
  const latest = Array.isArray(reviews) && reviews.length ? reviews[reviews.length - 1] : {};
  return Boolean(latest && (latest.status === 'running' || latest.state === 'verifying'));
}

function value(provider) {
  return String(typeof provider === 'function' ? provider() || '' : provider || '').trim();
}
