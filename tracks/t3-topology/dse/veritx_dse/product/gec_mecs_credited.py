"""Per-tap credit wiring and the pipelined wire model.

This module closes the fabric-side flow-control gap on the shared, multidrop
GEC-MECS fabric, and in the process makes the shared wire a *modeled* wire
instead of a zero-latency net.

What the transformation adds, on top of the shipped fabric template:

* a **VC field** in the shared flit (adjacent to the payload-side framing
  bits), pinned at injection allocation;
* an **injection-side VC allocation policy, first-hop-credit-aware**: the
  producer's VC field is not trusted. Each packet takes ONE VC at its HEAD
  (or SINGLE); the same VC is stamped on every BODY/TAIL flit until the
  TAIL retires it. BODY/TAIL accepted with no packet open are counted in
  `inject_error_q` and never burn a rotation slot. The HEAD/SINGLE pick is
  the round-robin-earliest VC whose *first-hop* (tap, VC) pool still holds
  a credit; a packet whose first-hop pools are all exhausted is not
  admitted at all -- the endpoint holds `valid`, the fabric withholds
  `ready`, no rotation slot is burned -- instead of injecting a packet that
  cannot move. Local (no-wire) packets skip the pool consultation; a
  HEAD/SINGLE addressed outside the router range is consumed at the port
  and counted in `inject_error_q` instead of wedging a router port;
* a **credit pool per (wire)** -- `tap_credit_pool` is per (tap, VC), so one
  instance per wire is the (port, tap, VC) domain the contract names;
  same-cycle return/grant updates preserve both accounting events;
* a **credited grant path**: a flit leaves the router for a wire only when
  its exact (tap, VC) has a credit, and the credit is consumed at the same
  edge the flit enters the wire pipe;
* a **pipelined wire model**: each (src, axis) wire is a `WIRE_PIPE`-deep
  elastic pipe instead of a combinational path. Stage 0 fills when the
  source router grants the wire; each stage registers (valid, flit) when
  the next stage accepts; the last stage exits into the addressed tap's
  input port when that router can accept the flit. The source router sees
  `row_ready`/`col_ready` from stage 0's acceptance space, so backpressure
  propagates with bounded pipeline latency instead of zero;
* a **release at destination dequeue**: the credit returns when the far end
  dequeues the flit (the pending-return queue plus the pool pipeline quantize
  the return), which is necessarily later than wire-exit -- conservative,
  never optimistic;
* a **per-VC packet lock**: the lock on each output (local/row/col) is
   indexed by the packet's VC, so two packets on different VCs may hold one
   output concurrently. A packet still cannot overtake another on one wire;
   what the lock no longer does is refuse a second, different-VC packet for
   the output;

The fabric template is transformed, not re-implemented: the routing logic
stays single-sourced, and every replacement is anchored -- if an anchor is
missing the transformation refuses instead of emitting a half-wired fabric.

Scope and honest limits:
  * the credit accounts for flits IN FLIGHT on a wire and held in the far
    buffer, claimed when the flit enters stage 0 and released at destination
    dequeue -- necessarily conservative for the wire segment itself;
  * VC allocation is round-robin per source router, gated by first-hop
    pool state (above). It is fair per VC and it refuses to admit a packet
    with no first-hop credit, but it is NOT iSLIP (no two-phase grant /
    grant-accept matching against VCs), it does not consult pools beyond
    the first hop, and formal starvation-freedom under adversarial traffic
    is not established -- only bounded outstanding state and eventual drain
    under the regression's traffic;
  * the destination's input buffer is single-entry; when it is full the
    pipe stalls head-of-line, which is the real backpressure this model
    intends; a deeper destination buffer is a separate design decision.
    Packet locks on every output are per (output, VC): two packets on
    different VCs may hold one output concurrently, which is why the old
    one-packet-per-wire restriction is gone. What is NOT established is a
    full wormhole network: the wire pipe is FIFO, a flit still cannot pass
    another on one wire, and the endpoint-side reassembly of interleaved
    packets is a consumer contract, not a modeled block;
  * multicast, AXI/CDC composition and physical signoff are not established
    here.
"""
from __future__ import annotations

from pathlib import Path

from veritx_dse.core.paths import REPO

POOL_SOURCE = REPO / "tracks" / "t3-topology" / "rtl" / "tap_credit" / "tap_credit_pool.sv"

ROUTER_PARAMS_ANCHOR = "  parameter int PORTS = 7\n"
ROUTER_PORTS_ANCHOR = """  output logic [1:0]             col_vc
);
"""
ROUTER_LOCALS_ANCHOR = """  localparam int DEST_LSB = W - DEST_W;
  // Flit type (wormhole packet framing): SINGLE = a one-flit packet,
  // HEAD = first flit of a multi-flit packet, BODY = continuation,
  // TAIL = last.  TYPE sits directly below the SRC field in the raw
  // fabric and directly below the VC field in the credited fabric.
  localparam int TYPE_W = 2;
  localparam int TYPE_LSB = DEST_LSB - DEST_W - 2;
"""
ROUTER_GRANT_ANCHOR = """    if (found_row) begin
      row_valid = 1'b1;
      row_flit = flit_q[grant_row];
      row_dest = flit_q[grant_row][DEST_LSB +: DEST_W];
      dest_x = K_W'(row_dest % K);
      drop_idx = 2'((int'(dest_x) < int'(my_x)) ? int'(dest_x) : int'(dest_x) - 1);
      row_vc = 2'(drop_idx);
    end
    if (found_col) begin
      col_valid = 1'b1;
      col_flit = flit_q[grant_col];
      col_dest = flit_q[grant_col][DEST_LSB +: DEST_W];
      dest_y = K_W'(col_dest / K);
      drop_idx = 2'((int'(dest_y) < int'(my_y)) ? int'(dest_y) : int'(dest_y) - 1);
      col_vc = 2'(drop_idx);
    end
"""
ROUTER_SCAN_ANCHOR = """      scan_idx = (rr_row + offset) % PORTS;
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      dest_x = K_W'(candidate_dest % K);
      if (!found_row && valid_q[scan_idx] && int'(candidate_dest) < K*K && dest_x != my_x &&
          (!row_lock || row_lock_port == scan_idx)) begin
        found_row = 1'b1;
        grant_row = scan_idx;
      end
      scan_idx = (rr_col + offset) % PORTS;
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      dest_x = K_W'(candidate_dest % K);
      dest_y = K_W'(candidate_dest / K);
      if (!found_col && valid_q[scan_idx] && int'(candidate_dest) < K*K &&
          dest_x == my_x && dest_y != my_y &&
          (!col_lock || col_lock_port == scan_idx)) begin
        found_col = 1'b1;
        grant_col = scan_idx;
      end
"""
ROUTER_POP_ANCHOR = """  always_comb begin
    pop = '0;
    if (found_local && local_ready) pop[grant_local] = 1'b1;
    if (found_row && row_ready) pop[grant_row] = 1'b1;
    if (found_col && col_ready) pop[grant_col] = 1'b1;
  end
"""
FABRIC_DECL_ANCHOR = "  logic [N-1:0][1:0] row_vc, col_vc;\n"
FABRIC_INST_ANCHOR = """      .row_valid(row_valid[n]), .row_ready(row_ready[n]), .row_flit(row_flit[n]),
      .row_dest(row_dest[n]), .row_vc(row_vc[n]),
      .col_valid(col_valid[n]), .col_ready(col_ready[n]), .col_flit(col_flit[n]),
      .col_dest(col_dest[n]), .col_vc(col_vc[n])
"""
FABRIC_RELEASE_ANCHOR = """  assign ep_out_valid = local_valid;
"""
FABRIC_INJECT_ANCHOR = """    for (int n = 0; n < N; n++) begin
      node_in_valid[n][0] = ep_in_valid[n];
      node_in_flit[n][0] = ep_in_flit[n];
    end
"""
FABRIC_DRIVER_ANCHOR = """    for (int src = 0; src < N; src++) begin
      for (int dst = 0; dst < N; dst++) begin
        if ((src / K) == (dst / K) && src != dst && int'(row_dest[src]) % K == dst % K) begin
          node_in_valid[dst][1 + row_tap(src, dst)] = row_valid[src];
          node_in_flit[dst][1 + row_tap(src, dst)] = row_flit[src];
        end
        if ((src % K) == (dst % K) && src != dst && int'(col_dest[src]) / K == dst / K) begin
          node_in_valid[dst][1 + (K-1) + col_tap(src, dst)] = col_valid[src];
          node_in_flit[dst][1 + (K-1) + col_tap(src, dst)] = col_flit[src];
        end
      end
    end
"""
FABRIC_READY_ANCHOR = """  always_comb begin
    row_ready = '0;
    col_ready = '0;
    for (int src = 0; src < N; src++) begin
      for (int dst = 0; dst < N; dst++) begin
        if ((src / K) == (dst / K) && src != dst && int'(row_dest[src]) % K == dst % K)
          row_ready[src] = node_in_ready[dst][1 + row_tap(src, dst)];
        if ((src % K) == (dst % K) && src != dst && int'(col_dest[src]) / K == dst / K)
          col_ready[src] = node_in_ready[dst][1 + (K-1) + col_tap(src, dst)];
      end
    end
  end
"""


ROUTER_LOCK_DECL_ANCHOR = """  // While a multi-flit packet occupies an output, only the port that owns
  // it may be granted that output, so two packets cannot interleave on a
  // wire.  The lock is taken when the HEAD is granted and released when
  // the packet's TAIL is granted; a SINGLE takes and releases it in one
  // cycle.  The VC travels in the flit bits pinned at injection, so the
  // route, the output and the VC are all held HEAD -> TAIL.
  logic local_lock, row_lock, col_lock;
  int local_lock_port, row_lock_port, col_lock_port;
"""
ROUTER_LOCAL_SCAN_ANCHOR = """      scan_idx = (rr_local + offset) % PORTS;
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      if (!found_local && valid_q[scan_idx] && candidate_dest == DEST_W'(ID) &&
          (!local_lock || local_lock_port == scan_idx)) begin
"""
ROUTER_LOCK_RESET_ANCHOR = """      local_lock <= 1'b0;
      row_lock <= 1'b0;
      col_lock <= 1'b0;
"""
ROUTER_LOCAL_LOCK_SET_ANCHOR = """        if (flit_is_head(flit_q[grant_local])) begin
          local_lock <= 1'b1;
          local_lock_port <= grant_local;
        end
        if (flit_is_tail(flit_q[grant_local])) local_lock <= 1'b0;
"""
ROUTER_ROW_LOCK_SET_ANCHOR = """        if (flit_is_head(flit_q[grant_row])) begin
          row_lock <= 1'b1;
          row_lock_port <= grant_row;
        end
        if (flit_is_tail(flit_q[grant_row])) row_lock <= 1'b0;
"""
ROUTER_COL_LOCK_SET_ANCHOR = """        if (flit_is_head(flit_q[grant_col])) begin
          col_lock <= 1'b1;
          col_lock_port <= grant_col;
        end
        if (flit_is_tail(flit_q[grant_col])) col_lock <= 1'b0;
"""
FABRIC_IN_READY_ANCHOR = """    assign ep_in_ready[n] = node_in_ready[n][0];
    gec_mecs_router #("""


class CreditedFabricError(RuntimeError):
    """The template did not carry the anchor the transformation needs."""


def _require(text: str, anchor: str, what: str) -> None:
    if anchor not in text:
        raise CreditedFabricError(
            "the shared fabric template no longer carries the " + what +
            " anchor, so the credit wiring cannot be applied; the template "
            "and this transformation must be updated together")


def _pool_source() -> str:
    if not POOL_SOURCE.is_file():
        raise CreditedFabricError(
            "the proven credit pool is missing at " + str(POOL_SOURCE))
    return POOL_SOURCE.read_text()


def render_credited_fabric(*, template: str, module_name: str, k: int,
                            flit_w: int, dest_w: int, num_vcs: int,
                            taps_per_wire: int, capacity: int,
                            wire_latency: int, credit_w: int = 4,
                            wire_pipe: int = 2,
                            destination_field: tuple[int, int] | None = None,
                            vc_field: tuple[int, int] | None = None,
                            endpoint_routers: tuple[int, ...] = ()) -> str:
    """Wire credits without changing packet bits; optionally decode endpoint IDs."""
    tap_w = max(1, (taps_per_wire - 1).bit_length())
    vc_w = max(1, (num_vcs - 1).bit_length())
    dst_lsb, packet_dst_w = destination_field or (flit_w - dest_w, dest_w)
    vc_lsb, packet_vc_w = vc_field or (flit_w - 2*dest_w - vc_w, vc_w)
    if wire_pipe < 1:
        raise CreditedFabricError("the wire pipe needs at least one stage")
    if (k < 2 or taps_per_wire != k - 1 or num_vcs < 1 or
            dest_w < (k*k - 1).bit_length()):
        raise CreditedFabricError("invalid shared-wire router/tap/VC dimensions")
    if (dst_lsb < 0 or packet_dst_w < 1 or dst_lsb + packet_dst_w > flit_w or
            vc_lsb < 0 or packet_vc_w != vc_w or vc_lsb + vc_w > flit_w or
            max(dst_lsb, vc_lsb) < min(dst_lsb + packet_dst_w, vc_lsb + vc_w)):
        raise CreditedFabricError("destination/VC fields overlap or exceed the flit")
    if endpoint_routers:
        if (len(endpoint_routers) > (1 << packet_dst_w) or
                len(set(endpoint_routers)) != len(endpoint_routers) or
                any(type(r) is not int or not 0 <= r < k*k for r in endpoint_routers)):
            raise CreditedFabricError("endpoint map exceeds packet/router dimensions")
    elif (1 << packet_dst_w) < k*k:
        raise CreditedFabricError("destination field needs an endpoint-to-router map")

    text = template

    # 1. The router's parameters: the credit domain it now owns.
    _require(text, ROUTER_PARAMS_ANCHOR, "router parameter")
    text = text.replace(ROUTER_PARAMS_ANCHOR, (
        "  parameter int PORTS = 7,\n"
        "  parameter int N_TAPS = %d,\n"
        "  parameter int NUM_VCS = %d,\n"
        "  parameter int CAPACITY = %d,\n"
        "  parameter int TAP_W = %d,\n"
        "  parameter int VC_W = %d,\n"
        "  parameter int CREDIT_W = %d,\n"
        "  parameter int WIRE_PIPE = %d\n"
        % (taps_per_wire, num_vcs, capacity, tap_w, vc_w, credit_w, wire_pipe)), 1)

    # 2. The router's ports: the release inputs and the pop report.
    _require(text, ROUTER_PORTS_ANCHOR, "router port list")
    text = text.replace(ROUTER_PORTS_ANCHOR, """  output logic [1:0]             col_vc,
  output logic                   row_alias,
  output logic                   col_alias,
  output logic [15:0]            row_outstanding,
  output logic [15:0]            row_available,
  output logic [15:0]            col_outstanding,
  output logic [15:0]            col_available,
  input  logic                   pop_rel_row_valid,
  input  logic [TAP_W-1:0]       pop_rel_row_tap,
  input  logic [VC_W-1:0]        pop_rel_row_vc,
  input  logic                   pop_rel_col_valid,
  input  logic [TAP_W-1:0]       pop_rel_col_tap,
  input  logic [VC_W-1:0]        pop_rel_col_vc,
  output logic [PORTS-1:0]       pop_report,
  output logic [PORTS-1:0][VC_W-1:0] pop_vc_report,
  output logic [N_TAPS-1:0][NUM_VCS-1:0] row_pool_nz,
  output logic [N_TAPS-1:0][NUM_VCS-1:0] col_pool_nz
);
""", 1)

    # 3. The flit field the credit domain needs.
    _require(text, ROUTER_LOCALS_ANCHOR, "router locals")
    # The framing (TYPE field, flit_is_head/tail, the per-output packet
    # locks and their resets) lives in the shared fabric template itself;
    # the transformation only re-bases the field positions for its own
    # VC-aware layout (TYPE stays directly below VC).
    text = text.replace(ROUTER_LOCALS_ANCHOR, (
        f"  localparam int DEST_LSB = {dst_lsb};\n"
        f"  localparam int VC_LSB = {vc_lsb};\n"
        "  // TYPE stays directly below the VC field in the credited fabric.\n"
        "  localparam int TYPE_W = 2;\n"
        "  localparam int TYPE_LSB = VC_LSB - TYPE_W;\n"), 1)

    # 4. The scan selects only candidates whose exact (tap, VC) has credit.
    _require(text, ROUTER_GRANT_ANCHOR, "router grant")
    text = text.replace(ROUTER_GRANT_ANCHOR, """    row_req_tap = '0;
    row_req_vc = '0;
    col_req_tap = '0;
    col_req_vc = '0;
    if (found_row) begin
      row_flit = flit_q[grant_row];
      row_dest = flit_q[grant_row][DEST_LSB +: DEST_W];
      dest_x = K_W'(row_dest % K);
      drop_idx = TAP_W'((int'(dest_x) < int'(my_x)) ? int'(dest_x) : int'(dest_x) - 1);
      row_vc = 2'(drop_idx);
      row_req_tap = drop_idx;
      row_req_vc = flit_q[grant_row][VC_LSB +: VC_W];
    end
    if (found_col) begin
      col_flit = flit_q[grant_col];
      col_dest = flit_q[grant_col][DEST_LSB +: DEST_W];
      dest_y = K_W'(col_dest / K);
      drop_idx = TAP_W'((int'(dest_y) < int'(my_y)) ? int'(dest_y) : int'(dest_y) - 1);
      col_vc = 2'(drop_idx);
      col_req_tap = drop_idx;
      col_req_vc = flit_q[grant_col][VC_LSB +: VC_W];
    end
""", 1)
    # Keep ready/grant feedback outside the candidate-selection block.
    for axis in ("row", "col"):
        anchor = f"    {axis}_valid = 1'b0;\n"
        _require(text, anchor, axis + " valid default")
        text = text.replace(anchor, "", 1)
    text = text.replace(ROUTER_POP_ANCHOR,
                        "  assign row_valid = found_row;\n"
                        "  assign col_valid = found_col;\n" + ROUTER_POP_ANCHOR, 1)

    # 5. The router's request signals and the pool instances.
    _require(text, "  logic [1:0] drop_idx;\n", "router drop index")
    text = text.replace("  logic [1:0] drop_idx;\n", """  logic [TAP_W-1:0] drop_idx;
  logic [TAP_W-1:0] row_req_tap, col_req_tap;
  logic [VC_W-1:0] row_req_vc, col_req_vc;
  logic [TAP_W-1:0] cand_tap;
  logic [VC_W-1:0] cand_vc;
  logic row_req_valid, row_req_ready, row_req_grant;
  logic col_req_valid, col_req_ready, col_req_grant;
  // The router reports the request side's ready signal to the fabric,
  // which drives the request itself and does not read them back.
  wire unused_row_req_ready = row_req_ready;
  wire unused_col_req_ready = col_req_ready;
  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] row_credits, col_credits;
  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] row_out_q, col_out_q;
  logic row_alias_q, col_alias_q;
  integer t_i;
  integer v_i;
  always @* begin
    row_outstanding = '0;
    row_available = '0;
    col_outstanding = '0;
    col_available = '0;
    for (t_i = 0; t_i < N_TAPS; t_i = t_i + 1) begin
      for (v_i = 0; v_i < NUM_VCS; v_i = v_i + 1) begin
        row_outstanding = row_outstanding + row_out_q[t_i][v_i];
        row_available = row_available + row_credits[t_i][v_i];
        col_outstanding = col_outstanding + col_out_q[t_i][v_i];
        col_available = col_available + col_credits[t_i][v_i];
      end
    end
  end
  // The per-(tap, VC) zero test, exported so the fabric's injection
  // allocator can gate on pool state without reaching into pool internals.
  always @* begin
    row_pool_nz = '0;
    col_pool_nz = '0;
    for (t_i = 0; t_i < N_TAPS; t_i = t_i + 1) begin
      for (v_i = 0; v_i < NUM_VCS; v_i = v_i + 1) begin
        row_pool_nz[t_i][v_i] = |row_credits[t_i][v_i];
        col_pool_nz[t_i][v_i] = |col_credits[t_i][v_i];
      end
    end
  end
""", 1)

    # 5a. The per-output packet lock becomes per (output, VC): packets on
    #     different VCs may hold one output concurrently; same-VC ordering
    #     HEAD -> TAIL is unchanged.
    _require(text, ROUTER_LOCK_DECL_ANCHOR, "router packet-lock declarations")
    text = text.replace(ROUTER_LOCK_DECL_ANCHOR, """  // While a multi-flit packet occupies an output, the lock is per
  // (output, VC): only packets on the same VC are blocked by it.  The lock
  // is taken when the HEAD is granted and released when the packet's TAIL
  // is granted; a SINGLE takes and releases it in one cycle.  The VC
  // travels in the flit bits pinned at injection, so the route, the output
  // and the VC are all held HEAD -> TAIL.  Packets on different VCs no
  // longer block each other on one output; a packet still cannot overtake
  // another on one wire.
  logic [NUM_VCS-1:0] local_lock, row_lock, col_lock;
  int unsigned local_lock_port [NUM_VCS], row_lock_port [NUM_VCS], col_lock_port [NUM_VCS];
""", 1)
    _require(text, ROUTER_LOCK_RESET_ANCHOR, "router packet-lock reset")
    text = text.replace(ROUTER_LOCK_RESET_ANCHOR, """      local_lock <= '0;
      row_lock <= '0;
      col_lock <= '0;
""", 1)
    _require(text, ROUTER_LOCAL_SCAN_ANCHOR, "router local candidate scan")
    text = text.replace(ROUTER_LOCAL_SCAN_ANCHOR, """      scan_idx = (rr_local + offset) % PORTS;
      cand_vc = flit_q[scan_idx][VC_LSB +: VC_W];
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      if (!found_local && valid_q[scan_idx] && candidate_dest == DEST_W'(ID) &&
          (!local_lock[cand_vc] || local_lock_port[cand_vc] == scan_idx)) begin
""", 1)
    for _lock, _grant, _anchor in (
            ("local", "grant_local", ROUTER_LOCAL_LOCK_SET_ANCHOR),
            ("row", "grant_row", ROUTER_ROW_LOCK_SET_ANCHOR),
            ("col", "grant_col", ROUTER_COL_LOCK_SET_ANCHOR)):
        _require(text, _anchor, "router " + _lock + " lock set/clear")
        text = text.replace(_anchor, ("""        if (flit_is_head(flit_q[GRANT])) begin
          LOCK[flit_q[GRANT][VC_LSB +: VC_W]] <= 1'b1;
          LOCK_PORT[flit_q[GRANT][VC_LSB +: VC_W]] <= GRANT;
        end
        if (flit_is_tail(flit_q[GRANT])) LOCK[flit_q[GRANT][VC_LSB +: VC_W]] <= 1'b0;
""".replace("GRANT", _grant)
              .replace("LOCK_PORT", _lock + "_lock_port")
              .replace("LOCK", _lock + "_lock")), 1)

    # 5b. The candidate scan only offers a tap that still has a credit, so an
    #     exhausted tap never blocks the other taps on the same wire.
    _require(text, ROUTER_SCAN_ANCHOR, "router candidate scan")
    text = text.replace(ROUTER_SCAN_ANCHOR, """      scan_idx = (rr_row + offset) % PORTS;
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      dest_x = K_W'(candidate_dest % K);
      cand_tap = TAP_W'((int'(dest_x) < int'(my_x)) ? int'(dest_x) : int'(dest_x) - 1);
      cand_vc = flit_q[scan_idx][VC_LSB +: VC_W];
      if (!found_row && valid_q[scan_idx] && int'(candidate_dest) < K*K &&
          dest_x != my_x && row_credits[cand_tap][cand_vc] != '0 &&
          (!row_lock[cand_vc] || row_lock_port[cand_vc] == scan_idx)) begin
        found_row = 1'b1;
        grant_row = scan_idx;
      end
      scan_idx = (rr_col + offset) % PORTS;
      candidate_dest = flit_q[scan_idx][DEST_LSB +: DEST_W];
      dest_x = K_W'(candidate_dest % K);
      dest_y = K_W'(candidate_dest / K);
      cand_tap = TAP_W'((int'(dest_y) < int'(my_y)) ? int'(dest_y) : int'(dest_y) - 1);
      cand_vc = flit_q[scan_idx][VC_LSB +: VC_W];
      if (!found_col && valid_q[scan_idx] && int'(candidate_dest) < K*K &&
          dest_x == my_x && dest_y != my_y && col_credits[cand_tap][cand_vc] != '0 &&
          (!col_lock[cand_vc] || col_lock_port[cand_vc] == scan_idx)) begin
        found_col = 1'b1;
        grant_col = scan_idx;
      end
""", 1)


    # 6. The local pop report: which (source, tap, VC) has to be credited.
    _require(text, ROUTER_POP_ANCHOR, "router pop")
    pop_logic = ROUTER_POP_ANCHOR.replace(
        "if (found_row && row_ready)", "if (found_row && row_req_grant && row_ready)").replace(
        "if (found_col && col_ready)", "if (found_col && col_req_grant && col_ready)")
    text = text.replace(pop_logic.replace(
        "if (found_row && row_req_grant && row_ready)", "if (found_row && row_ready)").replace(
        "if (found_col && col_req_grant && col_ready)", "if (found_col && col_ready)"),
        pop_logic + """  always_comb begin
    pop_report = pop;
    pop_vc_report = '0;
    for (int p = 1; p < PORTS; p++) begin
      pop_vc_report[p] = flit_q[p][VC_LSB +: VC_W];
    end
  end

  // The credit is claimed only when the flit actually moves onto the wire:
  // claiming it for a flit the wire cannot take would burn a credit that no
  // dequeue will ever return.
  assign row_req_valid = found_row && row_ready;
  assign col_req_valid = found_col && col_ready;
  tap_credit_pool #(
    .N_TAPS(N_TAPS), .NUM_VCS(NUM_VCS), .CAPACITY(CAPACITY),
    .CREDIT_W(CREDIT_W), .TAP_W(TAP_W), .VC_W(VC_W), .LATENCY(WIRE_PIPE)
  ) u_row_credits (
    .clk(clk), .rst_n(rst_n),
    .req_tap(row_req_tap), .req_vc(row_req_vc), .req_valid(row_req_valid),
    .req_ready(row_req_ready), .req_grant(row_req_grant),
    .free_tap(pop_rel_row_tap), .free_vc(pop_rel_row_vc), .free_valid(pop_rel_row_valid),
    .credits(row_credits), .outstanding(row_out_q), .alias_detected(row_alias_q)
  );
  tap_credit_pool #(
    .N_TAPS(N_TAPS), .NUM_VCS(NUM_VCS), .CAPACITY(CAPACITY),
    .CREDIT_W(CREDIT_W), .TAP_W(TAP_W), .VC_W(VC_W), .LATENCY(WIRE_PIPE)
  ) u_col_credits (
    .clk(clk), .rst_n(rst_n),
    .req_tap(col_req_tap), .req_vc(col_req_vc), .req_valid(col_req_valid),
    .req_ready(col_req_ready), .req_grant(col_req_grant),
    .free_tap(pop_rel_col_tap), .free_vc(pop_rel_col_vc), .free_valid(pop_rel_col_valid),
    .credits(col_credits), .outstanding(col_out_q), .alias_detected(col_alias_q)
  );
  assign row_alias = row_alias_q;
  assign col_alias = col_alias_q;
""", 1)

    # 7. The fabric's release routing: collect every upstream pop and
    #    serialize returns into each source router's single-port credit pool.
    #    Also the pipelined-wire state, the injection-side VC allocator state,
    #    and the packet field positions as fabric-visible localparams.
    decl = [
        "  logic [N-1:0] row_alias, col_alias;\n",
        "  logic [N-1:0][15:0] row_outstanding, row_available;\n",
        "  logic [N-1:0][15:0] col_outstanding, col_available;\n",
        "  logic [N-1:0] pop_rel_row_valid, pop_rel_col_valid;\n",
        "  logic [N-1:0][TAP_W-1:0] pop_rel_row_tap, pop_rel_col_tap;\n",
        "  logic [N-1:0][VC_W-1:0] pop_rel_row_vc, pop_rel_col_vc;\n",
        "  logic [N-1:0][PORTS-1:0] router_pop_report;\n",
        "  logic [N-1:0][PORTS-1:0][VC_W-1:0] router_pop_vc_report;\n",
        "  localparam int RETURN_COUNT_W = (N > 1) ? $clog2(N+1) : 1;\n",
        "  logic [N-1:0][N_TAPS-1:0][NUM_VCS-1:0][RETURN_COUNT_W-1:0] row_ret_count, col_ret_count;\n",
        "  logic [N-1:0][N_TAPS-1:0][NUM_VCS-1:0][RETURN_COUNT_W-1:0] row_ret_arrivals, col_ret_arrivals;\n",
        "  localparam int PACKET_VC_LSB = %d;\n" % vc_lsb,
        "  localparam int PACKET_TYPE_LSB = %d;\n" % (vc_lsb - 2),
        "  // Pipelined wire model: WIRE_PIPE elastic valid/flit stages per (src, axis).\n",
        "  logic [N-1:0][WIRE_PIPE-1:0] pipe_row_v, pipe_col_v;\n",
        "  logic [N-1:0][WIRE_PIPE-1:0][W-1:0] pipe_row_f, pipe_col_f;\n",
        "  logic [N-1:0] row_wire_exit, col_wire_exit;\n",
        "  logic [N-1:0][WIRE_PIPE-1:0] row_stage_rdy, col_stage_rdy;\n",
        "  // Injection-side VC allocation state (per endpoint router).\n",
        "  logic [N-1:0][VC_W-1:0] inject_rr_q;\n",
        "  logic [N-1:0] pkt_active_q;\n",
        "  logic [N-1:0][VC_W-1:0] pkt_vc_q;\n",
        "  logic [N-1:0][31:0] inject_error_q;\n",
        "  logic [VC_W-1:0] inject_vc;\n",
        "  logic [1:0] inject_type;\n",
        "  logic [N-1:0] inj_enter, inj_ready;\n",
        "  logic [N-1:0][VC_W-1:0] inj_vc;\n",
        "  logic [N-1:0][N_TAPS-1:0][NUM_VCS-1:0] row_pool_nz, col_pool_nz;\n",
        "  wire unused_inject_error = &{1'b0, inject_error_q};\n",
        "  // The wire drivers no longer read row_dest/col_dest; state the fact.\n",
        "  wire [N-1:0][DEST_W-1:0] unused_row_dest = row_dest;\n",
        "  wire [N-1:0][DEST_W-1:0] unused_col_dest = col_dest;\n",
        "  // The family that instantiates this module does not read the bookkeeping\n",
        "  // below; consume it here and make the omission visible in the source.\n",
        "  wire [N-1:0][1:0] unused_row_vc = row_vc;\n",
        "  wire [N-1:0][1:0] unused_col_vc = col_vc;\n",
        "  wire [N-1:0] unused_row_alias = row_alias;\n",
        "  wire [N-1:0] unused_col_alias = col_alias;\n",
        "  wire [N-1:0][15:0] unused_row_outstanding = row_outstanding;\n",
        "  wire [N-1:0][15:0] unused_row_available = row_available;\n",
        "  wire [N-1:0][15:0] unused_col_outstanding = col_outstanding;\n",
        "  wire [N-1:0][15:0] unused_col_available = col_available;\n",
    ]
    _require(text, FABRIC_DECL_ANCHOR, "fabric declarations")
    text = text.replace(FABRIC_DECL_ANCHOR, FABRIC_DECL_ANCHOR + "".join(decl), 1)

    # The destination's ingress port is indexed by row_tap(src, dst), but the
    # source pool is indexed by the destination's slot on that source wire:
    # row_tap(dst, src). This topology-derived identity replaces tap echo bits.
    route_f = ["  // Endpoint (or router) IDs and packet endpoint IDs need not agree;\n",
               "  // an invalid endpoint decodes outside the router range, never to router 0.\n",
               "  function automatic int unsigned route_destination_f(input logic [W-1:0] flit);\n",
               "    automatic logic unused_flit_bits;\n",
               "    unused_flit_bits = &{1'b0, flit};\n"]
    if endpoint_routers:
        route_f.append(f"    case (flit[{dst_lsb} +: {packet_dst_w}])\n")
        route_f.extend(f"      {packet_dst_w}'d{ep}: return {router};\n"
                       for ep, router in enumerate(endpoint_routers))
        route_f.append("      default: return K*K;\n    endcase\n")
    else:
        route_f.append(f"    return int'(flit[{dst_lsb} +: {packet_dst_w}]);\n")
    route_f.append("  endfunction\n")
    route_f_text = "".join(route_f)
    _require(text, FABRIC_RELEASE_ANCHOR, "fabric output")
    text = text.replace(FABRIC_RELEASE_ANCHOR, FABRIC_RELEASE_ANCHOR + route_f_text + """  // Count every upstream release, then serialize each source's returns into
  // its single-port credit pool. Multiple destinations can pop concurrently.
  always_comb begin
    row_ret_arrivals = '0;
    col_ret_arrivals = '0;
    for (int src = 0; src < N; src++) begin
      for (int dst = 0; dst < N; dst++) begin
        if ((src / K) == (dst / K) && src != dst &&
            router_pop_report[dst][1 + row_tap(src, dst)]) begin
          row_ret_arrivals[src][row_tap(dst, src)]
            [router_pop_vc_report[dst][1 + row_tap(src, dst)]] =
              row_ret_arrivals[src][row_tap(dst, src)]
                [router_pop_vc_report[dst][1 + row_tap(src, dst)]] + 1'b1;
        end
        if ((src % K) == (dst % K) && src != dst &&
            router_pop_report[dst][1 + (K-1) + col_tap(src, dst)]) begin
          col_ret_arrivals[src][col_tap(dst, src)]
            [router_pop_vc_report[dst][1 + (K-1) + col_tap(src, dst)]] =
              col_ret_arrivals[src][col_tap(dst, src)]
                [router_pop_vc_report[dst][1 + (K-1) + col_tap(src, dst)]] + 1'b1;
        end
      end
    end
  end

  always_comb begin
    pop_rel_row_valid = '0;
    pop_rel_col_valid = '0;
    pop_rel_row_tap = '0;
    pop_rel_col_tap = '0;
    pop_rel_row_vc = '0;
    pop_rel_col_vc = '0;
    for (int src = 0; src < N; src++) begin
      for (int t = 0; t < N_TAPS; t++) begin
        for (int v = 0; v < NUM_VCS; v++) begin
          if (!pop_rel_row_valid[src] && row_ret_count[src][t][v] != '0) begin
            pop_rel_row_valid[src] = 1'b1;
            pop_rel_row_tap[src] = TAP_W'(t);
            pop_rel_row_vc[src] = VC_W'(v);
          end
          if (!pop_rel_col_valid[src] && col_ret_count[src][t][v] != '0) begin
            pop_rel_col_valid[src] = 1'b1;
            pop_rel_col_tap[src] = TAP_W'(t);
            pop_rel_col_vc[src] = VC_W'(v);
          end
        end
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      row_ret_count <= '0;
      col_ret_count <= '0;
    end else begin
      for (int src = 0; src < N; src++) begin
        for (int t = 0; t < N_TAPS; t++) begin
          for (int v = 0; v < NUM_VCS; v++) begin
            row_ret_count[src][t][v] <= row_ret_count[src][t][v]
              + row_ret_arrivals[src][t][v]
              - ((pop_rel_row_valid[src] && pop_rel_row_tap[src] == TAP_W'(t) &&
                  pop_rel_row_vc[src] == VC_W'(v)) ? 1'b1 : 1'b0);
            col_ret_count[src][t][v] <= col_ret_count[src][t][v]
              + col_ret_arrivals[src][t][v]
              - ((pop_rel_col_valid[src] && pop_rel_col_tap[src] == TAP_W'(t) &&
                  pop_rel_col_vc[src] == VC_W'(v)) ? 1'b1 : 1'b0);
          end
        end
      end
    end
  end

  // The pipelined wire registers.  Stage 0 fills when the source router
  // grants the wire (valid && stage 0 acceptance space); stage i registers
  // (valid, flit) when stage i+1 accepts; stage WIRE_PIPE-1 holds until the
  // addressed tap's input port accepts the flit.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pipe_row_v <= '0;
      pipe_col_v <= '0;
      inject_rr_q <= '0;
      pkt_active_q <= '0;
      pkt_vc_q <= '0;
      inject_error_q <= '0;
    end else begin
      for (int src = 0; src < N; src++) begin
        for (int i = 0; i < WIRE_PIPE; i = i + 1) begin
          if (i == 0) begin
            // Stage 0 is elastic: it holds its occupant when the next stage
            // cannot accept. Writing `valid && ready` unconditionally would
            // clear the flit on every stalled cycle and lose it.
            if (row_stage_rdy[src][0]) begin
              pipe_row_v[src][0] <= row_valid[src];
              if (row_valid[src]) pipe_row_f[src][0] <= row_flit[src];
            end
            if (col_stage_rdy[src][0]) begin
              pipe_col_v[src][0] <= col_valid[src];
              if (col_valid[src]) pipe_col_f[src][0] <= col_flit[src];
            end
          end else begin
            if (row_stage_rdy[src][i]) begin
              pipe_row_v[src][i] <= pipe_row_v[src][i-1];
              pipe_row_f[src][i] <= pipe_row_f[src][i-1];
            end
            if (col_stage_rdy[src][i]) begin
              pipe_col_v[src][i] <= pipe_col_v[src][i-1];
              pipe_col_f[src][i] <= pipe_col_f[src][i-1];
            end
          end
        end
        // Injection-side VC allocation, credit-aware: HEAD/SINGLE take
        // the VC the comb block selected (round-robin-earliest VC with a
        // first-hop credit) and advance the rotation past it.  A refused
        // HEAD/SINGLE never reaches this block: ep_in_ready withholds it
        // at the boundary and no rotation slot burns.  BODY/TAIL inherit
        // the packet VC; BODY/TAIL with no packet open count an error and
        // burn no rotation slot.  A HEAD/SINGLE with inj_enter low
        // (invalid endpoint) is consumed and counted, never injected.
        if (ep_in_valid[src] && node_in_ready[src][0] && inj_ready[src]) begin
          logic [1:0] itype;
          itype = ep_in_flit[src][PACKET_TYPE_LSB +: 2];
          if (itype == 2'b00) begin
            if (pkt_active_q[src])
              inject_error_q[src] <= inject_error_q[src] + 1'b1;
            if (inj_enter[src]) begin
              pkt_active_q[src] <= 1'b1;
              pkt_vc_q[src] <= inj_vc[src];
              inject_rr_q[src] <= (inj_vc[src] == VC_W'(NUM_VCS - 1)) ? '0 : inj_vc[src] + 1'b1;
            end else if (!pkt_active_q[src]) inject_error_q[src] <= inject_error_q[src] + 1'b1;
          end else if (itype == 2'b11) begin
            if (inj_enter[src])
              inject_rr_q[src] <= (inj_vc[src] == VC_W'(NUM_VCS - 1)) ? '0 : inj_vc[src] + 1'b1;
            else inject_error_q[src] <= inject_error_q[src] + 1'b1;
          end else if (itype == 2'b10) begin
            if (pkt_active_q[src]) pkt_active_q[src] <= 1'b0;
            else inject_error_q[src] <= inject_error_q[src] + 1'b1;
          end else begin
            if (!pkt_active_q[src])
              inject_error_q[src] <= inject_error_q[src] + 1'b1;
          end
        end
      end
    end
  end
""", 1)

    _require(text, FABRIC_INJECT_ANCHOR, "fabric injection inputs")
    text = text.replace(FABRIC_INJECT_ANCHOR, """    // Injection-side VC allocation, first-hop-credit-aware: the producer's
    // VC field is not trusted.  HEAD/SINGLE take the round-robin-earliest
    // VC whose first-hop (tap, VC) pool still holds a credit.  Local
    // (no-wire) packets keep the plain rotation.  A packet whose first-hop
    // pools are all exhausted is withheld at the port: the endpoint holds
    // valid, the fabric reports no ready, and no rotation slot burns.  A
    // HEAD/SINGLE addressed outside the router range is consumed at the
    // port, counted in inject_error_q, and never enters the fabric.
    // BODY/TAIL inherit the packet VC stamped at the HEAD; an orphan
    // BODY/TAIL is counted and injected as a plain flit.
    for (int n = 0; n < N; n++) begin
      int dst_d;
      int mx;
      int my;
      int dx;
      int dy;
      int tap;
      int voff;
      int vc_c;
      int vsel;
      int found;
      dst_d = 0;
      mx = n % K;
      my = n / K;
      dx = 0;
      dy = 0;
      tap = 0;
      voff = 0;
      vc_c = 0;
      vsel = 0;
      found = 0;
      node_in_valid[n][0] = ep_in_valid[n];
      node_in_flit[n][0] = ep_in_flit[n];
      inject_type = ep_in_flit[n][PACKET_TYPE_LSB +: 2];
      inj_ready[n] = 1'b1;
      inj_enter[n] = 1'b1;
      inj_vc[n] = '0;
      if ((inject_type == 2'b00) || (inject_type == 2'b11)) begin
        dst_d = int'(route_destination_f(ep_in_flit[n]));
        if (dst_d >= N) begin
          inj_enter[n] = 1'b0;
          node_in_valid[n][0] = 1'b0;
          node_in_flit[n][0] = '0;
        end else begin
          dx = dst_d % K;
          dy = dst_d / K;
          if ((dx == mx) && (dy == my)) begin
            vsel = int'(inject_rr_q[n]);
            found = 1;
          end else if (dx != mx) begin
            tap = (dx < mx) ? dx : dx - 1;
            for (voff = 0; voff < NUM_VCS; voff = voff + 1) begin
              vc_c = (int'(inject_rr_q[n]) + voff) % NUM_VCS;
              if (!found && row_pool_nz[n][tap][vc_c]) begin
                vsel = vc_c;
                found = 1;
              end
            end
          end else begin
            tap = (dy < my) ? dy : dy - 1;
            for (voff = 0; voff < NUM_VCS; voff = voff + 1) begin
              vc_c = (int'(inject_rr_q[n]) + voff) % NUM_VCS;
              if (!found && col_pool_nz[n][tap][vc_c]) begin
                vsel = vc_c;
                found = 1;
              end
            end
          end
          if (found) begin
            inj_vc[n] = VC_W'(vsel);
          end else begin
            inj_ready[n] = 1'b0;
            inj_enter[n] = 1'b0;
            node_in_valid[n][0] = 1'b0;
            node_in_flit[n][0] = '0;
          end
        end
      end else if (pkt_active_q[n]) begin
        inj_vc[n] = pkt_vc_q[n];
      end else begin
        inj_vc[n] = inject_rr_q[n];
      end
      if (inj_enter[n])
        node_in_flit[n][0][PACKET_VC_LSB +: VC_W] = inj_vc[n];
    end
""", 1)
    _require(text, FABRIC_DRIVER_ANCHOR, "fabric wire drivers")
    text = text.replace(FABRIC_DRIVER_ANCHOR, "    // The pipe emits a flit only when it leaves stage WIRE_PIPE-1: that is\n    // the multidrop tap the addressed destination sees.\n    for (int src = 0; src < N; src++) begin\n      int pd;\n      int row_dst;\n      int col_dst;\n      pd = -1;\n      row_dst = 0;\n      col_dst = 0;\n      if (pipe_row_v[src][WIRE_PIPE-1]) pd = route_destination_f(pipe_row_f[src][WIRE_PIPE-1]);\n      if (pd >= 0 && (pd % K) != (src % K)) begin\n        row_dst = (src / K) * K + (pd % K);\n        node_in_valid[row_dst][1 + row_tap(src, row_dst)] = 1'b1;\n        node_in_flit[row_dst][1 + row_tap(src, row_dst)] = pipe_row_f[src][WIRE_PIPE-1];\n      end\n      pd = -1;\n      if (pipe_col_v[src][WIRE_PIPE-1]) pd = route_destination_f(pipe_col_f[src][WIRE_PIPE-1]);\n      if (pd >= 0 && (pd / K) != (src / K)) begin\n        col_dst = (pd / K) * K + (src % K);\n        node_in_valid[col_dst][1 + (K-1) + col_tap(src, col_dst)] = 1'b1;\n        node_in_flit[col_dst][1 + (K-1) + col_tap(src, col_dst)] = pipe_col_f[src][WIRE_PIPE-1];\n      end\n    end\n", 1)
    _require(text, FABRIC_READY_ANCHOR, "fabric wire ready chain")
    text = text.replace(FABRIC_READY_ANCHOR, "  // Stage acceptance space, from the destination backwards.  Stage\n  // WIRE_PIPE-1 accepts when its slot is empty or its occupant exits into\n  // the addressed tap; stage i accepts when it is empty or stage i+1 can.\n  // The router sees stage 0's acceptance space as its row/col ready.\n  always_comb begin\n    row_ready = '0;\n    col_ready = '0;\n    row_wire_exit = '0;\n    col_wire_exit = '0;\n    for (int src = 0; src < N; src++) begin\n      int pd;\n      int row_dst;\n      int col_dst;\n      pd = -1;\n      row_dst = 0;\n      col_dst = 0;\n      if (pipe_row_v[src][WIRE_PIPE-1]) begin\n        pd = route_destination_f(pipe_row_f[src][WIRE_PIPE-1]);\n        if ((pd % K) != (src % K)) begin\n          row_dst = (src / K) * K + (pd % K);\n          row_wire_exit[src] = node_in_ready[row_dst][1 + row_tap(src, row_dst)];\n        end else row_wire_exit[src] = 1'b0;\n      end\n      row_stage_rdy[src][WIRE_PIPE-1] = !pipe_row_v[src][WIRE_PIPE-1] || row_wire_exit[src];\n      for (int i = WIRE_PIPE - 2; i >= 0; i = i - 1)\n        row_stage_rdy[src][i] = !pipe_row_v[src][i] || row_stage_rdy[src][i+1];\n      row_ready[src] = row_stage_rdy[src][0];\n      pd = -1;\n      if (pipe_col_v[src][WIRE_PIPE-1]) begin\n        pd = route_destination_f(pipe_col_f[src][WIRE_PIPE-1]);\n        if ((pd / K) != (src / K)) begin\n          col_dst = (pd / K) * K + (src % K);\n          col_wire_exit[src] = node_in_ready[col_dst][1 + (K-1) + col_tap(src, col_dst)];\n        end else col_wire_exit[src] = 1'b0;\n      end\n      col_stage_rdy[src][WIRE_PIPE-1] = !pipe_col_v[src][WIRE_PIPE-1] || col_wire_exit[src];\n      for (int i = WIRE_PIPE - 2; i >= 0; i = i - 1)\n        col_stage_rdy[src][i] = !pipe_col_v[src][i] || col_stage_rdy[src][i+1];\n      col_ready[src] = col_stage_rdy[src][0];\n    end\n  end\n", 1)
    _require(text, FABRIC_IN_READY_ANCHOR, "fabric injection ready")
    text = text.replace(FABRIC_IN_READY_ANCHOR, """    assign ep_in_ready[n] = node_in_ready[n][0] && inj_ready[n];
    gec_mecs_router #(""", 1)
    _require(text, "    gec_mecs_router #(.ID(n), .K(K), .W(W), .DEST_W(DEST_W), .PORTS(PORTS)) u_router (", 
             "fabric router instance")
    text = text.replace(
        "    gec_mecs_router #(.ID(n), .K(K), .W(W), .DEST_W(DEST_W), .PORTS(PORTS)) u_router (",
        "    gec_mecs_router #(.ID(n), .K(K), .W(W), .DEST_W(DEST_W), .PORTS(PORTS),\n"
        "      .N_TAPS(N_TAPS), .NUM_VCS(NUM_VCS), .CAPACITY(CAPACITY),\n"
        "      .TAP_W(TAP_W), .VC_W(VC_W), .CREDIT_W(CREDIT_W),\n"
        "      .WIRE_PIPE(WIRE_PIPE)) u_router (", 1)
    _require(text, FABRIC_INST_ANCHOR, "fabric router port connections")
    text = text.replace(FABRIC_INST_ANCHOR, """      .row_valid(row_valid[n]), .row_ready(row_ready[n]), .row_flit(row_flit[n]),
      .row_dest(row_dest[n]), .row_vc(row_vc[n]),
      .col_valid(col_valid[n]), .col_ready(col_ready[n]), .col_flit(col_flit[n]),
      .col_dest(col_dest[n]), .col_vc(col_vc[n]),
      .row_alias(row_alias[n]), .col_alias(col_alias[n]),
      .row_outstanding(row_outstanding[n]), .row_available(row_available[n]),
      .col_outstanding(col_outstanding[n]), .col_available(col_available[n]),
      .pop_rel_row_valid(pop_rel_row_valid[n]), .pop_rel_row_tap(pop_rel_row_tap[n]),
      .pop_rel_row_vc(pop_rel_row_vc[n]),
      .pop_rel_col_valid(pop_rel_col_valid[n]), .pop_rel_col_tap(pop_rel_col_tap[n]),
      .pop_rel_col_vc(pop_rel_col_vc[n]),
      .pop_report(router_pop_report[n]),
      .pop_vc_report(router_pop_vc_report[n]),
      .row_pool_nz(row_pool_nz[n]),
      .col_pool_nz(col_pool_nz[n])
""", 1)

    # 8. The fabric module needs the credit parameters too.
    _require(text, "  parameter int DEST_W = 4\n", "fabric parameters")
    text = text.replace("  parameter int DEST_W = 4\n", (
        "  parameter int DEST_W = 4,\n"
        "  parameter int N_TAPS = %d,\n"
        "  parameter int NUM_VCS = %d,\n"
        "  parameter int CAPACITY = %d,\n"
        "  parameter int TAP_W = %d,\n"
        "  parameter int VC_W = %d,\n"
        "  parameter int CREDIT_W = %d,\n"
        "  parameter int WIRE_PIPE = %d\n"
        % (taps_per_wire, num_vcs, capacity, tap_w, vc_w, credit_w, wire_pipe)), 1)

    # Router IDs and packet endpoint IDs need not have the same width or value.
    # An invalid endpoint decodes outside the router range, never to router 0.
    route = ["  function automatic int unsigned route_destination(input logic [W-1:0] flit);",
             "    automatic logic unused_flit_bits;",
             "    unused_flit_bits = &{1'b0, flit};"]
    if endpoint_routers:
        route.append(f"    case (flit[DEST_LSB +: {packet_dst_w}])")
        route.extend(f"      {packet_dst_w}'d{ep}: return {router};"
                     for ep, router in enumerate(endpoint_routers))
        route.extend(["      default: return K*K;", "    endcase"])
    else:
        route.append(f"    return int'(flit[DEST_LSB +: {packet_dst_w}]);")
    route.append("  endfunction\n")
    anchor = "  logic [DEST_W-1:0] candidate_dest;\n"
    _require(text, anchor, "router destination decode")
    text = text.replace(anchor, "\n".join(route) + "  int unsigned candidate_dest;\n", 1)
    for index in ("scan_idx", "grant_row", "grant_col"):
        anchor = f"flit_q[{index}][DEST_LSB +: DEST_W]"
        _require(text, anchor, "router packet destination")
        text = text.replace(anchor, f"route_destination(flit_q[{index}])")

    # 9. The proven pool travels in its own file: one module per file,
    # each file named for the module it holds.
    return text


def render_credited_pool() -> str:
    """The proven credit pool, in the file that holds it."""
    return _pool_source()


__all__ = [
    "CreditedFabricError",
    "render_credited_fabric",
]
