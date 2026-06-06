from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from genomi.capabilities.decode import dashboard as decode_dashboard
from genomi.capabilities.decode.panel_states import (
    EMPTY_COVERAGE_STATES,
    EMPTY_NATIVE_STATUSES,
    EMPTY_PGX_STATUSES,
    EMPTY_PRS_STATUSES,
)

JsonObject = dict[str, object]
EvidenceFactory = Callable[[str], object]

DECODE_RESULT_STATE_OPERATION = "decode.render_dashboard"
DECODE_RESULT_STATE_MODES = frozenset({"fresh_render", "update_clears_stale"})
DECODE_NATIVE_STATUS_PANELS = frozenset({"ancestry", "variants", "variants_all", "nutrigenomics"})
DECODE_COVERAGE_STATE_PANELS = frozenset({"variants", "variants_all", "nutrigenomics"})
DECODE_PGX_STATUS_PANELS = frozenset({"pgx"})
DECODE_PRS_STATUS_PANELS = frozenset({"risk"})


@dataclass(frozen=True)
class DecodeResultStateCase:
    operation: str
    panel: str
    state_axis: str
    state: str
    mode: str
    evidence: EvidenceFactory

    @property
    def cell(self) -> tuple[str, str, str, str, str]:
        return (self.operation, self.panel, self.state_axis, self.state, self.mode)

    def run(self, tmp_path: Path) -> JsonObject:
        out = tmp_path / f"{self.panel}-{self.state_axis}-{self.state}-{self.mode}.html"
        if self.mode == "update_clears_stale":
            decode_dashboard.render_dashboard(
                evidence={
                    "overview": {"sampleId": "HG-RESULT-STATE", "variantCount": 10},
                    self.panel: _stale_panel(self.panel),
                },
                mode="full",
                output=out,
            )
            render_mode = "update"
        else:
            render_mode = "full"

        result = decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-RESULT-STATE", "variantCount": 10},
                self.panel: self.evidence(self.state),
            },
            mode=render_mode,
            output=out,
        )
        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        panel_keys = {key for key in parsed if key in decode_dashboard.PANEL_KEYS}
        assert panel_keys == {"overview"}
        assert self.panel not in result["panels_rendered"]
        assert self.panel in result["panels_empty"]
        return result


@dataclass(frozen=True)
class DecodeDataReturnedCase:
    operation: str
    panel: str
    mode: str
    evidence: object

    @property
    def cell(self) -> tuple[str, str, str]:
        return (self.operation, self.panel, self.mode)

    def run(self, tmp_path: Path) -> JsonObject:
        out = tmp_path / f"{self.panel}-data-returned-{self.mode}.html"
        if self.mode == "update":
            decode_dashboard.render_dashboard(
                evidence={
                    "overview": {"sampleId": "HG-DATA-OLD", "variantCount": 1},
                    self.panel: _stale_panel(self.panel),
                },
                mode="full",
                output=out,
            )
        result = decode_dashboard.render_dashboard(
            evidence={
                "overview": {"sampleId": "HG-DATA", "variantCount": 10},
                self.panel: self.evidence,
            },
            mode=self.mode,
            output=out,
        )
        parsed = _extract_evidence(out.read_text(encoding="utf-8"))
        assert self.panel in parsed
        assert self.panel in result["panels_rendered"]
        assert self.panel not in result["panels_empty"]
        return result


def _extract_evidence(html: str) -> JsonObject:
    marker = "window.__GENOMI_DASHBOARD__"
    assignment_index = html.find(marker)
    assert assignment_index >= 0, "no __GENOMI_DASHBOARD__ block in HTML"
    json_start = html.find("{", assignment_index)
    assert json_start >= 0, "no __GENOMI_DASHBOARD__ object in HTML"
    parsed, _end = json.JSONDecoder().raw_decode(html[json_start:].replace("<\\/", "</"))
    assert isinstance(parsed, dict), "__GENOMI_DASHBOARD__ is not an object"
    return parsed


def _stale_panel(panel: str) -> object:
    if panel == "overview":
        return {"sampleId": "HG-DATA-OLD", "variantCount": 1}
    if panel == "ancestry":
        return {
            "dominantAncestry": "EUR",
            "neighbors": [{"population": "EUR", "similarity": 0.9}],
        }
    if panel in {"variants", "variants_all"}:
        return [{"rsid": "rs1", "gene": "GENE1"}]
    if panel == "nutrigenomics":
        return [{"marker": "Folate Metabolism", "gene": "MTHFR"}]
    if panel == "pgx":
        return [{"gene": "CYP2C19", "phenotype": "Intermediate"}]
    if panel == "risk":
        return [{"trait": "T2D", "score": 1.0}]
    if panel == "journal":
        return [{"kind": "observation", "title": "Stale note", "ts": "2026-05-24"}]
    raise AssertionError(f"unknown panel: {panel}")


def _native_status_evidence(panel: str) -> EvidenceFactory:
    def build(status: str) -> JsonObject:
        if panel == "ancestry":
            return {
                "status": status,
                "nearest_reference_groups": [],
                "sample_qc": {"marker_overlap_quality": "insufficient", "overlap_fraction": 0.06},
                "reference_panel": {"panel_id": "1000g-30x-grch37"},
            }
        if panel in {"variants", "variants_all"}:
            return {"status": status, "missing_library": {"library": "clinvar-grch38"}}
        if panel == "nutrigenomics":
            return {"status": status, "markers": []}
        raise AssertionError(f"unsupported native status panel: {panel}")

    return build


def _coverage_state_evidence(panel: str) -> EvidenceFactory:
    def build(coverage_state: str) -> JsonObject:
        if panel in {"variants", "variants_all"}:
            return {"coverage_state": coverage_state, "candidate_inventory": []}
        if panel == "nutrigenomics":
            return {"coverage_state": coverage_state, "markers": []}
        raise AssertionError(f"unsupported coverage-state panel: {panel}")

    return build


def _pgx_status_evidence(status: str) -> JsonObject:
    return {
        "status": status,
        "pharmcat_input": {"status": status},
        "input_preflight": {"status": "completed"},
    }


def _prs_status_evidence(status: str) -> JsonObject:
    return {"status": status, "missing_library": {"library": "PGS900001"}}


def _cases() -> tuple[DecodeResultStateCase, ...]:
    cases: list[DecodeResultStateCase] = []
    for mode in sorted(DECODE_RESULT_STATE_MODES):
        for panel in sorted(DECODE_NATIVE_STATUS_PANELS):
            for status in sorted(EMPTY_NATIVE_STATUSES):
                cases.append(
                    DecodeResultStateCase(
                        DECODE_RESULT_STATE_OPERATION,
                        panel,
                        "status",
                        status,
                        mode,
                        _native_status_evidence(panel),
                    )
                )
        for panel in sorted(DECODE_COVERAGE_STATE_PANELS):
            for coverage_state in sorted(EMPTY_COVERAGE_STATES):
                cases.append(
                    DecodeResultStateCase(
                        DECODE_RESULT_STATE_OPERATION,
                        panel,
                        "coverage_state",
                        coverage_state,
                        mode,
                        _coverage_state_evidence(panel),
                    )
                )
        for status in sorted(EMPTY_PGX_STATUSES):
            cases.append(
                DecodeResultStateCase(
                    DECODE_RESULT_STATE_OPERATION,
                    "pgx",
                    "status",
                    status,
                    mode,
                    _pgx_status_evidence,
                )
            )
        for status in sorted(EMPTY_PRS_STATUSES):
            cases.append(
                DecodeResultStateCase(
                    DECODE_RESULT_STATE_OPERATION,
                    "risk",
                    "status",
                    status,
                    mode,
                    lambda state: [_prs_status_evidence(state)],
                )
            )
    return tuple(cases)


def _data_returned_evidence(panel: str) -> object:
    if panel == "overview":
        return {"sampleId": "HG-DATA", "variantCount": 10}
    if panel in {"variants", "variants_all"}:
        return [{"rsid": "rs900000001", "gene": "GENE1", "zygosity": "het"}]
    if panel == "pgx":
        return [{"gene": "CYP2C19", "diplotype": "*1/*2", "phenotype": "Intermediate", "impact": "reduced"}]
    if panel == "risk":
        return [{"trait": "Synthetic common trait", "score": 2.0, "sources": ["PGS900001"]}]
    if panel == "ancestry":
        return {
            "dominantAncestry": "EUR",
            "neighbors": [{"population": "EUR", "similarity": 0.9}],
        }
    if panel == "nutrigenomics":
        return [{"marker": "Folate Metabolism", "gene": "MTHFR", "rsid": "rs1801133"}]
    if panel == "journal":
        return [{"kind": "observation", "title": "Current note", "ts": "2026-05-25"}]
    raise AssertionError(f"unknown panel: {panel}")


def _data_returned_cases() -> tuple[DecodeDataReturnedCase, ...]:
    return tuple(
        DecodeDataReturnedCase(DECODE_RESULT_STATE_OPERATION, panel, mode, _data_returned_evidence(panel))
        for panel in sorted(decode_dashboard.PANEL_KEYS)
        for mode in ("full", "update")
    )


DECODE_RESULT_STATE_CASES = _cases()
DECODE_DATA_RETURNED_CASES = _data_returned_cases()
DECODE_RESULT_STATE_CELLS = frozenset(case.cell for case in DECODE_RESULT_STATE_CASES)
DECODE_DATA_RETURNED_CELLS = frozenset(case.cell for case in DECODE_DATA_RETURNED_CASES)
DECODE_NATIVE_STATUS_CELLS = frozenset(
    (DECODE_RESULT_STATE_OPERATION, panel, "status", status, mode)
    for panel in DECODE_NATIVE_STATUS_PANELS
    for status in EMPTY_NATIVE_STATUSES
    for mode in DECODE_RESULT_STATE_MODES
)
DECODE_COVERAGE_STATE_CELLS = frozenset(
    (DECODE_RESULT_STATE_OPERATION, panel, "coverage_state", coverage_state, mode)
    for panel in DECODE_COVERAGE_STATE_PANELS
    for coverage_state in EMPTY_COVERAGE_STATES
    for mode in DECODE_RESULT_STATE_MODES
)
DECODE_PGX_STATUS_CELLS = frozenset(
    (DECODE_RESULT_STATE_OPERATION, "pgx", "status", status, mode)
    for status in EMPTY_PGX_STATUSES
    for mode in DECODE_RESULT_STATE_MODES
)
DECODE_PRS_STATUS_CELLS = frozenset(
    (DECODE_RESULT_STATE_OPERATION, "risk", "status", status, mode)
    for status in EMPTY_PRS_STATUSES
    for mode in DECODE_RESULT_STATE_MODES
)
