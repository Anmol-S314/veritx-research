"""Tests for UVM generation wired into the compile pipeline (PRD §13.5-§13.6)."""
import json
import tempfile
import pytest
from pathlib import Path
from veritx_dse.model.compile_model import (
    CompileRequest, Workload, ModelFamily, ServingMode,
    Agent, AgentKind, NocConfig, TopologyFamily,
    OutputFormat, validate, derive_vc_assignment,
    VerificationResult, verify_design, generate_artifacts,
    DependencyGraph,
)
from veritx_dse.reports.reports import generate_report
from veritx_dse.verification.uvm_gen import generate_uvm

def _make_cr(output_formats=(OutputFormat.SYSTEMVERILOG,)) -> CompileRequest:
    """Build a minimal CompileRequest for testing."""
    return CompileRequest(
        workload=Workload(
            model_family=ModelFamily.MOE,
            model_name="Qwen3-30B",
            tp=16, ep=8, serving_mode=ServingMode.DECODE_HEAVY,
        ),
        requirements=(),
        agents=(
            Agent(AgentKind.COMPUTE_TILE, 16, 256, 64, "AXI"),
            Agent(AgentKind.HBM_CONTROLLER, 4, 256, 64, "AXI"),
        ),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH, radix=8,
                             output_formats=output_formats),
    )

class TestGenerateArtifactsUVM:
    """Test that generate_artifacts tracks UVM when output_formats includes it."""

    def test_uvm_artifact_in_output(self):
        """When output_formats includes UVM, artifacts should contain a uvm entry."""
        cr = _make_cr(output_formats=(OutputFormat.SYSTEMVERILOG, OutputFormat.UVM))
        artifacts = generate_artifacts(cr)
        kinds = [a.kind for a in artifacts]
        assert "uvm" in kinds

    def test_no_uvm_when_not_requested(self):
        """When output_formats is just SystemVerilog, no uvm artifact."""
        cr = _make_cr(output_formats=(OutputFormat.SYSTEMVERILOG,))
        artifacts = generate_artifacts(cr)
        kinds = [a.kind for a in artifacts]
        assert "uvm" not in kinds

    def test_uvm_artifact_has_correct_fields(self):
        """UVM artifact should have artifact_id, design_id, kind, uri."""
        cr = _make_cr(output_formats=(OutputFormat.UVM,))
        artifacts = generate_artifacts(cr)
        uvm_art = [a for a in artifacts if a.kind == "uvm"][0]
        assert uvm_art.artifact_id.endswith("-uvm")
        assert uvm_art.kind == "uvm"
        assert ".sv" in uvm_art.uri

class TestVerifyInReport:
    """Test that verification checks appear in the report."""

    def test_report_has_verification(self):
        cr = _make_cr()
        report = generate_report(cr, {"latency": 100.0, "hops": 4.0})
        assert "verification" in report
        vr = report["verification"]
        assert vr["ok"] is True
        assert len(vr["checks"]) >= 6

    def test_report_exposes_only_planned_outputs(self):
        """Report schema labels intended URIs as plans, not materialized files."""
        cr = _make_cr()
        report = generate_report(cr, {"latency": 100.0})
        assert "artifacts" not in report
        assert "artifact_plan" in report
        assert len(report["artifact_plan"]) >= 2
        assert all("uri" in item for item in report["artifact_plan"])
        assert all("checksum_sha256" not in item for item in report["artifact_plan"])
        assert all("signature" not in item for item in report["artifact_plan"])

    def test_f1_deadlock_check(self):
        cr = _make_cr()
        report = generate_report(cr, {"latency": 100.0})
        checks = {c["name"]: c for c in report["verification"]["checks"]}
        assert "F1_deadlock_freedom" in checks
        assert checks["F1_deadlock_freedom"]["status"] == "PASS"

    def test_f7_qos_warn_with_requirements(self):
        """F7 should WARN when requirements are defined (formal QoS pending)."""
        from veritx_dse.model.compile_model import Requirement, QoSClass
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER),
            requirements=(Requirement(QoSClass.LATENCY_CRITICAL, 5000, binding=True),),
            agents=(Agent(AgentKind.COMPUTE_TILE, 4),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        report = generate_report(cr, {"latency": 100.0})
        checks = {c["name"]: c for c in report["verification"]["checks"]}
        assert checks["F7_qos_isolation"]["status"] == "WARN"

class TestUVMGeneration:
    """Test UVM generation produces valid SystemVerilog."""

    def test_uvm_generates_all_files(self):
        cr = _make_cr()
        result = generate_uvm(cr, n_nodes=16, k=4)
        expected = {"dut_binding", "tb_top", "sequences", "assertions", "coverage", "files"}
        assert expected == set(result.keys())
        assert len(result["files"]) == 5
        assert "noc_dut_binding.sv" in result["files"]

    def test_uvm_tb_has_module(self):
        cr = _make_cr()
        result = generate_uvm(cr, n_nodes=16, k=4)
        assert "module tb_noc" in result["tb_top"]

    def test_uvm_tb_has_nodes_parameter(self):
        cr = _make_cr()
        result = generate_uvm(cr, n_nodes=16, k=4)
        assert "localparam int NUM_NODES" in result["tb_top"]

    def test_uvm_assertions_include_f1_f8(self):
        cr = _make_cr()
        result = generate_uvm(cr, n_nodes=16, k=4)
        for f in ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]:
            assert f in result["assertions"]

    def test_uvm_coverage_has_bins(self):
        cr = _make_cr()
        result = generate_uvm(cr, n_nodes=16, k=4)
        assert "covergroup" in result["coverage"]
        assert "bins" in result["coverage"]

class TestCompilePipelineSteps:
    """Verify the compile pipeline reports all 6 stages."""

    def test_report_has_all_stages(self):
        """Report keeps analysis/verification and labels output URIs as plans."""
        cr = _make_cr()
        report = generate_report(cr, {"latency": 1850.0, "hops": 4.2})
        assert "validation" in report
        assert "vc_assignment" in report
        assert "verification" in report
        assert "artifact_plan" in report
        assert "area" in report
        assert "power" in report
        assert "timing" in report
        assert "energy" in report

    def test_derived_routing_is_locked(self):
        """Routing function should be derived from dependency graph."""
        cr = _make_cr()
        report = generate_report(cr, {"latency": 100.0})
        routing = report["vc_assignment"]["routing_function"]
        assert routing == "dim_order"
