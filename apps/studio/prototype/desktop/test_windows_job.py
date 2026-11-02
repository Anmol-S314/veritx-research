"""Run with Windows Python; Wine results are not native Windows acceptance."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tracks/t3-topology/dse"))


@unittest.skipUnless(os.name == "nt", "requires Windows process/job APIs")
class WindowsContainmentTest(unittest.TestCase):
    def test_worker_death_kills_descendant_not_unrelated_process(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory(prefix="srota job λ ") as root:
            marker = Path(root) / "child.json"
            unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
            owner = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--owned-child", str(marker)])
            descendant = None
            try:
                deadline = time.monotonic() + 30
                while not marker.is_file() and time.monotonic() < deadline:
                    self.assertIsNone(owner.poll(), "contained owner failed to start")
                    time.sleep(0.05)
                self.assertTrue(marker.is_file(), "contained owner did not publish readiness")
                pid = json.loads(marker.read_text())["pid"]
                descendant = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
                self.assertTrue(descendant, "could not retain descendant process handle")
                self.assertEqual(kernel.WaitForSingleObject(descendant, 0), 0x102)
                owner.kill()
                owner.wait(timeout=10)
                self.assertEqual(kernel.WaitForSingleObject(descendant, 10000), 0)
                self.assertIsNone(unrelated.poll(), "unrelated process was terminated")
            finally:
                for process in (owner, unrelated):
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
                if descendant:
                    kernel.CloseHandle(descendant)


def owned_child(marker):
    from veritx_dse.core.windows_job import contain_current_process
    contain_current_process(memory_limit_bytes=128 * 1024**2)
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
    path = Path(marker)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"pid": child.pid}))
    temporary.replace(path)
    time.sleep(120)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--owned-child":
        owned_child(sys.argv[2])
    else:
        unittest.main()
