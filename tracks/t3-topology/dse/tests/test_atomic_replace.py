"""Windows rename semantics: readers holding the target must not fail writes."""
from __future__ import annotations

import errno
import os
import unittest
from unittest import mock

from veritx_dse.core.atomic import atomic_replace


class AtomicReplaceTest(unittest.TestCase):
    def test_plain_replace(self, tmp_path=None):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "a", Path(tmp) / "b"
            src.write_text("new")
            dst.write_text("old")
            atomic_replace(src, dst)
            self.assertEqual(dst.read_text(), "new")
            self.assertFalse(src.exists())

    def test_retries_a_transient_windows_sharing_violation(self):
        """A reader holding the job file must not turn a write into a failure."""
        import tempfile
        from pathlib import Path
        calls = []

        def flaky(src, dst, *args, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                exc = PermissionError(errno.EACCES, "Access is denied", str(dst))
                exc.winerror = 5
                raise exc
            real_replace(src, dst)

        real_replace = os.replace
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("veritx_dse.core.atomic._replace", flaky), \
                mock.patch("veritx_dse.core.atomic._IS_WINDOWS", True):
            src, dst = Path(tmp) / "a", Path(tmp) / "b"
            src.write_text("new")
            atomic_replace(src, dst)
            self.assertGreaterEqual(len(calls), 3)
            self.assertEqual(dst.read_text(), "new")

    def test_non_transient_error_is_raised_immediately(self):
        def denied(src, dst, *args, **kwargs):
            raise PermissionError(errno.EACCES, "Access is denied", str(dst))

        with mock.patch("veritx_dse.core.atomic._replace", denied), \
                mock.patch("veritx_dse.core.atomic._IS_WINDOWS", True):
            with self.assertRaises(PermissionError):
                atomic_replace("missing-source", "target")

    def test_posix_is_never_retried(self):
        calls = []

        def denied(src, dst, *args, **kwargs):
            calls.append(1)
            exc = PermissionError(errno.EACCES, "nope", str(dst))
            exc.winerror = 5
            raise exc

        with mock.patch("veritx_dse.core.atomic._replace", denied), \
                mock.patch("veritx_dse.core.atomic._IS_WINDOWS", False):
            with self.assertRaises(PermissionError):
                atomic_replace("s", "d")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
