"""Phase-3 evidence/bundle hardening: anti-transplant, identity binding,
bundle integrity and reproduction pinning.

Each test names the exact hole it closes. Builders emulate a
currently-qualified producer and stamp the live certified recipe
constant (``ev.BOOKSIM_BUILD_RECIPE_VERSION``), never a hardcoded
generation.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend import evidence as ev  # noqa: E402
from veritx_dse.backend.booksim_adapter import (  # noqa: E402
    BOOKSIM_MODEL_FIDELITY,
)
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    MetricValue, NormalizedBackendEvidence, NormalizedEvidenceError,
    assert_envelope_matches_native,
)
from veritx_dse.backend.reproduce import (  # noqa: E402
    _canonical_stats, _pinned_binary,
)
from veritx_dse.backend.reproduce import (  # noqa: E402
    _admitted_evidence,
)
from veritx_dse.core.run_bundle import (  # noqa: E402
    CHECKSUMS_NAME, RunBundleError, finalize_run_bundle,
    read_verified_file, verify_run_bundle,
)

def _native(**over) -> "ev.ScientificBackendEvidence":
    fields = {
        "prepared_id": "a" * 64,
        "profile_id": "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
        "projection_semantics_version": "v1",
        "config_sha256": "b" * 64,
        "trace_sha256": "c" * 64,
        "topology_sha256": None,
        "resolved_fabric_hash": "d" * 64,
        "physical_traffic_id": "e" * 64,
        "message_artifact_id": "f" * 64,
        "binary_sha256": "0" * 64,
        "binary_size": 123,
        "producer_source_revision": "1" * 40,
        "producer_dirty": False,
        "seed": 0,
        "parser_version": ev.PARSER_VERSION,
        "execution_fidelity": "QUALIFIED",
        "route_observation": "EXECUTED_ROUTE_OBSERVED",
        "stats": {"completion_cycles": 100, "flits_by_class": {0: 10}},
        "exit_status": 0,
        "transport": ev.EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
        "build_manifest_sha256": "9" * 64,
        "build_recipe_version": ev.BOOKSIM_BUILD_RECIPE_VERSION,
        "route_dump_sha256": "7" * 64,
    }
    fields.update(over)
    return ev.ScientificBackendEvidence(**fields)

def _envelope(native, **over) -> NormalizedBackendEvidence:
    kwargs = {
        "backend_id": "BOOKSIM_STANDALONE",
        "question": EvaluationQuestion.NETWORK_COMPLETION,
        "model_fidelity": BOOKSIM_MODEL_FIDELITY,
        "canonical_parent_ids": (
            "ab" * 32,
            native.resolved_fabric_hash,
            "wl",
            native.message_artifact_id,
            native.physical_traffic_id,
        ),
        "native_evidence_id": native.evidence_id(),
        "qualification": native.execution_fidelity,
        "producer_identity": native.binary_sha256,
        "metrics": (
            MetricValue(key="completion_cycles", value=100.0, unit=None,
                        source_metric_key="completion_cycles"),
        ),
    }
    kwargs.update(over)
    return NormalizedBackendEvidence(**kwargs)

def test_admit_normalize_evidence_accepts_bound_bytes(tmp_path):
    ref = ev.write_evidence(tmp_path, {"evidence": _native().to_dict(),
                                       "attempt": {}})
    got = ev.admit_normalize_evidence(
        Path(ref.path), prepared_id="a" * 64, config_sha256="b" * 64,
        trace_sha256="c" * 64, binary_sha256="0" * 64)
    assert got.evidence_id() == _native().evidence_id()

def test_copied_file_with_wrong_binding_refuses(tmp_path):
    ref = ev.write_evidence(tmp_path, {"evidence": _native().to_dict(),
                                       "attempt": {}})
    other = tmp_path / "other"
    other.mkdir()
    shutil.copy2(ref.path, other / "backend-evidence.json")
    with pytest.raises(ev.BackendEvidenceError, match="prepared_id"):
        ev.admit_normalize_evidence(
            other / "backend-evidence.json", prepared_id="f" * 64,
            config_sha256="b" * 64, trace_sha256="c" * 64,
            binary_sha256="0" * 64)

def test_wrong_reference_digest_refuses(tmp_path):
    ref = ev.write_evidence(tmp_path, {"evidence": _native().to_dict(),
                                       "attempt": {}})
    bad = ev.EvidenceRef(path=ref.path, sha256="1" * 64)
    with pytest.raises(ev.BackendEvidenceError, match="does not match"):
        ev.read_verified_evidence(bad)

def test_diagnostic_bundle_refuses_admission(tmp_path):
    injected = _native(
        execution_fidelity="TEST_INJECTED",
        transport=ev.EXECUTION_TRANSPORT_TEST_INJECTED).to_dict()
    (tmp_path / "backend-evidence.json").write_text(
        json.dumps({"evidence": injected, "attempt": {}}), encoding="utf-8")
    with pytest.raises(RunBundleError,
                       match="not reproducible certified evidence"):
        _admitted_evidence(tmp_path)

def test_prefixed_and_bare_forms_bind_equally():
    record = ev.ExecutionRecord(
        evidence=_native(prepared_id="sha256:" + "a" * 64),
        attempt=ev.ExecutionAttempt(
            wall_time_s=0.0, run_dir="", binary_path="", command=(),
            host="", platform=""))
    got = ev.verify_reusable_record(
        record, prepared_id="a" * 64, config_sha256="b" * 64,
        trace_sha256="c" * 64, binary_sha256="0" * 64)
    assert got.prepared_id == "sha256:" + "a" * 64

def test_mutated_digest_still_refuses():
    record = ev.ExecutionRecord(
        evidence=_native(),
        attempt=ev.ExecutionAttempt(
            wall_time_s=0.0, run_dir="", binary_path="", command=(),
            host="", platform=""))
    with pytest.raises(ev.BackendEvidenceError, match="prepared_id"):
        ev.verify_reusable_record(
            record, prepared_id="b" * 64, config_sha256="b" * 64,
            trace_sha256="c" * 64, binary_sha256="0" * 64)
    with pytest.raises(ev.BackendEvidenceError):
        ev.canonical_hex64("not-a-digest", "probe")

def test_pinned_binary_refuses_swapped_producer(tmp_path):
    from veritx_dse.core.build_manifest import write_build_manifest
    bin_a = tmp_path / "binA"
    bin_a.write_bytes(b"A" * 128)
    write_build_manifest(bin_a,
                         recipe_version=ev.BOOKSIM_BUILD_RECIPE_VERSION)
    manifest_a = tmp_path / "binA.build-manifest.json"
    manifest_sha = hashlib.sha256(
        manifest_a.read_bytes()).hexdigest()
    native = _native(
        binary_sha256=hashlib.sha256(b"A" * 128).hexdigest(),
        binary_size=128, build_manifest_sha256=manifest_sha)
    assert _pinned_binary(native, bin_a, None) == bin_a
    bin_b = tmp_path / "binB"
    bin_b.write_bytes(b"B" * 128)
    with pytest.raises(RunBundleError, match="does not match the evidence"):
        _pinned_binary(native, bin_b, None)

def test_matching_envelope_passes():
    native = _native()
    assert_envelope_matches_native(_envelope(native), native)

def test_swapped_statistics_refuse():
    native = _native()
    env = _envelope(
        native,
        metrics=(MetricValue(key="completion_cycles", value=999.0,
                             unit=None,
                             source_metric_key="completion_cycles"),))
    with pytest.raises(NormalizedEvidenceError, match="does not equal"):
        assert_envelope_matches_native(env, native)

def test_envelope_pointing_at_another_run_refuses():
    native = _native()
    other = _native(trace_sha256="2" * 64)
    env = _envelope(native, native_evidence_id=other.evidence_id())
    with pytest.raises(NormalizedEvidenceError,
                       match="another run's evidence"):
        assert_envelope_matches_native(env, native)

def test_envelope_missing_parent_refuses():
    native = _native()
    env = _envelope(native, canonical_parent_ids=("dd" * 32,))
    with pytest.raises(NormalizedEvidenceError, match="omit"):
        assert_envelope_matches_native(env, native)

def test_derived_metric_without_source_is_not_value_checked():
    native = _native()
    env = _envelope(
        native,
        metrics=(MetricValue(key="ratio", value=0.5, unit=None,
                             source_metric_key=None),))
    assert_envelope_matches_native(env, native)

def _sealed(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("science\n", encoding="utf-8")
    finalize_run_bundle(root)
    return root

def test_finalize_refuses_symlink(tmp_path):
    root = tmp_path / "run"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("science\n", encoding="utf-8")
    (root / "link").symlink_to(root / "a.txt")
    with pytest.raises(RunBundleError, match="symlink"):
        finalize_run_bundle(root)

def test_fifo_is_never_bundle_content(tmp_path):
    root = tmp_path / "run"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("science\n", encoding="utf-8")
    try:
        os.mkfifo(root / "pipe")
    except (AttributeError, OSError):
        pytest.skip("fifo unsupported on this platform")
    summary = finalize_run_bundle(root)
    assert summary["file_count"] == 1
    assert verify_run_bundle(root)["bundle_id"] == summary["bundle_id"]

def test_stale_checksum_temp_does_not_break_verify(tmp_path):
    root = _sealed(tmp_path)
    (root / ".checksums-9").write_text("crash leftover", encoding="utf-8")
    assert verify_run_bundle(root)["bundle_id"]
    finalize_run_bundle(root)
    assert not (root / ".checksums-9").exists()
    verify_run_bundle(root)

def test_manifest_declaring_foreign_bundle_id_refuses(tmp_path):
    root = tmp_path / "run"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("science\n", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "bundle_id": "0" * 64}),
        encoding="utf-8")
    finalize_run_bundle(root)
    with pytest.raises(RunBundleError, match="does not describe"):
        verify_run_bundle(root)

def test_manifest_without_bundle_id_seals_and_verifies(tmp_path):
    root = tmp_path / "run"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("science\n", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "note": "run metadata"}),
        encoding="utf-8")
    summary = finalize_run_bundle(root)
    assert summary["file_count"] == 2
    assert verify_run_bundle(root)["bundle_id"] == summary["bundle_id"]

def test_manifest_added_after_finalize_is_undeclared(tmp_path):
    root = _sealed(tmp_path)
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(RunBundleError, match="undeclared"):
        verify_run_bundle(root)

def test_read_verified_file_pins_bytes(tmp_path):
    root = _sealed(tmp_path)
    assert read_verified_file(root, "a.txt") == b"science\n"
    (root / "a.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(RunBundleError, match="changed after verification"):
        read_verified_file(root, "a.txt")
    with pytest.raises(RunBundleError, match="not sealed"):
        read_verified_file(root, "nope.txt")

def test_int_and_str_keys_compare_equal():
    fresh = {"completion_cycles": 1000,
             "flits_by_class": {0: {"injected": 10, "accepted": 10}}}
    persisted = {"completion_cycles": 1000,
                 "flits_by_class": {"0": {"injected": 10, "accepted": 10}}}
    assert _canonical_stats(fresh) == _canonical_stats(persisted)

def test_genuine_divergence_still_refuses():
    fresh = {"completion_cycles": 1000,
             "flits_by_class": {0: {"injected": 10, "accepted": 9}}}
    persisted = {"completion_cycles": 1000,
                 "flits_by_class": {"0": {"injected": 10, "accepted": 10}}}
    assert _canonical_stats(fresh) != _canonical_stats(persisted)
