"""Unit tests for core utility modules: logging, recovery, constants."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

class TestLogger:
    """veritx_dse.logger"""

    def test_logger_returns_logger(self):
        """get_logger returns a usable logger object."""
        from veritx_dse.core.logging import get_logger
        log = get_logger("test")
        assert log is not None
        log.info("test message")

class TestRecovery:
    """veritx_dse.recovery"""

    def test_atomic_write(self):
        """atomic_write writes via temp file then renames."""
        from veritx_dse.core.recovery import atomic_write
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "output.txt"
            with atomic_write(target) as tmp_path:
                tmp_path.write_bytes(b"hello world")
            assert target.read_bytes() == b"hello world"

    def test_temporary_directory(self):
        """temporary_directory creates and cleans up."""
        from veritx_dse.core.recovery import temporary_directory
        with temporary_directory() as d:
            assert Path(d).exists()
            (Path(d) / "test.txt").write_text("test")
        assert not Path(d).exists()

class TestConstants:
    """veritx_dse.constants"""

    def test_has_expected_constants(self):
        """constants module has version and paths."""
        from veritx_dse import constants
        public = [x for x in dir(constants) if not x.startswith('_') and x.isupper()]
        assert len(public) > 0, f"No uppercase constants found: {[x for x in dir(constants) if not x.startswith('_')]}"
