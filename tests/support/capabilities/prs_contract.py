from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.active_genome_index import create_active_genome_index, default_agi_path
from genomi.capabilities.prs import scorer as prs_scorer
from genomi.runtime import context as runtime_context
from genomi.runtime.liftover import chain_file_path, liftover_preflight
from genomi.runtime.sqlite_support import connect_sqlite


class PolygenicScoreTestBase(unittest.TestCase):
    _tiny_thresholds = staticmethod(lambda *args, **kwargs: tiny_thresholds(*args, **kwargs))

    def setUp(self) -> None:
        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self.genomi_home = Path(self._home_tmp.name) / "genomi-home"
        self._env = mock.patch.dict(
            os.environ,
            {
                "GENOMI_HOME": str(self.genomi_home),
                "GENOMI_CONTEXT": "",
                "GENOMI_SESSION_ID": "",
                "GENOMI_MCP_BACKGROUND": "0",
                **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)

    def _select_approved_agi(self, vcf: Path, *, genome_build: str = "GRCh38") -> None:
        runtime_context.set_active_agi_from_source(
            vcf,
            status="parsed",
            agi_path=default_agi_path(vcf),
            genome_build=genome_build,
        )
        runtime_context.approve_agi_access(reason="test approved Active Genome Index access")

    def _link_real_liftover_chains(self) -> bool:
        from genomi.runtime.paths import DEFAULT_GENOMI_HOME

        real_chain_dir = DEFAULT_GENOMI_HOME / "resources" / "liftover"
        chains = [
            real_chain_dir / "hg38ToHg19.over.chain.gz",
            real_chain_dir / "hg19ToHg38.over.chain.gz",
        ]
        if not all(path.exists() for path in chains):
            return False
        target_dir = self.genomi_home / "resources" / "liftover"
        target_dir.mkdir(parents=True, exist_ok=True)
        for chain in chains:
            link = target_dir / chain.name
            if not link.exists():
                link.symlink_to(chain)
        return liftover_preflight("GRCh38", "GRCh37", root=self.genomi_home)["status"] == "available"

    def _write_fake_liftover_chains(self) -> None:
        for source_build, target_build in (("GRCh38", "GRCh37"), ("GRCh37", "GRCh38")):
            path = chain_file_path(source_build, target_build, root=self.genomi_home)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")

    def _write_scoring_file(
        self,
        *,
        filename: str = "PGS900001_hmPOS_GRCh38.txt",
        pgs_id: str = "PGS900001",
        harmonized: bool = True,
    ) -> Path:
        path = Path(self._home_tmp.name) / filename
        header = "hm_chr\thm_pos\trsID\teffect_allele\tother_allele\teffect_weight"
        rows = [
            "1\t100\trs1\tC\tA\t0.5",
            "1\t200\trs2\tG\tT\t1.0",
            "1\t300\trs3\tG\tA\t-0.25",
            "1\t400\trs4\tT\tC\t2.0",
        ]
        if not harmonized:
            header = "chr_name\tchr_position\trsID\teffect_allele\tother_allele\teffect_weight"
        path.write_text(
            "\n".join(
                [
                    f"#pgs_id={pgs_id}",
                    "#pgs_name=SYNTHETIC",
                    "#reported_trait=Synthetic common trait",
                    header,
                    *rows,
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _pgs_metadata_row(
        self,
        *,
        pgs_id: str,
        name: str = "score",
        reported_trait: str,
        mapped_trait_labels: str,
        mapped_trait_ids: str,
        variant_count: str = "10",
    ) -> dict[str, str]:
        return {
            "Polygenic Score (PGS) ID": pgs_id,
            "PGS Name": name,
            "Reported Trait": reported_trait,
            "Mapped Trait(s) (EFO label)": mapped_trait_labels,
            "Mapped Trait(s) (EFO ID)": mapped_trait_ids,
            "PGS Development Method": "",
            "PGS Development Details/Relevant Parameters": "",
            "Original Genome Build": "GRCh38",
            "Number of Variants": variant_count,
            "Number of Interaction Terms": "0",
            "Type of Variant Weight": "effect_weight",
            "PGS Publication (PGP) ID": "PGP000001",
            "Publication (PMID)": "34995502",
            "Publication (doi)": "10.1016/j.ajhg.2021.11.008",
            "Score and results match the original publication": "true",
            "Ancestry Distribution (%) - Source of Variant Associations (GWAS)": "",
            "Ancestry Distribution (%) - Score Development/Training": "",
            "Ancestry Distribution (%) - PGS Evaluation": "",
            "FTP link": "",
            "Release Date": "",
            "License/Terms of Use": "",
        }

    def _write_indexed_vcf(self, name: str, *, include_positions: set[int] | None = None) -> Path:
        include_positions = include_positions or {100, 200, 300, 400}
        rows = [
            (100, "rs1", "A", "C", "1/1"),
            (200, "rs2", "G", "T", "0/1"),
            (300, "rs3", "A", "G", "0/0"),
            (400, "rs4", "C", "T", "0/0"),
        ]
        vcf = Path(self._home_tmp.name) / name
        lines = [
            "##fileformat=VCFv4.2",
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
        ]
        for pos, rsid, ref, alt, gt in rows:
            if pos not in include_positions:
                continue
            lines.append(f"1\t{pos}\t{rsid}\t{ref}\t{alt}\t.\tPASS\t.\tGT\t{gt}")
        vcf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        create_active_genome_index(vcf, parallel_workers=1, reuse_existing=False)
        return vcf


def memory_prs_index() -> sqlite3.Connection:
    connection = connect_sqlite(":memory:", row_factory=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        create table records (
            chrom text not null,
            chrom_sort integer not null,
            pos integer not null,
            end integer not null,
            ref text not null,
            alt text not null,
            filter text not null,
            format text,
            genotype text not null,
            record_kind text not null,
            observed_alleles text,
            offset integer not null,
            sample_index integer not null
        );
        create table spans (
            chrom text not null,
            chrom_sort integer not null,
            pos integer not null,
            end integer not null,
            offset integer not null,
            sample_index integer not null
        );
        """
    )
    return connection


def insert_prs_record(
    connection: sqlite3.Connection,
    *,
    pos: int,
    ref: str,
    alt: str,
    genotype: str,
) -> None:
    record_kind, observed_alleles = vcf_record_observation(ref=ref, alt=alt, genotype=genotype)
    _insert_record(
        connection,
        pos=pos,
        ref=ref,
        alt=alt,
        genotype=genotype,
        record_kind=record_kind,
        observed_alleles=observed_alleles,
        format_value="GT",
        filter_value="PASS",
    )


def insert_array_prs_record(
    connection: sqlite3.Connection,
    *,
    pos: int,
    genotype: str,
    filter_value: str = "PASS",
) -> None:
    is_called = filter_value == "PASS" and genotype not in {"", ".", "--", "00", "NN"}
    _insert_record(
        connection,
        pos=pos,
        ref=".",
        alt=".",
        genotype=genotype,
        record_kind="array_call" if is_called else "array_no_call",
        observed_alleles=list(genotype) if is_called else None,
        format_value="GT_ARRAY",
        filter_value=filter_value,
    )


def vcf_record_observation(*, ref: str, alt: str, genotype: str) -> tuple[str, list[str] | None]:
    tokens = [token for token in genotype.replace("|", "/").split("/") if token]
    if not tokens or any(token == "." for token in tokens):
        return "no_call", None
    alts = [] if alt == "." else alt.split(",")
    observed: list[str] = []
    for token in tokens:
        if token == "0":
            observed.append(ref)
            continue
        try:
            observed.append(alts[int(token) - 1])
        except (IndexError, ValueError):
            return "no_call", None
    record_kind = "variant_call" if any(token != "0" for token in tokens) and alts else "reference_block"
    return record_kind, observed


def score_variant(*, pos: int, effect_allele: str, other_allele: str) -> dict[str, object]:
    return {
        "variant_index": 0,
        "variant_id": f"1:{pos}:{other_allele}:{effect_allele}",
        "rsid": "rs-test",
        "chrom": "1",
        "pos": pos,
        "effect_allele": effect_allele,
        "other_allele": other_allele,
        "effect_weight": 1.0,
        "harmonized": True,
        "palindromic": False,
    }


def tiny_thresholds(*, min_variants: int = 1, min_fraction: float = 0.10):
    return mock.patch.multiple(
        prs_scorer,
        MIN_SCORE_VARIANTS=min_variants,
        MIN_OVERLAP_FRACTION=min_fraction,
        MODERATE_OVERLAP_FRACTION=0.50,
        HIGH_OVERLAP_FRACTION=0.90,
    )


def _insert_record(
    connection: sqlite3.Connection,
    *,
    pos: int,
    ref: str,
    alt: str,
    genotype: str,
    record_kind: str,
    observed_alleles: list[str] | None,
    format_value: str,
    filter_value: str,
) -> None:
    connection.execute(
        """
        insert into records(
            chrom, chrom_sort, pos, end, ref, alt, filter, format, genotype,
            record_kind, observed_alleles, offset, sample_index
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "1",
            1,
            pos,
            pos,
            ref,
            alt,
            filter_value,
            format_value,
            genotype,
            record_kind,
            json.dumps(observed_alleles, sort_keys=True) if observed_alleles is not None else None,
            pos,
            0,
        ),
    )
