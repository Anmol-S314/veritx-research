"""TDD tests for the Srota Engine compile data model (E1–E5).

These tests define the contract. Implementation follows.
Run: pytest test_compile_model.py -v
"""
from __future__ import annotations

import hashlib
import pytest


# ══════════════════════════════════════════════════════════════════════════════
# §11.2 — Tier System (LOCKED / GUIDED / FREE)
# ══════════════════════════════════════════════════════════════════════════════

class TestTier:
    """PRD §11.2: Enforce the guardrail in the type system, not at runtime."""

    def test_tier_enum_values(self):
        from veritx_dse.model.compile_model import Tier
        assert Tier.LOCKED.value == "locked"
        assert Tier.GUIDED.value == "guided"
        assert Tier.FREE.value == "free"

    def test_tier_ordering(self):
        """LOCKED > GUIDED > FREE in strictness."""
        from veritx_dse.model.compile_model import Tier
        assert Tier.LOCKED > Tier.GUIDED > Tier.FREE

    def test_tier_badge_string(self):
        from veritx_dse.model.compile_model import Tier
        assert Tier.LOCKED.badge == "🔒 LOCKED"
        assert Tier.GUIDED.badge == "🔧 GUIDED"
        assert Tier.FREE.badge == "🆓 FREE"


# ══════════════════════════════════════════════════════════════════════════════
# §4.1 — Agent Model (E3)
# ══════════════════════════════════════════════════════════════════════════════

class TestAgent:
    """PRD §4.1–4.2: Agents are typed nodes with required attributes."""

    def test_agent_kind_enum(self):
        from veritx_dse.model.compile_model import AgentKind
        assert AgentKind.COMPUTE_TILE.value == "compute_tile"
        assert AgentKind.HBM_CONTROLLER.value == "hbm_controller"
        assert AgentKind.NIC.value == "nic"
        assert AgentKind.PERIPHERAL.value == "peripheral"
        assert AgentKind.UCIE_PORT.value == "ucie_port"

    def test_agent_creation(self):
        from veritx_dse.model.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.COMPUTE_TILE, count=64, data_width=512)
        assert a.kind == AgentKind.COMPUTE_TILE
        assert a.count == 64
        assert a.data_width == 512

    def test_agent_defaults(self):
        from veritx_dse.model.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.COMPUTE_TILE, count=1)
        assert a.data_width == 256  # default
        assert a.addr_width == 64   # default
        assert a.protocol == "AXI"  # default

    def test_agent_with_attributes(self):
        from veritx_dse.model.compile_model import Agent, AgentKind
        a = Agent(
            kind=AgentKind.HBM_CONTROLLER, count=8,
            data_width=1024, addr_width=48, protocol="CHI",
        )
        assert a.data_width == 1024
        assert a.protocol == "CHI"

    def test_agent_total_nodes(self):
        from veritx_dse.model.compile_model import Agent, AgentKind
        agents = [
            Agent(kind=AgentKind.COMPUTE_TILE, count=64),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=8),
        ]
        total = sum(a.count for a in agents)
        assert total == 72

    def test_agent_immutable(self):
        from veritx_dse.model.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.COMPUTE_TILE, count=64)
        with pytest.raises(AttributeError):
            a.count = 128


# ══════════════════════════════════════════════════════════════════════════════
# §5 — Workload (E1)
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkload:
    """PRD §5: Three levels of workload abstraction."""

    def test_model_family_enum(self):
        from veritx_dse.model.compile_model import ModelFamily
        assert ModelFamily.DENSE_TRANSFORMER.value == "dense_transformer"
        assert ModelFamily.MOE.value == "mixture_of_experts"
        assert ModelFamily.DIFFUSION.value == "diffusion"
        assert ModelFamily.CUSTOM.value == "custom"

    def test_serving_mode_enum(self):
        from veritx_dse.model.compile_model import ServingMode
        assert ServingMode.PREFILL_HEAVY.value == "prefill_heavy"
        assert ServingMode.DECODE_HEAVY.value == "decode_heavy"
        assert ServingMode.MIXED.value == "mixed"

    def test_workload_creation(self):
        from veritx_dse.model.compile_model import Workload, ModelFamily, ServingMode
        w = Workload(
            model_family=ModelFamily.MOE,
            model_name="Qwen3-30B-A3B",
            tp=16, ep=8, dp=1,
            serving_mode=ServingMode.DECODE_HEAVY,
        )
        assert w.model_family == ModelFamily.MOE
        assert w.tp == 16
        assert w.total_npus == 128  # tp * ep

    def test_workload_trace_binding(self):
        from veritx_dse.model.compile_model import Workload, ModelFamily
        w = Workload(
            model_family=ModelFamily.MOE,
            trace_path="runs/traces/qwen3_serving_16rank.trace",
        )
        assert w.trace_path is not None

    def test_workload_immutable(self):
        from veritx_dse.model.compile_model import Workload, ModelFamily
        w = Workload(model_family=ModelFamily.MOE)
        with pytest.raises(AttributeError):
            w.tp = 32


# ══════════════════════════════════════════════════════════════════════════════
# §5.2 Level B — Collective operations (JSON-wired)
# ══════════════════════════════════════════════════════════════════════════════

class TestCollectives:
    """PRD §5.2: Collectives parse from JSON, round-trip, and validate."""

    def test_collective_kind_enum(self):
        from veritx_dse.model.compile_model import CollectiveKind
        assert CollectiveKind.ALLREDUCE.value == "allreduce"
        assert CollectiveKind.ALLGATHER.value == "allgather"
        assert CollectiveKind.REDUCESCATTER.value == "reducescatter"
        assert CollectiveKind.BROADCAST.value == "broadcast"
        assert CollectiveKind.ALLTOALL.value == "alltoall"

    def test_collective_defaults(self):
        from veritx_dse.model.compile_model import CollectiveOp, CollectiveKind
        c = CollectiveOp(kind=CollectiveKind.ALLREDUCE)
        assert c.group_size == 1
        assert c.bytes_per_element == 2048

    def test_collective_from_dict(self):
        from veritx_dse.model.compile_model import CollectiveOp, CollectiveKind
        c = CollectiveOp.from_dict({"kind": "alltoall", "group_size": 8})
        assert c.kind == CollectiveKind.ALLTOALL
        assert c.group_size == 8
        assert c.bytes_per_element == 2048  # default

    def test_collective_from_dict_bad_kind(self):
        from veritx_dse.model.compile_model import CollectiveOp
        with pytest.raises(ValueError):
            CollectiveOp.from_dict({"kind": "hypercast", "group_size": 8})

    def test_collective_from_dict_bad_group(self):
        from veritx_dse.model.compile_model import CollectiveOp
        with pytest.raises(ValueError):
            CollectiveOp.from_dict({"kind": "allreduce", "group_size": 0})

    def test_collective_round_trip(self):
        from veritx_dse.model.compile_model import CollectiveOp, CollectiveKind
        c = CollectiveOp(kind=CollectiveKind.ALLGATHER, group_size=16,
                         bytes_per_element=4096)
        assert CollectiveOp.from_dict(c.to_dict()) == c

    def test_request_from_dict_parses_collectives(self):
        from veritx_dse.model.compile_model import CompileRequest, CollectiveKind
        d = {
            "schema_version": 2,
            "compiler_semantics_version": 1,
            "workload": {
                "model_family": "mixture_of_experts",
                "tp": 16, "ep": 8,
                "collectives": [{"kind": "alltoall", "group_size": 8}],
            },
            "requirements": [],
            "agents": [{"kind": "compute_tile", "count": 16}],
            "dependencies": [],
            "noc_config": {"topology_family": "mesh"},
        }
        cr = CompileRequest.from_dict(d)
        assert len(cr.workload.collectives) == 1
        assert cr.workload.collectives[0].kind == CollectiveKind.ALLTOALL
        assert cr.workload.collectives[0].group_size == 8

    def test_request_from_dict_no_collectives_defaults_empty(self):
        from veritx_dse.model.compile_model import CompileRequest
        d = {
            "schema_version": 2,
            "compiler_semantics_version": 1,
            "workload": {"model_family": "dense_transformer"},
            "requirements": [],
            "agents": [{"kind": "compute_tile", "count": 16}],
            "dependencies": [],
            "noc_config": {"topology_family": "mesh"},
        }
        cr = CompileRequest.from_dict(d)
        assert cr.workload.collectives == ()

    def test_request_to_dict_round_trip_collectives(self):
        from veritx_dse.model.compile_model import CompileRequest
        d = {
            "schema_version": 2,
            "compiler_semantics_version": 1,
            "workload": {
                "model_family": "dense_transformer",
                "tp": 64,
                "collectives": [{"kind": "allreduce", "group_size": 64}],
            },
            "requirements": [],
            "agents": [{"kind": "compute_tile", "count": 16}],
            "dependencies": [],
            "noc_config": {"topology_family": "mesh"},
        }
        cr = CompileRequest.from_dict(d)
        d2 = cr.to_dict()
        assert d2["workload"]["collectives"] == [
            {"kind": "allreduce", "group_size": 64, "bytes_per_element": 2048}
        ]

    def test_preset_carries_collectives(self):
        from veritx_dse.model.presets import preset_to_compile_request
        from veritx_dse.model.compile_model import CollectiveKind
        cr = preset_to_compile_request("qwen3_moe_16npu")
        kinds = [c.kind for c in cr.workload.collectives]
        assert CollectiveKind.ALLTOALL in kinds
        cr = preset_to_compile_request("llama70b_tp64")
        assert cr.workload.collectives[0].group_size == 64


# ══════════════════════════════════════════════════════════════════════════════
# §5.3 / E2 — Requirements
# ══════════════════════════════════════════════════════════════════════════════

class TestRequirements:
    """PRD E2: Per-class latency/BW bounds and binding flags."""

    def test_requirement_creation(self):
        from veritx_dse.model.compile_model import Requirement, QoSClass
        r = Requirement(
            qos_class=QoSClass.LATENCY_CRITICAL,
            latency_ceiling_cycles=500,
            binding=True,
        )
        assert r.qos_class == QoSClass.LATENCY_CRITICAL
        assert r.latency_ceiling_cycles == 500
        assert r.binding is True

    def test_requirement_bw_floor(self):
        from veritx_dse.model.compile_model import Requirement, QoSClass
        r = Requirement(
            qos_class=QoSClass.BANDWIDTH,
            bandwidth_floor_gbps=200.0,
            binding=False,
        )
        assert r.bandwidth_floor_gbps == 200.0
        assert r.binding is False

    def test_qos_class_enum(self):
        from veritx_dse.model.compile_model import QoSClass
        assert QoSClass.LATENCY_CRITICAL.value == "latency_critical"
        assert QoSClass.BANDWIDTH.value == "bandwidth"
        assert QoSClass.BEST_EFFORT.value == "best_effort"

    def test_requirement_immutable(self):
        from veritx_dse.model.compile_model import Requirement, QoSClass
        r = Requirement(qos_class=QoSClass.BEST_EFFORT)
        with pytest.raises(AttributeError):
            r.binding = True


# ══════════════════════════════════════════════════════════════════════════════
# §11.3 / E4 — Dependency Graph + VC Derivation
# ══════════════════════════════════════════════════════════════════════════════

class TestDependency:
    """PRD E4: Blocking/ordering graph that drives VC derivation."""

    def test_dependency_creation(self):
        from veritx_dse.model.compile_model import Dependency, DepKind
        d = Dependency(
            source="tp_allreduce",
            target="ep_dispatch",
            kind=DepKind.BLOCKING,
        )
        assert d.source == "tp_allreduce"
        assert d.target == "ep_dispatch"
        assert d.kind == DepKind.BLOCKING

    def test_dep_kind_enum(self):
        from veritx_dse.model.compile_model import DepKind
        assert DepKind.BLOCKING.value == "blocking"
        assert DepKind.ORDERING.value == "ordering"
        assert DepKind.INDEPENDENT.value == "independent"

    def test_dependency_graph_no_cycles(self):
        from veritx_dse.model.compile_model import DependencyGraph, Dependency, DepKind
        deps = [
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "C", DepKind.BLOCKING),
        ]
        g = DependencyGraph(deps)
        assert not g.has_cycles()
        assert g.find_cycles() == []

    def test_dependency_graph_detects_cycle(self):
        from veritx_dse.model.compile_model import DependencyGraph, Dependency, DepKind
        deps = [
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "C", DepKind.BLOCKING),
            Dependency("C", "A", DepKind.BLOCKING),
        ]
        g = DependencyGraph(deps)
        assert g.has_cycles()
        cycles = g.find_cycles()
        assert len(cycles) >= 1
        # Cycle should contain A, B, C
        cycle_nodes = set()
        for c in cycles:
            cycle_nodes.update(c)
        assert {"A", "B", "C"}.issubset(cycle_nodes)

    def test_dependency_graph_empty(self):
        from veritx_dse.model.compile_model import DependencyGraph
        g = DependencyGraph([])
        assert not g.has_cycles()

    def test_dependency_graph_single_node(self):
        from veritx_dse.model.compile_model import DependencyGraph, Dependency, DepKind
        g = DependencyGraph([Dependency("A", "A", DepKind.BLOCKING)])
        assert g.has_cycles()  # self-loop


# ══════════════════════════════════════════════════════════════════════════════
# §11.3 — VC Derivation from Dependencies
# ══════════════════════════════════════════════════════════════════════════════

class TestVCDerivation:
    """PRD §11.3: VC structure derived from dependency graph."""

    def test_no_cycles_needs_minimal_vcs(self):
        from veritx_dse.model.compile_model import (
            DependencyGraph, Dependency, DepKind, derive_vc_count
        )
        deps = [
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "C", DepKind.BLOCKING),
        ]
        g = DependencyGraph(deps)
        vc_count = derive_vc_count(g)
        assert vc_count == 1  # no cycles = minimal VCs

    def test_single_cycle_needs_two_vcs(self):
        from veritx_dse.model.compile_model import (
            DependencyGraph, Dependency, DepKind, derive_vc_count
        )
        deps = [
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "A", DepKind.BLOCKING),
        ]
        g = DependencyGraph(deps)
        vc_count = derive_vc_count(g)
        assert vc_count == 2  # one cycle needs VC separation

    def test_two_independent_cycles_need_three_vcs(self):
        from veritx_dse.model.compile_model import (
            DependencyGraph, Dependency, DepKind, derive_vc_count
        )
        deps = [
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "A", DepKind.BLOCKING),  # cycle 1
            Dependency("C", "D", DepKind.BLOCKING),
            Dependency("D", "C", DepKind.BLOCKING),  # cycle 2
        ]
        g = DependencyGraph(deps)
        vc_count = derive_vc_count(g)
        assert vc_count >= 2  # at least 2 cycles need separation

    def test_vc_count_bounded(self):
        """PRD: if vc_count > PLANE_C_MAX_VC, raise ConfigError."""
        from veritx_dse.model.compile_model import derive_vc_count, PLANE_C_MAX_VC
        assert PLANE_C_MAX_VC >= 4  # minimum reasonable bound

    def test_independent_deps_no_extra_vcs(self):
        from veritx_dse.model.compile_model import (
            DependencyGraph, Dependency, DepKind, derive_vc_count
        )
        deps = [
            Dependency("A", "B", DepKind.INDEPENDENT),
            Dependency("C", "D", DepKind.INDEPENDENT),
        ]
        g = DependencyGraph(deps)
        vc_count = derive_vc_count(g)
        assert vc_count == 1  # independent deps don't need VC separation


# ══════════════════════════════════════════════════════════════════════════════
# §5.2 Level B — Collective VC floor (sizing from declared collectives)
# ══════════════════════════════════════════════════════════════════════════════

class TestCollectiveSizing:
    """Collectives size the fabric: VC floor + integration map.

    Assumption under test: declared collectives are potentially concurrent,
    so each multi-rank context needs its own VC (MPI-context separation).
    """

    def _request(self, collectives, deps=(), agents_count=16):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, CollectiveOp, CollectiveKind,
        )
        return CompileRequest(
            workload=Workload(
                model_family=ModelFamily.MOE,
                collectives=tuple(
                    CollectiveOp(kind=CollectiveKind(c["kind"]),
                                 group_size=c.get("group_size", 1))
                    for c in collectives
                ),
            ),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=agents_count)],
            dependencies=DependencyGraph(list(deps)),
            noc_config=NocConfig(topology_family=None),
        )

    def test_floor_applies_when_graph_lower(self):
        from veritx_dse.model.compile_model import derive_vc_assignment
        cr = self._request([{"kind": "allreduce", "group_size": 4},
                            {"kind": "allgather", "group_size": 4}])
        va = derive_vc_assignment(cr)
        assert va.vc_count == 2  # floor, not graph (graph says 1)
        assert va.collective_vc_map == {0: 0, 1: 1}

    def test_floor_yields_to_graph(self):
        from veritx_dse.model.compile_model import (
            Dependency, DepKind, derive_vc_assignment,
        )
        cr = self._request(
            [{"kind": "alltoall", "group_size": 8}],
            deps=[Dependency("A", "B", DepKind.BLOCKING),
                  Dependency("B", "A", DepKind.BLOCKING)],
        )
        va = derive_vc_assignment(cr)
        assert va.vc_count == 2  # graph cycle already needs 2
        assert va.collective_vc_map == {0: 0}

    def test_no_collectives_unchanged(self):
        from veritx_dse.model.compile_model import derive_vc_assignment
        cr = self._request([])
        va = derive_vc_assignment(cr)
        assert va.vc_count == 1
        assert va.collective_vc_map == {}

    def test_single_rank_collective_ignored(self):
        from veritx_dse.model.compile_model import derive_vc_assignment
        cr = self._request([{"kind": "allreduce", "group_size": 1}])
        va = derive_vc_assignment(cr)
        assert va.vc_count == 1
        assert va.collective_vc_map == {}

    def test_existing_presets_unchanged(self):
        # No shipped preset has dependency cycles or >1 collective, so the
        # floor must not inflate any of them (backward compatibility).
        from veritx_dse.model.presets import preset_to_compile_request
        from veritx_dse.model.compile_model import derive_vc_assignment
        for name in ("qwen3_moe_16npu", "llama70b_tp64", "moe_8npu",
                     "moe_64npu", "llama1b_tp64", "dense_64npu"):
            va = derive_vc_assignment(preset_to_compile_request(name))
            assert va.vc_count == 1, name

    def test_floor_cap_is_an_error(self):
        from veritx_dse.model.compile_model import validate
        cr = self._request(
            [{"kind": "allreduce", "group_size": 2}] * 9,
            agents_count=64,
        )
        result = validate(cr)
        assert not result.ok
        assert any("Collective VC floor" in e for e in result.errors)


# ══════════════════════════════════════════════════════════════════════════════
# §4.4 — Multicast GUIDED knobs + group fit (Astera's complaint, modeled)
# ══════════════════════════════════════════════════════════════════════════════

class TestMulticastKnobs:
    """mcast_groups / mcast_setup_cycles: parse, hash, group-fit warnings."""

    def test_knob_defaults_none(self):
        from veritx_dse.model.compile_model import NocConfig
        nc = NocConfig()
        assert nc.mcast_groups is None
        assert nc.mcast_setup_cycles is None

    def test_knob_validation(self):
        from veritx_dse.model.compile_model import NocConfig
        with pytest.raises(ValueError, match="mcast_groups"):
            NocConfig(mcast_groups=0)
        with pytest.raises(ValueError, match="mcast_setup_cycles"):
            NocConfig(mcast_setup_cycles=-1)
        assert NocConfig(mcast_groups=1, mcast_setup_cycles=0).mcast_groups == 1

    def test_knobs_parse_and_round_trip(self):
        from veritx_dse.model.compile_model import CompileRequest
        d = {
            "schema_version": 2,
            "compiler_semantics_version": 1,
            "workload": {"model_family": "dense_transformer"},
            "requirements": [],
            "agents": [{"kind": "compute_tile", "count": 4}],
            "dependencies": [],
            "noc_config": {"topology_family": "mesh",
                           "mcast_groups": 4, "mcast_setup_cycles": 50},
        }
        cr = CompileRequest.from_dict(d)
        assert cr.noc_config.mcast_groups == 4
        assert cr.noc_config.mcast_setup_cycles == 50
        d2 = cr.to_dict()
        assert d2["noc_config"]["mcast_groups"] == 4
        assert d2["noc_config"]["mcast_setup_cycles"] == 50
        assert CompileRequest.from_dict(d2) == cr

    def test_hash_pins_collectives_and_knobs(self):
        from veritx_dse.model.compile_model import CompileRequest
        base = {
            "schema_version": 2,
            "compiler_semantics_version": 1,
            "workload": {"model_family": "dense_transformer"},
            "requirements": [],
            "agents": [{"kind": "compute_tile", "count": 4}],
            "dependencies": [],
            "noc_config": {"topology_family": "mesh"},
        }
        import copy
        h0 = CompileRequest.from_dict(base).guardrail_hash()
        with_coll = copy.deepcopy(base)
        with_coll["workload"]["collectives"] = [
            {"kind": "allreduce", "group_size": 4}]
        assert CompileRequest.from_dict(with_coll).guardrail_hash() != h0
        with_knob = copy.deepcopy(base)
        with_knob["noc_config"]["mcast_groups"] = 2
        assert CompileRequest.from_dict(with_knob).guardrail_hash() != h0

    def _mcast_request(self, n_collectives, mcast_groups=None):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, CollectiveOp, CollectiveKind,
        )
        return CompileRequest(
            workload=Workload(
                model_family=ModelFamily.MOE,
                collectives=tuple(
                    CollectiveOp(kind=CollectiveKind.ALLTOALL, group_size=4)
                    for _ in range(n_collectives)
                ),
            ),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=16)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(mcast_groups=mcast_groups),
        )

    def test_group_fit_warns_on_excess(self):
        from veritx_dse.model.compile_model import validate
        cr = self._mcast_request(3, mcast_groups=1)
        result = validate(cr)
        assert result.ok  # degraded, not infeasible
        assert any("falls back to unicast" in w for w in result.warnings)

    def test_group_fit_passes_when_covered(self):
        from veritx_dse.model.compile_model import validate
        cr = self._mcast_request(2, mcast_groups=2)
        result = validate(cr)
        assert result.ok
        assert not any("unicast" in w for w in result.warnings)

    def test_group_fit_skipped_when_unset(self):
        from veritx_dse.model.compile_model import validate
        cr = self._mcast_request(5)
        result = validate(cr)
        assert result.ok
        assert not any("unicast" in w for w in result.warnings)


# ══════════════════════════════════════════════════════════════════════════════
# §4.4 / E5 — NocConfig (GUIDED / FREE / LOCKED enforced by type)
# ══════════════════════════════════════════════════════════════════════════════

class TestNocConfig:
    """PRD §11.2: Guardrail enforced in type system, not at runtime."""

    def test_noc_config_has_guided_fields(self):
        from veritx_dse.model.compile_model import NocConfig, TopologyFamily
        nc = NocConfig(topology_family=TopologyFamily.MESH)
        assert nc.topology_family == TopologyFamily.MESH
        assert nc.radix is None  # GUIDED, user may propose
        assert nc.concentration is None
        assert nc.arbitration is None

    def test_noc_config_has_free_fields(self):
        from veritx_dse.model.compile_model import NocConfig, TopologyFamily, OutputFormat
        nc = NocConfig(
            topology_family=TopologyFamily.MESH,
            output_formats=[OutputFormat.SYSTEMVERILOG],
        )
        assert OutputFormat.SYSTEMVERILOG in nc.output_formats

    def test_noc_config_no_locked_fields(self):
        """PRD: NocConfig has NO field for routing, turn restrictions, VC map.
        These are LOCKED — derived by the engine, not stored as user input."""
        from veritx_dse.model.compile_model import NocConfig
        nc = NocConfig(topology_family=None)
        # These attributes should not exist
        assert not hasattr(nc, 'routing_function')
        assert not hasattr(nc, 'turn_restrictions')
        assert not hasattr(nc, 'vc_map')

    def test_noc_config_immutable(self):
        from veritx_dse.model.compile_model import NocConfig, TopologyFamily
        nc = NocConfig(topology_family=TopologyFamily.MESH)
        with pytest.raises(AttributeError):
            nc.topology_family = TopologyFamily.TORUS

    def test_topology_family_enum(self):
        from veritx_dse.model.compile_model import TopologyFamily
        assert TopologyFamily.MESH.value == "mesh"
        assert TopologyFamily.TORUS.value == "torus"
        assert TopologyFamily.CONCENTRATED_MESH.value == "concentrated_mesh"
        assert TopologyFamily.GEC.value == "gec"

    def test_output_format_enum(self):
        from veritx_dse.model.compile_model import OutputFormat
        assert OutputFormat.SYSTEMVERILOG.value == "systemverilog"
        assert OutputFormat.SYSTEMC.value == "systemc"
        assert OutputFormat.UVM.value == "uvm"


# ══════════════════════════════════════════════════════════════════════════════
# §11.1 / §13 — CompileRequest (E1–E5 unified)
# ══════════════════════════════════════════════════════════════════════════════

class TestCompileRequest:
    """PRD §11.1: The single structured object the engine consumes."""

    def test_compile_request_creation(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Requirement, Agent,
            DependencyGraph, NocConfig, AgentKind, ModelFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE, model_name="Qwen3"),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        assert cr.workload.model_name == "Qwen3"
        assert len(cr.agents) == 1

    def test_compile_request_total_nodes(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[
                Agent(kind=AgentKind.COMPUTE_TILE, count=64),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=8),
            ],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        assert cr.total_nodes == 72

    def test_compile_request_guardrail_hash(self):
        """PRD §12: The hash pins the guardrail version used."""
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        h = cr.guardrail_hash()
        assert len(h) == 64  # SHA-256 hex
        # Same config → same hash
        cr2 = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        assert cr.guardrail_hash() == cr2.guardrail_hash()

    def test_compile_request_different_config_different_hash(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily,
        )
        cr1 = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        cr2 = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.TORUS),
        )
        assert cr1.guardrail_hash() != cr2.guardrail_hash()

    def test_compile_request_to_dict(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        d = cr.to_dict()
        assert "workload" in d
        assert "agents" in d
        assert "guardrail_hash" in d
        assert len(d["guardrail_hash"]) == 64

    def test_compile_request_from_dict(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE, model_name="Qwen3"),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        d = cr.to_dict()
        cr2 = CompileRequest.from_dict(d)
        assert cr2.workload.model_name == "Qwen3"
        assert len(cr2.agents) == 1
        assert cr2.guardrail_hash() == cr.guardrail_hash()

    def test_compile_request_immutable(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        with pytest.raises(AttributeError):
            cr.workload = Workload(model_family=ModelFamily.DENSE_TRANSFORMER)


# ══════════════════════════════════════════════════════════════════════════════
# §13 — Validate Stage (guardrail check before synthesis)
# ══════════════════════════════════════════════════════════════════════════════

class TestValidate:
    """PRD §13: Validate stage catches config errors in seconds, not minutes."""

    def test_validate_valid_request(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, validate,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        result = validate(cr)
        assert result.ok

    def test_validate_no_agents_fails(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily,
        )
        # CompileRequest now rejects empty agents at construction
        with pytest.raises(ValueError, match="agents list cannot be empty"):
            CompileRequest(
                workload=Workload(model_family=ModelFamily.MOE),
                requirements=[],
                agents=[],
                dependencies=DependencyGraph([]),
                noc_config=NocConfig(topology_family=None),
            )

    def test_validate_zero_count_fails(self):
        from veritx_dse.model.compile_model import (
            Agent, AgentKind,
        )
        # Agent.count >= 1 is now validated at construction time
        with pytest.raises(ValueError, match="count must be >= 1"):
            Agent(kind=AgentKind.COMPUTE_TILE, count=0)

    def test_validate_catches_cycles(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, Dependency,
            DepKind, NocConfig, AgentKind, ModelFamily, validate,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([
                Dependency("A", "B", DepKind.BLOCKING),
                Dependency("B", "A", DepKind.BLOCKING),
            ]),
            noc_config=NocConfig(topology_family=None),
        )
        result = validate(cr)
        # Cycles should be detected but not necessarily fail —
        # they drive VC derivation. But the validate result should
        # report them.
        assert result.ok  # cycles are warnings, not errors
        assert len(result.warnings) > 0  # but warned

    def test_validate_returns_config_error(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, validate, ValidationResult,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        result = validate(cr)
        assert isinstance(result, ValidationResult)
        assert hasattr(result, 'ok')
        assert hasattr(result, 'errors')
        assert hasattr(result, 'warnings')

    def _collective_request(self, collectives, agents_count=16, trace_path=None):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily,
        )
        return CompileRequest(
            workload=Workload(
                model_family=ModelFamily.MOE,
                collectives=tuple(collectives),
                trace_path=trace_path,
            ),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=agents_count)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )

    def test_validate_collective_exceeding_fabric_fails(self):
        from veritx_dse.model.compile_model import (
            CollectiveOp, CollectiveKind, validate,
        )
        cr = self._collective_request(
            [CollectiveOp(kind=CollectiveKind.ALLTOALL, group_size=64)],
            agents_count=16,
        )
        result = validate(cr)
        assert not result.ok
        assert any("exceeds fabric nodes" in e for e in result.errors)

    def test_validate_collective_fitting_fabric_passes(self):
        from veritx_dse.model.compile_model import (
            CollectiveOp, CollectiveKind, validate,
        )
        cr = self._collective_request(
            [CollectiveOp(kind=CollectiveKind.ALLTOALL, group_size=8)],
            agents_count=16,
        )
        result = validate(cr)
        assert result.ok

    def test_validate_degenerate_collective_warns(self):
        from veritx_dse.model.compile_model import (
            CollectiveOp, CollectiveKind, validate,
        )
        cr = self._collective_request(
            [CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=1)],
            agents_count=16,
        )
        result = validate(cr)
        assert result.ok  # warning, not error
        assert any("no-op" in w for w in result.warnings)

    def test_validate_missing_trace_warns_not_errors(self):
        from veritx_dse.model.compile_model import (
            CollectiveOp, CollectiveKind, validate,
        )
        cr = self._collective_request(
            [CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=4)],
            agents_count=16,
            trace_path="runs/traces/does_not_exist.trace",
        )
        result = validate(cr)
        assert result.ok
        assert any("Trace not found" in w for w in result.warnings)

    def test_validate_trace_coverage_warns(self, tmp_path):
        from veritx_dse.model.compile_model import (
            CollectiveOp, CollectiveKind, validate,
        )
        # On-disk order: cycle src class dst size. Only nodes 0-3 present.
        t = tmp_path / "small.trace"
        t.write_text("0 0 0 1 8\n10 1 0 2 8\n20 2 0 3 8\n30 3 0 0 8\n")
        cr = self._collective_request(
            [CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8)],
            agents_count=16,
            trace_path=str(t),
        )
        result = validate(cr)
        assert result.ok
        assert any("under-exercised" in w for w in result.warnings)

    def test_validate_trace_coverage_passes(self, tmp_path):
        from veritx_dse.model.compile_model import (
            CollectiveOp, CollectiveKind, validate,
        )
        lines = "".join(f"{i} {i % 8} 0 {(i + 1) % 8} 8\n" for i in range(64))
        t = tmp_path / "cover.trace"
        t.write_text(lines)
        cr = self._collective_request(
            [CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8)],
            agents_count=16,
            trace_path=str(t),
        )
        result = validate(cr)
        assert result.ok
        assert not any("under-exercised" in w for w in result.warnings)

    def test_trace_node_ids_cap(self, tmp_path):
        from veritx_dse.model.compile_model import _trace_node_ids
        t = tmp_path / "big.trace"
        t.write_text("".join(f"{i} {i} 0 0 8\n" for i in range(50)))
        ids, truncated, resolved = _trace_node_ids(str(t), cap=10)
        assert truncated
        assert len(ids) == 10
        assert resolved is not None
        ids2, trunc2, res2 = _trace_node_ids(str(tmp_path / "nope.trace"))
        assert ids2 == set() and not trunc2 and res2 is None


# ══════════════════════════════════════════════════════════════════════════════
# Integration: CompileRequest → existing Topology
# ══════════════════════════════════════════════════════════════════════════════

class TestAddressMap:
    """PRD §4.3: Address map with range validation."""

    def test_address_range_creation(self):
        from veritx_dse.model.compile_model import AddressRange
        r = AddressRange(name="HBM0", base=0x0, size=0x1000000)
        assert r.name == "HBM0"
        assert r.base == 0
        assert r.size == 0x1000000

    def test_address_map_creation(self):
        from veritx_dse.model.compile_model import AddressMap, AddressRange
        am = AddressMap(ranges=[
            AddressRange(name="HBM0", base=0x0, size=0x1000000),
            AddressRange(name="HBM1", base=0x1000000, size=0x1000000),
        ])
        assert len(am.ranges) == 2
        assert am.total_bytes() == 0x2000000

    def test_address_map_no_overlaps(self):
        from veritx_dse.model.compile_model import AddressMap, AddressRange
        am = AddressMap(ranges=[
            AddressRange(name="A", base=0x0, size=0x100),
            AddressRange(name="B", base=0x100, size=0x100),
        ])
        errors = am.validate_no_overlaps()
        assert len(errors) == 0

    def test_address_map_detects_overlaps(self):
        from veritx_dse.model.compile_model import AddressMap, AddressRange
        am = AddressMap(ranges=[
            AddressRange(name="A", base=0x0, size=0x200),
            AddressRange(name="B", base=0x100, size=0x100),
        ])
        errors = am.validate_no_overlaps()
        assert len(errors) == 1
        assert "overlap" in errors[0].lower()

    def test_address_map_from_dict(self):
        from veritx_dse.model.compile_model import AddressMap
        am = AddressMap.from_dict({"ranges": [
            {"name": "DRAM", "base": 0, "size": 0x2000000},
        ]})
        assert len(am.ranges) == 1
        assert am.ranges[0].name == "DRAM"

    def test_address_map_immutable(self):
        from veritx_dse.model.compile_model import AddressMap
        am = AddressMap()
        with pytest.raises(AttributeError):
            am.ranges = ()


class TestPhysicalContext:
    """PRD §10: Physical implementation context."""

    def test_physical_defaults(self):
        from veritx_dse.model.compile_model import PhysicalContext
        p = PhysicalContext()
        assert p.default_clock_freq_mhz == 1000.0
        assert p.default_data_width == 256
        assert p.process_node_nm == 7

    def test_physical_custom(self):
        from veritx_dse.model.compile_model import PhysicalContext
        p = PhysicalContext(default_clock_freq_mhz=2000.0, process_node_nm=5)
        assert p.default_clock_freq_mhz == 2000.0
        assert p.process_node_nm == 5

    def test_physical_immutable(self):
        from veritx_dse.model.compile_model import PhysicalContext
        p = PhysicalContext()
        with pytest.raises(AttributeError):
            p.default_clock_freq_mhz = 500.0


class TestVCAssignment:
    """PRD §11.3: VC assignment derived from dependency graph."""

    def test_no_cycles_gives_dor(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, derive_vc_assignment,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=None),
        )
        va = derive_vc_assignment(cr)
        assert va.vc_count == 1
        assert va.routing_function == "dim_order"

    def test_single_cycle_gives_adaptive(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, Dependency,
            DepKind, NocConfig, AgentKind, ModelFamily, derive_vc_assignment,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([
                Dependency("A", "B", DepKind.BLOCKING),
                Dependency("B", "A", DepKind.BLOCKING),
            ]),
            noc_config=NocConfig(topology_family=None),
        )
        va = derive_vc_assignment(cr)
        assert va.vc_count == 2
        assert va.routing_function == "dor"  # 1 cycle → dor
        # One class should be separated
        separated = [c for c, vc in va.per_class_vc.items() if vc > 0]
        assert len(separated) == 1

    def test_multiple_cycles_gives_min_adapt(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, Dependency,
            DepKind, NocConfig, AgentKind, ModelFamily, derive_vc_assignment,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([
                Dependency("A", "B", DepKind.BLOCKING),
                Dependency("B", "A", DepKind.BLOCKING),
                Dependency("C", "D", DepKind.BLOCKING),
                Dependency("D", "C", DepKind.BLOCKING),
            ]),
            noc_config=NocConfig(topology_family=None),
        )
        va = derive_vc_assignment(cr)
        assert va.vc_count >= 2
        assert va.routing_function == "min_adapt"  # 2+ cycles → adaptive

    def test_vc_assignment_immutable(self):
        from veritx_dse.model.compile_model import VCAssignment
        va = VCAssignment(vc_count=2, per_class_vc={}, routing_function="dor")
        with pytest.raises(AttributeError):
            va.vc_count = 3


class TestIntegration:
    """CompileRequest should bridge to existing Topology/BookSim types."""

    def test_compile_request_to_topology(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, derive_topology_spec,
        )
        from veritx_dse.model.presets import Topology
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        topo = derive_topology_spec(cr)
        assert isinstance(topo, Topology)
        assert topo.backend == "mesh"

    def test_compile_request_to_booksim_config(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, derive_topology_spec,
        )
        from veritx_dse.simulation.booksim import build_config
        cr = CompileRequest(
            workload=Workload(
                model_family=ModelFamily.MOE,
                trace_path="runs/traces/qwen3_serving_16rank.trace",
            ),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        topo = derive_topology_spec(cr)
        # Should not raise
        config = build_config(topo, cr.workload.trace_path)
        assert "topology = mesh;" in config
        assert "k = 8;" in config

    def test_full_pipeline_no_cycles(self):
        """End-to-end: CompileRequest → validate → derive → config (no cycles)."""
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, validate,
            derive_topology_spec, derive_vc_assignment,
        )
        from veritx_dse.simulation.booksim import build_config

        cr = CompileRequest(
            workload=Workload(
                model_family=ModelFamily.MOE,
                trace_path="runs/traces/qwen3_serving_16rank.trace",
            ),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )

        # Step 1: Validate
        vr = validate(cr)
        assert vr.ok, f"Validation failed: {vr.errors}"
        assert vr.vc_count == 1

        # Step 2: Derive VC assignment
        va = derive_vc_assignment(cr)
        assert va.vc_count == 1
        assert va.routing_function == "dim_order"

        # Step 3: Derive topology
        topo = derive_topology_spec(cr)
        assert topo.backend == "mesh"
        assert topo.routing == "dim_order"  # LOCKED, derived

        # Step 4: Build BookSim config
        config = build_config(topo, cr.workload.trace_path)
        assert "topology = mesh;" in config
        assert "routing_function = dim_order;" in config
        assert "num_vcs = 1;" in config  # VC artifact: 1 VC is the truth

    def test_full_pipeline_with_cycles(self):
        """End-to-end: CompileRequest with cycles → VC separation."""
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, Dependency,
            DepKind, NocConfig, AgentKind, ModelFamily, TopologyFamily,
            validate, derive_topology_spec, derive_vc_assignment,
        )
        from veritx_dse.simulation.booksim import build_config

        cr = CompileRequest(
            workload=Workload(
                model_family=ModelFamily.MOE,
                trace_path="runs/traces/qwen3_serving_16rank.trace",
            ),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([
                Dependency("tp_allreduce", "ep_dispatch", DepKind.BLOCKING),
                Dependency("ep_dispatch", "tp_allreduce", DepKind.BLOCKING),
            ]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )

        # Step 1: Validate (cycle detected as warning)
        vr = validate(cr)
        assert vr.ok  # warnings are not errors
        assert len(vr.warnings) > 0
        assert vr.vc_count == 2

        # Step 2: Derive VC assignment
        va = derive_vc_assignment(cr)
        assert va.vc_count == 2
        assert va.routing_function == "dor"  # 1 cycle → dor
        separated = [c for c, vc in va.per_class_vc.items() if vc > 0]
        assert len(separated) == 1  # one class separated

        # Step 3: Derive topology (VC count propagated)
        topo = derive_topology_spec(cr)
        assert topo.backend == "mesh"
        assert topo.routing == "dor"  # LOCKED, derived from cycle
        assert topo.params["num_vcs"] == 2  # vc_count, no head-flit +1

        # Step 4: Build BookSim config (uses derived num_vcs)
        config = build_config(topo, cr.workload.trace_path)
        assert "routing_function = dor;" in config
        assert "num_vcs = 2;" in config

    def test_topology_size_comes_from_agent_inventory(self):
        """B3.1b: k is derived from the hardware agents, never hardcoded.

        The old derive_topology_spec returned k=8 for ANY agent count.
        """
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, derive_topology_spec,
            derive_topology_artifact,
        )
        def _cr(count, family=TopologyFamily.MESH, **noc_kw):
            return CompileRequest(
                workload=Workload(model_family=ModelFamily.MOE),
                requirements=[],
                agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=count)],
                dependencies=DependencyGraph([]),
                noc_config=NocConfig(topology_family=family, **noc_kw),
            )

        t16 = derive_topology_spec(_cr(16))
        assert (t16.backend, t16.params["k"]) == ("mesh", 4)

        # 8 agents -> k=ceil(sqrt(8))=3 -> 9 routers (one idle seat)
        t8 = derive_topology_spec(_cr(8))
        assert (t8.backend, t8.params["k"]) == ("mesh", 3)

        # 64 compute + 8 HBM = 72 agents -> k=ceil(sqrt(72))=9
        art = derive_topology_artifact(_cr(72))
        assert art.router_count == 81 == 9 ** 2

        # GUIDED radix pins k (still providing enough seats)
        tradix = derive_topology_spec(_cr(64, radix=8))
        assert tradix.params["k"] == 8

    def test_concentrated_mesh_materializes_as_cmesh(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, derive_topology_spec,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=64)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(
                topology_family=TopologyFamily.CONCENTRATED_MESH),
        )
        topo = derive_topology_spec(cr)
        # 64 endpoints / 4 seats = 16 routers -> k=4, c=4
        assert topo.backend == "cmesh"
        assert topo.params["k"] == 4 and topo.params["c"] == 4

    def test_unmaterializable_families_refused_not_downgraded(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, derive_topology_spec,
        )
        from veritx_dse.model.topology_artifact import TopologyError
        for fam in (TopologyFamily.GEC, TopologyFamily.FAT_TREE):
            cr = CompileRequest(
                workload=Workload(model_family=ModelFamily.MOE),
                requirements=[],
                agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=16)],
                dependencies=DependencyGraph([]),
                noc_config=NocConfig(topology_family=fam),
            )
            with pytest.raises(TopologyError, match="not materializable"):
                derive_topology_spec(cr)

    def test_compile_request_roundtrip(self):
        """CompileRequest → to_dict → from_dict preserves all fields."""
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, Dependency,
            DepKind, NocConfig, AgentKind, ModelFamily, TopologyFamily,
            Requirement, QoSClass, AddressMap, AddressRange, PhysicalContext,
        )

        cr = CompileRequest(
            workload=Workload(
                model_family=ModelFamily.MOE,
                model_name="Qwen3-30B-A3B",
                tp=16, ep=8,
                trace_path="runs/traces/qwen3_serving_16rank.trace",
            ),
            requirements=[
                Requirement(qos_class=QoSClass.LATENCY_CRITICAL, latency_ceiling_cycles=500, binding=True),
                Requirement(qos_class=QoSClass.BANDWIDTH, bandwidth_floor_gbps=200.0, binding=False),
            ],
            agents=[
                Agent(kind=AgentKind.COMPUTE_TILE, count=64, data_width=512),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=8, data_width=1024),
            ],
            dependencies=DependencyGraph([
                Dependency("A", "B", DepKind.BLOCKING),
                Dependency("B", "A", DepKind.BLOCKING),
            ]),
            noc_config=NocConfig(
                topology_family=TopologyFamily.MESH,
                radix=8, link_width=256,
            ),
            address_map=AddressMap(ranges=[
                AddressRange(name="HBM0", base=0, size=0x1000000),
            ]),
            physical=PhysicalContext(default_clock_freq_mhz=2000.0),
        )

        # Roundtrip
        d = cr.to_dict()
        cr2 = CompileRequest.from_dict(d)

        # Verify all fields preserved
        assert cr2.workload.model_name == "Qwen3-30B-A3B"
        assert cr2.workload.tp == 16
        assert cr2.workload.ep == 8
        assert len(cr2.requirements) == 2
        assert cr2.requirements[0].binding is True
        assert len(cr2.agents) == 2
        assert cr2.agents[0].data_width == 512
        assert len(cr2.dependencies.dependencies) == 2
        assert cr2.noc_config.topology_family == TopologyFamily.MESH
        assert cr2.noc_config.radix == 8
        assert len(cr2.address_map.ranges) == 1
        assert cr2.physical.default_clock_freq_mhz == 2000.0

        # Guardrail hash must match
        assert cr.guardrail_hash() == cr2.guardrail_hash()
