"use strict";

import {
  array,
  elements,
  empty,
  friendly,
  isObject,
  node,
  text,
} from "./render-dom.js";

export function specialistBoardPresentation(boardValue, roundValue) {
  const board = isObject(boardValue) ? boardValue : null;
  const currentRound = board && isObject(roundValue) ? roundValue : null;
  const memberValues = currentRound && Array.isArray(currentRound.members)
    ? currentRound.members
    : board && board.members;
  const members = board
    ? array(memberValues).filter(isObject).map(specialistMemberPresentation)
    : [];
  const status = safeText(currentRound && currentRound.status)
    || safeText(board && board.status);
  const beforeFormation = !members.length
    && ["", "not_formed", "not_started"].includes(status.toLowerCase());
  return {
    visible: Boolean(board && !beforeFormation),
    statusLabel: boardStatusLabel(status, members.length),
    chairBoundary: boardChairBoundary(board),
    currentRound: currentRoundPresentation(currentRound),
    members,
  };
}

export function renderSpecialistBoard(boardValue, roundValue) {
  const presentation = specialistBoardPresentation(boardValue, roundValue);
  elements.specialistBoard.hidden = !presentation.visible;
  elements.specialistBoardStatus.textContent = presentation.statusLabel;
  const chairCopy = node("span", presentation.chairBoundary, "specialist-chair-copy");
  const chairContent = [chairCopy];
  if (presentation.currentRound) {
    const roundContext = node("span", "", "specialist-round-context");
    roundContext.append(
      node("span", presentation.currentRound.label, "specialist-round-number"),
      node("span", presentation.currentRound.focusQuestion, "specialist-round-focus")
    );
    chairContent.push(roundContext);
  }
  elements.specialistBoardChair.replaceChildren(...chairContent);
  if (!presentation.visible) {
    elements.specialistBoardList.replaceChildren(
      empty("The specialist board has not been formed.")
    );
    return;
  }
  if (!presentation.members.length) {
    elements.specialistBoardList.replaceChildren(
      empty("The board is forming; specialist assignments will appear here.")
    );
    return;
  }
  elements.specialistBoardList.replaceChildren(...presentation.members.map((member) => {
    const item = node("li", "", "specialist-board-member");
    const heading = node("div", "", "specialist-member-heading");
    const identity = document.createElement("div");
    identity.append(
      node("strong", member.role),
      node("span", member.specialistId || "Specialist agent", "specialist-identity")
    );
    heading.append(
      identity,
      node("span", friendly(member.status) || "Assigned", "specialist-status")
    );
    item.append(
      heading,
      node("p", member.currentWork, "specialist-current-work"),
      node("span", `Assignment: ${member.task}`, "specialist-task")
    );
    if (member.report) item.append(renderSpecialistReport(member.report));
    return item;
  }));
}

function specialistMemberPresentation(member) {
  const status = safeText(member.status);
  const completed = status.toLowerCase() === "completed";
  return {
    specialistId: safeText(member.specialist_id),
    role: safeText(member.role) || "Domain specialist",
    task: safeText(member.task) || "Assignment pending",
    status,
    currentWork: safeText(member.current_work)
      || (completed
        ? "Completed the assigned work."
        : "Waiting to begin the assigned work."),
    report: completed ? specialistReportPresentation(member.report) : null,
  };
}

function currentRoundPresentation(currentRound) {
  if (!currentRound) return null;
  const roundNumber = safeRoundNumber(currentRound.round_number);
  return {
    label: roundNumber ? `Round ${roundNumber}` : "Current round",
    focusQuestion: safeText(currentRound.focus_question)
      || "Focus question unavailable.",
  };
}

function specialistReportPresentation(reportValue) {
  const reportRecord = isObject(reportValue) ? reportValue : null;
  const report = reportRecord && isObject(reportRecord.report)
    ? reportRecord.report
    : null;
  if (!report) return null;
  const anchoredFindings = array(report.findings)
    .filter(isObject)
    .map((finding) => {
      const evidenceAnchorCount = anchorCount(finding.evidence_record_ids);
      const profileAnchorCount = anchorCount(finding.profile_revision_ids);
      return {
        statement: safeText(finding.statement),
        stance: safeText(finding.stance),
        anchorLabel: anchorLabel(evidenceAnchorCount, profileAnchorCount),
      };
    })
    .filter((finding) => finding.statement && finding.anchorLabel);
  const openGaps = array(report.gaps)
    .filter(isObject)
    .map((gap) => ({
      question: safeText(gap.question),
      anchorLabel: anchorLabel(
        anchorCount(gap.evidence_record_ids),
        anchorCount(gap.profile_revision_ids)
      ),
    }))
    .filter((gap) => gap.question);
  return {anchoredFindings, openGaps};
}

function renderSpecialistReport(report) {
  const section = node("section", "", "specialist-report");
  section.append(
    node("h4", "Completed report", "specialist-report-heading"),
    renderReportItems({
      label: "Anchored findings",
      emptyLabel: "No anchored findings reported.",
      items: report.anchoredFindings,
      itemText: (item) => item.statement,
      itemMeta: (item) => [friendly(item.stance), item.anchorLabel]
        .filter(Boolean)
        .join(" · "),
    }),
    renderReportItems({
      label: "Open gaps",
      emptyLabel: "No open gaps reported.",
      items: report.openGaps,
      itemText: (item) => item.question,
      itemMeta: (item) => item.anchorLabel,
    })
  );
  return section;
}

function renderReportItems({label, emptyLabel, items, itemText, itemMeta}) {
  const group = node("div", "", "specialist-report-group");
  group.append(node("h5", label));
  if (!items.length) {
    group.append(node("p", emptyLabel, "specialist-report-empty"));
    return group;
  }
  const list = node("ul", "", "specialist-report-list");
  list.append(...items.map((item) => {
    const row = node("li", "", "specialist-report-item");
    row.append(node("p", itemText(item)));
    const meta = itemMeta(item);
    if (meta) row.append(node("span", meta, "specialist-report-meta"));
    return row;
  }));
  group.append(list);
  return group;
}

function anchorCount(value) {
  return array(value).filter((item) => safeText(item)).length;
}

function anchorLabel(evidenceCount, profileCount) {
  const anchors = [];
  if (evidenceCount) {
    anchors.push(`${evidenceCount} evidence ${evidenceCount === 1 ? "record" : "records"}`);
  }
  if (profileCount) {
    anchors.push(`${profileCount} profile ${profileCount === 1 ? "revision" : "revisions"}`);
  }
  return anchors.length ? `Anchored to ${anchors.join(" and ")}` : "";
}

function safeRoundNumber(value) {
  if (typeof value === "number" && Number.isSafeInteger(value) && value > 0) {
    return String(value);
  }
  if (typeof value === "string" && /^[1-9]\d*$/.test(value.trim())) {
    return value.trim();
  }
  return "";
}

function safeText(value) {
  return typeof value === "string" || typeof value === "number"
    ? text(value).trim()
    : "";
}

function boardChairBoundary(board) {
  const chair = board && isObject(board.chair) ? board.chair : {};
  if (
    text(chair.role) === "main_agent"
    && text(chair.responsibility) === "patient_interaction_and_active_genome_index_context_owner"
  ) {
    return "The main agent is board chair and owns patient interaction and Active Genome Index context. Specialists receive scoped roles and assignments; this view only monitors their work.";
  }
  return "The main agent remains board chair and the Active Genome Index context owner. Specialists receive scoped roles and assignments; this view only monitors their work.";
}

function boardStatusLabel(status, memberCount) {
  switch (status.toLowerCase()) {
    case "forming":
      return "Board forming";
    case "formed":
    case "planned":
      return "Board formed";
    case "active":
    case "in_progress":
    case "working":
      return "Board working";
    case "blocked":
      return "Board blocked";
    case "complete":
    case "completed":
      return "Board completed";
    default:
      return friendly(status) || (memberCount ? "Board formed" : "Not formed");
  }
}
