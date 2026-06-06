from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.active_genome_index.canonical import build_canonical_bgzip


class ActiveGenomeIndexCanonicalDependencyTests(unittest.TestCase):
    def test_missing_bgzip_error_names_linux_tabix_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.vcf"
            source.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
                "1\t100\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
                encoding="utf-8",
            )
            with (
                mock.patch("genomi.active_genome_index.canonical.shutil.which", return_value=None),
                self.assertRaises(RuntimeError) as raised,
            ):
                build_canonical_bgzip(source, root / "work")

        message = str(raised.exception)
        self.assertIn("bgzip CLI not found on PATH", message)
        self.assertIn("tabix package", message)


if __name__ == "__main__":
    unittest.main()
