from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from genomi.runtime.libraries import transforms


class TransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_gunzip_faidx_decompresses_and_indexes(self) -> None:
        fasta_text = ">chr1 desc\nACGTACGTAC\nACGT\n>chr2\nTTTT\n"
        gz = self.tmp / "ref.fa.gz"
        gz.write_bytes(gzip.compress(fasta_text.encode()))
        out = self.tmp / "ref.fa"
        fai = self.tmp / "ref.fa.fai"

        transforms.gunzip_faidx(gz, out, fai)

        self.assertEqual(out.read_text(), fasta_text)
        # chr1: length 14 (10+4), offset 11 (after ">chr1 desc\n"), bases 10, width 11
        # chr2: length 4, offset 33, bases 4, width 5
        self.assertEqual(fai.read_text(), "chr1\t14\t11\t10\t11\nchr2\t4\t33\t4\t5\n")

    def test_verify_sha256(self) -> None:
        payload = self.tmp / "blob"
        payload.write_bytes(b"genomi")
        digest = hashlib.sha256(b"genomi").hexdigest()
        transforms.verify_sha256(payload, digest)  # no raise
        self.assertEqual(transforms.sha256_file(payload), digest)
        with self.assertRaises(ValueError):
            transforms.verify_sha256(payload, "0" * 64)

    def test_xlsx_to_tsv_normalizes_cellmarker_columns(self) -> None:
        from openpyxl import Workbook

        source = self.tmp / "Cell_marker_Human.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["cell_name", "Symbol", "marker", "tissue_type", "cancer_type", "cellontology_id"])
        sheet.append(["T cell", "CD3D", "CD3", "Blood", "Normal", "CL:0000084"])
        sheet.append(["", "NOGENE", "", "", "", ""])  # dropped: no cell_type
        workbook.save(source)

        out = self.tmp / "markers.tsv"
        transforms.xlsx_to_tsv(source, out)

        lines = out.read_text().splitlines()
        self.assertEqual(
            lines[0],
            "cell_type\tgene_symbol\tmarker\tlineage_context\tmarker_strength\trecord_id\treference",
        )
        self.assertEqual(len(lines), 2)  # header + one valid row (the empty cell_type row is dropped)
        fields = lines[1].split("\t")
        self.assertEqual(fields[0], "T cell")
        self.assertEqual(fields[1], "CD3D")
        self.assertEqual(fields[5], "CL:0000084")

    def test_extract_named_binary_flattens_leading_dir(self) -> None:
        tarball = self.tmp / "minimap2.tar.bz2"
        data = b"#!/bin/sh\necho minimap2\n"
        with tarfile.open(tarball, "w:bz2") as tar:
            info = tarfile.TarInfo("minimap2-2.28_x64-linux/minimap2")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            other = b"readme"
            info2 = tarfile.TarInfo("minimap2-2.28_x64-linux/README.md")
            info2.size = len(other)
            tar.addfile(info2, io.BytesIO(other))

        install_dir = self.tmp / "bin"
        binary = transforms.extract_named_binary(tarball, install_dir, "minimap2", compression="bz2")
        self.assertEqual(binary, install_dir / "minimap2")
        self.assertTrue(binary.is_file())
        self.assertEqual(binary.read_bytes(), data)
        self.assertEqual(oct(binary.stat().st_mode & 0o777), "0o755")

    def test_extract_named_binary_missing_binary_raises(self) -> None:
        tarball = self.tmp / "empty.tar.gz"
        with tarfile.open(tarball, "w:gz") as tar:
            info = tarfile.TarInfo("dir/other")
            info.size = 0
            tar.addfile(info, io.BytesIO(b""))
        with self.assertRaises(ValueError):
            transforms.extract_named_binary(tarball, self.tmp / "out", "minimap2", compression="gz")

    def test_extract_flat_tarball_flattens_panel(self) -> None:
        tarball = self.tmp / "panel.tar.gz"
        names = ("manifest.json", "samples.tsv", "markers.tsv")
        with tarfile.open(tarball, "w:gz") as tar:
            for name in names:
                data = b"{}"
                info = tarfile.TarInfo(f"panel-001/{name}")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

        target = self.tmp / "panel"
        extracted = transforms.extract_flat_tarball(tarball, target, compression="gz")
        self.assertEqual(sorted(extracted), sorted(names))
        for name in names:
            self.assertTrue((target / name).is_file())


if __name__ == "__main__":
    unittest.main()
