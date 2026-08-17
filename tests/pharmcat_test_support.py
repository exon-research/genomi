from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _escaped_header_vcf_text() -> str:
    """A GRCh38 VCF carrying a bcftools-style FILTER description with
    backslash-escaped quotes (CHROM=\\"X\\") — the exact metadata shape that
    crashes PharmCAT's parser. Includes a real CYP2C19 PGx position so the
    matcher has something to call.
    """
    return (
        "##fileformat=VCFv4.2\n"
        "##reference=GRCh38\n"
        '##FILTER=<ID=PASS,Description="All filters passed">\n'
        '##FILTER=<ID=LowDP,Description="Set if true: (CHROM=\\"X\\" && FORMAT/DP<6) || (CHROM=\\"Y\\" && FORMAT/DP<6)">\n'
        "##contig=<ID=chr10,length=133797422>\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "chr10\t94761900\trs4244285\tG\tA\t.\tPASS\t.\tGT\t0/1\n"
    )


def _resolve_real_pharmcat_jar() -> str | None:
    candidates: list[Path] = []
    env_jar = os.environ.get("PHARMCAT_JAR")
    if env_jar:
        candidates.append(Path(env_jar).expanduser())
    candidates.append(Path.home() / ".genomi" / "tools" / "pharmcat" / "pharmcat.jar")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


_REAL_PHARMCAT_JAR = _resolve_real_pharmcat_jar()


def _real_java_runtime_available() -> bool:
    """Distinguish a working JVM from macOS's non-functional java launcher shim."""

    executable = shutil.which("java")
    if not executable:
        return False
    try:
        probe = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


_REAL_JAVA_RUNTIME_AVAILABLE = _real_java_runtime_available()



__all__ = [
    "_escaped_header_vcf_text",
    "_REAL_JAVA_RUNTIME_AVAILABLE",
    "_REAL_PHARMCAT_JAR",
]
