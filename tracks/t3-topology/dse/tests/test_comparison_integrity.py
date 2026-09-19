"""Phase 8 — scientific comparison integrity (ComparisonSpec enforcement).

Core principle under test: a comparison is valid only when every
scientifically relevant difference is either controlled-and-equal or an
explicitly declared experimental variable. Undeclared differences fail
closed. Tests live at the seams (spec parse, fingerprint resolution from
real run-dir files / legacy rows, evaluate_comparability, pareto_with_scope)
— never against internals.
"""
import json
from pathlib import Path

import pytest

from veritx_dse.core.comparison import (
    ComparisonIntent,
    ComparisonSpecError,
    eval_metric_compatibility,
    evaluate_comparability,
    fingerprint_from_legacy_row,
    fingerprint_from_run,
    resolve_intent,
    pareto_with_scope,
)
from veritx_dse.core.spec import ComparisonSpec, parse as parse_spec


# ── helpers ──────────────────────────────────────────────────────────────────

def _cs(**kw):
    return ComparisonSpec(**kw)


def _run_fingerprint(**kw):
    base = {
        "workload_hash": "w1", "node_count": 64, "participant_count": 64,
        "topology": "mesh_8x8", "routing": "dim_order", "vc_count": 2,
        "packetization": "64B", "simulator": "booksim2",
        "network_engine": None, "network_mode": "REAL_SIMULATION",
        "fidelity": "NETWORK_SIMULATION", "seed_policy": "deterministic:[42]",
        "tp": 1, "dp": 1, "ep": 1, "pp": 1, "instance_mapping": "single",
        "metric_schema": 1,
    }
    base.update(kw)
    return base


def _legacy_row(**kw):
    base = {"name": "mesh_8x8", "topology": "mesh_8x8", "nodes": 64,
            "seed": 42, "latency": 35.05, "honest_latency": 35.05,
            "sim_type": "latency", "ir": 0.05}
    base.update(kw)
    return base


def _cspec(variables=(), controlled=None, kind="DESIGN_COMPARISON",
           objectives=("latency",), **kw):
    return {
        "kind": kind,
        "objectives": list(objectives),
        "experimental_variables": list(variables),
        "controlled_dimensions": dict(controlled or {}),
        **kw,
    }


# ── ComparisonSpec parse/resolve (spec boundary) ─────────────────────────────

class TestComparisonSpecBoundary:
    def test_unknown_field_rejected(self):
        with pytest.raises(Exception):
            ComparisonSpec(experimental_variable=["topology"])

    def test_parse_via_experiment_spec(self):
        d = {
            "name": "x", "workload": {"id": "w", "trace": "t"},
            "system": {"nodes": 1}, "network": {"topology": "mesh_4x4"},
            "comparison": {"variable": ["topology"], "controlled": {"seed": "42"}},
        }
        spec = parse_spec(d)
        assert spec.comparison.variable == ["topology"]

    def test_empty_declaration_is_legal_and_conservative(self):
        # An empty declaration treats every dimension as controlled —
        # maximally fail-closed, not an error in itself. Refusals come
        # from material differences, never from the request shape.
        intent = resolve_intent({"objectives": ["latency"]})
        assert intent.experimental_variables == frozenset()
        assert intent.kind == "DESIGN_COMPARISON"


# ── fingerprint resolution ───────────────────────────────────────────────────

class TestFingerprints:
    def test_from_run_dir(self, tmp_path):
        run = tmp_path / "run1"
        (run / "artifacts").mkdir(parents=True)
        (run / "spec.resolved.json").write_text(json.dumps({
            "workload": {"id": "w", "trace": "archive/inputs/traces/x.trace"},
            "system": {"nodes": 8, "tp_size": 2, "instances_per_node": 1},
            # Study-integrity P0: serving specs carry NO network block —
            # the cluster owns fabric intent; identity comes from the
            # executed-fabric record below.
            "simulation": {"mode": "serving", "timeout_s": 60},
            "replication": {"mode": "deterministic", "seeds": [42]},
            "serving": {"cluster": "single_tp2_ep2", "dataset": "example",
                        "num_reqs": 1, "network_backend": "booksim",
                        "cycle_accurate": True,
                        "request_routing_policy": "LOAD",
                        "expected_fabric": {
                            "source": "serving_cluster", "topology": "mesh",
                            "routing": "dor", "dimensions": [2],
                            "npu_count": 2, "k": 2, "n": 1,
                            "num_vcs": 16, "vc_buf_size": 512,
                            "packet_size": 64}},
        }))
        (run / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "run_id": "run1", "status": "SUCCEEDED",
            "results": [{"task_id": "serve",
                         "provenance": {"engine": "llmservingsim",
                                        "network_backend": "booksim",
                                        "network_mode": "REAL_SIMULATION",
                                        "semantic_losses": [],
                                        "fidelity": "SYSTEM_SERVING_SIMULATION"},
                         "metric_schema": 1,
                         "executed_fabric": {
                             "topology": "mesh", "size": {"k": "2", "n": "1"},
                             "routing": "dor", "num_vcs": "16",
                             "vc_buf_size": "512", "packet_size": "64",
                             "config_sha256": "sha256:abc"},
                         "metrics": {"TTFT": {"value": 1.0, "unit": "ns",
                                              "producer": "llmservingsim",
                                              "fidelity": "SYSTEM_SERVING_SIMULATION",
                                              "scope": "per_request"}}}],
        }))
        # Canonical workload identity (Phase 9): a certified run carries
        # content-addressed workload artifacts — the fake writes the same
        # index the real slice emits for a single-rank workload.
        wl = tmp_path / "run1" / "workload"
        wl.mkdir(parents=True)
        (wl / "index.json").write_text(json.dumps({
            "schema_version": 1, "source_kind": "llmservingsim",
            "cluster_sha256": "cafe",
            "artifacts": [{"rank": 0, "trace": "trace/instance0_batch1.txt",
                           "artifact_hash": "sha256:w0"}]}))
        fp = fingerprint_from_run(run)
        assert fp["workload_hash"] == "sha256:w0"  # canonical artifact hash
        assert fp["node_count"] == 8
        # Serving topology/routing identity comes from EXECUTED evidence.
        assert fp["topology"] == "mesh"
        assert fp["routing"] == "dor"
        assert fp["vc_count"] == 16
        assert fp["packetization"] == 64
        assert fp["certified"] is True
        assert fp["certification_status"] == "RESOLVED"
        assert fp["simulator"] == "llmservingsim/booksim"
        assert fp["fidelity"] == "SYSTEM_SERVING_SIMULATION"
        assert fp["semantic_losses"] == []
        assert fp["seed_policy"] == "deterministic:[42]"

    def test_unresolved_mandatory_fields_are_never_certified(self, tmp_path):
        # Two candidates that BOTH fail to record a material parameter are
        # not equal on it — shared ignorance is not equality (P0 #7).
        run = tmp_path / "run1"
        run.mkdir()
        (run / "spec.resolved.json").write_text(json.dumps({
            "workload": {"id": "w", "trace": "archive/inputs/traces/x.trace"},
            "system": {"nodes": 8, "tp_size": 2, "instances_per_node": 1},
            "simulation": {"mode": "serving", "timeout_s": 60},
            "replication": {"mode": "deterministic", "seeds": [42]},
            "serving": {"cluster": "single_tp2_ep2", "dataset": "example",
                        "num_reqs": 1, "network_backend": "booksim",
                        "cycle_accurate": True,
                        "request_routing_policy": "LOAD"},
        }))
        (run / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "run_id": "run1", "status": "SUCCEEDED",
            "results": [{"task_id": "serve",
                         "provenance": {"engine": "llmservingsim",
                                        "network_backend": "booksim",
                                        "network_mode": "REAL_SIMULATION",
                                        "semantic_losses": [],
                                        "fidelity": "SYSTEM_SERVING_SIMULATION"},
                         "metric_schema": 1,
                         # NO executed_fabric record -> vc/packetization/
                         # topology/routing unresolved.
                         "metrics": {}}],
        }))
        fp = fingerprint_from_run(run)
        assert fp["vc_count"] is None
        assert fp["packetization"] is None
        assert fp["certified"] is False
        assert fp["certification_status"] == "INSUFFICIENT_PROVENANCE"
        assert "vc_count" in fp["unresolved_dimensions"]
        assert "packetization" in fp["unresolved_dimensions"]

    def test_from_run_dir_missing_files_is_insufficient(self, tmp_path):
        run = tmp_path / "empty"
        run.mkdir()
        with pytest.raises(ValueError, match="INSUFFICIENT_PROVENANCE"):
            fingerprint_from_run(run)

    def test_legacy_row_marks_unresolved(self):
        fp = fingerprint_from_legacy_row(_legacy_row())
        assert fp["topology"] == "mesh_8x8"
        assert fp["node_count"] == 64
        assert fp["certified"] is False
        assert "vc_count" in fp["unresolved_dimensions"]
        assert "simulator" in fp["unresolved_dimensions"]

    def test_legacy_row_fidelity_is_declared_default(self):
        fp = fingerprint_from_legacy_row(_legacy_row())
        assert fp["fidelity"] == "NETWORK_SIMULATION"
        assert fp["fidelity_provenance"] == "adapter_default_booksim_latency"


# ── controlled vs experimental ───────────────────────────────────────────────

class TestControlledVsVariable:
    def test_same_config_allows(self):
        v = evaluate_comparability(
            [_run_fingerprint(), _run_fingerprint()], _cspec())
        assert v.status == "COMPARABLE"

    def test_workload_differs_undeclared_refuses(self):
        v = evaluate_comparability(
            [_run_fingerprint(workload_hash="w1"),
             _run_fingerprint(workload_hash="w2")], _cspec())
        assert v.status == "INVALID_COMPARISON"
        d = v.differences[0]
        assert d["field"] == "workload_hash"
        assert d["reason"] == "UNDECLARED_DIFFERENCE"

    def test_node_count_differs_undeclared_refuses(self):
        v = evaluate_comparability(
            [_run_fingerprint(), _run_fingerprint(node_count=128)], _cspec())
        assert v.status == "INVALID_COMPARISON"
        assert v.differences[0]["field"] == "node_count"

    def test_topology_variable_allows(self):
        v = evaluate_comparability(
            [_run_fingerprint(topology="mesh_8x8"),
             _run_fingerprint(topology="torus_8x8")],
            _cspec(variables=["topology", "routing"]))
        assert v.status == "COMPARABLE"

    def test_routing_differs_undeclared_refuses(self):
        v = evaluate_comparability(
            [_run_fingerprint(routing="dim_order"),
             _run_fingerprint(routing="xy_yx")], _cspec())
        assert v.status == "INVALID_COMPARISON"
        assert v.differences[0]["field"] == "routing"

    def test_routing_variable_allows(self):
        v = evaluate_comparability(
            [_run_fingerprint(routing="dim_order"),
             _run_fingerprint(routing="xy_yx")],
            _cspec(variables=["routing"]))
        assert v.status == "COMPARABLE"

    def test_vc_differs_undeclared_refuses(self):
        v = evaluate_comparability(
            [_run_fingerprint(vc_count=2), _run_fingerprint(vc_count=4)],
            _cspec())
        assert v.status == "INVALID_COMPARISON"
        assert v.differences[0]["field"] == "vc_count"

    def test_declared_constant_variable_is_harmless(self):
        # The rule is one-directional (spec §4): differing ⇒ must be
        # declared. A declared variable that happens to be constant makes
        # the axis degenerate but the comparison still valid — the spec's
        # own example declares topology+routing while only topology varies.
        v = evaluate_comparability(
            [_run_fingerprint(), _run_fingerprint()],
            _cspec(variables=["topology"]))
        assert v.status == "COMPARABLE"


# ── fidelity policy ──────────────────────────────────────────────────────────

class TestFidelityPolicy:
    def test_booksim_vs_analytical_design_comparison_refuses(self):
        v = evaluate_comparability(
            [_run_fingerprint(),
             _run_fingerprint(simulator="analytical/congestion_aware",
                              fidelity="ANALYTICAL_ESTIMATE",
                              network_mode="REAL_SIMULATION")],
            _cspec())
        assert v.status == "INVALID_COMPARISON"
        d = v.differences[0]
        assert d["field"] == "fidelity"
        assert d["reason"] == "FIDELITY_MISMATCH"

    def test_booksim_vs_analytical_calibration_allows(self):
        v = evaluate_comparability(
            [_run_fingerprint(),
             _run_fingerprint(simulator="analytical/congestion_aware",
                              fidelity="ANALYTICAL_ESTIMATE")],
            _cspec(variables=["simulator", "fidelity"],
                   kind="CROSS_FIDELITY_CALIBRATION"))
        assert v.status == "COMPARABLE"
        assert v.comparison_kind == "CROSS_FIDELITY_CALIBRATION"

    def test_replay_vs_real_refuses_normally(self):
        v = evaluate_comparability(
            [_run_fingerprint(),
             _run_fingerprint(network_mode="TRACE_REPLAY",
                              fidelity="TRACE_REPLAY")],
            _cspec(variables=["simulator", "fidelity"]))
        assert v.status == "INVALID_COMPARISON"
        d = v.differences[0]
        assert d["field"] == "network_mode"
        assert d["reason"] == "TRACE_REPLAY_MIXED"

    def test_calibration_kind_cannot_launder_replay(self):
        # CROSS_FIDELITY_CALIBRATION legitimizes estimate-vs-simulation,
        # never replay-vs-simulation.
        v = evaluate_comparability(
            [_run_fingerprint(),
             _run_fingerprint(network_mode="TRACE_REPLAY",
                              fidelity="TRACE_REPLAY")],
            _cspec(variables=["simulator", "fidelity", "network_mode"],
                   kind="CROSS_FIDELITY_CALIBRATION"))
        assert v.status == "INVALID_COMPARISON"
        assert v.differences[0]["reason"] == "TRACE_REPLAY_MIXED"


# ── metric compatibility (§6) + unaware zero-exposed (§7) ────────────────────

class TestMetricCompatibility:
    def _m(self, **kw):
        base = {"name": "latency", "value": 10.0, "unit": "cycles",
                "producer": "booksim2", "fidelity": "NETWORK_SIMULATION",
                "scope": "per_packet"}
        base.update(kw)
        return base

    def test_same_semantics_compatible(self):
        ok, reason = eval_metric_compatibility(
            self._m(), self._m(), "latency")
        assert ok and reason is None

    def test_unit_mismatch_refuses(self):
        ok, reason = eval_metric_compatibility(
            self._m(), self._m(unit="ns"), "latency")
        assert not ok and reason == "UNIT_MISMATCH"

    def test_unknown_unit_refuses(self):
        ok, reason = eval_metric_compatibility(
            self._m(unit="blinkenlights"), self._m(), "latency")
        assert not ok and reason == "UNKNOWN_UNIT"

    def test_unknown_metric_name_refuses(self):
        ok, reason = eval_metric_compatibility(
            self._m(name="mystique"), self._m(name="mystique"), "mystique")
        assert not ok and reason == "UNKNOWN_METRIC"

    def test_unaware_exposed_comm_not_comparable(self):
        # §7: congestion-unaware analytical reports exposed=0 because the
        # engine does not produce the metric — never a measured zero.
        ok, reason = eval_metric_compatibility(
            self._m(name="exposed_communication", value=512.0),
            self._m(name="exposed_communication", value=0.0,
                    producer="astra-analytical"),
            "exposed_communication")
        assert not ok
        assert reason == "METRIC_NOT_COMPARABLE"

    def test_unaware_run_excluded_by_engine(self):
        """§7: the unaware candidate is NOT_COMPARABLE (visible
        exclusion), while any unaware-free subset stays comparable."""
        v = evaluate_comparability(
            [_run_fingerprint(network_engine="congestion_unaware",
                              simulator="analytical/congestion_unaware",
                              fidelity="ANALYTICAL_ESTIMATE"),
             _run_fingerprint(network_engine="congestion_aware",
                              simulator="analytical/congestion_aware",
                              fidelity="ANALYTICAL_ESTIMATE", run_id="aware")],
            _cspec(variables=["simulator", "network_engine"],
                   kind="DESIGN_COMPARISON",
                   objectives=["exposed_communication"]))
        assert v.status == "COMPARABLE"
        by_id = {c["run_id"]: c for c in v.candidates}
        assert by_id[None]["status"] == "NOT_COMPARABLE" or \
            any(c["status"] == "NOT_COMPARABLE" for c in v.candidates)
        assert by_id["aware"]["status"] == "COMPARABLE"

    def test_missing_metric_candidate_visible(self):
        v = evaluate_comparability(
            [_run_fingerprint(), _run_fingerprint()],
            _cspec(), metric_lookup=lambda fp, m: None)
        # Comparability verdict still holds; the metric layer marks the
        # candidate MISSING_METRIC at the Pareto boundary.
        assert v.status == "COMPARABLE"


# ── semantic loss (§9) ───────────────────────────────────────────────────────

class TestSemanticLoss:
    def test_semantic_loss_candidate_excluded_visibly(self):
        """§9: the lossy run is ineligible — excluded with SEMANTIC_LOSS,
        never silently dropped, never merged into the frontier."""
        v = evaluate_comparability(
            [_run_fingerprint(), _run_fingerprint(semantic_losses=["x"],
                                                  run_id="lossy")],
            _cspec())
        assert v.status == "COMPARABLE"  # set is coherent
        by_id = {c["run_id"]: c for c in v.candidates}
        assert by_id["lossy"]["status"] == "SEMANTIC_LOSS"
        assert by_id["lossy"]["reason"].startswith("semantic_losses:")
        assert by_id[None]["status"] == "COMPARABLE" or \
            any(c["status"] == "COMPARABLE" for c in v.candidates)


# ── scoped Pareto (§8, §11) ──────────────────────────────────────────────────

class TestParetoIntegrity:
    def test_failed_and_missing_stay_visible(self):
        cands = [
            {"run_id": "a", "metrics": {"latency": 10.0}},
            {"run_id": "b", "status": "FAILED_EXECUTION", "metrics": {}},
            {"run_id": "c", "status": "COMPARABLE", "metrics": {}},  # no metric
            {"run_id": "d", "metrics": {"latency": 12.0}},
        ]
        out = pareto_with_scope(cands, ["latency"])
        assert out["candidate_count"] == 4
        assert out["comparable_count"] == 2
        by_id = {c["run_id"]: c for c in out["candidates"]}
        assert by_id["b"]["status"] == "FAILED_EXECUTION"
        assert by_id["c"]["status"] == "MISSING_METRIC"
        assert out["pareto_scope"]["candidate_count"] == 2

    def test_dominance_basic(self):
        cands = [
            {"run_id": "a", "metrics": {"latency": 10.0}},
            {"run_id": "b", "metrics": {"latency": 12.0}},
        ]
        out = pareto_with_scope(cands, ["latency"])
        assert out["front"] == ["a"]
        assert out["dominated"] == ["b"]

    def test_no_silent_filter_drop(self):
        # The banned shape: pareto_front([x for x in cands if x.ok]).
        # Every requested candidate must appear in the output.
        cands = [
            {"run_id": "a", "metrics": {"latency": 10.0}},
            {"run_id": "z", "status": "FAILED_EXECUTION", "metrics": {}},
        ]
        out = pareto_with_scope(cands, ["latency"])
        assert {c["run_id"] for c in out["candidates"]} == {"a", "z"}

    def test_never_mixed_fidelity_front(self):
        # Even if a caller bypasses the gate, pareto_with_scope refuses to
        # build a DESIGN_COMPARISON frontier over mixed fidelities.
        cands = [
            {"run_id": "a", "metrics": {"latency": 10.0},
             "fidelity": "NETWORK_SIMULATION"},
            {"run_id": "b", "metrics": {"latency": 12.0},
             "fidelity": "ANALYTICAL_ESTIMATE"},
        ]
        with pytest.raises(Exception):
            pareto_with_scope(cands, ["latency"], kind="DESIGN_COMPARISON")

    def test_topology_experiment_end_to_end(self):
        """§12/§13: intended topology experiment → verdict carries the
        machine-readable shape, Pareto computes over the comparable set,
        and the excluded candidate keeps its reason."""
        fps = [
            _run_fingerprint(topology="mesh_8x8", run_id="mesh"),
            _run_fingerprint(topology="torus_8x8", run_id="torus"),
            _run_fingerprint(topology="fat_tree", run_id="broken",
                             semantic_losses=["pp"]),
        ]
        v = evaluate_comparability(fps, _cspec(variables=["topology"]))
        assert v.status == "COMPARABLE"
        out = pareto_with_scope(
            [{"run_id": "mesh", "status": "COMPARABLE",
              "metrics": {"latency": 30.0},
              "fidelity": "NETWORK_SIMULATION"},
             {"run_id": "torus", "status": "COMPARABLE",
              "metrics": {"latency": 28.0},
              "fidelity": "NETWORK_SIMULATION"},
             {"run_id": "broken", "status": "SEMANTIC_LOSS",
              "reason": "semantic_losses: ['pp']", "metrics": {}}],
            ["latency"], kind=v.comparison_kind)
        assert out["candidate_count"] == 3
        assert out["comparable_count"] == 2
        assert out["front"] == ["torus"]
        assert out["pareto_scope"] == {
            "candidate_count": 2, "objectives": ["latency"]}
        ex = {e["run_id"]: e for e in out["excluded"]}
        assert ex["broken"]["status"] == "SEMANTIC_LOSS"
        assert "reason" in ex["broken"]


# ── provenance gate (§14): unresolved required dims are ineligible ─────────

class TestProvenanceGate:
    def test_all_unresolved_required_dims_refuse(self):
        fps = [_run_fingerprint(vc_count=None, packetization=None,
                                routing=None, participant_count=None),
               _run_fingerprint(vc_count=None, packetization=None,
                                routing=None, participant_count=None)]
        v = evaluate_comparability(fps, _cspec())
        assert v.status == "INSUFFICIENT_PROVENANCE"
        assert v.certified is False
        for d in ("vc_count", "packetization", "routing",
                  "participant_count"):
            assert d in v.unresolved_dimensions
        assert all(c["status"] == "INSUFFICIENT_PROVENANCE"
                   for c in v.candidates)

    def test_legacy_rows_are_ineligible(self):
        fps = [fingerprint_from_legacy_row(_legacy_row()),
               fingerprint_from_legacy_row(_legacy_row())]
        v = evaluate_comparability(fps, _cspec())
        assert v.status == "INSUFFICIENT_PROVENANCE"

    def test_declared_experimental_axis_is_exempt(self):
        fps = [_run_fingerprint(topology="mesh_8x8"),
               _run_fingerprint(topology="torus_8x8")]
        v = evaluate_comparability(fps, _cspec(variables=["topology"]))
        assert v.status == "COMPARABLE"

    def test_calibration_kind_is_exempt(self):
        fps = [_run_fingerprint(vc_count=None),
               _run_fingerprint(vc_count=None,
                                simulator="analytical/congestion_aware",
                                fidelity="ANALYTICAL_ESTIMATE")]
        v = evaluate_comparability(
            fps, _cspec(variables=["simulator", "fidelity"],
                        kind="CROSS_FIDELITY_CALIBRATION"))
        assert v.status == "COMPARABLE"

    def test_resolved_set_still_comparable(self):
        v = evaluate_comparability(
            [_run_fingerprint(), _run_fingerprint()], _cspec())
        assert v.status == "COMPARABLE"
        assert v.unresolved_dimensions == []
