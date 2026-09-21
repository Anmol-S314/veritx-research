"""tests/test_evidence_artifact.py — M1.4: the evidence identity.

An EvidenceArtifact names the backend input, the exact raw bytes, the parser
version that read them and the stats digest they carry. Stats without raw
evidence refuse; a different reader is a different claim; tampered bytes or
stats refuse; a valid artifact cannot authenticate another run's bytes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.backend.evidence import (  # noqa: E402
    BackendEvidenceError, EvidenceArtifact, EvidenceRef,
    LEGACY_PARSER_VERSION, PARSER_VERSION, stats_sha256_of, write_evidence,
)

STATS = {"completion_time": 128, "delivered": 4, "cycles": 1000}
INPUT_SHA = "a" * 64
RAW_SHA = "b" * 64


def artifact(**over):
    kw = dict(backend="CERTIFIED_BOOKSIM_SUPERVISED",
              backend_input_id=INPUT_SHA, backend_input_sha256=INPUT_SHA,
              raw_evidence_sha256=RAW_SHA, stats=STATS)
    kw.update(over)
    return EvidenceArtifact.build(**kw)


def test_stats_digest_is_of_the_canonical_stats():
    ev = artifact()
    assert ev.stats_sha256 == stats_sha256_of(STATS)
    assert EvidenceArtifact.build(
        backend=ev.backend, backend_input_id=ev.backend_input_id,
        backend_input_sha256=INPUT_SHA, raw_evidence_sha256=RAW_SHA,
        stats=STATS).evidence_id() == ev.evidence_id()


def test_stats_without_raw_evidence_refuse():
    with pytest.raises(BackendEvidenceError):
        EvidenceArtifact.from_verified_evidence(
            {"backend_input_hash": INPUT_SHA, "stats": STATS},
            "/tmp/naked-path-has-no-identity.json")
    with pytest.raises(BackendEvidenceError):
        stats_sha256_of({})


def test_parser_version_is_identity_bearing():
    a = artifact(parser_version="reader/1")
    b = artifact(parser_version="reader/2")
    assert a.evidence_id() != b.evidence_id()
    assert a.authenticates(backend_input_sha256=INPUT_SHA,
                           raw_evidence_sha256=RAW_SHA, stats=STATS)


def test_changed_stats_move_the_identity():
    a = artifact()
    b = artifact(stats={**STATS, "delivered": 5})
    assert a.stats_sha256 != b.stats_sha256
    assert a.evidence_id() != b.evidence_id()
    assert not a.authenticates(backend_input_sha256=INPUT_SHA,
                               raw_evidence_sha256=RAW_SHA,
                               stats={**STATS, "delivered": 5})


def test_hand_set_stats_digest_does_not_authenticate_real_stats():
    """The constructor pins the digest it is given; it cannot authenticate
    stats that do not hash to it. Only `build` recomputes, so a forged
    digest never survives `from_verified_evidence` or `from_dict`."""
    ev = artifact()
    stale = EvidenceArtifact(ev.backend, ev.backend_input_id,
                             ev.backend_input_sha256, ev.raw_evidence_sha256,
                             ev.parser_version, "0" * 64)
    assert not stale.authenticates(backend_input_sha256=INPUT_SHA,
                                   raw_evidence_sha256=RAW_SHA, stats=STATS)
    assert stale.evidence_id() != ev.evidence_id()


def test_invalid_digests_and_names_refuse():
    with pytest.raises(BackendEvidenceError):
        artifact(backend_input_sha256="not-a-digest")
    with pytest.raises(BackendEvidenceError):
        artifact(raw_evidence_sha256="zz" + "0" * 62)
    with pytest.raises(BackendEvidenceError):
        artifact(backend="")


class TestPersistence:
    def test_strict_round_trip(self):
        ev = artifact()
        assert EvidenceArtifact.from_dict(ev.to_dict()).evidence_id() == \
            ev.evidence_id()

    def test_re_signed_evidence_id_refuses(self):
        ev = artifact()
        d = ev.to_dict()
        d["evidence_id"] = "f" * 64
        with pytest.raises(BackendEvidenceError):
            EvidenceArtifact.from_dict(d)

    def test_swapped_stats_refuse(self):
        ev = artifact()
        d = ev.to_dict()
        d["stats_sha256"] = "e" * 64
        with pytest.raises(BackendEvidenceError):
            EvidenceArtifact.from_dict(d)


class TestFromVerifiedEvidence:
    @staticmethod
    def _write(tmp_path, **over):
        doc = {"backend_input_hash": INPUT_SHA, "stats": dict(STATS),
               "backend_config_hash": "c" * 64}
        doc.update(over)
        return write_evidence(tmp_path, doc)

    def test_verified_document_yields_a_stable_artifact(self, tmp_path):
        from veritx_dse.backend.evidence import read_verified_evidence
        ref = self._write(tmp_path)
        ev = EvidenceArtifact.from_verified_evidence(
            read_verified_evidence(ref), ref)
        assert ev.raw_evidence_sha256 == ref.sha256
        assert ev.parser_version == LEGACY_PARSER_VERSION
        assert ev.evidence_id() == \
            EvidenceArtifact.from_verified_evidence(
                read_verified_evidence(ref), ref).evidence_id()

    def test_document_parser_version_is_honoured(self, tmp_path):
        from veritx_dse.backend.evidence import read_verified_evidence
        ref = self._write(tmp_path, parser_version=PARSER_VERSION)
        ev = EvidenceArtifact.from_verified_evidence(
            read_verified_evidence(ref), ref)
        assert ev.parser_version == PARSER_VERSION

    def test_missing_bindings_refuse(self):
        with pytest.raises(BackendEvidenceError):
            EvidenceArtifact.from_verified_evidence(
                {"stats": STATS}, EvidenceRef(path="p", sha256="0" * 64))
        with pytest.raises(BackendEvidenceError):
            EvidenceArtifact.from_verified_evidence(
                {"backend_input_hash": INPUT_SHA},
                EvidenceRef(path="p", sha256="0" * 64))
