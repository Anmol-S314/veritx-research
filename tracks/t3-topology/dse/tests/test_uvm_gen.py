"""TDD tests for UVM testbench generator (PRD §9.3).

Generates SystemVerilog UVM testbenches for NoC verification.
Tests written BEFORE implementation (red phase).
"""
from __future__ import annotations

import re

import pytest
from pathlib import Path

class TestUVMGenerator:
    """PRD §9.3: UVM verification suite generation."""

    def test_generator_importable(self):
        from veritx_dse.verification.uvm_gen import generate_uvm
        assert callable(generate_uvm)

    def test_generate_returns_dict(self):
        from veritx_dse.verification.uvm_gen import generate_uvm
        from veritx_dse.model.compile_model import (
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
        from veritx_dse.verification.uvm_gen import generate_uvm
        from veritx_dse.model.compile_model import (
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
        from veritx_dse.verification.uvm_gen import generate_uvm
        from veritx_dse.model.compile_model import (
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
        from veritx_dse.verification.uvm_gen import generate_uvm
        from veritx_dse.model.compile_model import (
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
        assert "deadlock" in assertions.lower() or "liveness" in assertions.lower()

    def test_generate_produces_coverage(self):
        from veritx_dse.verification.uvm_gen import generate_uvm
        from veritx_dse.model.compile_model import (
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
        from veritx_dse.verification.uvm_gen import generate_uvm
        from veritx_dse.model.compile_model import (
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
        assert len(result["files"]) >= 4

    def test_generate_tops_from_agents(self):
        from veritx_dse.verification.uvm_gen import generate_uvm
        from veritx_dse.model.compile_model import (
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
        assert "16" in tb or "compute_tile" in tb.lower()

    def test_generate_with_cycles_warning(self):
        from veritx_dse.verification.uvm_gen import generate_uvm
        from veritx_dse.model.compile_model import (
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
        seq = result["sequences"]
        assert "vc" in seq.lower() or "virtual_channel" in seq.lower()

def _generate(**request_overrides):
    """Collateral for one 2x2 mesh, through the legacy v2 entry point.

    ``generate_uvm_for_bundle`` calls the same emitters, so the pins below
    cover both entry points.
    """
    from veritx_dse.verification.uvm_gen import generate_uvm
    from veritx_dse.model.compile_model import (
        CompileRequest, Workload, ModelFamily, Agent, AgentKind,
        NocConfig, DependencyGraph, TopologyFamily,
    )
    fields = dict(
        workload=Workload(model_family=ModelFamily.CUSTOM),
        requirements=(),
        agents=(Agent(AgentKind.COMPUTE_TILE, 4, 256, 64, "AXI"),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    )
    fields.update(request_overrides)
    return generate_uvm(CompileRequest(**fields), n_nodes=4, k=2)


def _rtl_flit_field_width(field: str) -> int:
    """Width of one ``noc_pkg::flit_t`` field, read from the repository RTL."""
    pkg = Path(__file__).resolve().parents[2] / "rtl/t3/noc_pkg.sv"
    text = pkg.read_text()
    match = re.search(rf"logic\s*\[(\d+):0\]\s+{field};", text)
    assert match, f"noc_pkg::flit_t no longer declares {field}"
    return int(match.group(1)) + 1


def _emitted_field_width(source: str, field: str) -> int:
    match = re.search(rf"rand\s+bit\s*(?:\[(\d+):0\])?\s+{field};", source)
    assert match, f"the emitted transaction declares no {field}"
    return int(match.group(1)) + 1 if match.group(1) else 1


class TestEmittedTransaction:
    """The sequences and the coverage name a transaction that exists.

    Every emitted sequence extends ``uvm_sequence #(noc_tx)`` and every
    coverpoint samples ``noc_tx``, but no generated file declared it: the
    collateral could not even parse ("Package/class 'noc_tx' not found").
    """

    def test_sequences_and_coverage_declare_the_transaction_they_use(self):
        result = _generate()
        for name in ("sequences", "coverage"):
            source = result[name]
            assert "class noc_tx extends uvm_sequence_item;" in source, name
            assert "`uvm_object_utils(noc_tx)" in source, name
            # Emitted in both sources behind a guard, so either file may be
            # compiled first without a duplicate declaration.
            assert "`ifndef NOC_TX_SV" in source, name
            assert "`define NOC_TX_SV" in source, name
            # uvm_sequence/uvm_sequence_item/uvm_component are unresolved
            # without the package import; the include alone is not enough.
            assert "import uvm_pkg::*;" in source, name

    def test_the_transaction_carries_every_field_the_sequences_constrain(self):
        source = _generate()["sequences"]
        for field in ("src", "dst", "vc", "head", "tail", "pid"):
            _emitted_field_width(source, field)
        assert re.search(r"int\s+unsigned\s+latency;", source)
        # The sequences constrain exactly these field names.
        assert "tx.src == src_node;" in source
        assert "tx.dst == dst_node;" in source
        coverage = _generate()["coverage"]
        for field in ("src", "dst", "vc", "latency"):
            assert f"coverpoint tx.{field}" in coverage, field

    def test_the_transaction_mirrors_the_native_pin_map(self):
        """Field widths are the RTL flit's widths, not a second invention."""
        source = _generate()["sequences"]
        for field in ("src", "dst", "vc", "pid"):
            assert (_emitted_field_width(source, field)
                    == _rtl_flit_field_width(field)), field
        for field in ("head", "tail"):
            assert _emitted_field_width(source, field) == 1, field

    def test_the_transaction_is_aliased_to_the_native_package_type(self):
        source = _generate()["coverage"]
        assert "typedef noc_pkg::flit_t noc_tx_flit_t;" in source
        assert "typedef noc_tx noc_tx_t;" in source


class TestEmittedAssertions:
    """Legal SVA that does not pretend to check what it does not check."""

    def test_no_property_declares_variables_inside_its_body(self):
        """``int inject_count;`` inside a property is not legal SVA.

        Verilator: "Unsupported: property variable declaration", followed by
        a syntax error that takes the rest of the file with it.
        """
        source = _generate()["assertions"]
        blocks = re.findall(r"property\s+(\w+);(.*?)endproperty", source,
                            re.S)
        assert blocks, "the assertion file declares no properties"
        declaration = re.compile(
            r"\b(?:int|integer|logic|bit|byte|shortint|longint|real)\b\s*"
            r"(?:\[[^\]]*\]\s*)?\w+\s*[;=]")
        for name, body in blocks:
            code = "\n".join(line.split("//")[0]
                             for line in body.splitlines())
            assert not declaration.search(code), (
                f"{name} declares a variable inside the property body")

    def test_only_conservation_is_an_assertion(self):
        """No always-true ``1'b1`` body is bound to an ``assert property``.

        A live placeholder assertion passes every run, so a green regression
        would read as proof of a property nobody wrote.
        """
        source = _generate()["assertions"]
        asserted = re.findall(r"assert\s+property\s*\(\s*(\w+)\s*\)",
                              source)
        assert asserted == ["p_conservation"], asserted
        for label, topic in (("F1", "deadlock"), ("F2", "liveness"),
                             ("F4", "ordering"), ("F5", "flow_control"),
                             ("F6", "routing"), ("F7", "qos_isolation"),
                             ("F8", "timeout")):
            marker = f"p_{label.lower()}_{topic}_unimplemented_placeholder;"
            assert marker in source, marker
            assert f"{label}:" in source, label
        assert source.count("UNIMPLEMENTED") >= 8

    def test_the_assertion_file_needs_no_uvm_library(self):
        source = _generate()["assertions"]
        assert "uvm_macros.svh" not in source
        assert "uvm_pkg" not in source
        assert "module noc_assertions" in source


class TestUVMCLI:
    """PRD §9.3: UVM generation via CLI."""

    def test_generate_command_exists(self):
        from veritx_dse.cli.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["generate", "uvm", "--request", "test.json",
                                   "--out", "/tmp/uvm_test"])
        assert args.gen_cmd == "uvm"
