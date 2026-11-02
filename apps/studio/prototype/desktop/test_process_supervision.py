"""Same output/timeout contract for POSIX groups and Windows job wrappers."""
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tracks/t3-topology/dse"))
from veritx_dse.core.process import supervised_run


class ProcessSupervisionTest(unittest.TestCase):
    def test_output_exit_code_and_original_command(self):
        command = [sys.executable, "-c", "import sys;print('out');print('err',file=sys.stderr);sys.exit(3)"]
        result = supervised_run(command, timeout=15)
        self.assertEqual(result.args, command)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.strip(), "out")
        self.assertEqual(result.stderr.strip(), "err")
        self.assertFalse(result.timed_out)

    def test_timeout_preserves_output_and_raises_when_requested(self):
        command = [sys.executable, "-c", "import time;print('started',flush=True);time.sleep(60)"]
        result = supervised_run(command, timeout=3, grace_s=0.2, on_timeout="complete")
        self.assertTrue(result.timed_out)
        self.assertIn("started", result.stdout)
        self.assertLess(result.wall_time_s, 15)
        with self.assertRaises(subprocess.TimeoutExpired) as error:
            supervised_run(command, timeout=3, grace_s=0.2)
        self.assertEqual(error.exception.cmd, command)
        self.assertIn("started", error.exception.stdout)


if __name__ == "__main__":
    unittest.main()
