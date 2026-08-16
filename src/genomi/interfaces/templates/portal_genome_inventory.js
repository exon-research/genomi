import { compactLine } from './portal_format.js';

export function genomeInventoryModel(payload = {}) {
  const genomes = Array.isArray(payload.genomes)
    ? payload.genomes.filter((item) => item && typeof item === 'object').map(genomeItem)
    : [];
  const users = Array.isArray(payload.users)
    ? payload.users.filter((item) => item && typeof item === 'object').map(userItem)
    : [];
  const active = payload.active && typeof payload.active === 'object' ? payload.active : {};
  return {
    status: firstText(payload.status) || 'completed',
    error: firstText(payload.error),
    activeAgiId: firstText(active.agi_id, active.agiId),
    activeUserId: firstText(active.user_id, active.userId),
    genomeCount: genomes.length,
    profileCount: users.length,
    summary: genomes.length
      ? String(genomes.length) + ' genome' + (genomes.length === 1 ? '' : 's') + (users.length ? ' · ' + users.length + ' profile' + (users.length === 1 ? '' : 's') : '')
      : 'No genomes yet',
    genomes,
    users
  };
}

export function renderGenomeInventory(container, payload = {}, options = {}) {
  if (!container) return;
  const model = genomeInventoryModel(payload);
  container.innerHTML = '';
  container.hidden = false;
  container.setAttribute('data-testid', 'genomi-genome-inventory');
  container.appendChild(inventoryHead(model, options));
  if (model.status === 'error') {
    container.appendChild(errorState(model, options));
    return;
  }
  if (!model.genomes.length) {
    container.appendChild(emptyState(options));
    return;
  }
  const list = document.createElement('div');
  list.className = 'genome-inventory-list';
  model.genomes.forEach((item) => list.appendChild(genomeRow(item, options)));
  container.appendChild(list);
}

export function activeGenomeHeaderModel(payload = {}, fallback = {}) {
  const model = genomeInventoryModel(payload);
  const active = activeGenomeItem(model);
  if (active) {
    return headerWithControls({
      status: active.queryReady ? 'ready' : 'needs_rebuild',
      title: activeHeaderTitle(active),
      subtitle: active.queryReady
        ? activeHeaderSubtitle(active, model)
        : 'This genome needs rebuilding before it can be used. Open to choose another ready genome or add the source again.',
      activeAgiId: active.agiId,
      activeUserId: active.userId
    }, model);
  }
  if (model.status === 'error') {
    return headerWithControls({
      status: fallback.status || 'pending',
      title: usefulFallbackTitle(fallback) || 'Genome list unavailable',
      subtitle: model.error || usefulFallbackSubtitle(fallback) || 'Open Active genome to add or switch genomes'
    }, model);
  }
  if (model.activeAgiId) {
    return headerWithControls({
      status: 'ready',
      title: usefulFallbackTitle(fallback) || genomeIdTitle(model.activeAgiId),
      subtitle: usefulFallbackSubtitle(fallback) || 'Open to inspect, switch, or add genomes',
      activeAgiId: model.activeAgiId,
      activeUserId: model.activeUserId
    }, model);
  }
  if (model.genomes.length) {
    return headerWithControls({
      status: fallback.status || 'pending',
      title: 'Choose a genome',
      subtitle: model.summary
    }, model);
  }
  return headerWithControls({
    status: fallback.status || 'empty',
    title: usefulFallbackTitle(fallback) || 'No genome loaded',
    subtitle: usefulFallbackSubtitle(fallback) || 'Add a genome to use genome-aware evidence'
  }, model);
}

export function inquiryGenomeStateLabel(header = {}) {
  const title = firstText(header.displayTitle, header.title) || 'Active genome';
  if (header.status === 'ready') return title + ' selected.';
  if (header.status === 'needs_rebuild') {
    return title + ' needs rebuilding; choose another ready genome or add the source again.';
  }
  return 'Choose an active genome for this workspace.';
}

function inventoryHead(model, options) {
  const head = document.createElement('div');
  head.className = 'genome-inventory-head';
  head.innerHTML = '<div><strong></strong><span></span></div><button type="button" class="secondary"></button>';
  head.querySelector('strong').textContent = 'Available genomes';
  head.querySelector('span').textContent = model.summary;
  const button = head.querySelector('button');
  button.textContent = 'Add genome';
  button.addEventListener('click', () => {
    if (typeof options.onAddGenome === 'function') options.onAddGenome();
  });
  return head;
}

function emptyState(options) {
  const empty = document.createElement('div');
  empty.className = 'genome-inventory-empty';
  empty.innerHTML = '<strong></strong><span></span><button type="button" class="secondary"></button>';
  empty.querySelector('strong').textContent = 'No genomes available';
  empty.querySelector('span').textContent = 'Add a local genome source to make genome-aware evidence available in this workspace.';
  const button = empty.querySelector('button');
  button.textContent = 'Add genome';
  button.addEventListener('click', () => {
    if (typeof options.onAddGenome === 'function') options.onAddGenome();
  });
  return empty;
}

function errorState(model, options) {
  const empty = document.createElement('div');
  empty.className = 'genome-inventory-empty warning';
  empty.innerHTML = '<strong></strong><span></span><button type="button" class="secondary"></button>';
  empty.querySelector('strong').textContent = 'Genome list unavailable';
  empty.querySelector('span').textContent = model.error || 'Refresh Genomi or add a genome source.';
  const button = empty.querySelector('button');
  button.textContent = 'Add genome';
  button.addEventListener('click', () => {
    if (typeof options.onAddGenome === 'function') options.onAddGenome();
  });
  return empty;
}

function genomeRow(item, options) {
  const row = document.createElement('div');
  row.className = 'genome-inventory-row' + (item.active ? ' active' : '');
  row.setAttribute('data-testid', 'genomi-genome-inventory-row');
  row.dataset.agiId = item.agiId;
  row.innerHTML = [
    '<div class="genome-inventory-main">',
    '<strong></strong>',
    '<span></span>',
    '<div class="genome-inventory-badges"></div>',
    '</div>',
    '<div class="genome-inventory-actions"></div>'
  ].join('');
  row.querySelector('strong').textContent = item.title;
  row.querySelector('span').textContent = item.summary;
  const badges = row.querySelector('.genome-inventory-badges');
  item.badges.forEach((badge) => {
    const el = document.createElement('em');
    el.textContent = badge;
    badges.appendChild(el);
  });
  const actions = row.querySelector('.genome-inventory-actions');
  if (!item.queryReady) {
    const state = document.createElement('span');
    state.className = 'genome-inventory-current warning';
    state.textContent = item.readinessText || 'Not ready';
    actions.appendChild(state);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = 'Add source to rebuild';
    button.setAttribute('data-testid', 'genomi-genome-rebuild');
    button.addEventListener('click', () => {
      if (typeof options.onAddGenome === 'function') options.onAddGenome();
    });
    actions.appendChild(button);
  } else if (item.active) {
    const current = document.createElement('span');
    current.className = 'genome-inventory-current';
    current.textContent = 'Current';
    actions.appendChild(current);
  } else {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tool-action';
    button.textContent = 'Use this genome';
    button.setAttribute('data-testid', 'genomi-genome-select');
    button.addEventListener('click', () => {
      if (typeof options.onSelectGenome === 'function') options.onSelectGenome(selectionFor(item));
    });
    actions.appendChild(button);
  }
  return row;
}

function genomeItem(item) {
  const users = Array.isArray(item.users) ? item.users.filter((user) => user && typeof user === 'object').map(userItem) : [];
  const readiness = item.readiness && typeof item.readiness === 'object' ? item.readiness : {};
  const source = item.source && typeof item.source === 'object' ? item.source : {};
  const agiId = firstText(item.agi_id, item.agiId);
  const sourceLabel = sourceDisplayLabel(firstText(source.format, source.kind, source.provider));
  const readinessStatus = firstText(readiness.status);
  const readinessText = readinessLabel(readinessStatus || (readiness.complete ? 'completed' : ''));
  const build = firstText(item.genome_build, item.genomeBuild);
  const rawDisplayName = firstText(item.display_name, item.displayName, item.sample_slug, item.sampleSlug);
  const displayName = isGenericReadyTitle(rawDisplayName) ? '' : rawDisplayName;
  const profileNames = users.map((user) => user.nickname).filter(Boolean);
  const summary = [
    build,
    sourceLabel,
    profileNames.length ? 'Profile: ' + profileNames.join(', ') : ''
  ].filter(Boolean).join(' · ');
  return {
    agiId,
    build,
    sourceLabel,
    readinessText,
    shortId: shortIdentifier(agiId),
    queryReady: genomeQueryReady(readinessStatus, readiness),
    title: displayName || genomeIdTitle(agiId) || 'Genome',
    active: Boolean(item.active),
    userId: firstText(users.find((user) => user.active)?.userId, users[0]?.userId),
    nickname: firstText(users.find((user) => user.active)?.nickname, users[0]?.nickname),
    summary: summary || 'Genome metadata available',
    badges: [
      build,
      sourceLabel,
      readinessText
    ].filter(Boolean).map((value) => compactLine(value, 36))
  };
}

function activeGenomeItem(model) {
  if (!model || !Array.isArray(model.genomes)) return null;
  return model.genomes.find((item) => item.active)
    || model.genomes.find((item) => item.agiId && item.agiId === model.activeAgiId)
    || null;
}

function headerWithControls(header, model) {
  const genomeCount = model && Number.isFinite(Number(model.genomeCount)) ? Number(model.genomeCount) : 0;
  const normalizedHeader = {
    ...header,
    title: safeHeaderTitle(header)
  };
  const hasActiveGenome = Boolean(normalizedHeader.activeAgiId);
  const canSwitch = genomeCount > 0 || hasActiveGenome;
  const switchLabel = hasActiveGenome ? 'Switch' : (genomeCount > 0 ? 'Choose' : '');
  const displayTitle = headerDisplayTitle(normalizedHeader);
  return {
    ...normalizedHeader,
    displayTitle,
    genomeCount,
    canSwitch,
    switchLabel,
    addLabel: 'Add genome',
    actionLabel: canSwitch
      ? switchLabel + ' active genome or add a genome'
      : 'Add a genome'
  };
}

function safeHeaderTitle(header) {
  const title = firstText(header && header.title);
  if (!isGenericReadyTitle(title)) return title || 'Active genome';
  const activeAgiId = firstText(header && header.activeAgiId);
  const idTitle = genomeIdTitle(activeAgiId);
  if (idTitle) return idTitle;
  if (header && header.status === 'ready') return 'Active genome selected';
  return 'Active genome';
}

function headerDisplayTitle(header) {
  const title = firstText(header && header.title) || 'Active genome';
  if (/^active\s+genome\s*:/i.test(title)) return title;
  if (header && (header.activeAgiId || (header.status === 'ready' && isGenomeIdentityTitle(title)))) return 'Active genome: ' + title;
  return title;
}

function isGenomeIdentityTitle(title) {
  return !/^(active\s+genome|choose\s+active\s+genome|no\s+genome\s+loaded|genome\s+list\s+unavailable|genome\s+access\s+requires\s+approval|genome\s+still\s+building|genome\s+readiness\s+unknown)$/i.test(firstText(title));
}

function activeHeaderTitle(item) {
  const title = firstText(item.title);
  const summary = [item.build, item.sourceLabel].filter(Boolean).join(' · ');
  const generatedShortTitle = item.shortId && title === 'Genome ' + item.shortId;
  if (title && title !== 'Genome' && !generatedShortTitle && !isGenericReadyTitle(title)) return title;
  if (summary) return summary + ' genome';
  if (item.shortId) return genomeIdTitle(item.shortId);
  return 'Active genome';
}

function activeHeaderSubtitle(item, model) {
  const title = activeHeaderTitle(item);
  const parts = [];
  if (item.summary && item.summary !== title && item.summary !== title.replace(/ genome$/, '')) {
    parts.push(item.summary);
  }
  if (model && model.genomeCount > 1) {
    parts.push(String(model.genomeCount) + ' genomes available');
  }
  parts.push('Open to switch or add genomes');
  return parts.filter(Boolean).join(' · ');
}

function usefulFallbackTitle(fallback) {
  const title = firstText(fallback && fallback.title);
  if (title && !isGenericReadyTitle(title)) return title;
  return fallbackIdentityTitle(fallback);
}

function usefulFallbackSubtitle(fallback) {
  return visibleGenomeIdentityLine(firstText(
    fallback && fallback.identity && fallback.identity.subtitle,
    fallback && fallback.subtitle
  ));
}

function fallbackIdentityTitle(fallback) {
  const identity = fallback && fallback.identity && typeof fallback.identity === 'object' ? fallback.identity : {};
  const displayName = firstText(identity.displayName, identity.display_name);
  if (displayName && !isGenericReadyTitle(displayName)) return displayName;
  const summary = visibleGenomeIdentityLine(firstText(identity.summaryLabel, identity.summary_label));
  if (summary) return summary + ' genome';
  const parts = [
    firstText(identity.build),
    firstText(identity.sourceLabel, identity.source_label)
  ].filter(Boolean).join(' · ');
  if (parts) return parts + ' genome';
  const shortId = firstText(identity.shortId, identity.short_id);
  if (shortId) return genomeIdTitle(shortId);
  return '';
}

function visibleGenomeIdentityLine(value) {
  const text = firstText(value);
  if (!text) return '';
  return text
    .split(/\s+·\s+/)
    .map((part) => part.trim())
    .filter((part) => part && !isReadinessOnlyLabel(part))
    .join(' · ');
}

function isReadinessOnlyLabel(value) {
  return /^(query[-\s]?ready|complete|completed|ready|not ready|in progress|pending)$/i.test(firstText(value));
}

function isGenericReadyTitle(value) {
  return /^(genome\s+ready|active\s+genome|genome\s+accessible)$/i.test(firstText(value));
}

function userItem(item) {
  return {
    userId: firstText(item.user_id, item.userId),
    nickname: firstText(item.nickname),
    default: Boolean(item.default),
    active: Boolean(item.active),
    activeAgiId: firstText(item.active_agi_id, item.activeAgiId),
    genomeCount: Number(item.genome_count || item.genomeCount || 0)
  };
}

function selectionFor(item) {
  if (item.userId) return { userId: item.userId, agiId: item.agiId };
  if (item.nickname) return { nickname: item.nickname, agiId: item.agiId };
  return { agiId: item.agiId };
}

function readinessLabel(value) {
  const clean = firstText(value).toLowerCase().replace(/[\s-]+/g, '_');
  if (/^(complete|completed|query_ready|ready)$/.test(clean)) return 'Ready';
  if (/^(building|in_progress|pending)$/.test(clean)) return 'Building';
  if (/^(needs_reparse|needs_rebuild|incomplete|stale)$/.test(clean)) return 'Needs rebuild';
  return clean ? 'Not ready' : 'Readiness unknown';
}

function genomeQueryReady(status, readiness) {
  const clean = firstText(status).toLowerCase().replace(/[\s-]+/g, '_');
  return Boolean(
    readiness
    && readiness.complete === true
    && readiness.snapshot_bound === true
    && /^(complete|completed|query_ready|ready)$/.test(clean)
  );
}

function sourceDisplayLabel(value) {
  const original = firstText(value);
  const clean = original.toLowerCase().replace(/[\s_-]+/g, '');
  if (!clean) return '';
  if (clean === 'vcf') return 'VCF';
  if (clean === 'gvcf') return 'gVCF';
  if (clean === '23andme') return '23andMe';
  if (clean === 'genome') return 'Genome bundle';
  if (clean === 'localpath') return 'Local source';
  return original.replace(/_/g, ' ');
}

function shortIdentifier(value) {
  const clean = firstText(value);
  if (!clean) return '';
  return clean.length > 14 ? clean.slice(0, 10) + '...' : clean;
}

function genomeIdTitle(value) {
  const shortId = shortIdentifier(value);
  if (!shortId) return '';
  if (/^(genome|vcf|gvcf|23andme)[-_]/i.test(shortId)) return shortId;
  return 'Genome ' + shortId;
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}
