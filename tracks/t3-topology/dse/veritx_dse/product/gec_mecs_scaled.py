"""Scalable GEC-MECS shared fabric: emitter and testbench for any shape.

The shipped shared fabric (`GEC_MECS_FABRIC_SV` in
`veritx_dse/product/project_top_rtl.py`) is a Verilog template whose top
level is a generate loop over `N = K*K` routers with K-derived row/column
routing and a `DEST_W`-wide destination field. The 16-router limit was a
**policy check in Python**, not a limit of the RTL: the template carries no
hardcoded 16 or 4.

This module reuses that template and emits it for an arbitrary declared
shape, so the pinned full-size contract (K=9 -> 81 routers, 162 shared
wires, 3 taps per wire, 128-bit flits) becomes emittable instead of
refused. The shape still comes from the compiled bundle; nothing here
invents topology.

Scope and honest limits:

* the fabric models one row wire and one column wire per router with
  `d` taps per wire; tap identity comes from the physical ingress port, while
  destination/VC offsets may be bound to the compiled packet contract;
* the emitter applies the credited-fabric transform, embedding the proven
  `tap_credit_pool` and accounting per (wire, tap, VC); the generated
  testbench checks routing, conservation, and credit behavior for its shape;
* passing a small emitted shape is not selected-project qualification: the
  81-router/74-endpoint Chisel path and native/physical gates remain separate.
"""
from __future__ import annotations

from dataclasses import dataclass

from veritx_dse.product.project_top_rtl import GEC_MECS_FABRIC_SV

MODULE_NAME = "gec_mecs16_fabric"

CREDIT_CAPACITY = 4
"""Flits in flight per (tap, VC) on one shared wire.

Small for a bounded regression. The router's current single-entry input
buffers can apply stricter backpressure than this credit limit; the test
checks bounded outstanding state, exact return routing, and eventual drain.
"""

CREDITED_SHARED_FABRIC = True
"""Whether the scalable shared fabric carries per-tap credits.

ON: a grant consumes the exact (tap, VC) credit when the flit moves onto
its wire. Each downstream input pop queues a return to the previous router;
returns are serialized per source without losing coincident tap releases.
The generated testbench checks all ordered pairs, payload preservation,
backpressure, return routing, and drain at its declared shape.

The honest limit is the wire model: it delivers one flit per cycle to one
destination, while router inputs are single-entry. The credit limit is not
claimed to model a deeper pipelined link. Injection admission is
first-hop-credit-aware: a packet whose (tap, VC) pools are all empty is
withheld at the port instead of injected into a path that cannot move it.
Packet locks on outputs are per (output, VC).
"""


class ScaledMecsShapeError(ValueError):
    """The declared shape is outside what the shared fabric models."""


@dataclass(frozen=True)
class ScaledMecsParams:
    k: int
    concentration: int
    express_groups: int
    taps_per_wire: int
    num_vcs: int
    router_count: int
    shared_wires: int
    flit_w: int
    dest_w: int
    ports: int
    drop_field_lsb: int
    drop_field_w: int
    endpoint_routers: tuple[int, ...] = ()
    """Endpoint seats, indexed by endpoint id, each on its own router.

    Empty means the fabric's endpoints are its routers, which is the
    historical behaviour.  When it is set, packets carry endpoint ids and the
    fabric decodes them to routers, so the run exercises the project's real
    agent seats rather than the router set.
    """

    @property
    def rows(self) -> int:
        return self.k

    @property
    def endpoint_count(self) -> int:
        return len(self.endpoint_routers)

    @property
    def endpoint_mode(self) -> bool:
        return bool(self.endpoint_routers)

    def router_of(self, endpoint: int) -> int:
        if self.endpoint_mode:
            return self.endpoint_routers[endpoint]
        return endpoint

    def endpoint_of(self, router: int) -> int:
        if self.endpoint_mode:
            return self.endpoint_routers.index(router)
        return router


def _log2(value: int) -> int:
    return max(1, (value - 1).bit_length())


def scaled_mecs_params(request, compiled) -> ScaledMecsParams:
    """Derive the fabric shape from the compiled bundle — nothing invented."""
    if compiled.status != "COMPILED" or compiled.bundle is None:
        raise ScaledMecsShapeError("compile did not produce a bundle")
    topo = compiled.bundle.topology
    routers = list(getattr(topo, "routers", ()) or ())
    shared = list(getattr(topo, "shared_links", ()) or ())
    channels = list(getattr(topo, "channels", ()) or ())
    if not routers or not shared:
        raise ScaledMecsShapeError("the bundle carries no routers or shared wires")
    if channels:
        raise ScaledMecsShapeError(
            "the shared fabric models wire-only fabrics; the bundle also "
            "carries point-to-point channels")
    intent = request.topology
    k = int(getattr(intent, "grid_side_length", 0) or 0)
    c = int(getattr(intent, "concentration", 1) or 1)
    o = int(getattr(intent, "express_channel_groups_per_dimension", 1) or 1)
    d = int(getattr(intent, "destinations_per_express_channel", 0) or 0)
    if k < 2:
        raise ScaledMecsShapeError("the shared fabric needs a grid side of at least 2")
    if c != 1:
        raise ScaledMecsShapeError(
            "the shared fabric models concentration 1; got " + str(c))
    if o != 1:
        raise ScaledMecsShapeError(
            "the shared fabric models one express channel group per dimension; got "
            + str(o))
    if d < 2:
        raise ScaledMecsShapeError(
            "the shared fabric needs at least two taps per wire; got " + str(d))
    if len(routers) != k * k:
        raise ScaledMecsShapeError(
            "the bundle carries " + str(len(routers)) + " routers but the declared "
            "grid side " + str(k) + " implies " + str(k * k))
    dest_w = _log2(len(routers))
    if (1 << dest_w) < len(routers):
        raise ScaledMecsShapeError(
            "the destination field cannot address every router; got "
            + str(len(routers)) + " routers")
    flit_w = int(getattr(shared[0], "width_bits", 64) or 64)
    ports = 1 + 2 * (k - 1)
    vc_assignment = getattr(compiled.bundle, "vc_assignment", None)
    num_vcs = int(getattr(vc_assignment, "vc_count", 0) or 0)
    return ScaledMecsParams(
        k=k, concentration=c, express_groups=o, taps_per_wire=d,
        num_vcs=num_vcs, router_count=len(routers), shared_wires=len(shared),
        flit_w=flit_w, dest_w=dest_w, ports=ports,
        drop_field_lsb=flit_w - dest_w, drop_field_w=dest_w)


def split_scaled_fabric(text: str) -> tuple[str, str]:
    """The router and the fabric, one module per file.

    Each file is named for the module it holds, so the lint can check
    the file name against the module name without a suppression.
    """
    marker = "module " + MODULE_NAME
    index = text.index(marker)
    return text[:index].rstrip() + "\n", text[index:]


def render_scaled_fabric(params: ScaledMecsParams, *,
                         destination_field: tuple[int, int] | None = None,
                         vc_field: tuple[int, int] | None = None,
                         endpoint_routers: tuple[int, ...] = (),
                         credit_capacity: int = CREDIT_CAPACITY) -> str:
    """The shared template, instantiated for the declared shape.

    The credit wiring is applied to the raw template first: it is anchored
    on the template's own text, so it has to see the template as it was
    written, and the shape substitutions come afterwards.
    """
    if CREDITED_SHARED_FABRIC:
        from veritx_dse.product.gec_mecs_credited import render_credited_fabric
        # An explicit seat map wins; otherwise the declared one is used.
        seat_map = tuple(endpoint_routers) if endpoint_routers \
            else tuple(params.endpoint_routers)
        text = render_credited_fabric(
            template=GEC_MECS_FABRIC_SV,
            module_name=MODULE_NAME,
            k=params.k,
            flit_w=params.flit_w,
            dest_w=params.dest_w,
            num_vcs=max(1, params.num_vcs),
            taps_per_wire=params.taps_per_wire,
            capacity=credit_capacity,
            wire_latency=1,
            destination_field=destination_field, vc_field=vc_field,
            endpoint_routers=seat_map,
        )
    else:
        text = GEC_MECS_FABRIC_SV
    text = text.replace("module gec_mecs16_fabric #(", "module " + MODULE_NAME + " #(")
    text = text.replace("parameter int K = 4,", "parameter int K = %d," % params.k)
    text = text.replace("parameter int W = 64,", "parameter int W = %d," % params.flit_w)
    text = text.replace("parameter int DEST_W = 4", "parameter int DEST_W = %d" % params.dest_w)
    # The template self-checks the shape it was written for; when it is
    # instantiated for another declared shape, the check must verify THAT
    # shape instead of the historical one.
    text = text.replace(
        "if (K != 4 || ID >= K*K || PORTS != 1 + 2*(K-1) || DEST_W != 4)",
        "if (K != %d || ID >= K*K || PORTS != 1 + 2*(K-1) || DEST_W != %d)"
        % (params.k, params.dest_w))
    return text


def _pairs(params: ScaledMecsParams) -> list[tuple[int, int]]:
    """All ordered endpoint pairs, including local and multi-hop routes."""
    if params.endpoint_mode:
        count = params.endpoint_count
        return [(src, dst) for src in range(count) for dst in range(count)]
    return [(src, dst) for src in range(params.router_count)
            for dst in range(params.router_count)]


def pair_count(params: ScaledMecsParams) -> int:
    """Number of flows the generated testbench drives for this shape."""
    return len(_pairs(params))


def render_scaled_tb(params: ScaledMecsParams, *,
                     credit_capacity: int = CREDIT_CAPACITY,
                     admission_scenario: bool = False) -> str:
    """A testbench for the declared shape: routing, payload, and credits.

    `credit_capacity` must match the capacity the fabric was rendered with;
    the credit-admission scenario is only emitted when asked for, and it
    requires a capacity the fabric's (tap, VC) pools can actually drain to
    zero (path depth < capacity keeps the gate from ever firing otherwise).
    """
    k = params.k
    n = params.router_count
    w = params.flit_w
    dest_w = params.dest_w
    dest_lsb = params.drop_field_lsb
    src_lsb = dest_lsb - dest_w
    vc_w = max(1, (max(1, params.num_vcs) - 1).bit_length())
    vc_lsb = src_lsb - vc_w
    # Multi-flit framing needs a type field. Carve it from the top of the
    # payload so the destination/VC offsets (and the C5 credit evidence)
    # stay unchanged: payload | type | vc | src | dest.
    type_w = 2
    type_lsb = vc_lsb - type_w
    payload_lsb, payload_w = 0, type_lsb
    pairs = _pairs(params)
    total = len(pairs)
    # The credit scenarios need a source and two destinations on one row.  In
    # endpoint mode they must be rows that actually carry seats.
    if params.endpoint_mode:
        by_row: dict[int, list[int]] = {}
        for router in params.endpoint_routers:
            by_row.setdefault(router // params.k, []).append(router)
        triples = [sorted(v)[:3] for v in by_row.values() if len(v) >= 3]
        if not triples:
            raise ScaledMecsShapeError(
                "the endpoint seats do not place three routers on one row, so "
                "the shared fabric's credit scenarios cannot run on them")
        credit_triple = tuple(triples[0])
    else:
        credit_triple = (0, 1, 2)
    lines = []
    add = lines.append
    add("`timescale 1ns/1ps")
    add(f"module tb_{MODULE_NAME};")
    add(f"  localparam int N = {n};")
    add(f"  localparam int W = {w};")
    add(f"  localparam int K = {k};")
    add(f"  localparam int DEST_LSB = {dest_lsb};")
    add(f"  localparam int SRC_LSB = {src_lsb};")
    add(f"  localparam int SRC_W = {dest_w};")
    add(f"  localparam int VC_LSB = {vc_lsb};")
    add(f"  localparam int VC_W = {vc_w};")
    add(f"  localparam int TYPE_LSB = {type_lsb};")
    add(f"  localparam int TYPE_W = {type_w};")
    add(f"  localparam int NUM_VCS = {max(1, params.num_vcs)};")
    add(f"  localparam int PAYLOAD_LSB = {payload_lsb};")
    add(f"  localparam int PAYLOAD_W = {payload_w};")
    add(f"  localparam int FT_HEAD = 2'd0;")
    add(f"  localparam int FT_BODY = 2'd1;")
    add(f"  localparam int FT_TAIL = 2'd2;")
    add(f"  localparam int FT_SINGLE = 2'd3;")
    add("  function automatic logic [W-1:0] bits_mask(input int lsb, input int msb);")
    add("    bits_mask = '0;")
    add("    for (int i = lsb; i <= msb; i++) bits_mask[i] = 1'b1;")
    add("    return bits_mask;")
    add("  endfunction")
    add("  function automatic bit same_flit(input logic [W-1:0] left, input logic [W-1:0] right);")
    add("    // The injection allocator re-stamps the VC field, so packet identity")
    add("    // is everything except the VC bits.")
    add("    same_flit = ((left & ~bits_mask(VC_LSB, VC_LSB + VC_W - 1)) ===")
    add("                (right & ~bits_mask(VC_LSB, VC_LSB + VC_W - 1)));")
    add("  endfunction")
    add(f"  localparam int CAPACITY = {credit_capacity};")
    add(f"  localparam int NEP = {params.endpoint_count};")
    add("  localparam int NO_ENDPOINT = -1;")
    add("  logic clk = 1'b0;")
    add("  always #5 clk = ~clk;")
    add("  logic rst_n = 1'b0;")
    add("  logic [N-1:0] ep_in_valid = '0;")
    add("  logic [N-1:0] ep_in_ready;")
    add("  logic [N-1:0][W-1:0] ep_in_flit = '0;")
    add("  logic [N-1:0] ep_out_valid;")
    add("  logic [N-1:0] ep_out_ready = '1;")
    add("  logic [N-1:0][W-1:0] ep_out_flit;")
    add("  int accepted = 0;")
    add("  int delivered = 0;")
    add("  int mf_delivered = 0;")
    add("  int mf_packets = 0;")
    add("  int mf_injected = 0;")
    add("  bit mf_active = 0;")
    add("  logic [1:0] mf_type_log[0:2];")
    add("  logic [%d - 1:0] mf_vc_log[0:2];" % vc_w)
    add("  // Contention-scenario capture: armed before the contended flits")
    add("  // are injected, so deliveries that land mid-injection are counted.")
    add("  int cap_a, cap_b, cap_alt, cap_last_src;")
    add("  int cap_vc_a, cap_vc_b;")
    add("  int cap_src_a, cap_src_b, cap_dr;")
    add("  bit cap_active = 1'b0;")
    add("  int seq = 0;")
    add("  int last_dst = -1;")
    add("  int last_src = -1;")
    add("  logic [W-1:0] last_flit = '0;")
    add("  int stall_cycles = 0;")
    add("  int routed_local = 0;")
    add("  int routed_same_row = 0;")
    add("  int routed_same_col = 0;")
    add("  int routed_row_then_col = 0;")
    add("  int drained = 0;")
    add("  int over_forwarded = 0;")
    add("  int over_other = 0;")
    add("  int over_injected = 0;")
    add("")
    add("  always @(posedge clk) begin")
    add("    if (cap_active && ep_out_valid[cap_dr] && ep_out_ready[cap_dr]) begin")
    add("      automatic logic [1:0] tp = ep_out_flit[cap_dr][TYPE_LSB +: TYPE_W];")
    add("      if (int'(ep_out_flit[cap_dr][SRC_LSB +: SRC_W]) == cap_src_a) begin")
    add("        if (cap_vc_a < 0) cap_vc_a = int'(ep_out_flit[cap_dr][VC_LSB +: VC_W]);")
    add("        else if (int'(ep_out_flit[cap_dr][VC_LSB +: VC_W]) != cap_vc_a) $fatal(1, \"packet A changed VC mid-flight\");")
    add("        if (tp != ((cap_a == 0) ? FT_HEAD : (cap_a == 1) ? FT_BODY : FT_TAIL))")
    add('          $fatal(1, "packet A order violated at flit %0d", cap_a);')
    add("        cap_a = cap_a + 1;")
    add("        if (cap_last_src == cap_src_b) cap_alt++;")
    add("        cap_last_src = cap_src_a;")
    add("      end else if (int'(ep_out_flit[cap_dr][SRC_LSB +: SRC_W]) == cap_src_b) begin")
    add("        if (cap_vc_b < 0) cap_vc_b = int'(ep_out_flit[cap_dr][VC_LSB +: VC_W]);")
    add("        else if (int'(ep_out_flit[cap_dr][VC_LSB +: VC_W]) != cap_vc_b) $fatal(1, \"packet B changed VC mid-flight\");")
    add("        if (tp != ((cap_b == 0) ? FT_HEAD : (cap_b == 1) ? FT_BODY : FT_TAIL))")
    add('          $fatal(1, "packet B order violated at flit %0d", cap_b);')
    add("        cap_b = cap_b + 1;")
    add("        if (cap_last_src == cap_src_a) cap_alt++;")
    add("        cap_last_src = cap_src_b;")
    add("      end")
    add("    end")
    add("  end")
    add("")
    add("  always @(posedge clk) begin")
    add("    for (int r = 0; r < N; r++) begin")
    add("      if (ep_out_valid[r] && ep_out_ready[r]) begin")
    add("        last_dst = int'(ep_out_flit[r][DEST_LSB +: %d]);" % dest_w)
    add("        last_src = int'(ep_out_flit[r][SRC_LSB +: SRC_W]);")
    add("        last_flit = ep_out_flit[r];")
    add("        if (mf_active && mf_delivered < 3) begin")
    add("          mf_type_log[mf_delivered] = ep_out_flit[r][TYPE_LSB +: TYPE_W];")
    add("          mf_vc_log[mf_delivered] = ep_out_flit[r][VC_LSB +: VC_W];")
    add("          mf_delivered++;")
    add("          if (ep_out_flit[r][TYPE_LSB +: TYPE_W] == FT_TAIL ||")
    add("              ep_out_flit[r][TYPE_LSB +: TYPE_W] == FT_SINGLE) mf_packets++;")
    add("        end else if (!mf_active) delivered++;")
    add("      end")
    add("    end")
    add("  end")
    add("")
    add(f"  {MODULE_NAME} dut (.*);")
    add("")
    add("  // The seat map: an endpoint id names the router that owns it, and")
    add("  // back again.  Without a seat map the endpoints ARE the routers.")
    add("  function automatic int router_of(input int ep);")
    if params.endpoint_mode:
        add("    case (ep)")
        for ep, router in enumerate(params.endpoint_routers):
            add(f"      {ep}: return {router};")
        add("      default: return -1;")
        add("    endcase")
    else:
        add("    return ep;")
    add("  endfunction")
    add("")
    add("  function automatic int endpoint_of(input int router);")
    if params.endpoint_mode:
        add("    case (router)")
        for ep, router in enumerate(params.endpoint_routers):
            add(f"      {router}: return {ep};")
        add("      default: return NO_ENDPOINT;")
        add("    endcase")
    else:
        add("    return router;")
    add("  endfunction")
    add("")
    add("  function automatic logic [W-1:0] make_flit(input int src, input int dst, input int vc, input int typ = 3);")
    add("    logic [W-1:0] value;")
    add("    value = '1;")
    add(f"    value[DEST_LSB +: {dest_w}] = {dest_w}'(dst);")
    add("    value[SRC_LSB +: SRC_W] = SRC_W'(src);")
    add(f"    value[VC_LSB +: {vc_w}] = {vc_w}'(vc);")
    add("    value[TYPE_LSB +: TYPE_W] = TYPE_W'(typ);")
    add("    value[PAYLOAD_LSB +: PAYLOAD_W] = PAYLOAD_W'(64'hd6e8_feb8_6659_fd93 ^ (64'(seq) << 8) ^ 64'(src * 17 + dst));")
    add("    return value;")
    add("  endfunction")
    add("")
    add("  task automatic send_pair(input int src, input int dst);")
    add("    logic [W-1:0] expected;")
    add("    int timeout;")
    add("    int delivered_before;")
    add("    int src_r;")
    add("    int dst_r;")
    add("    src_r = router_of(src);")
    add("    dst_r = router_of(dst);")
    add("    expected = make_flit(src, dst, seq % NUM_VCS);")
    add("    delivered_before = delivered;")
    add("    timeout = 0;")
    add("    @(negedge clk);")
    add("    ep_in_flit[src_r] = expected;")
    add("    ep_in_valid[src_r] = 1'b1;")
    add("    while (!ep_in_ready[src_r]) @(negedge clk);")
    add("    @(posedge clk);")
    add("    if (ep_in_ready[src_r]) accepted++;")
    add("    @(negedge clk);")
    add("    ep_in_valid[src_r] = 1'b0;")
    add("    while (delivered == delivered_before && timeout < 400) begin")
    add("      @(negedge clk);")
    add("      timeout++;")
    add("    end")
    add('    if (delivered == delivered_before) $fatal(1, "timeout waiting for delivery src=%0d dst=%0d", src, dst);')
    add('    if (last_dst != dst) $fatal(1, "wrong destination: expected %0d got %0d", dst, last_dst);')
    add('    if (last_src != src) $fatal(1, "wrong source: expected %0d got %0d", src, last_src);')
    add('    if (!same_flit(last_flit, expected)) $fatal(1, "packet corruption src=%0d dst=%0d got=%h expected=%h", src, dst, last_flit, expected);')
    add("    if (src_r == dst_r) routed_local++;")
    add("    else if ((src_r / K) == (dst_r / K)) routed_same_row++;")
    add("    else if ((src_r % K) == (dst_r % K)) routed_same_col++;")
    add("    else routed_row_then_col++;")
    add("    seq++;")
    add("  endtask")
    add("")
    add("  // Hold a destination backpressured while injecting repeated traffic.")
    add("  // Credits must remain bounded and tap-specific, then fully drain")
    add("  // after the destination is released.  The path is narrow (a")
    add("  // single-entry source port, a two-stage pipe, one single-entry tap),")
    add("  // so it fills before CAPACITY + 2 packets land; the resulting")
    add("  // injection stall IS the backpressure evidence and stops further")
    add("  // injection.  Conservation is asserted afterwards: every accepted")
    add("  // flit is delivered.")
    add("  task automatic oversubscribe(input int src, input int tap_dst, input int other_dst);")
    add("    int cycles;")
    add("    int sent;")
    add("    int stalled;")
    add("    cycles = 0;")
    add("    sent = 0;")
    add("    stalled = 0;")
    add("    @(negedge clk);")
    add("    ep_in_flit[src] = make_flit(endpoint_of(src), endpoint_of(tap_dst), 0);")
    add("    ep_in_valid[src] = 1'b1;")
    add("    while (!ep_in_ready[src] && cycles < 400) begin")
    add("      @(posedge clk);")
    add("      cycles++;")
    add("    end")
    add('    if (!ep_in_ready[src]) $fatal(1, "oversubscribe: initial flit never admitted");')
    add("    @(posedge clk);")
    add("    if (ep_in_ready[src]) accepted++;")
    add("    @(negedge clk);")
    add("    ep_in_valid[src] = 1'b0;")
    add("    cycles = 0;")
    add("    while (int'(dut.row_outstanding[src]) == 0 && cycles < 800) begin")
    add("      @(posedge clk);")
    add("      cycles++;")
    add("    end")
    add("    if (int'(dut.row_outstanding[src]) == 0) $fatal(1, \"no credit was claimed on the wire\");")
    add("    @(negedge clk);")
    add("    ep_out_ready[tap_dst] = 1'b0;")
    add("    while (sent < CAPACITY + 2 && stalled == 0) begin")
    add("      @(negedge clk);")
    add("      ep_in_flit[src] = make_flit(endpoint_of(src), endpoint_of(tap_dst), 0);")
    add("      ep_in_valid[src] = 1'b1;")
    add("      cycles = 0;")
    add("      while (!ep_in_ready[src] && cycles < 200) begin")
    add("        @(posedge clk);")
    add("        cycles++;")
    add("      end")
    add("      if (!ep_in_ready[src]) stalled = 1;")
    add("      else begin")
    add("        @(posedge clk);")
    add("        if (ep_in_ready[src]) accepted++;")
    add("        sent++;")
    add("        over_injected++;")
    add("        @(negedge clk);")
    add("      end")
    add("      ep_in_valid[src] = 1'b0;")
    add("    end")
    add('    if (stalled == 0) $fatal(1, "oversubscribe: the path never applied backpressure");')
    add("    // The allocator rotates VCs, so the bound is per-VC capacity times the VC count.")
    add("    if (int'(dut.row_outstanding[src]) > NUM_VCS * CAPACITY) $fatal(1, \"credit exceeded: outstanding=%0d > capacity %0d\", dut.row_outstanding[src], NUM_VCS * CAPACITY);")
    add("    for (int r = 0; r < N; r++) begin")
    add("      if (dut.row_alias[r] || dut.col_alias[r])")
    add('        $fatal(1, "a credit release was aliased to the wrong tap/VC at router %0d", r);')
    add("    end")
    add("    @(negedge clk);")
    add("    ep_out_ready[tap_dst] = 1'b1;")
    add("    cycles = 0;")
    add("    while (int'(dut.row_outstanding[src]) != 0 && cycles < 600) begin")
    add("      @(posedge clk);")
    add("      cycles++;")
    add("    end")
    add("    if (int'(dut.row_outstanding[src]) != 0) $fatal(1, \"the credit did not come back: outstanding=%0d\", dut.row_outstanding[src]);")
    add("    for (int r = 0; r < N; r++) begin")
    add("      if (dut.row_alias[r] || dut.col_alias[r])")
    add('        $fatal(1, "a credit release was aliased to the wrong tap/VC at router %0d", r);')
    add("    end")
    add("    cycles = 0;")
    add("    while (delivered != accepted && cycles < 2000) begin")
    add("      @(posedge clk);")
    add("      cycles++;")
    add("    end")
    add('    if (delivered != accepted) $fatal(1, "oversubscribe: delivered %0d != accepted %0d", delivered, accepted);')
    add('    $display("PASS gec_mecs16 oversubscribe: backpressure after %0d fill flits, released, drained, delivered=%0d accepted=%0d", sent, delivered, accepted);')
    add("  endtask")
    add("")
    add("  task automatic simultaneous_row_returns(input int src, input int dst_a, input int dst_b);")
    add("    int cycles;")
    add("    int delivered_before;")
    add("    int dst;")
    add("    delivered_before = delivered;")
    add("    ep_out_ready[dst_a] = 1'b0;")
    add("    ep_out_ready[dst_b] = 1'b0;")
    add("    cycles = 0;")
    add("    for (int i = 0; i < 2; i++) begin")
    add("      dst = (i == 0) ? dst_a : dst_b;")
    add("      @(negedge clk);")
    add("      ep_in_flit[src] = make_flit(endpoint_of(src), endpoint_of(dst), 0);")
    add("      ep_in_valid[src] = 1'b1;")
    add("      while (!ep_in_ready[src] && cycles < 800) begin @(posedge clk); cycles++; end")
    add('      if (!ep_in_ready[src]) $fatal(1, "timeout injecting simultaneous-return traffic");')
    add("      @(posedge clk);")
    add("      if (ep_in_ready[src]) accepted++;")
    add("      @(negedge clk);")
    add("      ep_in_valid[src] = 1'b0;")
    add("    end")
    add("    while (int'(dut.row_outstanding[src]) < 2 && cycles < 800) begin @(posedge clk); cycles++; end")
    add('    if (int\'(dut.row_outstanding[src]) < 2) $fatal(1, "both tap credits were not claimed");')
    add("    @(negedge clk);")
    add("    ep_out_ready[dst_a] = 1'b1;")
    add("    ep_out_ready[dst_b] = 1'b1;")
    add("    cycles = 0;")
    add("    while (int'(dut.row_outstanding[src]) != 0 && cycles < 800) begin @(posedge clk); cycles++; end")
    add('    if (int\'(dut.row_outstanding[src]) != 0) $fatal(1, "simultaneous tap returns were lost: outstanding=%0d", dut.row_outstanding[src]);')
    add("    cycles = 0;")
    add("    while (delivered != delivered_before + 2 && cycles < 800) begin @(posedge clk); cycles++; end")
    add('    if (delivered != delivered_before + 2) $fatal(1, "simultaneous-return flits were not both delivered");')
    add("  endtask")
    add("")
    add("  // C4: a HEAD/BODY/TAIL packet on one VC must arrive in order and")
    add("  // produce one packet, not three. The counters are separate from the")
    add("  // single-flit pair count so the C5 conservation numbers stay exact.")
    add("  task automatic send_multiflit(input int src, input int dst, input int vc);")
    add("    int src_r;")
    add("    int dst_r;")
    add("    int timeout;")
    add("    logic [W-1:0] f;")
    add("    src_r = router_of(src);")
    add("    dst_r = router_of(dst);")
    add("    mf_active = 1'b1;")
    add("    mf_delivered = 0;")
    add("    mf_packets = 0;")
    add("    mf_injected = 0;")
    add("    for (int t = 0; t < 3; t++) begin")
    add("      f = make_flit(src, dst, vc, (t == 0) ? FT_HEAD : (t == 1) ? FT_BODY : FT_TAIL);")
    add("      @(negedge clk);")
    add("      ep_in_flit[src_r] = f;")
    add("      ep_in_valid[src_r] = 1'b1;")
    add("      timeout = 0;")
    add("      while (!ep_in_ready[src_r] && timeout < 2000) begin @(posedge clk); timeout++; end")
    add('      if (!ep_in_ready[src_r]) $fatal(1, "multi-flit injection timeout");')
    add("      @(posedge clk);")
    add("      mf_injected++;")
    add("      @(negedge clk);")
    add("      ep_in_valid[src_r] = 1'b0;")
    add("    end")
    add("    timeout = 0;")
    add("    while (mf_delivered < 3 && timeout < 3000) begin @(posedge clk); timeout++; end")
    add('    if (mf_delivered != 3) $fatal(1, "multi-flit delivery timeout: %0d", mf_delivered);')
    add('    if (mf_packets != 1) $fatal(1, "multi-flit packets=%0d expected 1", mf_packets);')
    add('    if (mf_vc_log[0] != mf_vc_log[1] || mf_vc_log[1] != mf_vc_log[2])')
    add('      $fatal(1, "multi-flit packet VC not held HEAD->TAIL: %0d %0d %0d", mf_vc_log[0], mf_vc_log[1], mf_vc_log[2]);')
    add('    if (mf_type_log[0] != FT_HEAD || mf_type_log[1] != FT_BODY || mf_type_log[2] != FT_TAIL)')
    add('      $fatal(1, "multi-flit order: %0d %0d %0d", mf_type_log[0], mf_type_log[1], mf_type_log[2]);')
    add("    mf_active = 1'b0;")
    add('    $display("PASS gec_mecs16 multi_flit: flits=%0d packets=%0d ordered=1", mf_injected, mf_packets);')
    add("  endtask")
    add("")
    add("  task automatic inject_flit(input int r, input logic [W-1:0] f);")
    add("    @(negedge clk);")
    add("    ep_in_flit[r] = f;")
    add("    ep_in_valid[r] = 1'b1;")
    add("    while (!ep_in_ready[r]) @(negedge clk);")
    add("    @(posedge clk);")
    add("    if (ep_in_ready[r]) accepted++;")
    add("    @(negedge clk);")
    add("    ep_in_valid[r] = 1'b0;")
    add("  endtask")
    add("")
    add("  // Two packets contend for one destination.  The fabric assigns")
    add("  // their VCs.  Same VC: the per-VC output lock must serialize them")
    add("  // (exactly one source switch at the destination).  Different VCs:")
    add("  // the lock lets them overlap and delivery may interleave -- per-")
    add("  // source order must survive either way, and every flit keeps the")
    add("  // VC its packet opened with.  The capture always block is armed")
    add("  // before the first flit is injected, so nothing is missed.")
    add("  task automatic send_multiflit_contended(input int src_a, input int src_b, input int dst);")
    add("    int ra, rb, dr, timeout;")
    add("    ra = router_of(src_a); rb = router_of(src_b); dr = router_of(dst);")
    add("    cap_a = 0; cap_b = 0; cap_alt = 0; cap_last_src = -1;")
    add("    cap_vc_a = -1; cap_vc_b = -1;")
    add("    cap_src_a = src_a; cap_src_b = src_b; cap_dr = dr;")
    add("    cap_active = 1'b1;")
    add("    inject_flit(ra, make_flit(src_a, dst, 0, FT_HEAD));")
    add("    inject_flit(ra, make_flit(src_a, dst, 0, FT_BODY));")
    add("    inject_flit(rb, make_flit(src_b, dst, 0, FT_HEAD));")
    add("    inject_flit(ra, make_flit(src_a, dst, 0, FT_TAIL));")
    add("    inject_flit(rb, make_flit(src_b, dst, 0, FT_BODY));")
    add("    inject_flit(rb, make_flit(src_b, dst, 0, FT_TAIL));")
    add("    timeout = 0;")
    add("    while ((cap_a < 3 || cap_b < 3) && timeout < 8000) begin @(posedge clk); timeout++; end")
    add("    cap_active = 1'b0;")
    add('    if (cap_a != 3 || cap_b != 3) $fatal(1, "contended multi-flit timeout: a=%0d b=%0d", cap_a, cap_b);')
    add('    if (cap_alt < 1) $fatal(1, "no source switch at the destination");')
    add('    if (cap_vc_a == cap_vc_b && cap_alt != 1)')
    add('      $fatal(1, "same-VC contended packets interleaved: %0d source switches", cap_alt);')
    add('    $display("PASS gec_mecs16 multi_flit_contention: delivered=%0d source_switches=%0d vc_a=%0d vc_b=%0d", cap_a + cap_b, cap_alt, cap_vc_a, cap_vc_b);')
    add("  endtask")
    add("")

    if admission_scenario:
        add("  // Credit-aware admission: with every first-hop (tap, VC) pool")
        add("  // exhausted, the fabric must withhold ready instead of admitting a")
        add("  // packet that cannot move.  Emitted only for a capacity the")
        add("  // (tap, VC) pools can actually drain to zero; at capacity >=")
        add("  // path depth the gate never fires on this wire model.")
        add("  task automatic credit_admission(input int src, input int dst);")
        add("    int src_r, dst_r, timeout, i;")
        add("    int delivered_before;")
        add("    logic [W-1:0] f;")
        add("    src_r = router_of(src); dst_r = router_of(dst);")
        add("    delivered_before = delivered;")
        add("    ep_out_ready[dst_r] = 1'b0;")
        add("    for (i = 0; i < NUM_VCS * CAPACITY; i = i + 1) begin")
        add("      f = make_flit(src, dst, i % NUM_VCS, FT_SINGLE);")
        add("      @(negedge clk);")
        add("      ep_in_flit[src_r] = f;")
        add("      ep_in_valid[src_r] = 1'b1;")
        add("      timeout = 0;")
        add("      while (!ep_in_ready[src_r] && timeout < 4000) begin @(posedge clk); timeout++; end")
        add('      if (!ep_in_ready[src_r]) $fatal(1, "admission: pre-fill flit %0d never admitted", i);')
        add("      @(posedge clk);")
        add("      if (ep_in_ready[src_r]) accepted++;")
        add("      @(negedge clk);")
        add("      ep_in_valid[src_r] = 1'b0;")
        add("    end")
        add("    // Every first-hop (tap, VC) pool for this path is empty;")
        add("    // one more packet must NOT be admitted.")
        add("    f = make_flit(src, dst, 0, FT_SINGLE);")
        add("    @(negedge clk);")
        add("    ep_in_flit[src_r] = f;")
        add("    ep_in_valid[src_r] = 1'b1;")
        add("    timeout = 0;")
        add("    while (!ep_in_ready[src_r] && timeout < 200) begin @(posedge clk); timeout++; end")
        add('    if (ep_in_ready[src_r]) $fatal(1, "admission: accepted a packet with empty first-hop pools");')
        add("    // Release the endpoint; everything, including the held flit, drains.")
        add("    @(negedge clk);")
        add("    ep_out_ready[dst_r] = 1'b1;")
        add("    timeout = 0;")
        add("    while (!ep_in_ready[src_r] && timeout < 4000) begin @(posedge clk); timeout++; end")
        add('    if (!ep_in_ready[src_r]) $fatal(1, "admission: held flit never admitted after drain");')
        add("    @(posedge clk);")
        add("    if (ep_in_ready[src_r]) accepted++;")
        add("    @(negedge clk);")
        add("    ep_in_valid[src_r] = 1'b0;")
        add("    timeout = 0;")
        add("    while (delivered != delivered_before + NUM_VCS * CAPACITY + 1 && timeout < 8000) begin @(posedge clk); timeout++; end")
        add('    if (delivered != delivered_before + NUM_VCS * CAPACITY + 1) $fatal(1, "admission: delivered=%0d expected=%0d", delivered - delivered_before, NUM_VCS * CAPACITY + 1);')
        add("    if (dut.inject_error_q[src_r] != 32'b0)")
        add('      $fatal(1, "admission: inject_error_q nonzero at router %0d", src_r);')
        add('    $display("PASS gec_mecs16 credit_admission: pools exhausted, admission withheld, drained=%0d", delivered - delivered_before);')
        add("  endtask")
        add("")

    add("  // Reset accounting: a reset in the middle of a packet must leave no")
    add("  // output valid and no stuck lock, and the fabric must carry traffic")
    add("  // again afterwards.  Flits in flight at the reset are discarded; that")
    add("  // is the behaviour under test, so conservation is not asserted across")
    add("  // the reset, only recovery.")
    add("  task automatic reset_recovery(input int src, input int dst);")
    add("    int delivered_before, timeout;")
    add("    inject_flit(router_of(src), make_flit(src, dst, 0, FT_HEAD));")
    add("    @(negedge clk);")
    add("    rst_n = 1'b0;")
    add("    repeat (2) @(posedge clk);")
    add("    @(negedge clk);")
    add("    rst_n = 1'b1;")
    add("    repeat (4) @(posedge clk);")
    add("    for (int r = 0; r < N; r++)")
    add('      if (ep_out_valid[r]) $fatal(1, "reset left an output valid at router %0d", r);')
    add("    delivered_before = delivered;")
    add("    inject_flit(router_of(src), make_flit(src, dst, 0, FT_SINGLE));")
    add("    timeout = 0;")
    add("    while (delivered == delivered_before && timeout < 400) begin @(negedge clk); timeout++; end")
    add('    if (delivered == delivered_before) $fatal(1, "fabric did not recover after reset");')
    add('    if (last_dst != dst) $fatal(1, "post-reset destination: expected %0d got %0d", dst, last_dst);')
    add('    $display("PASS gec_mecs16 reset_recovery: outputs idle after reset, post-reset transfer delivered");')
    add("  endtask")
    add("")
    add("  task automatic hold_destination(input int cycles);")
    add("    @(negedge clk);")
    add("    ep_out_ready = '0;")
    add("    repeat (cycles) @(posedge clk);")
    add("    stall_cycles += cycles;")
    add("    @(negedge clk);")
    add("    ep_out_ready = '1;")
    add("  endtask")
    add("")
    add("  initial begin")
    add("    repeat (4) @(posedge clk);")
    add("    rst_n <= 1'b1;")
    add("    repeat (2) @(posedge clk);")
    add("    hold_destination(12);")
    for src, dst in pairs:
        add(f"    send_pair({src}, {dst});")
    add("    // Credit accounting on a blocked tap: the credits must be taken")
    add("    // on the wire, bounded by the capacity, and returned afterwards.")
    add("    // It runs AFTER the conservation check so the counters above")
    add("    // describe the routed pairs alone.")
    add("    repeat (4) @(posedge clk);")
    add("    drained = (delivered == accepted) ? 1 : 0;")
    add(f'    if (accepted != {total}) $fatal(1, "accepted %0d != {total}", accepted);')
    add('    if (delivered != accepted) $fatal(1, "delivered %0d != accepted %0d", delivered, accepted);')
    add(f'    $display("PASS gec_mecs16 routers=%0d shared_wires=%0d taps_per_wire=%0d all_pairs=%0d accepted=%0d delivered=%0d stall_cycles=%0d drained=%0d", N, N * 2, {params.taps_per_wire}, accepted, accepted, delivered, stall_cycles, drained);')
    add('    $display("PASS gec_mecs16 routing: local=%0d same_row=%0d same_col=%0d row_then_col=%0d", routed_local, routed_same_row, routed_same_col, routed_row_then_col);')
    add("    oversubscribe(%d, %d, %d);" % credit_triple)
    add('    $display("PASS gec_mecs16 credit_accounting: capacity bounded, alias-free, drained");')
    add("    simultaneous_row_returns(%d, %d, %d);" % credit_triple)
    add('    $display("PASS gec_mecs16 simultaneous_row_returns: both tap credits restored");')
    add("    send_multiflit(%d, %d, 0);" % (credit_triple[0], credit_triple[2]))
    # Contention/reset need at least three taps (two competing paths plus
    # the destination). The earlier "packet B order violated at flit 0"
    # reading at the 5-tap 6x6 shape was a testbench capture bug (mid-
    # injection deliveries were missed); with the capture armed before
    # injection the shape passes with per-source order preserved
    # (measured: source_switches=3, vc_a=3, vc_b=1). The 3x3/2-tap shape
    # remains a framing smoke.
    if params.taps_per_wire >= 3:
        add("    send_multiflit_contended(%d, %d, %d);" % (credit_triple[0], credit_triple[1], credit_triple[2]))
        add("    reset_recovery(%d, %d);" % (credit_triple[0], credit_triple[2]))
    if admission_scenario:
        add("    credit_admission(%d, %d);" % (credit_triple[0], credit_triple[2]))
    add('    $display("status: PASS");')
    add("    $finish;")
    add("  end")
    add("")
    add("  initial begin")
    add("    #4000000;")
    add('    $display("FAIL: timeout");')
    add("    $fatal(1);")
    add("  end")
    add("")
    add("endmodule")
    return "\n".join(lines)
