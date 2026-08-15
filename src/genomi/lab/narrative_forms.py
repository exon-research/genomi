"""Closed-vocabulary forms for patient-visible research narrative."""

from __future__ import annotations

import re

_RESEARCH_OPERATION_VERBS = {
    "add",
    "assess",
    "avoid",
    "begin",
    "bind",
    "check",
    "clarify",
    "compare",
    "confirm",
    "continue",
    "create",
    "curate",
    "evaluate",
    "extract",
    "ground",
    "investigate",
    "keep",
    "link",
    "preserve",
    "project",
    "propose",
    "record",
    "register",
    "resolve",
    "retrieve",
    "review",
    "search",
    "synthesize",
    "use",
    "validate",
    "verify",
}
_RESEARCH_OPERATION_WORDS = _RESEARCH_OPERATION_VERBS | {
    "a",
    "about",
    "against",
    "all",
    "an",
    "and",
    "answer",
    "answers",
    "anchor",
    "anchored",
    "anchors",
    "approved",
    "association",
    "associations",
    "available",
    "before",
    "bounded",
    "by",
    "candidate",
    "candidates",
    "can",
    "cannot",
    "capability",
    "capabilities",
    "categories",
    "cautiously",
    "cited",
    "claim",
    "claims",
    "clinical",
    "clinically",
    "committed",
    "comparison",
    "conclusion",
    "conclusions",
    "confirmed",
    "condition",
    "confirmation",
    "conflict",
    "conflicts",
    "context",
    "coverage",
    "current",
    "data",
    "declared",
    "disease",
    "disease-mechanism",
    "domain",
    "eligible",
    "establish",
    "evidence",
    "exact",
    "exact-scope",
    "exactly",
    "external",
    "facts",
    "finding",
    "findings",
    "focused",
    "for",
    "from",
    "gap",
    "gaps",
    "gene",
    "genome",
    "genomi",
    "genomilab",
    "grounded",
    "guidance",
    "harness",
    "help",
    "hypothesis",
    "hypotheses",
    "identity",
    "immutable",
    "in",
    "independent",
    "inference",
    "information",
    "interpretation",
    "investigation",
    "its",
    "laboratory",
    "limitations",
    "literature",
    "local",
    "mechanism",
    "mechanisms",
    "missing",
    "molecular",
    "needs",
    "new",
    "no",
    "not",
    "observation",
    "observations",
    "of",
    "one",
    "only",
    "open",
    "overlap",
    "original",
    "parameters",
    "patient",
    "patient-approved",
    "personal-genome",
    "pathogenic",
    "phenotype",
    "pinned",
    "plan",
    "possible",
    "prior",
    "private",
    "profile",
    "provenance",
    "provider",
    "public",
    "question",
    "questions",
    "reasoning",
    "record",
    "records",
    "relation",
    "relations",
    "relevance",
    "reported",
    "reviewing",
    "representation",
    "request",
    "requests",
    "required",
    "requirement",
    "requirements",
    "research",
    "resolved",
    "result",
    "results",
    "returned",
    "scope",
    "scoped",
    "separate",
    "separately",
    "separated",
    "slice",
    "source",
    "source-scoped",
    "sourced",
    "sources",
    "step",
    "steps",
    "stream",
    "support",
    "supported",
    "supporting",
    "synthetic",
    "targeted",
    "task",
    "template",
    "the",
    "their",
    "this",
    "through",
    "to",
    "tool",
    "tool-free",
    "traceable",
    "typed",
    "uncertainty",
    "unresolved",
    "unsupported",
    "using",
    "variant",
    "what",
    "whether",
    "while",
    "with",
    "without",
    "workflow",
    "work",
    "yet",
    "become",
    "collapsing",
    "gateway",
    "sending",
    "causes",
    "classification",
    "is",
}
_CHANGE_WORDS = {
    "a",
    "about",
    "added",
    "and",
    "approved",
    "anchors",
    "brief",
    "calls",
    "candidate",
    "capability",
    "clarified",
    "clinically",
    "created",
    "confirmed",
    "current",
    "draft",
    "evidence",
    "friendly",
    "gap",
    "hypothesis",
    "independent",
    "initial",
    "is",
    "it",
    "into",
    "made",
    "no",
    "not",
    "observation",
    "open",
    "patient",
    "prepared",
    "profile",
    "question",
    "reasoning",
    "record",
    "recorded",
    "records",
    "registered",
    "research",
    "research-observation",
    "review",
    "simulated",
    "source",
    "synthesized",
    "the",
    "that",
    "this",
    "three",
    "traceable",
    "updated",
    "using",
    "version",
    "were",
    "with",
    "whether",
}
_WORD_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*|\d+")
_IDENTIFIER_TOKEN = re.compile(
    r"(?:rs\d+|[A-Z][A-Z0-9-]{1,24}|(?:NM|NC|NP)_\d+)",
)

# Patient-visible agent artifacts use a closed vocabulary plus declared
# identifiers. Arbitrary disease, phenotype, and drug names remain available
# in the structured evidence/profile records that claims cite; they are not
# copied into an unconstrained prose slot. A terminal "unknown term" exception
# cannot be made fail-closed because an unknown predicate can have exactly the
# same lexical shape as an unknown entity (for example, after an unanticipated
# connector). Harness prose therefore refers to the reported condition,
# phenotype, finding, or treatment and lets its anchors carry the exact name.

_OBSERVATION_WORDS = {
    "a", "an", "and", "approved", "as", "association", "association-not-causation",
    "between", "both", "bounded", "candidate", "classifies", "classified", "clinical",
    "committable", "computational", "condition", "consulted", "contained", "contains",
    "current", "database", "depth", "derivative", "disease", "eligible", "establishes",
    "evidence", "explicitly", "finding", "findings", "fixture", "for", "found", "from",
    "gene", "genome", "genotype", "germline-panel", "has", "identified", "identifies",
    "identify", "in", "independent", "independently", "inference", "is", "issued", "it", "its", "laboratory", "lacks",
    "labelled", "labeled", "lists", "literature", "lookup", "matching", "model",
    "molecular", "not", "notes", "observation", "of", "only", "output", "panel",
    "paper", "patient", "patient-reported", "phenotype", "possible", "profile", "public", "quality",
    "record", "recorded", "records", "registered", "relation", "report", "reported", "reports",
    "remains", "research", "result", "retaining", "review", "sample", "scope", "scoped", "source",
    "states", "study", "supports", "synthetic", "that", "the", "uncertain", "uncertainty",
    "unestablished-clinical-significance", "variant", "variant-disease", "was", "were",
    "while", "with", "zygosity",
}
_CANDIDATE_WORDS = {
    "a", "agent-authored", "alone", "an", "and", "as", "association", "associated", "be", "become", "bounded", "but", "candidate",
    "are", "causal", "causality", "clinical", "conclusion", "condition", "consulted", "contribute",
    "could", "despite", "diagnosis", "different", "disease-focused", "evidence", "explain", "finding", "for", "further", "gene", "generic",
    "genome", "help", "hypothesis", "in", "inference", "interpretation", "is", "may",
    "lacks", "mechanism", "might", "model", "molecular", "must", "not", "of", "only", "or", "over", "overlap",
    "pathogenic", "patient", "personal", "phenotype", "possible", "present", "profile", "public", "qualify", "record", "recorded",
    "refuting", "registered", "relate", "relation", "remains", "reported", "research", "result", "review",
    "scope", "significance", "slice", "source-grounded", "still", "support", "supports", "tentative", "the", "this", "to", "typed",
    "uncertain", "unestablished", "unpinned", "unresolved", "variant", "was", "were",
}
_COUNTEREVIDENCE_WORDS = {
    "a", "against", "an", "association", "candidate", "contradicts", "counterevidence",
    "disease", "does", "evidence", "explanation", "finding", "issued", "mechanism", "not",
    "interpretation", "public", "record", "relation", "reported", "source", "study", "support", "the", "this", "weighs",
    "weakens",
}
_LIMITATION_WORDS = {
    "a", "actionability", "additional", "alone", "an", "and", "approved", "are", "as",
    "association", "be", "before", "but", "by", "candidate", "causal", "causality", "caused",
    "clinical", "clinically", "committable", "committed", "condition", "confirmation", "confirmed", "conflict",
    "consensus", "consequence", "consistent", "context", "could", "diagnosis", "diagnostic", "directive",
    "decisions", "disease", "does", "draft", "episodes", "establish", "established", "evidence", "finding", "for",
    "further", "gap", "genomilab", "has", "have", "identity", "in", "independent",
    "independently", "inference", "interpretation", "is", "it", "lacks", "link", "mechanism",
    "mistaken", "model", "molecular", "muscle-weakness", "must", "needs", "no", "none", "not", "of",
    "only", "open", "or", "overlap", "pathogenic", "patient", "personal", "phenotype",
    "profile", "proposed", "question", "record", "recorded", "relation", "relevance", "remain", "remains", "report",
    "reported", "required", "requirement", "requires", "research", "result", "review", "scope", "should",
    "significance", "source", "support", "supported", "technical", "testing", "that", "the",
    "this", "to", "treatment", "uncertain", "uncertainty", "unavailable", "unestablished",
    "unknown", "unresolved", "validation", "variant", "verification", "with", "without", "yet",
}
_TITLE_WORDS = {
    "about", "analysis", "assessment", "badge-integrity", "brief", "candidate", "confirmation", "counterevidence",
    "current", "draft", "evidence", "finding", "findings", "host-neutral", "in", "investigation",
    "mechanism", "model", "molecular", "profile", "proposed", "question", "record", "reported",
    "research", "review", "says", "summary", "synthetic", "the", "unsafe", "variant-disease", "what",
}


def _tokens_are_closed(text: str, allowed: set[str]) -> bool:
    tokens = _WORD_TOKEN.findall(text)
    return bool(tokens) and all(
        token.casefold() in allowed
        or token.isdigit()
        or bool(_IDENTIFIER_TOKEN.fullmatch(token))
        for token in tokens
    )


_QUESTION_CAN_COULD = re.compile(
    r"^(?:Can|Could)\s+(?:(?:the|this|that|an?|independent|original|reported|"
    r"molecular|laboratory|clinical|exact|patient(?:'s)?)\s+|rs\d+\s+|"
    r"[A-Z][A-Z0-9-]{1,20}\s+)*"
    r"(?:profile|finding|variant|result|record|report|evidence|testing|allele|"
    r"genotype|condition|phenotype|diagnosis|this)"
    r"(?:\s+and\s+(?:the\s+)?(?:rs\d+\s+)?(?:finding|variant|record|report|"
    r"allele|genotype))*\s+"
    r"(?:help\s+explain|inform|relate\s+to|be\s+(?:independently\s+)?"
    r"(?:reviewed|confirmed|verified|validated|reconciled)|prove\s+or\s+exclude)"
    r"\s+(?:(?:the|this|that|a|an|reported|patient(?:'s)?|clinical)\s+|"
    r"rs\d+\s+|[A-Z][A-Z0-9-]{1,20}\s+)*"
    r"(?:condition|phenotype|diagnosis|finding|variant|report|record|result|"
    r"interpretation|allele|genotype)"
    r"(?:\s+(?:before|with|against|and|or|through)\s+(?:the\s+|an?\s+|"
    r"independent\s+|clinical\s+|reported\s+)*"
    r"(?:interpretation|report|record|testing|confirmation|finding|variant|"
    r"allele|genotype))*\?$",
    re.IGNORECASE,
)
_QUESTION_WHAT = re.compile(
    r"^What\s+(?:(?:additional|clinical|current|independent|primary|reported|"
    r"original)\s+)*(?:evidence|information|confirmation|testing|review|"
    r"question|questions)\s+(?:is|are|would\s+be)\s+"
    r"(?:needed|required|appropriate)\?$|"
    r"^What\s+evidence\s+would\s+determine\s+whether\s+this\s+is\s+"
    r"medically\s+actionable\?$|"
    r"^What\s+would\s+determine\s+whether\s+this\s+is\s+medically\s+"
    r"actionable\?$",
    re.IGNORECASE,
)
_QUESTION_IS = re.compile(
    r"^Is\s+this\s+(?:diagnostic|medically\s+actionable)\?$|"
    r"^Is\s+there\s+(?:(?:validated|curated|functional|genetic|inheritance|"
    r"segregation|gene[-\u2013 ]disease|orthogonal|source|clinical|laboratory|"
    r"public|independent|supporting|contrary)[, ]+|and\s+|or\s+)*"
    r"(?:evidence|counterevidence)\s+"
    r"relevant\s+to\s+(?:this|the)\s+(?:candidate|finding|variant|"
    r"hypothesis|condition)\?$",
    re.IGNORECASE,
)
_QUESTION_SHOULD = re.compile(
    r"^Should\s+(?:I|the\s+patient|a\s+clinician)\s+"
    r"(?:consider|start|stop|change|continue|avoid|review)\s+"
    r"(?:this|the|any|a)?\s*(?:medication|medications|medication\s+changes|"
    r"treatment|therapy|care\s+changes|clinical\s+review)\?$",
    re.IGNORECASE,
)
_QUESTION_DOES = re.compile(
    r"^Does\s+this\s+(?:variant|finding|result)\s+"
    r"(?:cause|help\s+explain|support)\s+the\s+"
    r"(?:reported\s+condition|condition|phenotype)\?$",
    re.IGNORECASE,
)
_CONFIRMATION_NOUN_CLOSED = re.compile(
    r"^(?:(?:additional|further|independent|clinical|laboratory|primary|"
    r"appropriate|current|usable|exact|reported|source)\s+)*"
    r"(?:confirmation|review|testing|verification|validation|evaluation|"
    r"assessment|evidence|counterevidence|corroboration|replication|phenotype|"
    r"assay|laboratory\s+report)"
    r"(?:\s+and\s+(?:(?:additional|further|independent|clinical|laboratory|"
    r"usable|source)\s+)*(?:confirmation|review|testing|verification|"
    r"validation|evidence|counterevidence|phenotype|assay))?"
    r"(?:\s+before\s+(?:interpretation|treatment\s+decisions))?$",
    re.IGNORECASE,
)
_CONFIRMATION_WHETHER_CLOSED = re.compile(
    r"^(?:determine|review|assess|evaluate|clarify|resolve)\s+whether\s+"
    r"(?:this|the\s+(?:finding|variant|result|record|report|evidence|records|"
    r"relation|classification|interpretation))\s+"
    r"(?:is|are)\s+(?:clinically\s+confirmed|diagnostic|supported|sufficient|"
    r"consistent|verified|validated|resolved|relevant)$",
    re.IGNORECASE,
)
_CONFIRMATION_REVIEW_CLOSED = re.compile(
    r"^(?:review|assess|evaluate|clarify|resolve)\s+"
    r"(?:(?:the|this)\s+)?(?:(?:exact|reported|original|approved|candidate|"
    r"molecular|clinical|independent|source)\s+)*"
    r"(?:finding|variant|result|record|report|profile|relation|evidence|"
    r"counterevidence|interpretation|clinical\s+relevance|source\s+status)$",
    re.IGNORECASE,
)
_CONFIRMATION_IDENTITY_CLOSED = re.compile(
    r"^(?:confirm|test|verify|validate|corroborate|replicate|check)\s+"
    r"(?:(?:the|this)\s+)?(?:(?:exact|reported|original|laboratory|source|"
    r"independent|clinical)\s+)*(?:finding|variant|result|record|report|allele|"
    r"genotype|identity|rs\d+|[A-Z][A-Z0-9-]{1,24})"
    r"(?:\s+and\s+(?:(?:the|this|exact|reported|original|laboratory|source)\s+)*"
    r"(?:finding|variant|result|record|report|allele|genotype|identity|"
    r"rs\d+|[A-Z][A-Z0-9-]{1,24}))*$",
    re.IGNORECASE,
)
_CONFIRMATION_OBTAIN_CLOSED = re.compile(
    r"^obtain\s+(?:(?:additional|further|independent|clinical|laboratory|"
    r"usable|current|primary|supporting|source|public|orthogonal)\s+)*"
    r"(?:confirmation|review|testing|verification|validation|evidence|"
    r"counterevidence|records?|sources?)"
    r"(?:\s+before\s+deciding\s+whether\s+to\s+start\s+therapy)?$",
    re.IGNORECASE,
)
_CONFIRMATION_REQUIREMENT_CLOSED = re.compile(
    r"^(?:the\s+)?(?:finding|variant|result|record|report|evidence)\s+"
    r"requires?\s+(?:(?:additional|further|independent|clinical|laboratory)\s+)*"
    r"(?:confirmation|review|testing|verification|validation|evidence)"
    r"(?:\s+before\s+(?:interpretation|treatment\s+decisions))?$",
    re.IGNORECASE,
)
_CONFIRMATION_NONCAUSAL_CLOSED = re.compile(
    r"^assess\s+clinical\s+relevance\s+without\s+assuming\s+that\s+the\s+"
    r"candidate\s+finding\s+causes\s+the\s+condition(?:\s+or\s+"
    r"muscle-weakness\s+episodes)?$",
    re.IGNORECASE,
)
