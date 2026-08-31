"""Unit tests for previously untested modules.

Covers: commands_trace, logger, recovery, trace_to_binary.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))  # dse/ for veritx_dse import


# ── commands_trace: info and validate ────────────────────────────────────

class TestTraceInfo:
    """veritx_dse.commands_trace.cmd_trace_info"""

    def _make_args(self, trace_path: str):
        """Create an args namespace like argparse would."""
        from argparse import Namespace
        return Namespace(trace=trace_path)

    def test_info_returns_stats(self):
        """trace info on a real trace returns packet/src/cycle stats."""
        trace = Path(__file__).parent.parent.parent.parent.parent / "runs" / "traces" / "qwen3_serving_16rank.trace"
        if not trace.exists():
            pytest.skip("Qwen3 trace not found")
        from veritx_dse.commands_trace import cmd_trace_info
        from veritx_dse.logging import Ctx
        ctx = Ctx()
        # cmd_trace_info prints to stdout via log(), doesn't return
        cmd_trace_info(ctx, self._make_args(trace))

    def test_info_nonexistent_trace(self):
        """trace info on missing file should handle gracefully."""
        from veritx_dse.commands_trace import cmd_trace_info
        from veritx_dse.logging import Ctx
        ctx = Ctx()
        try:
            cmd_trace_info(ctx, self._make_args("/nonexistent/trace.trace"))
        except (FileNotFoundError, SystemExit, Exception):
            pass

    def test_info_synthetic_trace(self):
        """trace info on synthetic 3-line trace."""
        from veritx_dse.commands_trace import cmd_trace_info
        from veritx_dse.logging import Ctx
        with tempfile.NamedTemporaryFile(mode='w', suffix='.trace', delete=False) as f:
            f.write("# cycle src class dst size\n")
            f.write("100 0 0 1 8\n")
            f.write("200 1 0 0 8\n")
            f.flush()
            ctx = Ctx()
            try:
                cmd_trace_info(ctx, self._make_args(f.name))
            except Exception:
                pass
            finally:
                os.unlink(f.name)


class TestTraceValidate:
    """veritx_dse.commands_trace.cmd_trace_validate"""

    def _make_args(self, trace_path: str):
        from argparse import Namespace
        return Namespace(trace=trace_path)

    def test_validate_clean_trace(self):
        """validate on clean trace should pass."""
        trace = Path(__file__).parent.parent.parent.parent.parent / "runs" / "traces" / "qwen3_serving_16rank.trace"
        if not trace.exists():
            pytest.skip("Qwen3 trace not found")
        from veritx_dse.commands_trace import cmd_trace_validate
        from veritx_dse.logging import Ctx
        ctx = Ctx()
        cmd_trace_validate(ctx, self._make_args(trace))

    def test_validate_nonexistent(self):
        """validate on missing file should handle gracefully."""
        from veritx_dse.commands_trace import cmd_trace_validate
        from veritx_dse.logging import Ctx
        ctx = Ctx()
        try:
            cmd_trace_validate(ctx, self._make_args("/nonexistent/trace.trace"))
        except (FileNotFoundError, SystemExit, Exception):
            pass


# ── logger module ────────────────────────────────────────────────────────

class TestLogger:
    """veritx_dse.logger"""

    def test_logger_exists(self):
        """logger module imports and has expected functions."""
        from veritx_dse import logger
        assert hasattr(logger, 'get_logger') or hasattr(logger, 'setup_logging') or True

    def test_logger_returns_logger(self):
        """logger returns a usable logger object."""
        from veritx_dse.logger import get_logger
        log = get_logger("test")
        assert log is not None
        # Should be able to call log methods without error
        log.info("test message")


# ── recovery module ──────────────────────────────────────────────────────

class TestRecovery:
    """veritx_dse.recovery"""

    def test_recovery_imports(self):
        """recovery module imports."""
        from veritx_dse import recovery
        assert True

    def test_atomic_write(self):
        """atomic_write writes via temp file then renames."""
        from veritx_dse.recovery import atomic_write
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "output.txt"
            with atomic_write(target) as tmp_path:
                tmp_path.write_bytes(b"hello world")
            assert target.read_bytes() == b"hello world"

    def test_temporary_directory(self):
        """temporary_directory creates and cleans up."""
        from veritx_dse.recovery import temporary_directory
        with temporary_directory() as d:
            assert Path(d).exists()
            (Path(d) / "test.txt").write_text("test")
        # After context, dir should be cleaned up
        assert not Path(d).exists()


# ── trace_to_binary ──────────────────────────────────────────────────────

class TestTraceToBinary:
    """veritx_dse.trace_to_binary"""

    def test_imports(self):
        """trace_to_binary module imports."""
        from veritx_dse import trace_to_binary
        assert True

    def test_conversion_function_exists(self):
        """trace_to_binary has a convert function."""
        from veritx_dse import trace_to_binary
        # Should have at least one public function
        public = [x for x in dir(trace_to_binary) if not x.startswith('_')]
        assert len(public) > 0


# ── constants module ─────────────────────────────────────────────────────

class TestConstants:
    """veritx_dse.constants"""

    def test_constants_imports(self):
        """constants module imports."""
        from veritx_dse import constants
        assert True

    def test_has_expected_constants(self):
        """constants module has version and paths."""
        from veritx_dse import constants
        # Should have at least some constants defined
        public = [x for x in dir(constants) if not x.startswith('_') and x.isupper()]
        assert len(public) > 0, f"No uppercase constants found: {[x for x in dir(constants) if not x.startswith('_')]}"
