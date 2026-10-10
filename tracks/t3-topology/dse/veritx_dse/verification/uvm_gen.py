"""veritx_dse.uvm_gen — PRD §9.3: UVM testbench generator.

Rationale: docs/decisions/modules/verification.md
"""
from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import SemanticError
from ..model.compile_model import (
    CompileRequest, DependencyGraph, derive_vc_assignment,
    AgentKind, TopologyFamily,
)

class UvmGenerationError(ValueError, SemanticError):
    """Canonical UVM generation refuses rather than guesses a fabric."""


UVM_GENERATOR_VERSION = "1.1.0"
UVM_OUTPUT_SCHEMA_VERSION = 1

# The generated testbench instantiates `noc_mesh`, not a torus or a
# concentrated-mesh DUT. Refuse other families rather than emitting
# collateral that describes a different fabric.
_MESH_GRID_FAMILIES = frozenset({"mesh"})


class _BundleTemplateVa:
    """The bundle's authoritative VC assignment on the legacy generator contract.

    The legacy templates render `va.vc_count + 1` (their v2 derive returned
    the count WITHOUT the reserved slot the templates add back) and cover
    bins `[0:va.vc_count]`. The bundle's `vc_count` is the TOTAL canonical
    count — escape VCs are members of it (vc_ids == 0..count-1) — so this
    projection reports `total - 1`, making every template expression render
    the exact authoritative numbers with no +1 drift.
    """

    __slots__ = ("_va", "routing_function")

    def __init__(self, vc_assignment: Any, routing_function: str) -> None:
        self._va = vc_assignment
        self.routing_function = routing_function

    @property
    def vc_count(self) -> int:
        return self._va.vc_count - 1


def _derive_k(design: Any, topology: Any) -> tuple[int, str]:
    """K (grid side length) from declared or compiled evidence only.

    Returns (k, source) where source names the artifact K came from.
    Order of evidence: the declared grid intent (v4 side_length), then a
    declared v2 radix, then a perfect-square router count (the derivation
    the CLI already labels `compiled-topology`). A family that is not a
    square grid, or a grid whose declared side contradicts the compiled
    router count, is a typed refusal — never a guess.
    """
    family = topology.family.value
    n_routers = topology.router_count
    if family not in _MESH_GRID_FAMILIES:
        raise UvmGenerationError(
            f"topology family {family!r} is not supported: generated "
            f"collateral instantiates noc_mesh and cannot describe this DUT")
    intent = getattr(design, "topology", None)
    concentration = getattr(intent, "concentration", None)
    if concentration is None:
        concentration = getattr(
            getattr(design, "noc_config", None), "concentration", None)
    if concentration is None:
        concentration = 1
    if concentration != 1:
        raise UvmGenerationError(
            f"mesh concentration={concentration} is not supported: "
            f"generated noc_mesh collateral only describes concentration 1")
    side = getattr(intent, "side_length", None)
    if isinstance(side, int) and side > 0:
        if side * side != n_routers:
            raise UvmGenerationError(
                f"declared grid side_length={side} implies {side * side} "
                f"routers but the compiled topology has {n_routers}; "
                f"refusing to describe a fabric the compiler did not "
                f"produce")
        return side, "topology_intent.side_length"
    radix = getattr(getattr(design, "noc_config", None), "radix", None)
    if isinstance(radix, int) and radix > 0:
        if radix * radix != n_routers:
            raise UvmGenerationError(
                f"declared noc_config.radix={radix} implies {radix * radix} "
                f"routers but the compiled topology has {n_routers}; "
                f"refusing to describe a fabric the compiler did not "
                f"produce")
        return radix, "noc_config.radix"
    root = math.isqrt(n_routers)
    if root > 0 and root * root == n_routers:
        return root, "topology.router_count_isqrt"
    raise UvmGenerationError(
        f"cannot derive K for family {family!r}: no declared grid side "
        f"length and {n_routers} routers do not form a square grid. "
        f"Refusing rather than guessing a topology parameter.")


def generate_uvm_for_bundle(
    bundle: Any,
    *,
    revision_id: str | None = None,
    design_hash: str | None = None,
) -> dict[str, Any]:
    """Generate UVM collateral from a compiled ResolvedFabricBundle.

    The canonical entry point (PRODUCT-CONVERGENCE-V1 item G): every
    fabric parameter is DERIVED from compiled artifacts — n_nodes from
    the materialized topology, K from the declared grid, the VC count
    and routing class from the VC-assignment and route artifacts — so
    there is no size argument left to guess. The output is stamped with
    the identity (revision, design hash, schema, generator) of the
    fabric it describes.

    Args:
        bundle: The ResolvedFabricBundle the fabric was certified with.
        revision_id: The frozen revision identity to stamp; None for a
            direct library call (stamped as ``-``).
        design_hash: The frozen design hash to stamp; defaults to the
            bundle design's own hash.

    Returns:
        Dict with five SystemVerilog sources (including the native DUT
        binding), ``files``, an
        ``identity`` block, and the ``fabric`` derivation record.

    Raises:
        UvmGenerationError: the bundle cannot be described honestly
            (missing artifacts, non-grid family, contradictory grid).
    """
    design = getattr(bundle, "design", None)
    topology = getattr(bundle, "topology", None)
    vc_assignment = getattr(bundle, "vc_assignment", None)
    router_route = getattr(bundle, "router_route", None)
    missing = [name for name, part in (
        ("design", design), ("topology", topology),
        ("vc_assignment", vc_assignment), ("router_route", router_route),
    ) if part is None]
    if missing:
        raise UvmGenerationError(
            f"bundle is missing {', '.join(missing)} — there is no "
            f"compiled fabric to describe")

    routing_classes = tuple(router_route.routing_classes)
    if not routing_classes:
        raise UvmGenerationError(
            "route artifact declares no routing classes — refusing to "
            "invent a routing function")

    n_nodes = topology.router_count
    k, k_source = _derive_k(design, topology)
    if k < 2 or n_nodes > 256 or not 1 <= vc_assignment.vc_count <= 4:
        raise UvmGenerationError(
            "native mesh binding supports K >= 2, at most 256 nodes, "
            "and 1..4 VCs (noc_pkg endpoint/VC widths)")
    if any(rc.id != "DOR_XY" for rc in routing_classes):
        raise UvmGenerationError(
            "native mesh binding supports DOR_XY routing only")
    routing = ",".join(rc.id for rc in routing_classes)
    va = _BundleTemplateVa(vc_assignment, routing)
    topo = topology.family          # MaterializedFamily carries .value
    agents_summary = ", ".join(
        f"{a.kind.value}×{a.count}" for a in design.agents)
    has_cycles = design.dependencies.has_cycles()

    tb_top = _gen_tb_top(design, n_nodes, k, topo, va, agents_summary)
    sequences = _gen_sequences(design, n_nodes, k, va, has_cycles)
    assertions = _gen_assertions(design, n_nodes, k, topo, va)
    coverage = _gen_coverage(design, n_nodes, k, va)

    schema = getattr(design, "schema_version", 2)
    frozen_hash = design_hash if design_hash is not None \
        else design.design_hash()
    stamp = (
        f"// veritx-uvm generator={UVM_GENERATOR_VERSION} "
        f"output_schema={UVM_OUTPUT_SCHEMA_VERSION}\n"
        f"// design_schema={schema} design_hash={frozen_hash}\n"
        f"// revision={revision_id if revision_id is not None else '-'}\n"
    )

    files = ["noc_dut_binding.sv", "tb_noc.sv", "seq_lib.sv",
             "assertions.sv", "cov.sv"]
    return {
        "files": files,
        "dut_binding": stamp + _gen_dut_binding(),
        "tb_top": stamp + tb_top,
        "sequences": stamp + sequences,
        "assertions": stamp + assertions,
        "coverage": stamp + coverage,
        "identity": {
            "generator": "veritx-uvm",
            "generator_version": UVM_GENERATOR_VERSION,
            "output_schema_version": UVM_OUTPUT_SCHEMA_VERSION,
            "design_schema_version": schema,
            "design_hash": frozen_hash,
            "revision_id": revision_id,
        },
        "fabric": {
            "n_nodes": n_nodes,
            "k": k,
            "family": topology.family.value,
            "vc_count": vc_assignment.vc_count,
            "routing_classes": [rc.id for rc in routing_classes],
            # The repository DUT has a fixed 64-bit flit payload. Binding
            # validation is not equivalence to the compiled packet format.
            "dut_binding_scope": "NATIVE_RTL_LINK_INTERFACE_ONLY",
            "dut_payload_bits": 64,
            "derived_from": [
                "topology.router_count",
                k_source,
                "vc_assignment.vc_count",
                "router_route.routing_classes",
            ],
        },
    }

def generate_uvm(
    cr: CompileRequest,
    n_nodes: int = 64,
    k: int = 8,
) -> dict[str, Any]:
    """Generate UVM verification collateral for a CompileRequest.

    Args:
        cr: The CompileRequest describing the system.
        n_nodes: Total number of network nodes.
        k: Mesh/torus dimension (sqrt of n_nodes for 2D).

    Returns:
        Dict with keys: dut_binding, tb_top, sequences, assertions, coverage, files.
        Each value is a SystemVerilog source string.
    """
    files: list[str] = ["noc_dut_binding.sv"]
    agents_summary = ", ".join(f"{a.kind.value}×{a.count}" for a in cr.agents)
    va = derive_vc_assignment(cr)
    topo = cr.noc_config.topology_family or TopologyFamily.MESH
    has_cycles = cr.dependencies.has_cycles()

    tb_top = _gen_tb_top(cr, n_nodes, k, topo, va, agents_summary)
    files.append("tb_noc.sv")

    sequences = _gen_sequences(cr, n_nodes, k, va, has_cycles)
    files.append("seq_lib.sv")

    assertions = _gen_assertions(cr, n_nodes, k, topo, va)
    files.append("assertions.sv")

    coverage = _gen_coverage(cr, n_nodes, k, va)
    files.append("cov.sv")

    return {
        "files": files,
        "dut_binding": _gen_dut_binding(),
        "tb_top": tb_top,
        "sequences": sequences,
        "assertions": assertions,
        "coverage": coverage,
    }

def _gen_dut_binding() -> str:
    """Native flat endpoint pins mapped to the repository mesh's 2D pins.

    No UVM symbols: lint/simulation can check the real binding without
    substituting a fake UVM library. The driver must respect injection
    credits; ejection credits are returned by the testbench consumer.
    """
    return """// Native binding for tracks/t3-topology/rtl/t3/mesh.sv
// Link-interface smoke only; not packet-format or UVM qualification.
`timescale 1ns/1ps

interface noc_if(input logic clk, input logic rst_n);
  import noc_pkg::*;
  link_f_t inject;
  link_c_t inject_credit;
  link_c_t inject_credit_early;
  link_f_t eject;
  link_c_t eject_credit;
endinterface

module noc_dut_binding #(
  parameter int K = 2,
  parameter int NUM_VCS = 2
)(
  input logic clk,
  input logic rst_n,
  input noc_pkg::link_f_t inject [K*K],
  output noc_pkg::link_c_t inject_credit [K*K],
  output noc_pkg::link_c_t inject_credit_early [K*K],
  output noc_pkg::link_f_t eject [K*K],
  input noc_pkg::link_c_t eject_credit [K*K]
);
  import noc_pkg::*;
  link_f_t mesh_inject [K][K];
  link_c_t mesh_inject_credit [K][K];
  link_c_t mesh_inject_credit_early [K][K];
  link_f_t mesh_eject [K][K];
  link_c_t mesh_eject_credit [K][K];

  initial begin
    if (K < 2 || K*K > 256 || NUM_VCS < 1 || NUM_VCS > MAX_VC)
      $fatal(1, "native mesh binding dimensions or VC count unsupported");
  end

  for (genvar node = 0; node < K*K; node++) begin : gen_endpoint
    assign mesh_inject[node / K][node % K] = inject[node];
    assign inject_credit[node] = mesh_inject_credit[node / K][node % K];
    assign inject_credit_early[node] =
      mesh_inject_credit_early[node / K][node % K];
    assign eject[node] = mesh_eject[node / K][node % K];
    assign mesh_eject_credit[node / K][node % K] = eject_credit[node];
  end

  noc_mesh #(.VCS(NUM_VCS), .X_DIM(K), .Y_DIM(K)) dut (
    .clk(clk), .rst_n(rst_n), .inject(mesh_inject),
    .inject_credit(mesh_inject_credit),
    .inject_credit_early(mesh_inject_credit_early),
    .eject(mesh_eject), .eject_credit(mesh_eject_credit),
    .router_pop(), .router_recv(), .router_dbg()
  );
endmodule
"""


def _gen_tb_top(
    cr: CompileRequest,
    n_nodes: int,
    k: int,
    topo: TopologyFamily,
    va: Any,
    agents_summary: str,
) -> str:
    """Generate top-level UVM testbench module."""
    n_nics = sum(a.count for a in cr.agents if a.kind == AgentKind.COMPUTE_TILE)
    data_width = cr.physical.default_data_width

    return f"""// UVM Testbench for NoC Fabric
// Generated by VeritX v0.3.0 — PRD §9.3
// CompileRequest: {cr.workload.model_name or cr.workload.model_family.value}
// Agents: {agents_summary}
// Topology: {topo.value} k={k}, routing={va.routing_function}, VCs={va.vc_count}

`timescale 1ns/1ps

module tb_noc;

  // Imports
  import uvm_pkg::*;
  import noc_pkg::*;
  `include "uvm_macros.svh"

  // Parameters
  localparam int NUM_NODES = {n_nodes};
  localparam int K = {k};
  localparam int DATA_WIDTH = {data_width};
  localparam int NUM_VCS = {va.vc_count + 1};
  localparam string ROUTING = "{va.routing_function}";

  // Clock and reset
  logic clk;
  logic rst_n;

  initial begin
    clk = 0;
    forever #0.5 clk = ~clk;
  end

  initial begin
    rst_n = 0;
    repeat (10) @(posedge clk);
    rst_n = 1;
  end

  // Native RTL payload is noc_pkg::FLIT_BITS (64), not DATA_WIDTH.
  // No conversion/equivalence to the compiled packet format is claimed.
  link_f_t inject [NUM_NODES];
  link_c_t inject_credit [NUM_NODES];
  link_c_t inject_credit_early [NUM_NODES];
  link_f_t eject [NUM_NODES];
  link_c_t eject_credit [NUM_NODES];
  noc_if agent_if [NUM_NODES] (.clk(clk), .rst_n(rst_n));

  noc_dut_binding #(.K(K), .NUM_VCS(NUM_VCS)) binding (
    .clk(clk), .rst_n(rst_n), .inject(inject),
    .inject_credit(inject_credit),
    .inject_credit_early(inject_credit_early),
    .eject(eject), .eject_credit(eject_credit)
  );

  for (genvar node = 0; node < NUM_NODES; node++) begin : gen_agent
    assign inject[node] = agent_if[node].inject;
    assign agent_if[node].inject_credit = inject_credit[node];
    assign agent_if[node].inject_credit_early = inject_credit_early[node];
    assign agent_if[node].eject = eject[node];
    assign eject_credit[node] = agent_if[node].eject_credit;
    // Register each scalar interface, not an array as a virtual interface.
    initial uvm_config_db#(virtual noc_if)::set(
      null, $sformatf("*.agent[%0d]*", node), "vif", agent_if[node]);
  end

  initial begin
    if (NUM_NODES != K*K)
      $fatal(1, "NUM_NODES must match the native square mesh");
  end

  // UVM configuration
  initial begin
    uvm_config_db#(int)::set(null, "*", "NUM_NODES", NUM_NODES);
    uvm_config_db#(int)::set(null, "*", "NUM_VCS", NUM_VCS);
    uvm_config_db#(string)::set(null, "*", "ROUTING", ROUTING);
    run_test();
  end

  // Timeout
  initial begin
    #100000;
    `uvm_fatal("TIMEOUT", "Simulation timed out")
  end

endmodule
"""

def _gen_noc_tx() -> str:
    """The canonical transaction every emitted sequence and coverpoint names.

    The sequence and coverage sources both reference ``noc_tx``, which no
    generated file ever declared (the sequences could not even parse). It is
    emitted once per source behind an include guard so each generated file is
    self-sufficient no matter what order the collateral is compiled in.

    Field widths mirror the proven native pin map: ``noc_pkg::flit_t``
    (``src``/``dst`` are 8 bits, ``vc`` is 3 bits, ``pid`` is 16 bits,
    ``head``/``tail`` are single bits). ``latency`` is a testbench
    measurement, not a flit field.
    """
    return """`ifndef NOC_TX_SV
`define NOC_TX_SV

// noc_tx — the transaction this collateral drives and samples.
class noc_tx extends uvm_sequence_item;
  rand bit [7:0]  src;
  rand bit [7:0]  dst;
  rand bit [2:0]  vc;
  rand bit        head;
  rand bit        tail;
  rand bit [15:0] pid;
  int unsigned    latency;

  `uvm_object_utils(noc_tx)

  function new(string name = "noc_tx");
    super.new(name);
  endfunction
endclass

// noc_pkg typedef alias: the DUT link spells the same payload
// noc_pkg::flit_t. noc_pkg.sv defines NOC_PKG_SV, so the alias appears
// whenever the native RTL package is compiled with this collateral.
`ifdef NOC_PKG_SV
typedef noc_pkg::flit_t noc_tx_flit_t;
`endif
// Alias spelling for collateral that names the transaction type.
typedef noc_tx noc_tx_t;

`endif
"""


def _gen_sequences(
    cr: CompileRequest,
    n_nodes: int,
    k: int,
    va: Any,
    has_cycles: bool,
) -> str:
    """Generate UVM sequence library."""
    vc_section = ""
    if has_cycles:
        vc_section = f"""
// VC Separation Sequence — PRD §11.3
// Tests that blocking dependencies are properly separated across VCs
class vc_separation_seq extends uvm_sequence #(noc_tx);
  `uvm_object_utils(vc_separation_seq)

  int src_node;
  int dst_node;
  int target_vc;

  function new(string name = "vc_separation_seq");
    super.new(name);
  endfunction

  task body();
    noc_tx tx;
    tx = noc_tx::type_id::create("tx");
    start_item(tx);
    assert(tx.randomize() with {{
      tx.src == src_node;
      tx.dst == dst_node;
      tx.vc == target_vc;
    }});
    finish_item(tx);
  endtask
endclass
"""

    return f"""// UVM Sequence Library — PRD §9.3
// Generated by VeritX v0.3.0
// Topology: {n_nodes} nodes, k={k}, {va.vc_count + 1} VCs

`include "uvm_macros.svh"
import uvm_pkg::*;

{_gen_noc_tx()}
// Injected Sequence — directed single-packet test
class injected_seq extends uvm_sequence #(noc_tx);
  `uvm_object_utils(injected_seq)

  int src_node;
  int dst_node;

  function new(string name = "injected_seq");
    super.new(name);
  endfunction

  task body();
    noc_tx tx;
    tx = noc_tx::type_id::create("tx");
    start_item(tx);
    assert(tx.randomize() with {{
      tx.src == src_node;
      tx.dst == dst_node;
    }});
    finish_item(tx);
  endtask
endclass

// Random Sequence — uniform random traffic
class random_seq extends uvm_sequence #(noc_tx);
  `uvm_object_utils(random_seq)

  int num_packets;

  function new(string name = "random_seq");
    super.new(name);
  endfunction

  task body();
    noc_tx tx;
    repeat (num_packets) begin
      tx = noc_tx::type_id::create("tx");
      start_item(tx);
      assert(tx.randomize());
      finish_item(tx);
    end
  endtask
endclass

// All-to-All Sequence — every node sends to every other node
class alltoall_seq extends uvm_sequence #(noc_tx);
  `uvm_object_utils(alltoall_seq)

  function new(string name = "alltoall_seq");
    super.new(name);
  endfunction

  task body();
    noc_tx tx;
    for (int src = 0; src < {n_nodes}; src++) begin
      for (int dst = 0; dst < {n_nodes}; dst++) begin
        if (src != dst) begin
          tx = noc_tx::type_id::create("tx");
          start_item(tx);
          assert(tx.randomize() with {{
            tx.src == src;
            tx.dst == dst;
          }});
          finish_item(tx);
        end
      end
    end
  endtask
endclass

// Hotspot Sequence — one node receives from all others (MoE pattern)
class hotspot_seq extends uvm_sequence #(noc_tx);
  `uvm_object_utils(hotspot_seq)

  int hotspot_node;
  int num_senders;

  function new(string name = "hotspot_seq");
    super.new(name);
  endfunction

  task body();
    noc_tx tx;
    repeat (num_senders) begin
      tx = noc_tx::type_id::create("tx");
      start_item(tx);
      assert(tx.randomize() with {{
        tx.dst == hotspot_node;
        tx.src != hotspot_node;
      }});
      finish_item(tx);
    end
  endtask
endclass
{vc_section}
"""

def _gen_assertions(
    cr: CompileRequest,
    n_nodes: int,
    k: int,
    topo: TopologyFamily,
    va: Any,
) -> str:
    """Generate SVA assertions for F1-F8 formal properties.

    Only F3 (packet conservation) has a legal, non-trivial SVA form over the
    signals this module observes, so it is the only property actually
    asserted. F1, F2, F4, F5, F6, F7 and F8 are emitted as NAMED
    PLACEHOLDERS with no ``assert property`` statement: a ``1'b1`` body is
    not a check, and a live always-true assertion would let a green
    regression be read as proof of a property nobody wrote. Their PRD labels
    stay in the source, so the gap is visible instead of hidden behind a
    passing assertion.

    F2 and F8 used to declare local variables (``int inject_count``) inside a
    property, which is not legal SVA — Verilator rejects the file with
    "Unsupported: property variable declaration" and then fails to parse the
    rest of the file. The placeholders keep the file syntactically legal.
    """
    return f"""// SVA Assertions — F1-F8 Formal Properties
// Generated by VeritX v0.3.0 — PRD §9.7
// Topology: {topo.value} k={k}, routing={va.routing_function}
// VCs: {va.vc_count + 1}
//
// ASSERTED:      F3 (packet conservation).
// UNIMPLEMENTED: F1, F2, F4, F5, F6, F7, F8 — emitted below as named
// placeholder properties with NO `assert property` statement. They are not
// checks and must not be read as coverage of those properties. No UVM
// library is needed to parse this file.

module noc_assertions #(
  parameter NUM_NODES = {n_nodes},
  parameter NUM_VCS = {va.vc_count + 1}
)(
  input logic clk,
  input logic rst_n,
  // Flit interface signals (active-high valid)
  input logic [NUM_NODES-1:0] inj_valid,
  input logic [NUM_NODES-1:0] comp_valid
);

  // ── F1: Deadlock Freedom — UNIMPLEMENTED ────────────────────────────────
  // "No cyclic channel dependency" (PRD §11.3: each cycle needs >=1 member
  // on a distinct VC). This module observes only inj_valid/comp_valid, not
  // the channel dependency graph, so nothing is asserted. The previous
  // `1'b1 |-> 1'b1` was always true and asserted nothing.
  property p_f1_deadlock_unimplemented_placeholder;
    @(posedge clk) disable iff (!rst_n) 1'b1;
  endproperty

  // ── F2: Liveness — UNIMPLEMENTED ────────────────────────────────────────
  // "Every injected packet is eventually completed" needs per-packet state
  // tracked across time. The previous form declared local variables inside
  // the property (illegal SVA), so it is replaced by a placeholder.
  property p_f2_liveness_unimplemented_placeholder;
    @(posedge clk) disable iff (!rst_n) 1'b1;
  endproperty

  // ── F3: Packet Conservation ─────────────────────────────────────────────
  // Number of injected flits equals completed flits (no loss, no duplication)
  int total_injected, total_completed;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      total_injected <= 0;
      total_completed <= 0;
    end else begin
      for (int i = 0; i < NUM_NODES; i++) begin
        if (inj_valid[i]) total_injected <= total_injected + 1;
        if (comp_valid[i]) total_completed <= total_completed + 1;
      end
    end
  end

  property p_conservation;
    @(posedge clk) disable iff (!rst_n)
    total_injected == total_completed;
  endproperty

  a_conservation: assert property (p_conservation)
    else $error("F3 FAIL: Packet conservation violated (injected=%0d, completed=%0d)",
                total_injected, total_completed);

  // ── F4: Ordering — UNIMPLEMENTED ────────────────────────────────────────
  // Per-VC in-order delivery. No per-VC ordering signal is observed here;
  // the previous body was the constant 1'b1.
  property p_f4_ordering_unimplemented_placeholder;
    @(posedge clk) disable iff (!rst_n) 1'b1;
  endproperty

  // ── F5: Flow Control — UNIMPLEMENTED ────────────────────────────────────
  // Credit-based flow control (no buffer overflow). The credit pins live on
  // the native binding, not on this module; the previous body was 1'b1.
  property p_f5_flow_control_unimplemented_placeholder;
    @(posedge clk) disable iff (!rst_n) 1'b1;
  endproperty

  // ── F6: Routing Correctness — UNIMPLEMENTED ─────────────────────────────
  // Minimal/adaptive paths produce valid output ports. Routing is checked by
  // the route artifact and the DOR_XY certificate, not by this module; the
  // previous body was 1'b1.
  property p_f6_routing_unimplemented_placeholder;
    @(posedge clk) disable iff (!rst_n) 1'b1;
  endproperty

  // ── F7: QoS Isolation — UNIMPLEMENTED ───────────────────────────────────
  // Traffic classes must not starve each other (PRD §7.2). No VC progress
  // counter is observed here; the previous body was 1'b1.
  property p_f7_qos_isolation_unimplemented_placeholder;
    @(posedge clk) disable iff (!rst_n) 1'b1;
  endproperty

  // ── F8: Timeout — UNIMPLEMENTED ─────────────────────────────────────────
  // Bounded latency (every packet completes within MAX_LATENCY cycles)
  // needs a constant delay range and per-packet timestamps. The previous
  // form used property-local `int` variables and a variable range bound,
  // which is illegal SVA.
  property p_f8_timeout_unimplemented_placeholder;
    @(posedge clk) disable iff (!rst_n) 1'b1;
  endproperty

endmodule
"""

def _gen_coverage(
    cr: CompileRequest,
    n_nodes: int,
    k: int,
    va: Any,
) -> str:
    """Generate coverage model."""
    last_node = n_nodes - 1
    last_vc = va.vc_count
    return f"""// Coverage Model — PRD §9.3
// Generated by VeritX v0.3.0
// Cross-coverage: traffic class × latency bucket × topology

`include "uvm_macros.svh"
import uvm_pkg::*;

{_gen_noc_tx()}
class noc_coverage extends uvm_component;
  `uvm_component_utils(noc_coverage)

  // Transaction handle
  noc_tx tx;

  // Covergroup
  covergroup noc_cg;

    // Source node
    cp_src: coverpoint tx.src {{
      bins node[] = {{[0:{last_node}]}};
    }}

    // Destination node
    cp_dst: coverpoint tx.dst {{
      bins node[] = {{[0:{last_node}]}};
    }}

    // Latency bucket
    cp_latency: coverpoint tx.latency {{
      bins low      = {{[0:100]}};
      bins medium   = {{[101:1000]}};
      bins high     = {{[1001:10000]}};
      bins saturate = {{[10001:$]}};
    }}

    // VC used
    cp_vc: coverpoint tx.vc {{
      bins vc[] = {{[0:{last_vc}]}};
    }}

    // Cross: src x dst (routing coverage)
    cx_src_dst: cross cp_src, cp_dst;

    // Cross: latency x VC (VC separation coverage)
    cx_latency_vc: cross cp_latency, cp_vc;

  endgroup

  function new(string name = "noc_coverage", uvm_component parent = null);
    super.new(name, parent);
    noc_cg = new();
  endfunction

  function void write(noc_tx t);
    tx = t;
    noc_cg.sample();
  endfunction

endclass
"""
