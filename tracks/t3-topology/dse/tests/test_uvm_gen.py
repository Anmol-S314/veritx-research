"""TDD tests for UVM testbench generator (PRD §9.3).

Generates SystemVerilog UVM testbenches for NoC verification.
Tests written BEFORE implementation (red phase).
"""
from __future__ import annotations

import pytest
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
# UVM Generator Module
# ══════════════════════════════════════════════════════════════════════════════

class TestUVMGenerator:
    """PRD §9.3: UVM verification suite generation."""

    def test_generator_importable(self):
        from veritx_dse.uvm_gen import generate_uvm
        assert callable(generate_uvm)

    def test_generate_returns_dict(self):
        from veritx_dse.uvm_gen import generate_uvm
        from veritx_dse.compile_model import (
            CompileRequest, Workload, ModelFamily, Agent, AgentKind,
            NocConfig, DependencyGraph, TopologyFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8, 256, 64, "AXI"),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        result = generate_uvm(cr, n_nodes=8, k=2)
        assert isinstance(result, dict)
        assert "files" in result
        assert "tb_top" in result

    def test_generate_produces_tb_top(self):
        from veritx_dse.uvm_gen import generate_uvm
        from veritx_dse.compile_model import (
            CompileRequest, Workload, ModelFamily, Agent, AgentKind,
            NocConfig, DependencyGraph, TopologyFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 8, 256, 64, "AXI"),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        result = generate_uvm(cr, n_nodes=8, k=2)
        tb = result["tb_top"]
        assert "module" in tb
        assert "uvm" in tb.lower()
        assert "run_test" in tb

    def test_generate_produces_sequences(self):
        from veritx_dse.uvm_gen import generate_uvm
        from veritx_dse.compile_model import (
            CompileRequest, Workload, ModelFamily, Agent, AgentKind,
            NocConfig, DependencyGraph, TopologyFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 4, 256, 64, "AXI"),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        result = generate_uvm(cr, n_nodes=4, k=2)
        assert "sequences" in result
        seq = result["sequences"]
        assert "class" in seq
        assert "sequence" in seq.lower() or "uvm_sequence" in seq

    def test_generate_produces_assertions(self):
        from veritx_dse.uvm_gen import generate_uvm
        from veritx_dse.compile_model import (
            CompileRequest, Workload, ModelFamily, Agent, AgentKind,
            NocConfig, DependencyGraph, TopologyFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 4, 256, 64, "AXI"),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        result = generate_uvm(cr, n_nodes=4, k=2)
        assert "assertions" in result
        assertions = result["assertions"]
        assert "assert" in assertions.lower()
        # Should have F1-F8 property checks
        assert "deadlock" in assertions.lower() or "liveness" in assertions.lower()

    def test_generate_produces_coverage(self):
        from veritx_dse.uvm_gen import generate_uvm
        from veritx_dse.compile_model import (
            CompileRequest, Workload, ModelFamily, Agent, AgentKind,
            NocConfig, DependencyGraph, TopologyFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 4, 256, 64, "AXI"),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        result = generate_uvm(cr, n_nodes=4, k=2)
        assert "coverage" in result
        cov = result["coverage"]
        assert "covergroup" in cov.lower() or "coverpoint" in cov.lower()

    def test_generate_produces_all_files(self):
        from veritx_dse.uvm_gen import generate_uvm
        from veritx_dse.compile_model import (
            CompileRequest, Workload, ModelFamily, Agent, AgentKind,
            NocConfig, DependencyGraph, TopologyFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 4, 256, 64, "AXI"),),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        result = generate_uvm(cr, n_nodes=4, k=2)
        # Should produce at least: tb, sequences, assertions, coverage
        assert len(result["files"]) >= 4

    def test_generate_tops_from_agents(self):
        from veritx_dse.uvm_gen import generate_uvm
        from veritx_dse.compile_model import (
            CompileRequest, Workload, ModelFamily, Agent, AgentKind,
            NocConfig, DependencyGraph, TopologyFamily,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(
                Agent(AgentKind.COMPUTE_TILE, 16, 256, 64, "AXI"),
                Agent(AgentKind.HBM_CONTROLLER, 4, 256, 64, "AXI"),
            ),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        result = generate_uvm(cr, n_nodes=16, k=4)
        tb = result["tb_top"]
        # Should instantiate the right number of agents
        assert "16" in tb or "compute_tile" in tb.lower()

    def test_generate_with_cycles_warning(self):
        from veritx_dse.uvm_gen import generate_uvm
        from veritx_dse.compile_model import (
            CompileRequest, Workload, ModelFamily, Agent, AgentKind,
            NocConfig, DependencyGraph, TopologyFamily,
            Dependency, DepKind,
        )
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.CUSTOM),
            requirements=(),
            agents=(Agent(AgentKind.COMPUTE_TILE, 4, 256, 64, "AXI"),),
            dependencies=DependencyGraph([
                Dependency("A", "B", DepKind.BLOCKING),
                Dependency("B", "A", DepKind.BLOCKING),
            ]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        result = generate_uvm(cr, n_nodes=4, k=2)
        # With cycles, should include VC separation test sequences
        seq = result["sequences"]
        assert "vc" in seq.lower() or "virtual_channel" in seq.lower()


# ══════════════════════════════════════════════════════════════════════════════
# CLI Integration
# ══════════════════════════════════════════════════════════════════════════════

class TestUVMCLI:
    """PRD §9.3: UVM generation via CLI."""

    def test_generate_command_exists(self):
        from veritx_dse.cli import build_parser
        parser = build_parser()
        # Should be able to parse 'veritx generate uvm'
        args = parser.parse_args(["generate", "uvm", "--request", "test.json",
                                   "--out", "/tmp/uvm_test"])
        assert args.gen_cmd == "uvm"

    def test_generate_uvm_help(self):
        from veritx_dse.cli import build_parser
        parser = build_parser()
        try:
            args = parser.parse_args(["generate", "uvm", "--help"])
        except SystemExit:
            pass  # --help calls sys.exit(0)
