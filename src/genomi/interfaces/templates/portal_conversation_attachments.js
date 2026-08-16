// Records the person attached to a conversation. Files imported from the chat
// composer are bound to the conversation they were added to, so the transcript
// can show what the assistant was given. Ids and transport fields stay hidden.

const ATTACHED_ARTIFACT_KIND = 'project_file';

export function conversationAttachmentModels(artifacts, frameId) {
  const conversationId = text(frameId);
  if (!conversationId || !Array.isArray(artifacts)) return [];
  return artifacts
    .filter((artifact) => artifact && artifact.kind === ATTACHED_ARTIFACT_KIND)
    .filter((artifact) => originFrameId(artifact) === conversationId)
    .map(attachmentModel)
    .filter((model) => model.name);
}

export function renderConversationAttachments(section, models, options = {}) {
  if (!section) return;
  const list = section.querySelector('[data-conversation-attachment-list]');
  if (!list) return;
  list.replaceChildren();
  section.hidden = !models.length;
  if (!models.length) return;
  const heading = section.querySelector('[data-conversation-attachment-summary]');
  if (heading) heading.textContent = attachmentSummary(models);
  models.forEach((model) => list.append(attachmentCard(model, options)));
}

export function attachmentSummary(models) {
  const count = models.length;
  return count === 1
    ? 'Genomi can read this record in this conversation.'
    : 'Genomi can read these ' + count + ' records in this conversation.';
}

function attachmentModel(artifact) {
  const summary = artifact.summary && typeof artifact.summary === 'object' ? artifact.summary : {};
  return {
    id: text(artifact.id),
    name: text(summary.original_filename) || text(summary.filename) || text(artifact.title),
    detail: [readableKind(summary.content_type, artifact), readableSize(summary.size_bytes)].filter(Boolean).join(' · ')
  };
}

function attachmentCard(model, options) {
  const card = document.createElement('button');
  card.type = 'button';
  card.className = 'conversation-attachment';
  card.setAttribute('data-testid', 'genomi-conversation-attachment');
  const name = document.createElement('strong');
  name.textContent = model.name;
  card.append(name);
  if (model.detail) {
    const detail = document.createElement('span');
    detail.textContent = model.detail;
    card.append(detail);
  }
  card.setAttribute('aria-label', 'Open ' + model.name);
  card.addEventListener('click', () => {
    if (typeof options.onOpenAttachment === 'function') options.onOpenAttachment(model.id);
  });
  return card;
}

function readableKind(contentType, artifact) {
  const name = text(artifact && artifact.title).toLowerCase();
  if (/\.(vcf|vcf\.gz|gvcf|bam|cram|fastq|fq)(\.gz)?$/.test(name)) return 'Genome data file';
  const type = text(contentType).toLowerCase();
  if (type.startsWith('image/')) return 'Image';
  if (type === 'application/pdf' || name.endsWith('.pdf')) return 'PDF document';
  if (type.startsWith('text/') || /\.(md|txt|csv|tsv|json)$/.test(name)) return 'Text record';
  return 'File';
}

function readableSize(bytes) {
  const size = Number(bytes);
  if (!Number.isFinite(size) || size <= 0) return '';
  if (size < 1024) return size + ' B';
  if (size < 1024 * 1024) return Math.round(size / 1024) + ' KB';
  return (size / (1024 * 1024)).toFixed(1) + ' MB';
}

function originFrameId(artifact) {
  const origin = artifact.origin_context && typeof artifact.origin_context === 'object' ? artifact.origin_context : {};
  return text(origin.frame_id);
}

function text(value) {
  return value === null || value === undefined ? '' : String(value).trim();
}
