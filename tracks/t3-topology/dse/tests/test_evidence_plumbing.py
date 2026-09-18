"""Phase 13 precursor — evidence plumbing: sim result → F2/F3/F8.

The F-checks upgrade from NOT_RUN only when real evidence arrives
(verified-PRD §3.11: fabricated PASSes are the original sin). The
evidence exists in the BookSim result dict; it was dropped on the floor
between Step 3 and Step 4 of cmd_compile. These tests pin the seam that
forwards it — including the negative: absent stats produce absent keys,
never invented zeros (a stock binary prints no flit totals; F3 must
stay NOT_RUN, not read a fabricated 0 as measured zero).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.simulation.booksim import evidence_from_result


class TestEvidenceFromResult:
    def test_full_result_yields_f3_f8_evidence(self):
        result = {
            "latency": 23.45,
            "max_packet_latency": 89.0,
            "flits_injected": 4096,
            "flits_accepted": 4096,
            "metrics": {"latency": {"value": 23.45, "unit": "cycles"}},
        }
        ev = evidence_from_result(result)
        assert ev["booksim_injected_flits"] == 4096
        assert ev["booksim_completed_flits"] == 4096
        # no derived drop counter — complete-delivery semantics instead
        assert "booksim_dropped_flits" not in ev
        assert ev["max_packet_latency_cycles"] == 89.0

    def test_gap_between_injected_and_ejected_is_loss(self):
        # the fork's totals differ → F3 sees injected != completed and
        # must FAIL with the loss visible (never a derived identity)
        result = {"flits_injected": 5000, "flits_accepted": 4800}
        ev = evidence_from_result(result)
        assert ev["booksim_injected_flits"] == 5000
        assert ev["booksim_completed_flits"] == 4800
        from veritx_dse.model.compile_model import verify_design
        from tests.test_evidence_plumbing import TestEvidenceToVerifyDesign
        vr = verify_design(TestEvidenceToVerifyDesign()._cr(), evidence=ev)
        f3 = next(c for c in vr.checks if c["name"] == "F3_packet_conservation")
        assert f3["status"] == "FAIL"

    def test_stock_binary_without_totals_stays_honest(self):
        # no flit totals in the result → no F3 keys at all (F3 stays
        # NOT_RUN); never {"injected": 0} masquerading as a measurement
        result = {"latency": 12.0}
        ev = evidence_from_result(result)
        assert "booksim_injected_flits" not in ev
        assert "booksim_completed_flits" not in ev
        assert "booksim_dropped_flits" not in ev

    def test_no_max_latency_key_stays_absent(self):
        result = {"latency": 12.0}
        ev = evidence_from_result(result)
        assert "max_packet_latency_cycles" not in ev

    def test_contradictory_accounting_fails_loudly_not_clamped(self):
        # accepted > injected cannot happen physically. We never derive a
        # dropped counter (arithmetic identity); the contradiction must
        # surface as F3's complete-delivery check failing loudly.
        result = {"flits_injected": 100, "flits_accepted": 120}
        ev = evidence_from_result(result)
        assert "booksim_dropped_flits" not in ev
        from veritx_dse.model.compile_model import verify_design
        from tests.test_evidence_plumbing import TestEvidenceToVerifyDesign
        cr = TestEvidenceToVerifyDesign()._cr()
        vr = verify_design(cr, evidence=ev)
        f3 = next(c for c in vr.checks if c["name"] == "F3_packet_conservation")
        assert f3["status"] == "FAIL"
        assert "lost" in f3["detail"] or "never ejected" in f3["detail"]

    def test_trace_packet_count_cross_check_available(self):
        # pkt_count from the stats block rides along for F3 corroboration
        result = {"pkt_count": 64, "flits_injected": 4096,
                  "flits_accepted": 4096}
        ev = evidence_from_result(result)
        assert ev["booksim_pkts_expected"] == 64


class TestEvidenceToVerifyDesign:
    """End-to-end: evidence dict from a sim result upgrades F3/F8."""

    def _cr(self):
        from veritx_dse.model.compile_model import (
            Agent, AgentKind, CompileRequest, DependencyGraph, ModelFamily,
            NocConfig, Workload,
        )
        return CompileRequest(
            workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER,
                              collectives=()),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )

    def test_conserved_flits_pass_f3(self):
        from veritx_dse.model.compile_model import verify_design
        ev = evidence_from_result({
            "flits_injected": 4096, "flits_accepted": 4096,
            "max_packet_latency": 89.0})
        vr = verify_design(self._cr(), evidence=ev)
        f3 = next(c for c in vr.checks if c["name"] == "F3_packet_conservation")
        assert f3["status"] == "PASS"

    def test_broken_conservation_fails_f3(self):
        from veritx_dse.model.compile_model import verify_design
        ev = evidence_from_result({
            "flits_injected": 5000, "flits_accepted": 4800,
            "max_packet_latency": 89.0})
        vr = verify_design(self._cr(), evidence=ev)
        f3 = next(c for c in vr.checks if c["name"] == "F3_packet_conservation")
        assert f3["status"] == "FAIL"

    def test_latency_within_bound_passes_f8(self):
        from veritx_dse.model.compile_model import (
            QoSClass, Requirement, verify_design,
        )
        cr = self._cr()
        cr = cr.__class__(
            workload=cr.workload,
            requirements=[Requirement(qos_class=QoSClass.BEST_EFFORT,
                                      latency_ceiling_cycles=100.0,
                                      binding=True)],
            agents=cr.agents, dependencies=cr.dependencies,
            noc_config=cr.noc_config)
        ev = evidence_from_result({"max_packet_latency": 89.0})
        ev["latency_bound_cycles"] = 100.0
        vr = verify_design(cr, evidence=ev)
        f8 = next(c for c in vr.checks if c["name"] == "F8_timeout")
        assert f8["status"] == "PASS"

    def test_adjacency_evidence_passes_f2(self):
        from veritx_dse.model.compile_model import verify_design
        # 4-node ring: connected
        adj = {i: {(i - 1) % 4, (i + 1) % 4} for i in range(4)}
        ev = {"topology_adjacency": {str(k): sorted(v) for k, v in adj.items()}}
        vr = verify_design(self._cr(), evidence=ev)
        f2 = next(c for c in vr.checks if c["name"] == "F2_liveness")
        assert f2["status"] == "PASS"
        assert "reachable" in f2["detail"].lower()

    def test_disconnected_adjacency_fails_f2(self):
        from veritx_dse.model.compile_model import verify_design
        ev = {"topology_adjacency": {"0": [1], "1": [0], "2": [3], "3": [2]}}
        vr = verify_design(self._cr(), evidence=ev)
        f2 = next(c for c in vr.checks if c["name"] == "F2_liveness")
        assert f2["status"] == "FAIL"


class TestTopologyAdjacencyExtraction:
    """F2 evidence must come from the topology actually simulated."""

    def test_mesh_k4_adjacency_is_the_executed_mesh(self):
        from veritx_dse.model.compile_model import topology_adjacency
        from veritx_dse.model.presets import Topology
        topo = Topology(name="mesh_4x4", backend="mesh",
                        routing="dim_order", params={"k": 4, "n": 2})
        adj = topology_adjacency(topo)
        assert adj is not None
        assert len(adj) == 16
        # corner 0 neighbors: 1 and 4 in a 4x4 mesh
        assert adj[0] == {1, 4}
        # interior 5 neighbors: 1, 4, 6, 9
        assert adj[5] == {1, 4, 6, 9}

    def test_torus_k4_adds_wraparound(self):
        from veritx_dse.model.compile_model import topology_adjacency
        from veritx_dse.model.presets import Topology
        topo = Topology(name="torus_4x4", backend="torus",
                        routing="dim_order", params={"k": 4, "n": 2})
        adj = topology_adjacency(topo)
        assert adj is not None
        assert 3 in adj[0] and 12 in adj[0]  # wraparound edges

    def test_anynet_reads_the_network_file(self):
        from veritx_dse.model.compile_model import topology_adjacency
        from veritx_dse.model.presets import Topology
        from veritx_dse.core.paths import REPO
        links = REPO / "tracks" / "t3-topology" / "configs" / "anynet16.links"
        if not links.exists():
            pytest.skip("anynet16.links not present")
        topo = Topology(name="anynet16", backend="anynet", routing="min",
                        params={"network_file": str(links)})
        adj = topology_adjacency(topo)
        assert adj is not None and len(adj) == 16

    def test_unsupported_backend_returns_none(self):
        from veritx_dse.model.compile_model import topology_adjacency
        from veritx_dse.model.presets import Topology
        topo = Topology(name="x", backend="dragonflynew", routing="r",
                        params={})
        assert topology_adjacency(topo) is None


class TestLatencyBoundFromRequirements:
    """F8's bound is an E2 requirement, never invented from defaults."""

    def test_binding_latency_requirement_supplies_bound(self):
        from veritx_dse.model.compile_model import latency_bound_from_requirements
        from veritx_dse.model.compile_model import (
            QoSClass, Requirement,
        )
        reqs = [Requirement(qos_class=QoSClass.LATENCY_CRITICAL,
                            latency_ceiling_cycles=250.0, binding=True)]
        assert latency_bound_from_requirements(reqs) == 250.0

    def test_no_requirements_no_bound(self):
        from veritx_dse.model.compile_model import latency_bound_from_requirements
        assert latency_bound_from_requirements([]) is None

    def test_none_ceiling_no_bound(self):
        from veritx_dse.model.compile_model import latency_bound_from_requirements
        from veritx_dse.model.compile_model import QoSClass, Requirement
        reqs = [Requirement(qos_class=QoSClass.BEST_EFFORT,
                            latency_ceiling_cycles=None, binding=True)]
        assert latency_bound_from_requirements(reqs) is None

    def test_takes_min_over_declared_bounds(self):
        from veritx_dse.model.compile_model import latency_bound_from_requirements
        from veritx_dse.model.compile_model import QoSClass, Requirement
        reqs = [Requirement(qos_class=QoSClass.LATENCY_CRITICAL,
                            latency_ceiling_cycles=300.0, binding=True),
                Requirement(qos_class=QoSClass.LATENCY_CRITICAL,
                            latency_ceiling_cycles=250.0, binding=False)]
        assert latency_bound_from_requirements(reqs) == 250.0
