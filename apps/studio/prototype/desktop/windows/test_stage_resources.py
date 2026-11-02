"""Staging must fail loudly instead of shipping invented simulator readiness."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import stage_resources


class StagingTest(unittest.TestCase):
    def test_missing_windows_binary_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(stage_resources, "REPO", root), patch.object(
                    stage_resources, "WINDOWS", root / "build"), patch.object(
                    stage_resources, "STAGE", root / "stage"):
                with self.assertRaises(SystemExit):
                    stage_resources.main()

    def test_binary_without_manifest_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "booksim.exe"
            binary.write_bytes(b"PE fixture")
            with self.assertRaises(SystemExit) as error:
                stage_resources.copy_binary(binary, "out/booksim.exe")
            self.assertIn("provenance", str(error.exception))

    def test_copy_never_relabels_unlisted_suffixes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src"
            source.mkdir()
            (source / "keep.py").write_text("x = 1\n")
            (source / "skip.o").write_bytes(b"object")
            with patch.object(stage_resources, "REPO", root), patch.object(
                    stage_resources, "STAGE", root / "stage"):
                stage_resources.copy_tree("src", {".py"})
            self.assertTrue((root / "stage/src/keep.py").is_file())
            self.assertFalse((root / "stage/src/skip.o").exists())


if __name__ == "__main__":
    unittest.main()
