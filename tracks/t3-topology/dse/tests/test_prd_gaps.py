"""TDD tests for PRD gap fixes — §4.2, §5, §7, §12, §13, §14.

These tests are written BEFORE implementation (red phase). Implementation
in reports.py, artifact.py, and compile_model.py extensions must make
ALL tests pass.
"""
from __future__ import annotations

import hashlib
import json
import time
import pytest
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
# §7 — Formal area/power/timing reports
# ══════════════════════════════════════════════════════════════════════════════

class TestAreaModel:
    """PRD §7.1: Area — per-block and total fabric area."""

    def test_router_area_7nm(self):
        from veritx_dse.reports.reports import estimate_router_area
        # At 7nm: ~0.005 mm² per router (realistic for 64-port NoC router)
        area = estimate_router_area(count=64, process_nm=7)
        assert area > 0
        assert area < 1.0  # should be sub-mm² for 64 routers at 7nm

    def test_router_area_scales_with_count(self):
        from veritx_dse.reports.reports import estimate_router_area
        a1 = estimate_router_area(count=16, process_nm=7)
        a2 = estimate_router_area(count=64, process_nm=7)
        assert a2 > a1
        # Should scale roughly linearly
        assert abs(a2 / a1 - 4.0) < 0.5

    def test_link_area(self):
        from veritx_dse.reports.reports import estimate_link_area
        area = estimate_link_area(count=128, data_width=256, process_nm=7)
        assert area > 0

    def test_nic_area(self):
        from veritx_dse.reports.reports import estimate_nic_area
        area = estimate_nic_area(count=16, data_width=256, process_nm=7)
        assert area > 0

    def test_total_fabric_area(self):
        from veritx_dse.reports.reports import estimate_fabric_area
        result = estimate_fabric_area(
            n_routers=64, n_links=128, n_nics=16, data_width=256,
            process_nm=7, has_rcu=False, has_mecs=False,
        )
        assert "total_mm2" in result
        assert "routers_mm2" in result
        assert "links_mm2" in result
        assert "nics_mm2" in result
        assert result["total_mm2"] > 0
        # Sum check
        assert abs(result["total_mm2"] - (result["routers_mm2"] + result["links_mm2"] + result["nics_mm2"])) < 0.001

    def test_rcu_area_adds(self):
        from veritx_dse.reports.reports import estimate_fabric_area
        base = estimate_fabric_area(64, 128, 16, 256, 7, False, False)
        with_rcu = estimate_fabric_area(64, 128, 16, 256, 7, True, False)
        assert with_rcu["total_mm2"] > base["total_mm2"]

    def test_mecs_area_adds(self):
        from veritx_dse.reports.reports import estimate_fabric_area
        base = estimate_fabric_area(64, 128, 16, 256, 7, False, False)
        with_mecs = estimate_fabric_area(64, 128, 16, 256, 7, False, True)
        assert with_mecs["total_mm2"] > base["total_mm2"]


class TestPowerModel:
    """PRD §7.2: Power — dynamic + leakage by block."""

    def test_dynamic_power(self):
        from veritx_dse.reports.reports import estimate_dynamic_power
        power = estimate_dynamic_power(
            activity_rate=0.3, data_width=256, n_hops=4.0,
            voltage=0.75, freq_ghz=1.0,
        )
        assert power > 0
        assert power < 100  # reasonable watts for NoC

    def test_power_scales_with_activity(self):
        from veritx_dse.reports.reports import estimate_dynamic_power
        p1 = estimate_dynamic_power(0.1, 256, 4.0, 0.75, 1.0)
        p2 = estimate_dynamic_power(0.5, 256, 4.0, 0.75, 1.0)
        assert p2 > p1

    def test_leakage_power(self):
        from veritx_dse.reports.reports import estimate_leakage_power
        power = estimate_leakage_power(n_routers=64, process_nm=7)
        assert power > 0

    def test_total_power(self):
        from veritx_dse.reports.reports import estimate_total_power
        result = estimate_total_power(
            n_routers=64, data_width=256, activity_rate=0.3,
            avg_hops=4.0, voltage=0.75, freq_ghz=1.0, process_nm=7,
        )
        assert "dynamic_w" in result
        assert "leakage_w" in result
        assert "total_w" in result
        assert abs(result["total_w"] - (result["dynamic_w"] + result["leakage_w"])) < 0.0001

    def test_energy_per_bit(self):
        from veritx_dse.reports.reports import compute_energy_per_bit
        e = compute_energy_per_bit(data_width=256, avg_hops=4.0)
        # Typical: 0.1-1.0 pJ/bit for on-chip NoC
        assert 0.01 < e < 10.0


class TestTimingModel:
    """PRD §7.3: Timing — Fmax per path class, critical paths."""

    def test_max_frequency_mesh(self):
        from veritx_dse.reports.reports import estimate_max_frequency
        fmax = estimate_max_frequency(
            topology="mesh", process_nm=7, data_width=256,
        )
        # Derated 7nm mesh: 1.5-2.5 GHz
        assert fmax > 500  # MHz
        assert fmax < 3000

    def test_max_frequency_ideal_vs_derated(self):
        from veritx_dse.reports.reports import estimate_max_frequency
        ideal = estimate_max_frequency("mesh", 7, 256, derated=False)
        derated = estimate_max_frequency("mesh", 7, 256, derated=True)
        assert ideal > derated
        assert abs(derated / ideal - 0.75) < 0.01  # 75% derating

    def test_max_frequency_torus(self):
        from veritx_dse.reports.reports import estimate_max_frequency
        fmax_torus = estimate_max_frequency("torus", 7, 256)
        fmax_mesh = estimate_max_frequency("mesh", 7, 256)
        # Torus has wraparound → longer wire → slightly lower Fmax
        assert fmax_torus <= fmax_mesh * 1.1  # within 10%

    def test_critical_path(self):
        from veritx_dse.reports.reports import estimate_critical_path_ps
        cp = estimate_critical_path_ps("mesh", 7, 256)
        assert cp > 0
        assert cp < 2000  # picoseconds, reasonable for 7nm

    def test_pipeline_stages(self):
        from veritx_dse.reports.reports import router_pipeline_stages
        stages = router_pipeline_stages()
        # Standard: buffer → routing → VC alloc → switch alloc → crossbar
        assert len(stages) >= 4
        assert all("name" in s and "delay_ps" in s for s in stages)


class TestFullReport:
    """PRD §7: Complete report generation from CompileRequest + sim result."""

    def test_generate_report(self):
        from veritx_dse.reports.reports import generate_report
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, ModelFamily, ServingMode,
            Agent, AgentKind, NocConfig, TopologyFamily,
            DependencyGraph, PhysicalContext,
        )
        cr = CompileRequest(
            workload=Workload(
                model_family=ModelFamily.MOE,
                model_name="Qwen3-30B",
                tp=16, ep=8,
                serving_mode=ServingMode.DECODE_HEAVY,
                trace_path="runs/traces/qwen3_serving_16rank.trace",
            ),
            requirements=(),
            agents=(
                Agent(AgentKind.COMPUTE_TILE, 16, 256, 64, "AXI"),
                Agent(AgentKind.HBM_CONTROLLER, 4, 256, 64, "AXI"),
            ),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
            physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        )
        sim_result = {"latency": 1863.0, "hops": 4.2}

        report = generate_report(cr, sim_result)
        assert "area" in report
        assert "power" in report
        assert "timing" in report
        assert "guardrail_hash" in report
        assert report["area"]["total_mm2"] > 0
        assert report["power"]["total_w"] > 0
        assert report["timing"]["max_freq_mhz"] > 500

    def test_generate_report_with_edges(self):
        from veritx_dse.reports.reports import generate_report
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, ModelFamily,
            Agent, AgentKind, NocConfig, DependencyGraph,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 20),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        # With n_edges=448 (GEC), area should be larger than default
        report_with = generate_report(cr, {}, n_edges=448)
        report_without = generate_report(cr, {}, n_edges=None)
        assert report_with["area"]["links_mm2"] > report_without["area"]["links_mm2"]

    def test_report_has_guardrail_hash(self):
        from veritx_dse.reports.reports import generate_report
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, ModelFamily,
            Agent, AgentKind, NocConfig, DependencyGraph,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 64, 256, 64),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        report = generate_report(cr, {})
        assert "guardrail_hash" in report
        assert len(report["guardrail_hash"]) == 64  # SHA-256 hex


# ══════════════════════════════════════════════════════════════════════════════
# §5 — Workload shape fields + collective model
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkloadShape:
    """PRD §5.1 Level A: Shape — parameter count, seq length, batch, precision."""

    def test_workload_has_shape_fields(self):
        from veritx_dse.model.compile_model import Workload, ModelFamily
        wl = Workload(
            model_family=ModelFamily.MOE,
            param_count_b=30,
            sequence_length=4096,
            batch_size=1,
            precision="fp8",
        )
        assert wl.param_count_b == 30
        assert wl.sequence_length == 4096
        assert wl.batch_size == 1
        assert wl.precision == "fp8"

    def test_workload_defaults(self):
        from veritx_dse.model.compile_model import Workload, ModelFamily
        wl = Workload(model_family=ModelFamily.CNN)
        assert wl.param_count_b is None
        assert wl.precision == "fp16"  # default

    def test_collective_operations(self):
        from veritx_dse.model.compile_model import Workload, ModelFamily, CollectiveOp, CollectiveKind
        wl = Workload(
            model_family=ModelFamily.DENSE_TRANSFORMER,
            tp=8,
            collectives=(
                CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8, bytes_per_element=2048),
                CollectiveOp(kind=CollectiveKind.ALLGATHER, group_size=8, bytes_per_element=4096),
            ),
        )
        assert len(wl.collectives) == 2
        assert wl.collectives[0].kind == CollectiveKind.ALLREDUCE
        assert wl.collectives[1].bytes_per_element == 4096


class TestAgentClockPower:
    """PRD §4.2: Per-agent clock domain + power domain."""

    def test_agent_has_clock_domain(self):
        from veritx_dse.model.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.COMPUTE_TILE, count=64, clock_domain="fabric_clk")
        assert a.clock_domain == "fabric_clk"

    def test_agent_has_power_domain(self):
        from veritx_dse.model.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.HBM_CONTROLLER, count=4, power_domain="pd_hbm")
        assert a.power_domain == "pd_hbm"

    def test_agent_defaults(self):
        from veritx_dse.model.compile_model import Agent, AgentKind
        a = Agent(kind=AgentKind.NIC, count=2)
        assert a.clock_domain is None
        assert a.power_domain is None


# ══════════════════════════════════════════════════════════════════════════════
# §12 — Artifact signing + manifest with revision chain
# ══════════════════════════════════════════════════════════════════════════════

class TestArtifactSigning:
    """PRD §12, §14: Design manifest with signature and revision chain."""

    def test_sign_manifest(self):
        from veritx_dse.reports.artifact import sign_manifest
        manifest = {"design_id": "abc123", "guardrail_hash": "deadbeef"}
        sig = sign_manifest(manifest, secret_key="test-key")
        assert sig is not None
        assert len(sig) > 0

    def test_verify_manifest(self):
        from veritx_dse.reports.artifact import sign_manifest, verify_manifest
        manifest = {"design_id": "abc123", "guardrail_hash": "deadbeef"}
        sig = sign_manifest(manifest, secret_key="test-key")
        assert verify_manifest(manifest, sig, secret_key="test-key") is True

    def test_verify_wrong_key_fails(self):
        from veritx_dse.reports.artifact import sign_manifest, verify_manifest
        manifest = {"design_id": "abc123"}
        sig = sign_manifest(manifest, secret_key="right-key")
        assert verify_manifest(manifest, sig, secret_key="wrong-key") is False

    def test_verify_tampered_manifest_fails(self):
        from veritx_dse.reports.artifact import sign_manifest, verify_manifest
        manifest = {"design_id": "abc123"}
        sig = sign_manifest(manifest, secret_key="key")
        tampered = {"design_id": "abc123", "extra": "field"}
        assert verify_manifest(tampered, sig, secret_key="key") is False


class TestDesignManifest:
    """PRD §12: Design revision with full manifest."""

    def test_create_manifest(self):
        from veritx_dse.reports.artifact import DesignManifest
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, NocConfig, DependencyGraph, Agent, AgentKind
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 64),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        dm = DesignManifest.create(cr, secret_key="test-key")
        assert dm.design_id is not None
        assert dm.guardrail_hash == cr.guardrail_hash()
        assert dm.revision == 1

    def test_create_without_key_is_refused(self):
        """PR B: no default signing secret exists — omitting the key must
        fail loudly rather than sign with a source-embedded value."""
        from veritx_dse.reports.artifact import DesignManifest, MissingSigningKey
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, NocConfig, DependencyGraph, Agent, AgentKind
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 64),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        with pytest.raises(MissingSigningKey):
            DesignManifest.create(cr)

    def test_create_unsigned_is_honest(self):
        """PR B: unsigned mode records CHECKSUMMED_UNSIGNED and an empty
        signature — never a fake signature and never a hidden-key one."""
        from veritx_dse.reports.artifact import DesignManifest
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, NocConfig, DependencyGraph, Agent, AgentKind
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 64),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        dm = DesignManifest.create_unsigned(cr)
        assert dm.signature == ""
        assert dm.metadata["signing_mode"] == "CHECKSUMMED_UNSIGNED"
        assert dm.manifest_hash  # checksum integrity still present

    def test_manifest_revision_chain(self):
        from veritx_dse.reports.artifact import DesignManifest
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, NocConfig, DependencyGraph, Agent, AgentKind
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 64),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        dm1 = DesignManifest.create(cr, secret_key="test-key")
        dm2 = dm1.revise(cr, secret_key="test-key")
        assert dm2.revision == 2
        assert dm2.parent_hash == dm1.manifest_hash
        assert dm2.design_id == dm1.design_id  # same design, new revision

    def test_manifest_to_dict_roundtrip(self):
        from veritx_dse.reports.artifact import DesignManifest
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, NocConfig, DependencyGraph, Agent, AgentKind
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 64),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        dm = DesignManifest.create(cr, secret_key="test-key")
        d = dm.to_dict()
        dm2 = DesignManifest.from_dict(d)
        assert dm2.design_id == dm.design_id
        assert dm2.revision == dm.revision
        assert dm2.guardrail_hash == dm.guardrail_hash


# ══════════════════════════════════════════════════════════════════════════════
# §13 — Full compile pipeline with Verify + Generate stages
# ══════════════════════════════════════════════════════════════════════════════

class TestCompilePipeline:
    """PRD §13: Submit→Validate→Simulate→Optimize→Verify→Sign→Return."""

    def test_compile_report_includes_all_stages(self):
        """The compile output should include results from every pipeline stage."""
        from veritx_dse.reports.reports import generate_report
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, NocConfig, DependencyGraph, Agent, AgentKind
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.MOE),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 64),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        report = generate_report(cr, {"latency": 100.0})
        # Pipeline stages that must appear in report
        assert "validation" in report or "vc_assignment" in report
        assert "simulation" in report
        assert "area" in report
        assert "power" in report
        assert "timing" in report


class TestWorkloadPresets:
    """PRD §16: Built-in workload library."""

    def test_preset_exists(self):
        from veritx_dse.model.presets import WORKLOAD_PRESETS
        assert len(WORKLOAD_PRESETS) >= 5  # at least 5 presets

    def test_preset_has_required_fields(self):
        from veritx_dse.model.presets import WORKLOAD_PRESETS
        for name, preset in WORKLOAD_PRESETS.items():
            assert "desc" in preset
            assert "workload" in preset
            assert "agents" in preset

    def test_preset_to_compile_request(self):
        from veritx_dse.model.presets import WORKLOAD_PRESETS, preset_to_compile_request
        cr = preset_to_compile_request("qwen3_moe_16npu")
        assert cr.workload.model_family.value == "mixture_of_experts"
        assert cr.total_nodes > 0

    def test_known_presets(self):
        from veritx_dse.model.presets import WORKLOAD_PRESETS
        assert "qwen3_moe_16npu" in WORKLOAD_PRESETS
        assert "llama70b_tp64" in WORKLOAD_PRESETS
        assert "llama1b_tp64" in WORKLOAD_PRESETS
        assert "dense_64npu" in WORKLOAD_PRESETS
        assert "moe_8npu" in WORKLOAD_PRESETS
