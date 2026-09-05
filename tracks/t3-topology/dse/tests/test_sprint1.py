"""TDD tests for Sprint 1: Result entity, Artifact entity, Verify + Generate stages.

These tests are written BEFORE implementation (red phase).
"""
from __future__ import annotations

import hashlib
import json
import pytest
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
# §12.8 — Result Entity
# ══════════════════════════════════════════════════════════════════════════════

class TestResultEntity:
    """PRD §12.8: Result — latency/bw, area/power/timing."""

    def test_result_creation(self):
        from veritx_dse.model.compile_model import Result
        r = Result(
            design_id="abc-123",
            revision=1,
            latency_cycles=1863.12,
            throughput_gbps=100.0,
            area_mm2=0.298,
            power_w=0.070,
            fmax_mhz=1965,
            energy_pj_per_bit=0.630,
        )
        assert r.latency_cycles == 1863.12
        assert r.design_id == "abc-123"

    def test_result_immutable(self):
        from veritx_dse.model.compile_model import Result
        r = Result("abc", 1, 100.0, None, 0.1, 0.01, 1000, 0.5)
        with pytest.raises(AttributeError):
            r.latency_cycles = 200.0

    def test_result_to_dict(self):
        from veritx_dse.model.compile_model import Result
        r = Result("abc", 1, 100.0, 50.0, 0.1, 0.01, 1000, 0.5)
        d = r.to_dict()
        assert d["latency_cycles"] == 100.0
        assert d["throughput_gbps"] == 50.0
        assert d["design_id"] == "abc"

    def test_result_from_dict(self):
        from veritx_dse.model.compile_model import Result
        d = {"design_id": "abc", "revision": 1, "latency_cycles": 100.0,
             "throughput_gbps": None, "area_mm2": 0.1, "power_w": 0.01,
             "fmax_mhz": 1000, "energy_pj_per_bit": 0.5}
        r = Result.from_dict(d)
        assert r.latency_cycles == 100.0
        assert r.throughput_gbps is None


# ══════════════════════════════════════════════════════════════════════════════
# §12.9 — Artifact Entity
# ══════════════════════════════════════════════════════════════════════════════

class TestArtifactEntity:
    """PRD §12.9: Artifact — uri, signature, checksum."""

    def test_artifact_creation(self):
        from veritx_dse.model.compile_model import Artifact
        a = Artifact(
            artifact_id="art-001",
            design_id="abc-123",
            revision=1,
            kind="rtl",
            uri="runs/rtl/mesh_8x8/noc.sv",
            checksum_sha256="deadbeef",
            signature="abcdef",
        )
        assert a.kind == "rtl"
        assert a.uri == "runs/rtl/mesh_8x8/noc.sv"

    def test_artifact_immutable(self):
        from veritx_dse.model.compile_model import Artifact
        a = Artifact("a", "d", 1, "rtl", "f.sv", "ck", "sig")
        with pytest.raises(AttributeError):
            a.kind = "uvm"

    def test_artifact_to_dict(self):
        from veritx_dse.model.compile_model import Artifact
        a = Artifact("a", "d", 1, "rtl", "f.sv", "ck", "sig")
        d = a.to_dict()
        assert d["kind"] == "rtl"
        assert d["checksum_sha256"] == "ck"

    def test_artifact_from_dict(self):
        from veritx_dse.model.compile_model import Artifact
        d = {"artifact_id": "a", "design_id": "d", "revision": 1,
             "kind": "uvm", "uri": "tb.sv", "checksum_sha256": "ck",
             "signature": "sig"}
        a = Artifact.from_dict(d)
        assert a.kind == "uvm"

    def test_artifact_checksum_verification(self):
        from veritx_dse.model.compile_model import Artifact
        content = b"module noc; endmodule"
        checksum = hashlib.sha256(content).hexdigest()
        a = Artifact("a", "d", 1, "rtl", "noc.sv", checksum, "sig")
        # Verify checksum matches content
        assert hashlib.sha256(content).hexdigest() == a.checksum_sha256


# ══════════════════════════════════════════════════════════════════════════════
# §13.5 — Verify Stage
# ══════════════════════════════════════════════════════════════════════════════

class TestVerifyStage:
    """PRD §13.5: Verify — F1–F8 proof obligations."""

    def test_verify_stage_exists(self):
        from veritx_dse.model.compile_model import verify_design
        assert callable(verify_design)

    def test_verify_returns_result(self):
        from veritx_dse.model.compile_model import verify_design, CompileRequest, Workload, ModelFamily, Agent, AgentKind, NocConfig, DependencyGraph
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        vr = verify_design(cr, topology_name="mesh_8x8")
        assert hasattr(vr, "ok")
        assert hasattr(vr, "checks")
        assert hasattr(vr, "errors")

    def test_verify_mesh_has_checks(self):
        from veritx_dse.model.compile_model import verify_design, CompileRequest, Workload, ModelFamily, Agent, AgentKind, NocConfig, DependencyGraph
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        vr = verify_design(cr, topology_name="mesh_8x8")
        # Should have at least F1 (deadlock) and F2 (liveness) checks
        check_names = [c["name"] for c in vr.checks]
        assert "F1_deadlock_freedom" in check_names
        assert "F2_liveness" in check_names

    def test_verify_no_cycles_passes(self):
        from veritx_dse.model.compile_model import verify_design, CompileRequest, Workload, ModelFamily, Agent, AgentKind, NocConfig, DependencyGraph
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        vr = verify_design(cr, topology_name="mesh_8x8")
        # No cycles → deadlock check should pass
        deadlock_check = [c for c in vr.checks if c["name"] == "F1_deadlock_freedom"][0]
        assert deadlock_check["status"] == "PASS"


# ══════════════════════════════════════════════════════════════════════════════
# §13.6 — Generate Stage
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateStage:
    """PRD §13.6: Generate — RTL/report generation."""

    def test_generate_stage_exists(self):
        from veritx_dse.model.compile_model import generate_artifacts
        assert callable(generate_artifacts)

    def test_generate_returns_artifacts(self):
        from veritx_dse.model.compile_model import generate_artifacts, CompileRequest, Workload, ModelFamily, Agent, AgentKind, NocConfig, DependencyGraph
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        artifacts = generate_artifacts(cr, output_dir="/tmp/test_gen")
        assert isinstance(artifacts, list)
        assert all(hasattr(a, "kind") for a in artifacts)

    def test_generate_manifest_artifact(self):
        from veritx_dse.model.compile_model import generate_artifacts, CompileRequest, Workload, ModelFamily, Agent, AgentKind, NocConfig, DependencyGraph
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        artifacts = generate_artifacts(cr, output_dir="/tmp/test_gen")
        kinds = [a.kind for a in artifacts]
        assert "manifest" in kinds


# ══════════════════════════════════════════════════════════════════════════════
# §13 — Full Pipeline with All Stages
# ══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """PRD §13: Submit→Validate→Simulate→Verify→Generate→Sign→Return."""

    def test_pipeline_report_includes_result(self):
        from veritx_dse.reports.reports import generate_report
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, Agent, AgentKind, NocConfig, DependencyGraph
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        report = generate_report(cr, {"latency": 100.0, "hops": 4.0})
        # Report should now include result and artifacts sections
        assert "result" in report or "simulation" in report

    def test_pipeline_report_includes_verification(self):
        from veritx_dse.reports.reports import generate_report
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, Agent, AgentKind, NocConfig, DependencyGraph
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        report = generate_report(cr, {"latency": 100.0, "hops": 4.0})
        assert "verification" in report

    def test_pipeline_report_includes_artifacts(self):
        from veritx_dse.reports.reports import generate_report
        from veritx_dse.model.compile_model import CompileRequest, Workload, ModelFamily, Agent, AgentKind, NocConfig, DependencyGraph
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(),
        )
        report = generate_report(cr, {"latency": 100.0, "hops": 4.0})
        assert "artifacts" in report
