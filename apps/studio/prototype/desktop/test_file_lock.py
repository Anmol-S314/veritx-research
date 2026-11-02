"""Platform dispatch/error checks; actual contention uses spawned OS tests."""
import errno
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tracks/t3-topology/dse"))
from veritx_dse.core import file_lock


class WindowsLockContractTest(unittest.TestCase):
    def test_acquire_and_release_same_descriptor(self):
        with patch.object(file_lock, "os", SimpleNamespace(name="nt")), patch.object(
                file_lock, "_windows_lock") as native:
            file_lock.lock_exclusive(42)
            file_lock.unlock(42)
        self.assertEqual(native.call_args_list,
                         [call(42, release=False), call(42, release=True)])

    def test_native_errors_are_not_swallowed(self):
        with patch.object(file_lock, "os", SimpleNamespace(name="nt")), patch.object(
                file_lock, "_windows_lock", side_effect=OSError(errno.EBADF, "invalid descriptor")):
            with self.assertRaises(OSError) as error:
                file_lock.lock_exclusive(42)
        self.assertEqual(error.exception.errno, errno.EBADF)


if __name__ == "__main__":
    unittest.main()
