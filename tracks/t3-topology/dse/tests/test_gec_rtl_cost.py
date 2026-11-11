"""The GEC credit-router cost model must predict the elaboration blowup.

These tests pin the structural claim that the selected 74-endpoint GEC
contract's elaboration cost is dominated by the per-lane x per-slot route
interface, and that the compacted encoding is strictly smaller.

The selected contract is a 9x9 GEC-MECS mesh: 81 routers, 162 shared wires
(2 per router, 8 taps each), 74 endpoints, 8 VCs.  The test rebuilds that
shape from first principles so it does not depend on untracked run data, and
cross-checks it against the pinned revision when that artifact is present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veritx_dse.product.gec_rtl_cost import (
    contract_shape,
    router_shapes,
    structural_cost,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SELECTED_REVISION = (REPO_ROOT / "runs/studio-store/projects/projects"
                     / "p-fd7e5e31be77/revisions/p-fd7e5e31be77-r02.json")

SELECTED_ROUTERS = 81
SELECTED_VCS = 8
SELECTED_ENDPOINTS = 74
SELECTED_WIRE_TAPS = 8
SELECTED_GRID = 9


def selected_mesh() -> tuple[list[tuple[int, list[int]]], list[int]]:
    """The 9x9 GEC-MECS wire table and endpoint owners of the pinned shape.

    Each router drives one wire along its row and one along its column; each
    wire taps the other eight routers of that row/column.
    """
    wires: list[tuple[int, list[int]]] = []
    for router in range(SELECTED_ROUTERS):
        row, col = divmod(router, SELECTED_GRID)
        row_taps = [r * SELECTED_GRID + col
                    for c in range(SELECTED_GRID) if c != col
                    for r in [row]]
        col_taps = [r * SELECTED_GRID + col
                    for r in range(SELECTED_GRID) if r != row]
        wires.append((router, row_taps))
        wires.append((router, col_taps))
    owners = list(range(SELECTED_ENDPOINTS))
    return wires, owners


def selected_shape():
    wires, owners = selected_mesh()
    return router_shapes(routers=SELECTED_ROUTERS, wires=wires,
                         endpoints=owners, vcs=SELECTED_VCS)


def test_selected_shape_matches_the_compiled_contract():
    shapes = selected_shape()
    assert len(shapes) == SELECTED_ROUTERS
    assert sum(s.inputs for s in shapes) == 1370
    assert sum(s.slots for s in shapes) == 10960
    assert sum(s.lanes for s in shapes) == 10960


def test_synthetic_shape_matches_the_pinned_revision():
    """When the pinned artifact exists, the rebuilt shape must equal it."""
    if not SELECTED_REVISION.exists():
        pytest.skip("the pinned selected revision is not in this checkout")
    topology = json.loads(SELECTED_REVISION.read_text())["topology"]
    owners = [e["router_id"] for e in topology["endpoints"]]
    from_revision = contract_shape(routers=topology["routers"],
                                   shared_links=topology["shared_links"],
                                   endpoints=owners,
                                   vc_count=SELECTED_VCS)
    assert from_revision == selected_shape()


def test_route_interface_dominates_the_current_encoding():
    shapes = selected_shape()
    current = structural_cost(shapes, width=128, depth=8, output_depth=1,
                              tag_bits=1, encoding="per_slot")
    # The lane x slot reductions are the dominant FIRRTL node term: they are
    # what actually exhausts the elaborator's heap, not the bit counts.
    assert current.reduce_gate_nodes > 2_000_000
    # The route interface is the dominant interface term, and it is pure
    # overhead: the route table already resolves each destination to exactly
    # one slot per VC.
    assert current.route_io_bits > current.lane_grant_wire_bits
    assert current.route_io_bits > current.reserved_wire_bits
    assert current.route_io_bits > current.payload_wire_bits


def test_compacted_encoding_is_strictly_and_materially_smaller():
    shapes = selected_shape()
    current = structural_cost(shapes, width=128, depth=8, output_depth=1,
                              tag_bits=1, encoding="per_slot")
    compacted = structural_cost(shapes, width=128, depth=8, output_depth=1,
                                tag_bits=1, encoding="per_destination")
    assert compacted.route_io_bits * 10 < current.route_io_bits
    assert compacted.held_flop_bits * 10 < current.held_flop_bits
    assert compacted.reduce_gate_nodes * 2 < current.reduce_gate_nodes
    # The FIFO storage is unchanged: the fix removes interface width, not
    # buffering.  The model must not overstate the win.
    assert compacted.fifo_flop_bits == current.fifo_flop_bits
    assert compacted.queue_modules == current.queue_modules


def test_cost_scales_faster_than_router_count():
    """The blowup is superlinear in routers because slots also grow."""
    small = router_shapes(routers=36,
                          wires=[(r, [(r + 1 + k) % 36 for k in range(5)])
                                 for r in range(36)],
                          endpoints=range(32), vcs=5)
    large = selected_shape()
    small_cost = structural_cost(small, width=128, depth=8, output_depth=1,
                                 tag_bits=1, encoding="per_slot")
    large_cost = structural_cost(large, width=128, depth=8, output_depth=1,
                                 tag_bits=1, encoding="per_slot")
    router_ratio = len(large) / len(small)
    assert large_cost.route_io_bits / small_cost.route_io_bits > router_ratio


def test_model_rejects_a_bad_contract():
    with pytest.raises(ValueError):
        router_shapes(routers=4, wires=[(9, [0])], endpoints=[0], vcs=2)
    with pytest.raises(ValueError):
        router_shapes(routers=4, wires=[(0, [7])], endpoints=[0], vcs=2)
    with pytest.raises(ValueError):
        router_shapes(routers=4, wires=[(0, [1])], endpoints=[0], vcs=0)
    with pytest.raises(ValueError):
        structural_cost([], width=128, depth=8, output_depth=1, tag_bits=1,
                        encoding="nonsense")


def test_measure_firrtl_reports_the_real_cost_structure(tmp_path):
    """The measurement must read the IR, not estimate it."""
    from veritx_dse.product.gec_rtl_cost import measure_firrtl
    fir = tmp_path / "Design.fir"
    fir.write_text(
        "FIRRTL version 1.2.0\n"
        "circuit Design :\n"
        "  module CreditRouter :\n"
        "    input clock : Clock\n"
        "    node a = UInt<1>(0)\n"
        "    node b = UInt<1>(0)\n"
        "  endmodule\n"
        "  module CreditRouter_1 :\n"
        "    node c = UInt<1>(0)\n"
        "  endmodule\n"
        "  module Queue :\n"
        "    node d = UInt<1>(0)\n"
        "  endmodule\n")
    report = measure_firrtl(fir)
    assert report["module_count"] == 3
    assert report["families"]["CreditRouter"]["modules"] == 2
    assert report["families"]["Queue"]["modules"] == 1
    # Structural lines are not statements; the one clock input is.
    assert report["statement_kinds"]["node"] == 4
    assert report["statement_kinds"]["input"] == 1
    assert report["total_statements"] == 5
    assert report["families"]["CreditRouter"]["share"] > 0.5
