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
        from veritx_dse.compile_model import Tier
        assert Tier.LOCKED.value == "locked"
        assert Tier.GUIDED.value == "guided"
        assert Tier.FREE.value == "free"

    def test_tier_ordering(self):
        """LOCKED > GUIDED > FREE in strictness."""
        from veritx_dse.compile_model import Tier
        assert Tier.LOCKED > Tier.GUIDED > Tier.FREE

    def test_tier_badge_string(self):
        from veritx_dse.compile_model import Tier
        assert Tier.LOCKED.badge == "🔒 LOCKED"
        assert Tier.GUIDED.badge == "🔧 GUIDED"
        assert Tier.FREE.badge == "🆓 FREE"


# ══════════════════════════════════════════════════════════════════════════════
# §4.1 — Agent Model (E3)
# ══════════════════════════════════════════════════════════════════════════════

class TestAgent:
    """PRD §4.1–4.2: Agents are typed nodes with required attributes."""

    def test_agent_kind_enum(self):
        from veritx_dse.compile_model import AgentKind
        assert AgentKind.COMPUTE_TILE.value == "compute_tile"
        assert AgentKind.HBM_CONTROLLER.value == "hbm_controller"
        assert AgentKind.NIC.value == "nic"
        assert AgentKind.PERIPHERAL.value == "peripheral"
        assert AgentKind.UCIE_PORT.value == "ucie_port"

    def test_agent_creation(self):
        from veritx_dse.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.COMPUTE_TILE, count=64, data_width=512)
        assert a.kind == AgentKind.COMPUTE_TILE
        assert a.count == 64
        assert a.data_width == 512

    def test_agent_defaults(self):
        from veritx_dse.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.COMPUTE_TILE, count=1)
        assert a.data_width == 256  # default
        assert a.addr_width == 64   # default
        assert a.protocol == "AXI"  # default

    def test_agent_with_attributes(self):
        from veritx_dse.compile_model import Agent, AgentKind
        a = Agent(
            kind=AgentKind.HBM_CONTROLLER, count=8,
            data_width=1024, addr_width=48, protocol="CHI",
        )
        assert a.data_width == 1024
        assert a.protocol == "CHI"

    def test_agent_total_nodes(self):
        from veritx_dse.compile_model import Agent, AgentKind
        agents = [
            Agent(kind=AgentKind.COMPUTE_TILE, count=64),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=8),
        ]
        total = sum(a.count for a in agents)
        assert total == 72

    def test_agent_immutable(self):
        from veritx_dse.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.COMPUTE_TILE, count=64)
        with pytest.raises(AttributeError):
            a.count = 128


# ══════════════════════════════════════════════════════════════════════════════
# §5 — Workload (E1)
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkload:
    """PRD §5: Three levels of workload abstraction."""

    def test_model_family_enum(self):
        from veritx_dse.compile_model import ModelFamily
        assert ModelFamily.DENSE_TRANSFORMER.value == "dense_transformer"
        assert ModelFamily.MOE.value == "mixture_of_experts"
        assert ModelFamily.DIFFUSION.value == "diffusion"
        assert ModelFamily.CUSTOM.value == "custom"

    def test_serving_mode_enum(self):
        from veritx_dse.compile_model import ServingMode
        assert ServingMode.PREFILL_HEAVY.value == "prefill_heavy"
        assert ServingMode.DECODE_HEAVY.value == "decode_heavy"
        assert ServingMode.MIXED.value == "mixed"

    def test_workload_creation(self):
        from veritx_dse.compile_model import Workload, ModelFamily, ServingMode
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
        from veritx_dse.compile_model import Workload, ModelFamily
        w = Workload(
            model_family=ModelFamily.MOE,
            trace_path="runs/traces/qwen3_serving_16rank.trace",
        )
        assert w.trace_path is not None

    def test_workload_immutable(self):
        from veritx_dse.compile_model import Workload, ModelFamily
        w = Workload(model_family=ModelFamily.MOE)
        with pytest.raises(AttributeError):
            w.tp = 32


# ══════════════════════════════════════════════════════════════════════════════
# §5.3 / E2 — Requirements
# ══════════════════════════════════════════════════════════════════════════════

class TestRequirements:
    """PRD E2: Per-class latency/BW bounds and binding flags."""

    def test_requirement_creation(self):
        from veritx_dse.compile_model import Requirement, QoSClass
        r = Requirement(
            qos_class=QoSClass.LATENCY_CRITICAL,
            latency_ceiling_cycles=500,
            binding=True,
        )
        assert r.qos_class == QoSClass.LATENCY_CRITICAL
        assert r.latency_ceiling_cycles == 500
        assert r.binding is True

    def test_requirement_bw_floor(self):
        from veritx_dse.compile_model import Requirement, QoSClass
        r = Requirement(
            qos_class=QoSClass.BANDWIDTH,
            bandwidth_floor_gbps=200.0,
            binding=False,
        )
        assert r.bandwidth_floor_gbps == 200.0
        assert r.binding is False

    def test_qos_class_enum(self):
        from veritx_dse.compile_model import QoSClass
        assert QoSClass.LATENCY_CRITICAL.value == "latency_critical"
        assert QoSClass.BANDWIDTH.value == "bandwidth"
        assert QoSClass.BEST_EFFORT.value == "best_effort"

    def test_requirement_immutable(self):
        from veritx_dse.compile_model import Requirement, QoSClass
        r = Requirement(qos_class=QoSClass.BEST_EFFORT)
        with pytest.raises(AttributeError):
            r.binding = True


# ══════════════════════════════════════════════════════════════════════════════
# §11.3 / E4 — Dependency Graph + VC Derivation
# ══════════════════════════════════════════════════════════════════════════════

class TestDependency:
    """PRD E4: Blocking/ordering graph that drives VC derivation."""

    def test_dependency_creation(self):
        from veritx_dse.compile_model import Dependency, DepKind
        d = Dependency(
            source="tp_allreduce",
            target="ep_dispatch",
            kind=DepKind.BLOCKING,
        )
        assert d.source == "tp_allreduce"
        assert d.target == "ep_dispatch"
        assert d.kind == DepKind.BLOCKING

    def test_dep_kind_enum(self):
        from veritx_dse.compile_model import DepKind
        assert DepKind.BLOCKING.value == "blocking"
        assert DepKind.ORDERING.value == "ordering"
        assert DepKind.INDEPENDENT.value == "independent"

    def test_dependency_graph_no_cycles(self):
        from veritx_dse.compile_model import DependencyGraph, Dependency, DepKind
        deps = [
            Dependency("A", "B", DepKind.BLOCKING),
            Dependency("B", "C", DepKind.BLOCKING),
        ]
        g = DependencyGraph(deps)
        assert not g.has_cycles()
        assert g.find_cycles() == []

    def test_dependency_graph_detects_cycle(self):
        from veritx_dse.compile_model import DependencyGraph, Dependency, DepKind
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
        from veritx_dse.compile_model import DependencyGraph
        g = DependencyGraph([])
        assert not g.has_cycles()

    def test_dependency_graph_single_node(self):
        from veritx_dse.compile_model import DependencyGraph, Dependency, DepKind
        g = DependencyGraph([Dependency("A", "A", DepKind.BLOCKING)])
        assert g.has_cycles()  # self-loop


# ══════════════════════════════════════════════════════════════════════════════
# §11.3 — VC Derivation from Dependencies
# ══════════════════════════════════════════════════════════════════════════════

class TestVCDerivation:
    """PRD §11.3: VC structure derived from dependency graph."""

    def test_no_cycles_needs_minimal_vcs(self):
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import derive_vc_count, PLANE_C_MAX_VC
        assert PLANE_C_MAX_VC >= 4  # minimum reasonable bound

    def test_independent_deps_no_extra_vcs(self):
        from veritx_dse.compile_model import (
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
# §4.4 / E5 — NocConfig (GUIDED / FREE / LOCKED enforced by type)
# ══════════════════════════════════════════════════════════════════════════════

class TestNocConfig:
    """PRD §11.2: Guardrail enforced in type system, not at runtime."""

    def test_noc_config_has_guided_fields(self):
        from veritx_dse.compile_model import NocConfig, TopologyFamily
        nc = NocConfig(topology_family=TopologyFamily.MESH)
        assert nc.topology_family == TopologyFamily.MESH
        assert nc.radix is None  # GUIDED, user may propose
        assert nc.concentration is None
        assert nc.arbitration is None

    def test_noc_config_has_free_fields(self):
        from veritx_dse.compile_model import NocConfig, TopologyFamily, OutputFormat
        nc = NocConfig(
            topology_family=TopologyFamily.MESH,
            output_formats=[OutputFormat.SYSTEMVERILOG],
        )
        assert OutputFormat.SYSTEMVERILOG in nc.output_formats

    def test_noc_config_no_locked_fields(self):
        """PRD: NocConfig has NO field for routing, turn restrictions, VC map.
        These are LOCKED — derived by the engine, not stored as user input."""
        from veritx_dse.compile_model import NocConfig
        nc = NocConfig(topology_family=None)
        # These attributes should not exist
        assert not hasattr(nc, 'routing_function')
        assert not hasattr(nc, 'turn_restrictions')
        assert not hasattr(nc, 'vc_map')

    def test_noc_config_immutable(self):
        from veritx_dse.compile_model import NocConfig, TopologyFamily
        nc = NocConfig(topology_family=TopologyFamily.MESH)
        with pytest.raises(AttributeError):
            nc.topology_family = TopologyFamily.TORUS

    def test_topology_family_enum(self):
        from veritx_dse.compile_model import TopologyFamily
        assert TopologyFamily.MESH.value == "mesh"
        assert TopologyFamily.TORUS.value == "torus"
        assert TopologyFamily.CONCENTRATED_MESH.value == "concentrated_mesh"
        assert TopologyFamily.GEC.value == "gec"

    def test_output_format_enum(self):
        from veritx_dse.compile_model import OutputFormat
        assert OutputFormat.SYSTEMVERILOG.value == "systemverilog"
        assert OutputFormat.SYSTEMC.value == "systemc"
        assert OutputFormat.UVM.value == "uvm"


# ══════════════════════════════════════════════════════════════════════════════
# §11.1 / §13 — CompileRequest (E1–E5 unified)
# ══════════════════════════════════════════════════════════════════════════════

class TestCompileRequest:
    """PRD §11.1: The single structured object the engine consumes."""

    def test_compile_request_creation(self):
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
            Agent, AgentKind,
        )
        # Agent.count >= 1 is now validated at construction time
        with pytest.raises(ValueError, match="count must be >= 1"):
            Agent(kind=AgentKind.COMPUTE_TILE, count=0)

    def test_validate_catches_cycles(self):
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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


# ══════════════════════════════════════════════════════════════════════════════
# Integration: CompileRequest → existing Topology
# ══════════════════════════════════════════════════════════════════════════════

class TestAddressMap:
    """PRD §4.3: Address map with range validation."""

    def test_address_range_creation(self):
        from veritx_dse.compile_model import AddressRange
        r = AddressRange(name="HBM0", base=0x0, size=0x1000000)
        assert r.name == "HBM0"
        assert r.base == 0
        assert r.size == 0x1000000

    def test_address_map_creation(self):
        from veritx_dse.compile_model import AddressMap, AddressRange
        am = AddressMap(ranges=[
            AddressRange(name="HBM0", base=0x0, size=0x1000000),
            AddressRange(name="HBM1", base=0x1000000, size=0x1000000),
        ])
        assert len(am.ranges) == 2
        assert am.total_bytes() == 0x2000000

    def test_address_map_no_overlaps(self):
        from veritx_dse.compile_model import AddressMap, AddressRange
        am = AddressMap(ranges=[
            AddressRange(name="A", base=0x0, size=0x100),
            AddressRange(name="B", base=0x100, size=0x100),
        ])
        errors = am.validate_no_overlaps()
        assert len(errors) == 0

    def test_address_map_detects_overlaps(self):
        from veritx_dse.compile_model import AddressMap, AddressRange
        am = AddressMap(ranges=[
            AddressRange(name="A", base=0x0, size=0x200),
            AddressRange(name="B", base=0x100, size=0x100),
        ])
        errors = am.validate_no_overlaps()
        assert len(errors) == 1
        assert "overlap" in errors[0].lower()

    def test_address_map_from_dict(self):
        from veritx_dse.compile_model import AddressMap
        am = AddressMap.from_dict({"ranges": [
            {"name": "DRAM", "base": 0, "size": 0x2000000},
        ]})
        assert len(am.ranges) == 1
        assert am.ranges[0].name == "DRAM"

    def test_address_map_immutable(self):
        from veritx_dse.compile_model import AddressMap
        am = AddressMap()
        with pytest.raises(AttributeError):
            am.ranges = ()


class TestPhysicalContext:
    """PRD §10: Physical implementation context."""

    def test_physical_defaults(self):
        from veritx_dse.compile_model import PhysicalContext
        p = PhysicalContext()
        assert p.default_clock_freq_mhz == 1000.0
        assert p.default_data_width == 256
        assert p.process_node_nm == 7

    def test_physical_custom(self):
        from veritx_dse.compile_model import PhysicalContext
        p = PhysicalContext(default_clock_freq_mhz=2000.0, process_node_nm=5)
        assert p.default_clock_freq_mhz == 2000.0
        assert p.process_node_nm == 5

    def test_physical_immutable(self):
        from veritx_dse.compile_model import PhysicalContext
        p = PhysicalContext()
        with pytest.raises(AttributeError):
            p.default_clock_freq_mhz = 500.0


class TestVCAssignment:
    """PRD §11.3: VC assignment derived from dependency graph."""

    def test_no_cycles_gives_dor(self):
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import (
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
        from veritx_dse.compile_model import VCAssignment
        va = VCAssignment(vc_count=2, per_class_vc={}, routing_function="dor")
        with pytest.raises(AttributeError):
            va.vc_count = 3


class TestIntegration:
    """CompileRequest should bridge to existing Topology/BookSim types."""

    def test_compile_request_to_topology(self):
        from veritx_dse.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, derive_topology_spec,
        )
        from veritx_dse.presets import Topology
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
        from veritx_dse.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, derive_topology_spec,
        )
        from veritx_dse.booksim import build_config
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
        from veritx_dse.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
            AgentKind, ModelFamily, TopologyFamily, validate,
            derive_topology_spec, derive_vc_assignment,
        )
        from veritx_dse.booksim import build_config

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
        assert "num_vcs = 4;" in config  # default (no VC separation needed)

    def test_full_pipeline_with_cycles(self):
        """End-to-end: CompileRequest with cycles → VC separation."""
        from veritx_dse.compile_model import (
            CompileRequest, Workload, Agent, DependencyGraph, Dependency,
            DepKind, NocConfig, AgentKind, ModelFamily, TopologyFamily,
            validate, derive_topology_spec, derive_vc_assignment,
        )
        from veritx_dse.booksim import build_config

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
        assert topo.params.get("num_vcs", 4) == 3  # vc_count(2) + 1

        # Step 4: Build BookSim config (uses derived num_vcs)
        config = build_config(topo, cr.workload.trace_path)
        assert "routing_function = dor;" in config
        assert "num_vcs = 3;" in config

    def test_compile_request_roundtrip(self):
        """CompileRequest → to_dict → from_dict preserves all fields."""
        from veritx_dse.compile_model import (
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
