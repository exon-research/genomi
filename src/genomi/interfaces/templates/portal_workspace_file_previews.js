const maxTablePreviewRows = 50;
const maxTablePreviewColumns = 16;

export function workspaceFilePreviewContentElement(model) {
  if (model.status === 'loading') {
    return workspaceFilePreviewNotice('Loading preview...');
  }
  if (model.status === 'error') {
    return workspaceFilePreviewNotice(model.reason || 'Preview failed.');
  }
  if (model.previewKind === 'text' && model.fileKind === 'markdown') {
    return markdownFilePreviewElement(model);
  }
  if (model.previewKind === 'text' && model.fileKind === 'table') {
    return tableFilePreviewElement(model);
  }
  if (model.previewKind === 'text') {
    return textFilePreviewElement(model);
  }
  if (model.previewKind === 'image' && model.dataUrl) {
    const image = document.createElement('img');
    image.alt = model.name;
    image.src = model.dataUrl;
    return image;
  }
  if (model.previewKind === 'document' && model.documentUrl) {
    return documentFilePreviewElement(model);
  }
  if (model.previewKind === 'notebook' && model.notebook) {
    return notebookFilePreviewElement(model);
  }
  return workspaceFilePreviewNotice(model.reason || 'Preview unavailable for this file.');
}

function workspaceFilePreviewNotice(message) {
  const notice = document.createElement('div');
  notice.className = 'workspace-file-preview-notice';
  notice.textContent = message;
  return notice;
}

function textFilePreviewElement(model) {
  const pre = document.createElement('pre');
  pre.className = 'workspace-file-text-preview file-kind-' + model.fileKind;
  pre.textContent = model.text || '';
  return pre;
}

function documentFilePreviewElement(model) {
  const shell = document.createElement('div');
  shell.className = 'workspace-file-document-preview';
  shell.setAttribute('data-testid', 'genomi-workspace-file-document-preview');
  const iframe = document.createElement('iframe');
  iframe.title = model.name + ' document preview';
  iframe.src = model.documentUrl;
  iframe.loading = 'lazy';
  iframe.referrerPolicy = 'no-referrer';
  iframe.setAttribute('data-testid', 'genomi-workspace-file-document-frame');
  shell.appendChild(iframe);
  return shell;
}

function notebookFilePreviewElement(model) {
  const notebook = model.notebook || {};
  const shell = document.createElement('div');
  shell.className = 'workspace-file-notebook-preview';
  shell.setAttribute('data-testid', 'genomi-workspace-file-notebook-preview');
  const summary = document.createElement('div');
  summary.className = 'workspace-file-notebook-summary';
  summary.innerHTML = '<strong></strong><span></span>';
  summary.querySelector('strong').textContent = notebook.summary || 'Notebook record';
  summary.querySelector('span').textContent = notebook.truncated
    ? 'Showing ' + String(notebook.shownCellCount || 0) + ' of ' + String(notebook.cellCount || 0) + ' cells'
    : 'All cells shown';
  shell.appendChild(summary);
  if (!Array.isArray(notebook.cells) || !notebook.cells.length) {
    shell.appendChild(workspaceFilePreviewNotice('No notebook cells found.'));
    return shell;
  }
  const cells = document.createElement('div');
  cells.className = 'workspace-file-notebook-cells';
  notebook.cells.forEach((cell) => cells.appendChild(notebookCellElement(cell)));
  shell.appendChild(cells);
  return shell;
}

function notebookCellElement(cell) {
  const item = document.createElement('section');
  item.className = 'workspace-file-notebook-cell cell-type-' + cell.type;
  item.setAttribute('data-testid', 'genomi-workspace-file-notebook-cell');
  item.innerHTML = '<header><strong></strong><span></span></header><pre></pre>';
  item.querySelector('strong').textContent = notebookCellLabel(cell);
  item.querySelector('span').textContent = [
    cell.lineCount ? String(cell.lineCount) + ' line' + (cell.lineCount === 1 ? '' : 's') : '',
    cell.outputCount ? String(cell.outputCount) + ' output' + (cell.outputCount === 1 ? '' : 's') : '',
    cell.truncated ? 'truncated' : ''
  ].filter(Boolean).join(' · ');
  item.querySelector('pre').textContent = cell.source || '';
  return item;
}

export function markdownFilePreviewElement(model) {
  return markdownContentElement(model.text || '', {
    className: 'workspace-file-markdown-preview',
    testId: 'genomi-workspace-file-markdown-preview'
  });
}

export function markdownContentElement(text, options = {}) {
  const article = document.createElement('article');
  article.className = String(options.className || 'markdown-content');
  if (options.testId) article.setAttribute('data-testid', String(options.testId));
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  let paragraph = [];
  let list = null;
  let codeLines = null;
  let codeLanguage = '';

  function flushParagraph() {
    if (!paragraph.length) return;
    const p = document.createElement('p');
    appendInlineMarkdown(p, paragraph.join(' '));
    article.appendChild(p);
    paragraph = [];
  }

  function flushList() {
    if (!list) return;
    article.appendChild(list);
    list = null;
  }

  function flushCode() {
    if (!codeLines) return;
    const pre = document.createElement('pre');
    pre.className = 'workspace-file-markdown-code';
    const code = document.createElement('code');
    if (codeLanguage) code.setAttribute('data-language', codeLanguage);
    code.textContent = codeLines.join('\n');
    pre.appendChild(code);
    article.appendChild(pre);
    codeLines = null;
    codeLanguage = '';
  }

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
    const fence = line.match(/^```([\w.+-]*)\s*$/);
    if (fence) {
      if (codeLines) {
        flushCode();
      } else {
        flushParagraph();
        flushList();
        codeLines = [];
        codeLanguage = fence[1] || '';
      }
      continue;
    }
    if (codeLines) {
      codeLines.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    if (markdownTableStartsAt(lines, lineIndex)) {
      flushParagraph();
      flushList();
      const tableResult = markdownTableElement(lines, lineIndex);
      article.appendChild(tableResult.element);
      lineIndex = tableResult.lastLineIndex;
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(4, heading[1].length + 1);
      const h = document.createElement('h' + String(level));
      appendInlineMarkdown(h, heading[2]);
      article.appendChild(h);
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      if (list && list.tagName !== 'ul') flushList();
      if (!list) list = document.createElement('ul');
      const li = document.createElement('li');
      appendInlineMarkdown(li, bullet[1]);
      list.appendChild(li);
      continue;
    }
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      if (list && list.tagName !== 'ol') flushList();
      if (!list) list = document.createElement('ol');
      const li = document.createElement('li');
      appendInlineMarkdown(li, ordered[1]);
      list.appendChild(li);
      continue;
    }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      flushList();
      const blockquote = document.createElement('blockquote');
      appendInlineMarkdown(blockquote, quote[1]);
      article.appendChild(blockquote);
      continue;
    }
    paragraph.push(line.trim());
  }
  flushParagraph();
  flushList();
  flushCode();
  return article;
}

function markdownTableStartsAt(lines, index) {
  if (index + 1 >= lines.length || !String(lines[index] || '').includes('|')) return false;
  const separatorCells = markdownTableCells(lines[index + 1]);
  return separatorCells.length > 0 && separatorCells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function markdownTableElement(lines, startIndex) {
  const wrapper = document.createElement('div');
  wrapper.className = 'workspace-file-markdown-table';
  const table = document.createElement('table');
  const headers = markdownTableCells(lines[startIndex]);
  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  headers.forEach((header) => {
    const th = document.createElement('th');
    appendInlineMarkdown(th, header);
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  let lineIndex = startIndex + 2;
  while (lineIndex < lines.length && String(lines[lineIndex] || '').includes('|') && String(lines[lineIndex] || '').trim()) {
    const values = markdownTableCells(lines[lineIndex]);
    const row = document.createElement('tr');
    headers.forEach((_header, columnIndex) => {
      const td = document.createElement('td');
      appendInlineMarkdown(td, values[columnIndex] || '');
      row.appendChild(td);
    });
    tbody.appendChild(row);
    lineIndex += 1;
  }
  table.appendChild(tbody);
  wrapper.appendChild(table);
  return { element: wrapper, lastLineIndex: lineIndex - 1 };
}

function markdownTableCells(line) {
  const clean = String(line || '').trim().replace(/^\|/, '').replace(/\|$/, '');
  return clean.split('|').map((cell) => cell.trim()).filter((cell, index, cells) => cell || cells.length > 1 || index === 0);
}

function tableFilePreviewElement(model) {
  const shell = document.createElement('div');
  shell.className = 'workspace-file-table-preview';
  shell.setAttribute('data-testid', 'genomi-workspace-file-table-preview');
  const rows = parseDelimitedRows(model.text || '', tableDelimiter(model));
  const headers = rows.length ? rows[0] : [];
  const bodyRows = rows.slice(1);
  const visibleHeaders = headers.slice(0, maxTablePreviewColumns);
  const visibleRows = bodyRows.slice(0, maxTablePreviewRows);
  const summary = document.createElement('div');
  summary.className = 'workspace-file-table-summary';
  summary.textContent = tablePreviewSummary(rows, headers);
  shell.appendChild(summary);
  if (!rows.length || !headers.length) {
    shell.appendChild(workspaceFilePreviewNotice('No table rows found in this file.'));
    return shell;
  }
  const table = document.createElement('table');
  const thead = document.createElement('thead');
  const tr = document.createElement('tr');
  visibleHeaders.forEach((header, index) => {
    const th = document.createElement('th');
    th.textContent = header || 'Column ' + String(index + 1);
    tr.appendChild(th);
  });
  thead.appendChild(tr);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  visibleRows.forEach((row) => {
    const bodyTr = document.createElement('tr');
    visibleHeaders.forEach((_header, index) => {
      const td = document.createElement('td');
      td.textContent = row[index] || '';
      bodyTr.appendChild(td);
    });
    tbody.appendChild(bodyTr);
  });
  table.appendChild(tbody);
  shell.appendChild(table);
  if (bodyRows.length > visibleRows.length || headers.length > visibleHeaders.length) {
    const note = document.createElement('p');
    note.className = 'workspace-file-table-limit';
    note.textContent = 'Preview limited to ' + String(visibleRows.length) + ' rows and ' + String(visibleHeaders.length) + ' columns.';
    shell.appendChild(note);
  }
  return shell;
}

function tablePreviewSummary(rows, headers) {
  if (!rows.length) return 'No rows';
  const dataRows = Math.max(0, rows.length - 1);
  const columns = headers.length;
  return String(dataRows) + ' data row' + (dataRows === 1 ? '' : 's') + ' · ' + String(columns) + ' column' + (columns === 1 ? '' : 's');
}

function tableDelimiter(model) {
  const contentType = String(model && model.contentType || '').toLowerCase();
  const path = String(model && (model.path || model.name) || '').toLowerCase();
  return contentType === 'text/tab-separated-values' || path.endsWith('.tsv') ? '\t' : ',';
}

function parseDelimitedRows(text, delimiter) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  const value = String(text || '').replace(/\r\n?/g, '\n');
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    if (inQuotes) {
      if (char === '"') {
        if (value[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
      continue;
    }
    if (char === '"') {
      inQuotes = true;
      continue;
    }
    if (char === delimiter) {
      row.push(field);
      field = '';
      continue;
    }
    if (char === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
      continue;
    }
    field += char;
  }
  row.push(field);
  rows.push(row);
  return rows.filter((candidate, index) => {
    if (index === rows.length - 1 && candidate.length === 1 && !candidate[0]) return false;
    return candidate.some((cell) => String(cell || '').trim());
  });
}

function appendInlineMarkdown(parent, text) {
  const pattern = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`|\[[^\]]+\]\(([^)]+)\))/g;
  let cursor = 0;
  let match;
  const value = String(text || '');
  while ((match = pattern.exec(value))) {
    appendPlainText(parent, value.slice(cursor, match.index));
    const token = match[0];
    if (token.startsWith('`')) {
      const code = document.createElement('code');
      code.textContent = token.slice(1, -1);
      parent.appendChild(code);
    } else if (token.startsWith('**') || token.startsWith('__')) {
      const strong = document.createElement('strong');
      strong.textContent = token.slice(2, -2);
      parent.appendChild(strong);
    } else if (token.startsWith('*') || token.startsWith('_')) {
      const emphasis = document.createElement('em');
      emphasis.textContent = token.slice(1, -1);
      parent.appendChild(emphasis);
    } else {
      const parsed = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const href = safeMarkdownHref(parsed && parsed[2]);
      if (href) {
        const link = document.createElement('a');
        link.href = href;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = parsed[1];
        parent.appendChild(link);
      } else {
        appendPlainText(parent, parsed ? parsed[1] : token);
      }
    }
    cursor = match.index + token.length;
  }
  appendPlainText(parent, value.slice(cursor));
}

function appendPlainText(parent, text) {
  if (!text) return;
  const span = document.createElement('span');
  span.textContent = text;
  parent.appendChild(span);
}

function safeMarkdownHref(value) {
  const href = firstText(value);
  if (!href || /^(javascript|data|file):/i.test(href)) return '';
  if (/^(?:~|\/Users|\/home|\/tmp|\/private|\/var\/folders|\/Volumes)\b/i.test(href)) return '';
  if (/^(https?:|mailto:)/i.test(href)) return href;
  if (/^[./#?A-Za-z0-9_-]/.test(href)) return href;
  return '';
}

function notebookCellLabel(cell) {
  const type = String(cell && cell.type || 'cell').replace(/_/g, ' ');
  const label = type.slice(0, 1).toUpperCase() + type.slice(1);
  return label + ' cell ' + String(cell && cell.index || '');
}

function firstText(...values) {
  for (const value of values) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}
