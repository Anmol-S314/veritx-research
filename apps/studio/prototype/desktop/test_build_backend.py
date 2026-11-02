"""Build orchestration checks, without pretending to build Windows binaries."""
import importlib.util
from pathlib import Path
import subprocess
import runpy
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("desktop_build_backend", Path(__file__).with_name("build_backend.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildBackendTest(unittest.TestCase):
    def check_platform(self, platform, target, suffix):
        with tempfile.TemporaryDirectory() as directory:
            prototype = Path(directory)
            (prototype / "src-tauri").mkdir()
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if "PyInstaller" in command:
                    # One-dir output: a launcher plus its _internal directory.
                    produced = prototype / "src-tauri/binaries/srota-gateway"
                    (produced / "_internal").mkdir(parents=True)
                    (produced / f"srota-gateway{suffix}").write_bytes(b"build fixture")
                return subprocess.CompletedProcess(command, 0)

            with patch.object(builder, "PROTOTYPE", prototype), patch.object(
                    builder, "sys", SimpleNamespace(platform=platform, executable="python")), patch.object(
                    builder.subprocess, "run", side_effect=run), patch.object(
                    builder.subprocess, "check_output", return_value=f"host: {target}\n"):
                builder.main()
            self.assertTrue((prototype / "src-tauri/binaries/gateway" / f"srota-gateway{suffix}").is_file())
            self.assertEqual(len(calls), 2)

    def test_linux_sidecar_name(self):
        self.check_platform("linux", "x86_64-unknown-linux-gnu", "")

    def test_windows_sidecar_name(self):
        self.check_platform("win32", "x86_64-pc-windows-msvc", ".exe")

    def test_runtime_paths_match_target_executable_suffix(self):
        source = builder.REPO / "tracks/t3-topology/dse/veritx_dse/core/paths.py"
        for platform, suffix in (("linux", ""), ("win32", ".exe")):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform):
                paths = runpy.run_path(str(source))
            self.assertEqual(paths["BOOKSIM_BIN"].name, f"booksim{suffix}")
            self.assertEqual(paths["ASTRA_BS_BIN"].name, f"AstraSim_BookSim2{suffix}")

    def test_unsupported_host_refuses(self):
        with patch.object(builder, "sys", SimpleNamespace(platform="darwin")):
            with self.assertRaises(SystemExit):
                builder.main()


if __name__ == "__main__":
    unittest.main()
