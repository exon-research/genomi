"""Isolated Genomi intake and loopback portal lifecycle."""

from __future__ import annotations

import gzip
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from .constants import DISEASE_SCOPE, QUESTION, SPECIALISTS, JsonObject, approval
from .fixtures import paperclip_replay_fixture


class RuntimeOwner(Protocol):
    run_dir: Path
    genomi_home: Path
    port: int
    dry_run: bool
    fixture_mode: bool
    wait_for_viewer: bool
    viewer_timeout: float
    service: Any
    server: Any
    investigation_id: str
    observation_ids: dict[str, str]
    launch_url_path: Path
    manifest_path: Path
    viewer_ready_path: Path

    def emit(self, stage: str, title: str, detail: str, **kwargs: Any) -> None: ...


class RuntimeMixin:
    def prepare(self: RuntimeOwner) -> None:
        self._prepare_paths_and_environment()
        from genomi.capabilities.analytical_grounding.analytical_grounding.library import (
            analytical_library_path,
        )
        from genomi.lab.encrypted_sqlite import StaticEncryptionKeyProvider
        from genomi.lab.provider_policy import SourceFamily
        from genomi.lab.service import GenomiLabService
        from genomi.lab.store import GenomiLabStore
        from genomi.operations import call_operation

        fixture_dir = self.genomi_home / "synthetic-demo-input"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        vcf_path = fixture_dir / "genomilab-ctla4-demo.vcf"
        vcf_path.write_text(
            "##fileformat=VCFv4.2\n"
            "##contig=<ID=2,length=242193529,assembly=GRCh38>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tGENOMILAB_DEMO_PATIENT\n"
            "2\t203870704\trs2469719303\tG\tC\t.\tPASS\t.\tGT:DP:GQ\t0/1:42:99\n",
            encoding="utf-8",
        )
        gencode_path = analytical_library_path("gencode-grch38")
        gencode_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(gencode_path, "wt", encoding="utf-8") as handle:
            handle.write(
                "##description: exact five-gene subset of GENCODE v49 GRCh38 "
                "annotation (Ensembl 115)\n"
                "##date: 2025-07-08\n"
                "##source: https://ftp.ebi.ac.uk/pub/databases/gencode/"
                "Gencode_human/release_49/gencode.v49.annotation.gtf.gz\n"
            )
            rows = (
                'chr1\tHAVANA\tgene\t9629889\t9730117\t.\t+\t.\tgene_id "ENSG00000171608.19"; gene_type "protein_coding"; gene_name "PIK3CD"; level 2; hgnc_id "HGNC:8977"; havana_gene "OTTHUMG00000001450.3";',
                'chr2\tHAVANA\tgene\t203853888\t203873965\t.\t+\t.\tgene_id "ENSG00000163599.18"; gene_type "protein_coding"; gene_name "CTLA4"; level 2; hgnc_id "HGNC:2505"; havana_gene "OTTHUMG00000132877.8";',
                'chr4\tHAVANA\tgene\t102500937\t102617302\t.\t+\t.\tgene_id "ENSG00000109320.15"; gene_type "protein_coding"; gene_name "NFKB1"; level 1; hgnc_id "HGNC:7794"; havana_gene "OTTHUMG00000161080.10";',
                'chr4\tHAVANA\tgene\t150264435\t151015755\t.\t-\t.\tgene_id "ENSG00000198589.16"; gene_type "protein_coding"; gene_name "LRBA"; level 1; hgnc_id "HGNC:1742"; tag "ncRNA_host"; tag "overlapping_locus"; havana_gene "OTTHUMG00000161443.8";',
                'chr17\tHAVANA\tgene\t16929816\t16972118\t.\t-\t.\tgene_id "ENSG00000240505.9"; gene_type "protein_coding"; gene_name "TNFRSF13B"; level 1; hgnc_id "HGNC:18153"; tag "overlapping_locus"; havana_gene "OTTHUMG00000059262.7";',
            )
            for row in rows:
                handle.write(row + "\n")
        parsed = call_operation(
            "genomi.parse_source",
            {
                "source": str(vcf_path),
                "user_nickname": "Synthetic CTLA4 Recording Twin",
                "genome_build": "GRCh38",
            },
        )
        if parsed.get("status") != "completed":
            raise RuntimeError(f"synthetic source parse did not complete: {parsed}")
        context = call_operation("genomi.describe_context")
        if context.get("active_agi_id") != parsed["active_genome_index"]["agi_id"]:
            raise RuntimeError("the parsed synthetic AGI is not active")

        store = GenomiLabStore(
            self.genomi_home / "lab" / "ctla4-demo.sqlite3",
            key_provider=StaticEncryptionKeyProvider(secrets.token_bytes(32)),
        )
        self.service = GenomiLabService(
            store=store,
            session_id="genomilab-ctla4-demo-service",
            operation_call=call_operation,
            agent_host_id="ctla4-demo-main-investigator",
            agent_processing_destination="the GenomiLab CTLA4 demo runner",
        )
        self.service.configure_evidence_gateway(
            fixtures={SourceFamily.LITERATURE: paperclip_replay_fixture()}
        )
        if self.service.open_agent_workspace().get("status") != "ready":
            raise RuntimeError("GenomiLab workspace is not ready")
        self._seed_initial_profile()
        created = self.service.create_agent_investigation(
            {"question": QUESTION, "disease_scope": DISEASE_SCOPE}
        )
        investigation = created.get("investigation", created)
        self.investigation_id = str(investigation["investigation_id"])
        formed = self.service.form_agent_specialist_board(
            self.investigation_id, specialists=SPECIALISTS
        )
        if len(formed["specialist_board"].get("members") or []) != 3:
            raise RuntimeError("the demo requires exactly three persistent specialists")
        self._authorize(list(self.observation_ids.values()))
        manifest = {
            "demo": "GenomiLab synthetic CTLA4 recording-twin journey",
            "synthetic_patient": True,
            "fixture_mode": True,
            "genome_fixture_scope": (
                "one-variant synthetic recording twin; not a whole genome and not "
                "the user's active genome profile"
            ),
            "genomi_home": "fresh isolated runtime nested under this run directory",
            "question": QUESTION,
            "investigation_id": self.investigation_id,
            "active_agi_id": context.get("active_agi_id"),
            "active_agi_snapshot_id": context.get("active_agi_snapshot_id"),
            "specialist_count": 3,
            "paperclip_evidence_route": "curated replay fixture; never a live-provider claim",
            "esm_operation": "illustrative precomputed fixture; no local model execution",
            "proto_operation": "illustrative precomputed fixture; no local system execution",
            "orchestration": "scripted fixture walkthrough; no live specialist agents",
        }
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.emit(
            "investigation_ready",
            "Patient question and three-specialist board are ready",
            "The synthetic recording-twin profile and isolated local genome index are ready.",
            pause=False,
        )

    def _prepare_paths_and_environment(self: RuntimeOwner) -> None:
        if not self.fixture_mode:
            raise ValueError(
                "this harness is fixture-only; pass --fixture-mode explicitly"
            )
        expected_home = (self.run_dir / "private-genomi-home").resolve()
        if self.genomi_home.resolve() != expected_home:
            raise ValueError("the synthetic GENOMI_HOME must be nested under the run directory")
        if self.run_dir.exists() and any(self.run_dir.iterdir()):
            raise FileExistsError(
                f"refusing to reuse nonempty demo run directory: {self.run_dir}"
            )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.genomi_home.exists():
            raise FileExistsError(
                f"refusing to reuse synthetic GENOMI_HOME: {self.genomi_home}"
            )
        self.genomi_home.mkdir(parents=True)
        os.environ.update(
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "genomilab-ctla4-synthetic-demo",
                "GENOMI_MCP_BACKGROUND": "0",
            }
        )
        for name in (
            "CLAUDE_CODE_SESSION_ID",
            "CODEX_SESSION_ID",
            "OPENAI_SESSION_ID",
            "ANTHROPIC_SESSION_ID",
        ):
            os.environ[name] = ""

    def _seed_initial_profile(self: RuntimeOwner) -> None:
        rows = {
            "crohn": ("condition", "Crohn disease", "I have Crohn disease"),
            "infections": (
                "phenotype",
                "Recurrent sinus and chest infections",
                "I keep getting sinus and chest infections",
            ),
            "platelets": (
                "phenotype",
                "Very low platelets during adolescence",
                "I had very low platelets as a teenager",
            ),
            "medication": (
                "medication",
                "Possible medication-related infection risk",
                "My doctor thinks the infections might be from medication",
            ),
        }
        for key, (modality, label, wording) in rows.items():
            saved = self.service.add_profile_observation(
                {
                    "modality": modality,
                    "label": label,
                    "original_wording": wording,
                    "assertion_status": "present",
                    "verification_state": "user_confirmed",
                    "source_class": "patient_reported",
                }
            )
            self.observation_ids[key] = str(saved["observation_revision_id"])

    def _authorize(
        self: RuntimeOwner, observation_revision_ids: list[str]
    ) -> None:
        prepared = self.service.prepare_agent_authorization(
            self.investigation_id,
            observation_revision_ids=observation_revision_ids,
            purpose="Investigate whether the reported immune findings could be connected",
        )
        result = self.service.authorize_investigation_context(
            self.investigation_id, approval(prepared["candidate"])
        )
        if result.get("status") != "awaiting_agent_plan":
            raise RuntimeError(f"investigation authorization failed: {result}")

    def start_server(self: RuntimeOwner) -> None:
        from genomi.lab.server import GenomiLabHTTPServer

        self.server = GenomiLabHTTPServer(("127.0.0.1", self.port), self.service)
        threading.Thread(
            target=self.server.serve_forever,
            name="genomilab-ctla4-demo-http",
            daemon=True,
        ).start()
        descriptor = os.open(
            self.launch_url_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            presentation_launch_url = self.server.launch_url.replace(
                "/#token=", "/demo#token=", 1
            )
            os.write(descriptor, (presentation_launch_url + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["portal_base_url"] = self.server.base_url
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.emit(
            "portal_ready",
            "Monitor the real local portal",
            f"One-time launch URL is stored with mode 0600 at {self.launch_url_path}.",
            pause=False,
        )

    def wait_for_viewer_signal(self: RuntimeOwner) -> None:
        if not self.wait_for_viewer or self.dry_run:
            return
        self.emit(
            "waiting_for_viewer",
            "Waiting for the recording browser",
            "The investigation begins when the controller has opened the portal.",
            pause=False,
        )
        deadline = time.monotonic() + self.viewer_timeout
        while time.monotonic() < deadline:
            if self.viewer_ready_path.exists():
                return
            time.sleep(0.2)
        raise TimeoutError(f"viewer did not signal readiness within {self.viewer_timeout:g}s")

    def close(self: RuntimeOwner) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            self.service = None
        elif self.service is not None:
            self.service.close()
            self.service = None
        for private_signal in (self.launch_url_path, self.viewer_ready_path):
            if private_signal.exists():
                private_signal.unlink()
