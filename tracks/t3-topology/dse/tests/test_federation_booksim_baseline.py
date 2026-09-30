"""FEDERATION COMMIT 01 — characterization of the current product truth.

Freezes what ``FabricEvaluator.evaluate`` does TODAY so an adapter
refactor that changes externally visible behavior fails here first.
Nothing here may be relaxed to make new architecture pass: changing an
assertion means the product contract changed, and the commit must say so.

Happy-path tests skip (never lie) when the pinned producer cannot be
qualified in this worktree; that skip condition is itself pinned as a
typed BACKEND_UNAVAILABLE.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    BACKEND_UNAVAILABLE, EVALUATED, UNSUPPORTED,
    EvaluationError, FabricEvaluator,
)
from veritx_dse.backend.evidence import read_verified_evidence  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402
from veritx_dse.workload.graph import WorkloadGraph  # noqa: E402
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    lower_compile_workload,
)

DENSE = REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json"

_DIRTY_MARKERS = ("producer tree is DIRTY", "no verified build-time manifest")

def _dense_request():
    return parse_request_doc(json.loads(DENSE.read_text(encoding="utf-8")))

def _binary() -> Path | None:
    try:
        return find_booksim_bin(REPO)
    except FileNotFoundError:
        return None

def _options(tmp_path, **opts):
    from veritx_dse.application.fabric_evaluator import EvaluationOptions
    base = dict(
        network_clock_hz=1_000_000_000,
        timeout_s=600,
        run_dir=str(Path(tmp_path) / "eval"),
        repo_root=str(REPO),
    )
    base.update(opts)
    if base.get("binary") is None:
        found = _binary()
        if found is not None:
            base["binary"] = str(found)
    return EvaluationOptions(**base)

def _evaluate(tmp_path, request, **opts):
    """One round trip; the lowered intent class is asserted through the
    options by default (evaluation asserts, never relabels) unless a test
    overrides ``traffic_class=`` deliberately."""
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.status
    lowered = lower_compile_workload(request)
    opts.setdefault("traffic_class", lowered.unified_traffic_class)
    return FabricEvaluator().evaluate(
        compilation, lowered.graph,
        _options(tmp_path, **opts)), compilation, lowered

def _skip_if_producer_unqualified(outcome):
    """A parallel dirty tree is an environment condition, not a behavior
    change — skip, never lie."""
    if outcome.status != EVALUATED:
        reason = outcome.reason or ""
        assert outcome.status == BACKEND_UNAVAILABLE, (
            f"{outcome.status}: {reason}")
        assert any(marker in reason for marker in _DIRTY_MARKERS), reason
        pytest.skip(f"pinned producer unqualified in this worktree: {reason}")

def test_supported_mesh_request_evaluates_with_authenticated_evidence(
        tmp_path):
    outcome, _compilation, _lowered = _evaluate(tmp_path, _dense_request())
    _skip_if_producer_unqualified(outcome)

    assert outcome.status == EVALUATED, outcome.reason
    assert outcome.design_hash and len(outcome.design_hash) == 64
    assert outcome.resolved_fabric_hash and len(
        outcome.resolved_fabric_hash) == 64
    assert outcome.workload_id and len(
        outcome.workload_id.split(":")[-1]) == 64
    assert outcome.message_artifact_id and outcome.physical_traffic_id
    assert outcome.backend == "BOOKSIM_STANDALONE"
    assert outcome.backend_profile == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
    assert outcome.producer_identity and len(outcome.producer_identity) == 64
    assert outcome.backend_config_hash and outcome.backend_input_hash
    assert outcome.realization_digest
    assert outcome.evidence_path and Path(outcome.evidence_path).is_file()
    assert outcome.raw_evidence_digest and outcome.stats_digest
    assert outcome.performance_result_id is not None
    assert outcome.performance_result, "no verified performance result"
    assert outcome.network_traffic_window, "no completion window bound"
    assert isinstance(outcome.metrics, dict) and outcome.metrics
    assert "completion_cycles" in outcome.metrics
    assert outcome.fidelity_warning is not None, \
        "EVALUATED outcome must carry its calibration qualifier"
    assert "UNCALIBRATED" in outcome.fidelity_warning, \
        outcome.fidelity_warning

def test_same_request_and_seed_reproduces_scientific_identities(tmp_path):
    """Determinism law: identical request + producer + seed reproduces
    every scientific identity byte-for-byte; only run transport differs."""
    request = _dense_request()
    first, _c1, _l1 = _evaluate(tmp_path, request)
    _skip_if_producer_unqualified(first)

    from veritx_dse.application.fabric_evaluator import EvaluationOptions
    compilation = FabricCompiler().compile(request)
    lowered = lower_compile_workload(request)
    second = FabricEvaluator().evaluate(
        compilation, lowered.graph,
        EvaluationOptions(
            network_clock_hz=1_000_000_000, timeout_s=600,
            traffic_class=lowered.unified_traffic_class,
            run_dir=str(Path(tmp_path) / "eval-2"), repo_root=str(REPO),
            binary=str(_binary())))

    assert second.status == EVALUATED, second.reason
    identical = (
        "design_hash", "resolved_fabric_hash", "workload_id",
        "message_artifact_id", "physical_traffic_id", "backend",
        "backend_profile", "backend_config_hash", "backend_input_hash",
        "raw_evidence_digest", "stats_digest", "realization_digest",
        "performance_result_id")
    for field in identical:
        assert getattr(first, field) == getattr(second, field), field
    assert first.run_dir != second.run_dir

def test_unsupported_topology_family_refuses_at_compile(tmp_path):
    """Torus: authorable, routes via DOR_TORUS_XY, but the certificate
    fails DEADLOCK_FREE (dateline-proof pending) — a compile verdict
    with staged artifacts, no evaluation state ever produced."""
    request_doc = json.loads(DENSE.read_text(encoding="utf-8"))
    request_doc["noc_config"]["topology_family"] = "torus"
    compilation = FabricCompiler().compile(parse_request_doc(request_doc))

    assert compilation.status == "INVALID", compilation.status
    assert compilation.bundle is None
    assert compilation.certificate is None or \
        getattr(compilation.certificate, "overall", None) != "PASS"

def test_missing_booksim_binary_is_typed_backed_unavailable(tmp_path):
    outcome, _c, _l = _evaluate(
        tmp_path, _dense_request(), binary="/nonexistent/booksim")

    assert outcome.status == BACKEND_UNAVAILABLE, outcome.status
    assert "BookSim binary not found" in (outcome.reason or "")
    assert outcome.backend_profile == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
    assert outcome.backend_config_hash is not None
    assert outcome.producer_identity is None

def test_undeclared_traffic_class_is_refused_by_vc_admission(tmp_path):
    """Never silently mapped to VC0."""
    outcome, _c, _l = _evaluate(
        tmp_path, _dense_request(), traffic_class="MADE_UP")

    assert outcome.status == UNSUPPORTED, outcome.status
    reason = outcome.reason or ""
    assert ("not declared by the VC assignment" in reason
            or "eval-time relabeling is refused" in reason), reason

def test_wrong_workload_graph_refuses_before_any_backend_work(tmp_path):
    """The foreign graph is another request's TRUE lowering (payload
    changed), so the only difference is seam identity — proving
    re-derivation, not shape checking. No run dir is ever created."""
    request = _dense_request()
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED"
    other_doc = json.loads(DENSE.read_text(encoding="utf-8"))
    other_doc["workload"]["collectives"][0]["payload_bytes"] = 4096
    other_graph = lower_compile_workload(
        parse_request_doc(other_doc)).graph
    assert other_graph.workload_id() != \
        lower_compile_workload(request).graph.workload_id()

    run_dir = Path(tmp_path) / "eval"
    with pytest.raises(EvaluationError) as excinfo:
        FabricEvaluator().evaluate(
            compilation, other_graph,
            _options(tmp_path,
                     traffic_class=lower_compile_workload(
                         request).unified_traffic_class))
    assert "workload" in str(excinfo.value).lower() or \
        "lowering" in str(excinfo.value).lower(), str(excinfo.value)
    assert not run_dir.exists()

def test_tampered_evidence_bytes_are_refused_at_readback(tmp_path):
    outcome, _c, _l = _evaluate(tmp_path, _dense_request())
    _skip_if_producer_unqualified(outcome)

    path = Path(outcome.evidence_path)
    original = path.read_bytes()
    assert original, "empty evidence file"
    path.write_bytes(original.replace(b'"completion_cycles"', b'"taper_cycles"')
                     if b'"completion_cycles"' in original
                     else original + b" ")
    from veritx_dse.backend.evidence import BackendEvidenceError
    with pytest.raises(BackendEvidenceError):
        read_verified_evidence(
            type("Ref", (), {"path": str(path),
                             "sha256": outcome.raw_evidence_digest})())
    path.write_bytes(original)

def test_golden_evaluation_view_shape_is_frozen(tmp_path):
    """The view contract the Studio consumes; changing this shape changes
    the product contract."""
    outcome, _c, _l = _evaluate(
        tmp_path, _dense_request(), traffic_class="MADE_UP")
    view = outcome.to_view_dict()

    assert set(view) == {
        "contract_version", "status", "design_hash",
        "resolved_fabric_hash", "workload_id", "message_artifact_id",
        "physical_traffic_id", "backend_producer", "evidence",
        "performance_result_id", "network_traffic_window", "metrics",
        "fidelity_warning", "reason"}
    assert view["contract_version"] == 1
    assert view["status"] == "UNSUPPORTED"
    for key in ("design_hash", "resolved_fabric_hash", "workload_id",
                "message_artifact_id", "physical_traffic_id"):
        value = view[key]
        assert value is not None and len(value) >= 64, key
        assert len(value.split(":")[-1]) == 64, key
    assert view["backend_producer"] is None
    assert view["evidence"] is None
    assert view["performance_result_id"] is None
    assert view["network_traffic_window"] is None
    assert view["metrics"] is None
    assert view["fidelity_warning"] is None
    reason = view["reason"]
    assert ("not declared by the VC assignment" in reason
            or "eval-time relabeling is refused" in reason), reason

def test_dirty_producer_refusal_is_typed_backed_unavailable(tmp_path):
    """Pin the exact refusal this suite skips on: typed BACKEND_UNAVAILABLE,
    never a crash, never EVALUATED, never a silent downgrade."""
    outcome, _c, _l = _evaluate(tmp_path, _dense_request())
    if outcome.status == EVALUATED:
        pytest.skip("producer is pinned in this worktree; nothing to pin")
    assert outcome.status == BACKEND_UNAVAILABLE
    reason = outcome.reason or ""
    assert ("producer tree is DIRTY" in reason
            or "no verified build-time manifest" in reason), reason
    assert outcome.producer_identity is None
    assert outcome.raw_evidence_digest is None
