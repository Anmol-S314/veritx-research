"""Windows handle-relative artifact security checks (Wine != native proof)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tracks/t3-topology/dse"))
from veritx_dse.core.run_bundle import finalize_run_bundle, read_verified_file, RunBundleError
from veritx_dse.core.windows_files import open_regular_beneath


@unittest.skipUnless(os.name == "nt", "requires Windows relative file HANDLE APIs")
class WindowsArtifactTest(unittest.TestCase):
    def test_nested_unicode_bytes_caps_and_tampering(self):
        with tempfile.TemporaryDirectory(prefix="srota artifacts λ ") as directory:
            root = Path(directory)
            (root / "nested λ").mkdir()
            path = root / "nested λ" / "data.txt"
            path.write_bytes(b"sealed bytes")
            finalize_run_bundle(root)
            self.assertEqual(read_verified_file(root, "nested λ/data.txt"), b"sealed bytes")
            with self.assertRaises(RunBundleError):
                read_verified_file(root, "nested λ/data.txt", max_bytes=2)
            path.write_bytes(b"changed bytes")
            with self.assertRaises(RunBundleError):
                read_verified_file(root, "nested λ/data.txt")

    def test_relative_escape_and_alternate_stream_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            for parts in (("..", "secret"), ("file:stream",), ("child\\file",)):
                with self.subTest(parts=parts), self.assertRaises(ValueError):
                    open_regular_beneath(Path(directory), parts)

    def test_directory_junction_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "secret").write_bytes(b"outside bytes")
            junction = root / "linked"
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode != 0 or not junction.exists():
                # Wine does not implement NT junctions. Skipping here is honest
                # only because a native Windows run is still a required gate.
                self.skipTest("host cannot create an NT junction; native Windows must run this case: "
                              + (result.stdout + result.stderr).strip())
            self.assertTrue(junction.is_junction() or junction.is_symlink(), 'mklink output is not a reparse point')
            try:
                with self.assertRaises(OSError):
                    open_regular_beneath(root, ("linked", "secret"))
                with self.assertRaises(RunBundleError):
                    finalize_run_bundle(root)
            finally:
                # Remove the junction itself, never recursively delete its target.
                if junction.is_junction():
                    os.rmdir(junction)
                elif junction.is_symlink():
                    junction.unlink()


if __name__ == "__main__":
    unittest.main()
