import { promptSafeText, selectedEvidencePayload } from './portal_selected_evidence.js';

const ISSUE_VERDICTS = new Set(['warning', 'error']);

export function conversationReviewModel(value) {
  const review = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const status = clean(review.status);
  const state = clean(review.state);
  if (!status || !state) return null;
  const findings = Array.isArray(review.findings)
    ? review.findings.map(conversationReviewFindingModel).filter(Boolean)
    : [];
  const issueCount = findings.filter((finding) => ISSUE_VERDICTS.has(finding.verdict)).length;
  return {
    id: clean(review.review_run_id),
    status,
    state,
    running: status === 'running' || state === 'verifying',
    failed: status === 'failed',
    title: 'Reviewer',
    summary: promptSafeText(review.summary || review.error || reviewStateSummary(state, issueCount)),
    issueCount,
    checkCount: Number(review.check_count || findings.length || 0),
    findings: findings.filter((finding) => finding.verdict !== 'pass'),
    limitations: Array.isArray(review.limitations)
      ? review.limitations.map((item) => promptSafeText(item)).filter(Boolean)
      : []
  };
}

export function latestConversationReview(reviews) {
  const items = Array.isArray(reviews) ? reviews : [];
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const model = conversationReviewModel(items[index]);
    if (model) return model;
  }
  return null;
}

export function renderConversationReview(container, reviews, options = {}) {
  if (!container) return;
  const model = latestConversationReview(reviews);
  container.innerHTML = '';
  container.hidden = !model;
  if (!model) return;
  container.dataset.reviewState = model.state;
  container.dataset.reviewStatus = model.status;
  const header = document.createElement('div');
  header.className = 'conversation-review-head';
  header.innerHTML = '<div><strong></strong><span></span></div><div class="conversation-review-actions"></div>';
  header.querySelector('strong').textContent = model.title;
  header.querySelector('span').textContent = reviewHeadline(model);
  const actions = header.querySelector('.conversation-review-actions');
  if (!model.running && typeof options.onRequestReview === 'function') {
    const rerun = document.createElement('button');
    rerun.type = 'button';
    rerun.className = 'tool-action';
    rerun.textContent = 'Review again';
    rerun.addEventListener('click', options.onRequestReview);
    actions.appendChild(rerun);
  }
  container.appendChild(header);
  if (model.running) return;
  const details = document.createElement('details');
  details.className = 'conversation-review-details';
  details.open = model.issueCount > 0 || model.failed || model.state === 'inconclusive';
  const summary = document.createElement('summary');
  summary.textContent = model.checkCount
    ? String(model.checkCount) + ' check' + (model.checkCount === 1 ? '' : 's')
    : 'Review summary';
  details.appendChild(summary);
  const body = document.createElement('div');
  body.className = 'conversation-review-body';
  const summaryText = document.createElement('p');
  summaryText.textContent = model.summary;
  body.appendChild(summaryText);
  model.findings.forEach((finding) => body.appendChild(reviewFindingElement(finding, options)));
  if (model.limitations.length) {
    const limit = document.createElement('small');
    limit.textContent = model.limitations[0];
    body.appendChild(limit);
  }
  details.appendChild(body);
  container.appendChild(details);
}

export function conversationReviewFindingPayload(finding) {
  const model = conversationReviewFindingModel(finding);
  if (!model) return null;
  return selectedEvidencePayload({
    contextKind: 'review_finding',
    label: 'Reviewer finding: ' + model.claim,
    summary: [model.verdict, model.evidence, model.recommendation].filter(Boolean).join(' · '),
    sourceOperation: 'genomi.portal.conversation_review',
    selectedNodes: [
      { label: 'Claim', text: 'Reviewer finding / Claim: ' + model.claim, value: model.claim },
      { label: 'Evidence', text: 'Reviewer finding / Evidence: ' + model.evidence, value: model.evidence },
      { label: 'Recommendation', text: 'Reviewer finding / Recommendation: ' + model.recommendation, value: model.recommendation }
    ].filter((node) => node.value),
    promptIntro: 'Address this reviewer finding using the current conversation and evidence:'
  });
}

function conversationReviewFindingModel(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const verdict = clean(value.verdict);
  if (!['pass', 'warning', 'error', 'inconclusive'].includes(verdict)) return null;
  const source = value.source_ref && typeof value.source_ref === 'object' ? value.source_ref : {};
  const claim = promptSafeText(value.claim || '').trim();
  const evidence = promptSafeText(value.evidence || '').trim();
  if (!claim && !evidence) return null;
  return {
    id: clean(value.finding_id),
    verdict,
    claim: claim || 'Reviewed claim',
    evidence,
    recommendation: promptSafeText(value.recommendation || '').trim(),
    sourceMessageId: source.kind === 'message' ? clean(source.message_id) : ''
  };
}

function reviewFindingElement(finding, options) {
  const row = document.createElement('article');
  row.className = 'conversation-review-finding ' + finding.verdict;
  row.innerHTML = [
    '<div class="conversation-review-finding-head"><em></em><strong></strong></div>',
    '<p class="conversation-review-evidence"></p>',
    '<p class="conversation-review-recommendation"></p>',
    '<div class="conversation-review-finding-actions"></div>'
  ].join('');
  row.querySelector('em').textContent = verdictLabel(finding.verdict);
  row.querySelector('strong').textContent = finding.claim;
  const evidence = row.querySelector('.conversation-review-evidence');
  evidence.textContent = finding.evidence;
  evidence.hidden = !finding.evidence;
  const recommendation = row.querySelector('.conversation-review-recommendation');
  recommendation.textContent = finding.recommendation;
  recommendation.hidden = !finding.recommendation;
  const actions = row.querySelector('.conversation-review-finding-actions');
  if (finding.sourceMessageId && typeof options.onJumpToMessage === 'function') {
    const jump = document.createElement('button');
    jump.type = 'button';
    jump.className = 'tool-action';
    jump.textContent = 'Jump to claim';
    jump.addEventListener('click', () => options.onJumpToMessage(finding.sourceMessageId));
    actions.appendChild(jump);
  }
  if (typeof options.onUseFinding === 'function') {
    const use = document.createElement('button');
    use.type = 'button';
    use.className = 'tool-action';
    use.textContent = 'Use in chat';
    use.addEventListener('click', () => options.onUseFinding(conversationReviewFindingPayload(finding)));
    actions.appendChild(use);
  }
  return row;
}

function reviewHeadline(model) {
  if (model.running) return 'Reviewing this conversation…';
  if (model.failed) return 'Review could not finish';
  if (model.state === 'findings') return model.issueCount + ' ' + (model.issueCount === 1 ? 'finding' : 'findings');
  if (model.state === 'clear') return 'No issues found';
  return 'Inconclusive';
}

function reviewStateSummary(state, issueCount) {
  if (state === 'findings') return 'Reviewer found ' + issueCount + ' issue' + (issueCount === 1 ? '' : 's') + '.';
  if (state === 'clear') return 'No issues found in the reviewed conversation.';
  if (state === 'verifying') return 'Reviewer is checking this conversation.';
  return 'Reviewer could not verify all reviewed claims.';
}

function verdictLabel(verdict) {
  if (verdict === 'pass') return 'Checked';
  if (verdict === 'error') return 'Error';
  if (verdict === 'warning') return 'Warning';
  return 'Inconclusive';
}

function clean(value) {
  return String(value || '').trim().toLowerCase();
}
