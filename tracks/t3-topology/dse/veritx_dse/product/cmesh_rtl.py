"""Single-flit local endpoint arbitration and ejection for composed tops."""
from __future__ import annotations


def render_cmesh_concentrator() -> str:
    return r'''
module cmesh_concentrator #(
  parameter int W = 64,
  parameter int SEATS = 1,
  parameter int IN_SEATS = SEATS,
  parameter int OUT_SEATS = SEATS,
  parameter int DST_LSB = 0,
  parameter int DST_W = 1,
  parameter logic [OUT_SEATS*DST_W-1:0] ENDPOINT_IDS = '0
) (
  input logic clk, rst_n,
  input logic [IN_SEATS-1:0][W-1:0] seat_in_flit,
  input logic [IN_SEATS-1:0] seat_in_valid,
  output logic [IN_SEATS-1:0] seat_in_ready,
  output logic [W-1:0] noc_in_flit,
  output logic noc_in_valid,
  input logic noc_in_ready,
  input logic [W-1:0] noc_out_flit,
  input logic noc_out_valid,
  output logic noc_out_ready,
  output logic [OUT_SEATS-1:0][W-1:0] seat_out_flit,
  output logic [OUT_SEATS-1:0] seat_out_valid,
  input logic [OUT_SEATS-1:0] seat_out_ready
);
  integer next_q, selected_q, selected;
  logic held_q, found;
  always_comb begin
    selected = selected_q;
    found = held_q;
    for (int offset = 0; offset < IN_SEATS; offset++) begin
      if (!found && seat_in_valid[(next_q + offset) % IN_SEATS]) begin
        selected = (next_q + offset) % IN_SEATS;
        found = 1'b1;
      end
    end
    noc_in_valid = found && seat_in_valid[selected];
    noc_in_flit = seat_in_flit[selected];
    seat_in_ready = '0;
    if (noc_in_valid) seat_in_ready[selected] = noc_in_ready;
    seat_out_valid = '0;
    noc_out_ready = 1'b0;
    for (int seat = 0; seat < OUT_SEATS; seat++) begin
      seat_out_flit[seat] = noc_out_flit;
      if (noc_out_flit[DST_LSB +: DST_W] == ENDPOINT_IDS[seat*DST_W +: DST_W]) begin
        seat_out_valid[seat] = noc_out_valid;
        noc_out_ready = seat_out_ready[seat];
      end
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      next_q <= 0;
      selected_q <= 0;
      held_q <= 1'b0;
    end else if (noc_in_valid) begin
      if (noc_in_ready) begin
        next_q <= (selected + 1) % IN_SEATS;
        held_q <= 1'b0;
      end else begin
        selected_q <= selected;
        held_q <= 1'b1;
      end
    end
  end
endmodule
'''


def render_cmesh_attachment(params) -> str:
    """Wire initiators at ingress routers and responses at egress routers."""
    dst_lsb, dst_width = params.dst_field
    memory_endpoint = next(
        endpoint for endpoint, group, _ix, _router, _port in params.seats
        if group == params.memory_group)
    egress = {endpoint: router for endpoint, _ingress, router
              in params.endpoint_seats}
    injection_router = {
        endpoint: (egress[endpoint] if group == params.memory_group else router)
        for endpoint, group, _ix, router, _port in params.seats
    }
    endpoints = {endpoint for endpoint, *_ in params.seats}
    lines = []
    for endpoint in sorted(endpoints):
        for direction in ("in", "out"):
            lines.append(f"  logic [{params.flit_w - 1}:0] seat_{endpoint}_noc_{direction}_flit;")
            lines.append(f"  logic seat_{endpoint}_noc_{direction}_valid, seat_{endpoint}_noc_{direction}_ready;")
    for router in range(params.n_routers):
        ins = sorted(e for e, r in injection_router.items() if r == router)
        outs = sorted(e for e, r in egress.items() if r == router)
        if not ins and not outs:
            lines.extend((f"  assign noc_in_valid_{router} = 1'b0;",
                          f"  assign noc_in_flit_{router} = '0;",
                          f"  assign noc_out_ready_{router} = 1'b0;",
                          # This router hosts no seat: nothing injects into
                          # it and nothing drains from it, so its local
                          # outputs are consumed by named sinks.
                          f"  wire [{params.flit_w - 1}:0] unused_noc_out_{router} = noc_out_flit_{router};",
                          f"  wire unused_noc_out_valid_{router} = noc_out_valid_{router};",
                          f"  wire unused_noc_in_ready_{router} = noc_in_ready_{router};"))
            continue
        in_count, out_count = max(1, len(ins)), max(1, len(outs))
        ids = ", ".join(f"{dst_width}'d{e}" for e in reversed(outs)) or f"{dst_width}'d{memory_endpoint}"
        if not ins:
            lines.extend((f"  logic [{params.flit_w - 1}:0] unused_in_flit_{router};",
                          f"  logic unused_in_valid_{router}, unused_in_ready_{router};",
                          f"  assign unused_in_flit_{router} = '0;",
                          f"  assign unused_in_valid_{router} = 1'b0;"))
        if not outs:
            lines.extend((f"  logic [{params.flit_w - 1}:0] unused_out_flit_{router};",
                          f"  logic unused_out_valid_{router};"))
        lines.append(f"  cmesh_concentrator #(.W({params.flit_w}), .SEATS({max(in_count, out_count)}),")
        lines.append(f"    .IN_SEATS({in_count}), .OUT_SEATS({out_count}), .DST_LSB({dst_lsb}), .DST_W({dst_width}), .ENDPOINT_IDS({{{ids}}})) u_concentrator_{router} (")
        connections = [".clk(clk)", ".rst_n(rst_n)"]
        in_flits = ", ".join(f"seat_{e}_noc_in_flit" for e in reversed(ins)) or f"{params.flit_w}'d0"
        in_valids = ", ".join(f"seat_{e}_noc_in_valid" for e in reversed(ins)) or "1'b0"
        in_readys = ", ".join(f"seat_{e}_noc_in_ready" for e in reversed(ins)) or f"unused_in_ready_{router}"
        out_flits = ", ".join(f"seat_{e}_noc_out_flit" for e in reversed(outs)) or f"unused_out_flit_{router}"
        out_valids = ", ".join(f"seat_{e}_noc_out_valid" for e in reversed(outs)) or f"unused_out_valid_{router}"
        out_readys = ", ".join(f"seat_{e}_noc_out_ready" for e in reversed(outs)) or "1'b1"
        connections.extend((
            f".seat_in_flit({{{in_flits}}})", f".seat_in_valid({{{in_valids}}})",
            f".seat_in_ready({{{in_readys}}})", f".noc_in_flit(noc_in_flit_{router})",
            f".noc_in_valid(noc_in_valid_{router})", f".noc_in_ready(noc_in_ready_{router})",
            f".noc_out_flit(noc_out_flit_{router})", f".noc_out_valid(noc_out_valid_{router})",
            f".noc_out_ready(noc_out_ready_{router})", f".seat_out_flit({{{out_flits}}})",
            f".seat_out_valid({{{out_valids}}})", f".seat_out_ready({{{out_readys}}})",
        ))
        lines.append("    " + ",\n    ".join(connections))
        lines.append("  );")
    return "\n".join(lines)
