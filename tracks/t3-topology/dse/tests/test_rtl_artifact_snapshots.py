"""Downloads pin bytes, not just a mutable pathname or inode."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.product import rtl_prototypes


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    root = tmp_path / "trusted"
    source = root / "mesh8x8" / "CandidateNoCTop.v"
    source.parent.mkdir(parents=True)
    original = b"a" * (1024 * 1024) + b"b" * (1024 * 1024) + b"tail"
    source.write_bytes(original)
    monkeypatch.setenv("VERITX_RTL_RESEARCH_ROOTS", str(root))
    row = next(row for row in rtl_prototypes.list_prototypes() if row["topology_id"] == "mesh8x8")
    return source, original, row["artifacts"][0]["version"]


def test_download_is_pinned_before_first_stream_read(artifact):
    source, original, version = artifact
    chunks, size = rtl_prototypes.stream_artifact("mesh8x8", source.name, version)
    source.write_bytes(b"replacement")
    assert size == len(original)
    assert b"".join(chunks) == original


def test_in_place_write_between_stream_chunks_cannot_mix_download(artifact):
    source, original, version = artifact
    chunks, size = rtl_prototypes.stream_artifact("mesh8x8", source.name, version)
    first = next(chunks)
    source.write_bytes(b"x" * len(original))
    assert first + b"".join(chunks) == original
    assert size == len(original)


def test_mutation_during_snapshot_is_rejected_and_source_descriptor_closed(artifact, monkeypatch):
    source, original, version = artifact
    read = os.read
    descriptors = []

    def mutate_after_first_read(fd, size):
        data = read(fd, size)
        if not descriptors:
            descriptors.append(fd)
            source.write_bytes(b"x" * len(original))
        return data

    monkeypatch.setattr(rtl_prototypes.os, "read", mutate_after_first_read)
    with pytest.raises(FileNotFoundError, match="changed while taking download snapshot"):
        rtl_prototypes.stream_artifact("mesh8x8", source.name, version)
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
