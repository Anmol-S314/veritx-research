"""Multi-seat concentrator wiring for the composed family path.

Two endpoints of the same fabric router cannot share the router's local
injection port: the port is a single driver. The concentrator arbitrates the
seats onto that port and routes the fabric's response back to the seat that
owns it.

The primitive itself is product RTL with its own proven testbench
(`tracks/t3-topology/rtl/multi_seat/seat_concentrator.sv`, gate test
`tests/test_seat_concentrator.py`). It is tagless on purpose: the composed
fabric returns one response per beat and carries no seat identifier, so the
concentrator keeps at most one beat outstanding across all seats. That
serialises seats that could otherwise overlap in flight; per-seat pipelining
would need a seat tag in the flit (a fabric-format change), and is not
claimed here.
"""
from __future__ import annotations

from pathlib import Path

CONCENTRATOR_RELATIVE = Path("tracks/t3-topology/rtl/multi_seat/seat_concentrator.sv")


def render_seat_concentrator(repo_root: str | Path) -> str:
    path = Path(repo_root) / CONCENTRATOR_RELATIVE
    if not path.is_file():
        raise ValueError(
            "UNSUPPORTED: SEAT_CONCENTRATOR_MISSING: "
            + str(CONCENTRATOR_RELATIVE)
            + " is missing, so co-seated endpoints cannot share a router port "
              "(owner stage = RTL generation).")
    return path.read_text()


def seats_by_router(params) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for endpoint_id, _group, _instance, router_id, _port in params.seats:
        out.setdefault(int(router_id), []).append(int(endpoint_id))
    return {router: sorted(endpoints) for router, endpoints in out.items()}


def co_seated_routers(params) -> tuple[int, ...]:
    return tuple(sorted(router for router, endpoints in seats_by_router(params).items()
                        if len(endpoints) > 1))


def render_seat_attachment(params) -> str:
    """Per-seat nets plus one concentrator instance per co-seated router."""
    flit_w = int(getattr(params, "flit_w", 64))
    lines = []
    for router, endpoints in sorted(seats_by_router(params).items()):
        if len(endpoints) < 2:
            continue
        for endpoint in endpoints:
            lines.append("  logic [" + str(flit_w - 1) + ":0] seat_" + str(endpoint) + "_noc_in_flit;")
            lines.append("  logic seat_" + str(endpoint) + "_noc_in_valid, seat_" + str(endpoint) + "_noc_in_ready;")
            lines.append("  logic [" + str(flit_w - 1) + ":0] seat_" + str(endpoint) + "_noc_out_flit;")
            lines.append("  logic seat_" + str(endpoint) + "_noc_out_valid, seat_" + str(endpoint) + "_noc_out_ready;")
        seat_flit = ", ".join("seat_" + str(endpoint) + "_noc_in_flit" for endpoint in endpoints)
        seat_valid = ", ".join("seat_" + str(endpoint) + "_noc_in_valid" for endpoint in endpoints)
        seat_ready = ", ".join("seat_" + str(endpoint) + "_noc_in_ready" for endpoint in endpoints)
        out_flit = ", ".join("seat_" + str(endpoint) + "_noc_out_flit" for endpoint in endpoints)
        out_valid = ", ".join("seat_" + str(endpoint) + "_noc_out_valid" for endpoint in endpoints)
        out_ready = ", ".join("seat_" + str(endpoint) + "_noc_out_ready" for endpoint in endpoints)
        lines.append("  wire [1:0] concentrator_grant_" + str(router) + ";")
        lines.append("  wire concentrator_error_" + str(router) + ";")
        lines.append("  wire unused_concentrator_" + str(router) + " = concentrator_grant_" + str(router) + "[0] ^ concentrator_error_" + str(router) + ";")
        lines.append("  seat_concentrator #(.N_SEATS(" + str(len(endpoints)) + "), .FLIT_W(" + str(flit_w) + ")) u_concentrator_" + str(router) + " (")
        lines.append("    .clk(clk), .rst_n(rst_n),")
        lines.append("    .in_flit({" + seat_flit + "}), .in_valid({" + seat_valid + "}), .in_ready({" + seat_ready + "}),")
        lines.append("    .out_flit(noc_in_flit_" + str(router) + "), .out_valid(noc_in_valid_" + str(router) + "), .out_ready(noc_in_ready_" + str(router) + "),")
        lines.append("    .rsp_flit(noc_out_flit_" + str(router) + "), .rsp_valid(noc_out_valid_" + str(router) + "), .rsp_ready(noc_out_ready_" + str(router) + "),")
        lines.append("    .seat_rsp_flit({" + out_flit + "}), .seat_rsp_valid({" + out_valid + "}), .seat_rsp_ready({" + out_ready + "}),")
        lines.append("    .grant_seat(concentrator_grant_" + str(router) + "), .protocol_error(concentrator_error_" + str(router) + ")")
        lines.append("  );")
    return "\n".join(lines)
