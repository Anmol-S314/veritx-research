"""Build provenance must not clean, stage or commit the user's dirty checkout."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from snapshot_sources import snapshot


def git(root, *arguments):
    return subprocess.check_output(["git", "-c", "user.name=Snapshot test", "-c",
        "user.email=test@localhost", "-c", "commit.gpgsign=false", "-c",
        "core.hooksPath=/dev/null", *arguments], cwd=root, text=True).strip()


class SnapshotTest(unittest.TestCase):
    def test_dirty_inputs_are_committed_separately_and_origin_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "original"
            source = repo / "third_party/booksim2/src"
            recipe = repo / "apps/studio/prototype/desktop/windows"
            source.mkdir(parents=True)
            recipe.mkdir(parents=True)
            header = source / "booksim.hpp"
            header.write_text("original header\n")
            for name in ("build_booksim.sh", "snapshot_sources.py"):
                (recipe / name).write_text("recipe fixture\n")
            git(repo, "init", "-q")
            git(repo, "add", ".")
            git(repo, "commit", "-q", "-m", "original")
            original_revision = git(repo, "rev-parse", "HEAD")
            header.write_text("modified Windows header\n")
            (source / "stale.o").write_bytes(b"native object")
            before_status = git(repo, "status", "--porcelain")
            before_index = (repo / ".git/index").read_bytes()
            first = snapshot(repo, Path(directory) / "snapshots", "booksim")
            second = snapshot(repo, Path(directory) / "snapshots", "booksim")
            self.assertEqual(git(repo, "rev-parse", "HEAD"), original_revision)
            self.assertEqual(git(repo, "status", "--porcelain"), before_status)
            self.assertEqual((repo / ".git/index").read_bytes(), before_index)
            self.assertEqual(git(first, "status", "--porcelain"), "")
            self.assertEqual(git(first, "rev-parse", "HEAD"), git(second, "rev-parse", "HEAD"))
            self.assertEqual((first / "third_party/booksim2/src/booksim.hpp").read_text(), header.read_text())
            self.assertFalse((first / "third_party/booksim2/src/stale.o").exists())
            origin = json.loads((first / "SOURCE_ORIGIN.json").read_text())
            self.assertTrue(origin["origin_producer_dirty"])
            self.assertEqual(origin["origin_revision"], original_revision)


if __name__ == "__main__":
    unittest.main()
