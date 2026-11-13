"""Tests for the design-bound physical runner.

The runner must never turn absent tooling, absent metrics or a failing gate into
a physical pass. These tests pin that behaviour without requiring LibreLane.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from veritx_dse.product import physical_runner as pr

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_physical_file_selection_excludes_testbench_and_binaries(tmp_path):
    (tmp_path / "project_top.sv").write_text("module project_top(input logic clk);\nendmodule\n")
    (tmp_path / "noc_pkg.sv").write_text("package noc_pkg;\nendpackage\n")
    (tmp_path / "tb_project_top.sv").write_text("module tb_project_top;\nendmodule\n")
    (tmp_path / "tb_top.cpp").write_text("int main(){return 0;}\n")
    (tmp_path / "meta.json").write_text(json.dumps({"files": ["project_top.sv"]}))
    files = pr.physical_files(tmp_path)
    assert [path.name for path in files] == ["noc_pkg.sv", "project_top.sv"]


def test_declared_files_that_are_absent_refuse_to_run(tmp_path):
    (tmp_path / "project_top.sv").write_text("module project_top; endmodule\n")
    with pytest.raises(pr.PhysicalRunnerError):
        pr.physical_files(tmp_path, ["project_top.sv", "missing.sv"])


def test_design_without_rtl_refuses_to_run(tmp_path):
    with pytest.raises(pr.PhysicalRunnerError):
        pr.physical_files(tmp_path, [])


def test_clock_ports_reads_input_clock_like_ports():
    source = (
        "module project_top (\n"
        "  input logic clk,\n"
        "  input logic rst_n,\n"
        "  input logic init0_clk,\n"
        "  input logic [7:0] init0_awaddr,\n"
        "  output logic dbg_hold\n);\n"
    )
    assert pr.clock_ports(source) == ["clk", "init0_clk"]


def test_absent_metrics_never_report_a_pass():
    gates = pr.gates_from_metrics({})
    values = gates.pop("_values")
    assert set(gates.values()) == {"NOT_MEASURED"}
    assert all(value is None for value in values.values())


def test_clean_metrics_pass_every_gate():
    metrics = {
        "timing__setup__ws__corner:nom_tt_025C_1v80": 1.25,
        "timing__setup__tns__corner:nom_tt_025C_1v80": 0.0,
        "timing__hold__ws__corner:nom_tt_025C_1v80": 0.11,
        "magic__drc_error__count": 0,
        "netgen__lvs_error__count": 0,
        "design__antenna_violation__count": 0,
        "design__instance_unmapped__count": 0,
        "design__die__area": 1000.0,
        "design__instance__count": 42,
    }
    gates = pr.gates_from_metrics(metrics)
    values = gates.pop("_values")
    assert set(gates.values()) == {"PASS"}
    assert values["setup_ws"] == 1.25
    assert values["drc_errors"] == 0


@pytest.mark.parametrize("key,value,failed_gate", [
    ("timing__setup__ws__corner:nom_tt_025C_1v80", -0.5, "setup_slack"),
    ("timing__hold__ws__corner:nom_tt_025C_1v80", -0.01, "hold_slack"),
    ("magic__drc_error__count", 3, "drc"),
    ("netgen__lvs_error__count", 1, "lvs"),
    ("design__antenna_violation__count", 2, "antenna"),
    ("design__instance_unmapped__count", 7, "unmapped_cells_clear"),
])
def test_any_failing_gate_fails_the_run(key, value, failed_gate):
    metrics = {
        "timing__setup__ws__corner:nom_tt_025C_1v80": 1.25,
        "timing__hold__ws__corner:nom_tt_025C_1v80": 0.11,
        "magic__drc_error__count": 0,
        "netgen__lvs_error__count": 0,
        "design__antenna_violation__count": 0,
        "design__instance_unmapped__count": 0,
    }
    metrics[key] = value
    gates = pr.gates_from_metrics(metrics)
    gates.pop("_values")
    assert gates[failed_gate] == "FAIL"


def test_missing_toolchain_is_blocked_not_passed(tmp_path, monkeypatch):
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "project_top.sv").write_text(
        "module project_top(input logic clk); endmodule\n")
    monkeypatch.setattr(pr, "find_librelane", lambda explicit=None: None)
    result = pr.run_design_physical(tmp_path / "design", tmp_path / "out")
    assert result["status"] == "BLOCKED"
    assert "LibreLane" in result["reason"]


def test_missing_pdk_is_blocked_not_passed(tmp_path, monkeypatch):
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "project_top.sv").write_text(
        "module project_top(input logic clk); endmodule\n")
    monkeypatch.setattr(pr, "find_pdk_root", lambda platform, explicit=None: None)
    result = pr.run_design_physical(tmp_path / "design", tmp_path / "out")
    assert result["status"] == "BLOCKED"
    assert "PDK" in result["reason"]


def test_incomplete_backend_toolchain_is_blocked(tmp_path, monkeypatch):
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "project_top.sv").write_text(
        "module project_top(input logic clk); endmodule\n")
    monkeypatch.setattr(pr, "discover_tools",
                        lambda prefixes=None: {"openroad": None, "magic": None,
                                               "netgen": None, "klayout": None,
                                               "yosys": "/usr/bin/yosys",
                                               "verilator": "/usr/bin/verilator"})
    result = pr.run_design_physical(tmp_path / "design", tmp_path / "out")
    assert result["status"] == "BLOCKED"
    assert "missing" in result["reason"]
    assert "openroad" in result["missing_tools"]
    assert not (tmp_path / "out" / "runs").exists()


def test_physical_stage_records_evidence_and_blocker(tmp_path, monkeypatch):
    from scripts.complete_design import physical_stage

    design = tmp_path / "hardware" / "rtl"
    design.mkdir(parents=True)
    (design / "project_top.sv").write_text("module project_top(input logic clk); endmodule\n")
    (design / "meta.json").write_text(json.dumps({"files": ["project_top.sv"]}))

    def fake_run(*args, **kwargs):
        return {"schema": pr.SCHEMA, "status": "FAIL", "reason": "LibreLane exited 2",
                "design_name": "project_top", "clock_port": "clk",
                "rtl": [], "config_sha256": "abc", "flow_complete": False,
                "final_stage": None, "gates": {"drc": "NOT_MEASURED"},
                "metrics": {}, "duration_s": 1.0, "librelane": {"path": "x"}}

    monkeypatch.setattr(pr, "run_design_physical", fake_run)
    manifest = {"blockers": [], "stages": []}
    physical_stage(manifest, tmp_path, "sky130A", True)
    stage = manifest["stages"][-1]
    assert stage["status"] == "FAIL"
    assert stage["evidence_sha256"]
    assert manifest["blockers"][0]["code"] == "PHYSICAL_GATES_NOT_MET"


def test_invocation_runs_librelane_natively(tmp_path):
    command = pr.build_invocation(
        Path("/usr/bin/librelane"), tmp_path / "config.json", tmp_path, tmp_path / "pdks",
        "sky130A", "tagged", None)
    assert command[0] == "/usr/bin/librelane"
    assert "--pdk-root" in command
    assert str((tmp_path / "pdks").resolve()) in command
    assert "podman" not in command


def test_invocation_uses_the_container_toolchain(tmp_path):
    command = pr.build_invocation(
        Path("/usr/bin/librelane"), tmp_path / "config.json", tmp_path, tmp_path / "pdks",
        "sky130A", "tagged", "Yosys.Synthesis",
        container_image="localhost/librelane-ll:latest",
        library_path="/nix/store/x-lib/lib")
    assert command[:2] == ["podman", "run"]
    assert "localhost/librelane-ll:latest" in command
    joined = " ".join(command)
    assert ":/pdk:ro" in joined and ":/work:Z" in joined
    assert "--only" in joined and "Yosys.Synthesis" in joined
    assert "LD_LIBRARY_PATH=/nix/store/x-lib/lib" in joined


def test_container_image_skips_host_toolchain_check(tmp_path, monkeypatch):
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "project_top.sv").write_text(
        "module project_top(input logic clk); endmodule\n")
    monkeypatch.setattr(pr, "discover_tools",
                        lambda prefixes=None: {name: None for name in pr.BACKEND_TOOLS})
    called = {}

    def fake_stream(command, cwd, log_path, timeout_s):
        called["command"] = command
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("fake\n")
        return 2

    monkeypatch.setattr(pr, "_stream", fake_stream)
    result = pr.run_design_physical(
        tmp_path / "design", tmp_path / "out",
        container_image="localhost/librelane-ll:latest")
    assert called["command"][0] == "podman"
    assert result["status"] == "FAIL"
    assert result["container_image"] == "localhost/librelane-ll:latest"
