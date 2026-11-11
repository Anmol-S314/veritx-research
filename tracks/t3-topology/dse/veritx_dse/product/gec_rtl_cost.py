"""Structural cost model for the compiled GEC credit-router RTL.

This module answers one question without running a compiler: *why does the
selected 74-endpoint GEC contract fail to elaborate, and how much does the
route interface encoding cost?*

The router's route interface is the dominant term.  For one router:

* ``lanes = inputs * vcs``   (one input queue per input port per VC)
* ``slots = taps.sum * vcs`` (one credit slot per output tap per VC)

The current encoding carries, **per lane**, a ``slots``-wide one-hot legal
mask plus a ``slots``-wide tag vector.  Every router therefore holds
``lanes * slots`` route elements, and the router boundary carries the same
count again as top-level IO.  Three reductions in the router also iterate
``lanes x slots`` (credit reservation, stage reservation and output-lane
selection), even though at most one VC per input port is live at a time.

Measured against the selected 74-endpoint contract (81 routers, 162 shared
wires, 74 endpoints, 8 VCs), the current encoding costs 2,998,768 FIRRTL
reduction nodes and 2,966,784 bits of route-interface IO, against 11,749,120
bits of inherent FIFO storage.  The node count is what exhausts the
elaborator's heap: it is roughly 2.6 million more nodes than the buffering
alone needs, and attempt 4 of the selected-project emit died with sustained
GC at 80-100% before heap exhaustion.

The compacted encoding is exactly equivalent for the compiled contract, which
routes every destination to exactly one slot per VC:

* the route interface carries a slot *index* plus that slot's tag instead of
  a one-hot mask plus a tag vector (30x less route IO and held state);
* the three ``lanes x slots`` reductions reduce over inputs instead of lanes,
  because only the VC selected by the allocator for a given input port can
  hold a grant (8x fewer reduction nodes).

Together these cut the reduction nodes from 2,998,768 to 374,846 and the
route interface from 2,966,784 bits to 97,744 bits, leaving the FIFO storage
untouched.  Raising the heap cap cannot reach that: the cost is structural.

Measured structure
------------------

The model above estimates; the *measured* cost of an emitted design can be
read straight off the FIRRTL IR the Chisel stage writes next to the Verilog.
For the 36-router / 5-VC / 32-endpoint baseline:

* the FIRRTL IR is **302.8 MB of text in 2,174,947 statements**, while the
  Verilog beside it is 25.6 MB.  The IR is what the elaborator holds in
  heap, so it -- not the Verilog -- is the cost that exhausts memory;
* by module family: ``CreditRouter`` x36 = 56.0 %, ``CreditMatch`` x72 =
  34.6 %, ``Queue`` x3952 = 5.8 %, ``CreditOwnership`` x36 = 2.7 %;
* 70.5 % of all statements are primitive ``node`` operations, so the cost is
  node count, not bit width;
* each statement carries a source-location annotation, so a node costs on the
  order of a hundred bytes of text and more in memory.

Measured thresholds on this host (14 GB RAM, ``-Xmx3G``):

* 36 routers (55 slots/router): emits, but spends 85-90 % of its time in GC;
* 49 routers (78 slots/router): ``OutOfMemoryError: Java heap space``;
* 81 routers (128 slots/router): the selected project's shape.  The
  pre-compaction emit died at 6 GiB after 1,634 s.

``measure_firrtl`` below reports the real per-family cost of an emitted
design so a change can be judged against it rather than against an estimate.

Nothing here compiles, simulates or claims a result.  It is a cost estimate
that a reviewer can check by hand against ``CreditRouter.scala``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# Structural lines of a FIRRTL file are not statements.
_STRUCTURAL = frozenset({"module", "endmodule", "extmodule", "circuit",
                          "FIRRTL", "version"})

__all__ = [
    "RouterShape",
    "CostModel",
    "router_shapes",
    "structural_cost",
    "contract_shape",
    "measure_firrtl",
]


@dataclass(frozen=True)
class RouterShape:
    """Per-router structural shape of the compiled credit router."""

    router_id: int
    inputs: int
    taps: int
    outputs: int
    vcs: int

    @property
    def lanes(self) -> int:
        """Input-queue lanes: one per input port per VC."""
        return self.inputs * self.vcs

    @property
    def slots(self) -> int:
        """Credit slots: one per output tap per VC."""
        return self.taps * self.vcs


@dataclass(frozen=True)
class CostModel:
    """Structural cost of one route-interface encoding."""

    encoding: str
    route_io_bits: int = 0
    legal_wire_bits: int = 0
    tags_wire_bits: int = 0
    held_flop_bits: int = 0
    lane_grant_wire_bits: int = 0
    reserved_wire_bits: int = 0
    payload_wire_bits: int = 0
    fifo_flop_bits: int = 0
    queue_modules: int = 0
    reduce_gate_nodes: int = 0
    free_extract_nodes: int = 0
    oh_decode_nodes: int = 0

    @property
    def wire_bits(self) -> int:
        return (self.route_io_bits + self.legal_wire_bits + self.tags_wire_bits
                + self.lane_grant_wire_bits + self.reserved_wire_bits
                + self.payload_wire_bits)

    @property
    def flop_bits(self) -> int:
        return self.held_flop_bits + self.fifo_flop_bits

    @property
    def firrtl_nodes(self) -> int:
        """Approximate FIRRTL node count.

        Wires and registers are nodes; the reduction, slot-extraction and
        one-hot-decode terms are the arithmetic they drive.  This is the
        quantity that exhausts the elaborator's heap, not the bit count.
        """
        return (self.wire_bits + self.flop_bits + self.reduce_gate_nodes
                + self.free_extract_nodes + self.oh_decode_nodes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "encoding": self.encoding,
            "route_io_bits": self.route_io_bits,
            "legal_wire_bits": self.legal_wire_bits,
            "tags_wire_bits": self.tags_wire_bits,
            "held_flop_bits": self.held_flop_bits,
            "lane_grant_wire_bits": self.lane_grant_wire_bits,
            "reserved_wire_bits": self.reserved_wire_bits,
            "payload_wire_bits": self.payload_wire_bits,
            "fifo_flop_bits": self.fifo_flop_bits,
            "wire_bits": self.wire_bits,
            "flop_bits": self.flop_bits,
            "queue_modules": self.queue_modules,
            "reduce_gate_nodes": self.reduce_gate_nodes,
            "free_extract_nodes": self.free_extract_nodes,
            "oh_decode_nodes": self.oh_decode_nodes,
            "firrtl_nodes": self.firrtl_nodes,
        }


def _as_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative int, got {value!r}")
    return value


def router_shapes(*, routers: int, wires: Iterable[tuple[int, list[int]]],
                  endpoints: Iterable[int], vcs: int) -> list[RouterShape]:
    """Derive each router's input/tap counts from the compiled wire table.

    ``wires`` is the compiled ``(src_router, taps)`` table; ``endpoints`` maps
    each endpoint id to the router that owns it.
    """
    routers = _as_int(routers, "routers")
    vcs = _as_int(vcs, "vcs")
    if routers <= 0 or vcs <= 0:
        raise ValueError("routers and vcs must be positive")
    incoming = [0] * routers
    tap_total = [0] * routers
    for src, taps in wires:
        if not 0 <= src < routers:
            raise ValueError(f"wire source {src} outside 0..{routers - 1}")
        tap_total[src] += len(taps)
        for tap in taps:
            if not 0 <= tap < routers:
                raise ValueError(f"wire tap {tap} outside 0..{routers - 1}")
            incoming[tap] += 1
    local = [0] * routers
    for owner in endpoints:
        if not 0 <= owner < routers:
            raise ValueError(f"endpoint owner {owner} outside 0..{routers - 1}")
        local[owner] += 1
    # A router's egress objects are the wires it drives plus the endpoints it
    # owns locally; each becomes one output tap of one credit slot.
    driven = [0] * routers
    for src, taps in wires:
        driven[src] += 1
    return [
        RouterShape(
            router_id=router_id,
            inputs=incoming[router_id] + local[router_id],
            taps=tap_total[router_id] + local[router_id],
            outputs=driven[router_id] + local[router_id],
            vcs=vcs,
        )
        for router_id in range(routers)
    ]


def structural_cost(shapes: Iterable[RouterShape], *, width: int, depth: int,
                    output_depth: int, tag_bits: int,
                    encoding: str) -> CostModel:
    """Cost of one route-interface encoding over every router.

    ``encoding`` is ``"per_slot"`` (the current wide encoding) or
    ``"per_destination"`` (the compacted encoding).
    """
    if encoding not in {"per_slot", "per_destination"}:
        raise ValueError(f"unknown encoding {encoding!r}")
    width = _as_int(width, "width")
    depth = _as_int(depth, "depth")
    output_depth = _as_int(output_depth, "output_depth")
    tag_bits = _as_int(tag_bits, "tag_bits")

    totals = {
        "route_io_bits": 0,
        "legal_wire_bits": 0,
        "tags_wire_bits": 0,
        "held_flop_bits": 0,
        "lane_grant_wire_bits": 0,
        "reserved_wire_bits": 0,
        "payload_wire_bits": 0,
        "fifo_flop_bits": 0,
        "queue_modules": 0,
        "reduce_gate_nodes": 0,
        "free_extract_nodes": 0,
        "oh_decode_nodes": 0,
    }
    slot_bits_cache: dict[int, int] = {}

    def slot_bits(slots: int) -> int:
        if slots not in slot_bits_cache:
            slot_bits_cache[slots] = max(1, (slots - 1).bit_length())
        return slot_bits_cache[slots]

    for shape in shapes:
        lanes = shape.lanes
        slots = shape.slots
        inputs = shape.inputs
        outputs = shape.outputs
        sbits = slot_bits(slots)
        flit_bits = width + max(1, (shape.vcs - 1).bit_length()) + 2 + tag_bits

        if encoding == "per_slot":
            # legal: one-hot over slots; tag: one tag per slot.
            totals["route_io_bits"] += lanes * slots * (1 + tag_bits)
            totals["legal_wire_bits"] += lanes * slots
            totals["tags_wire_bits"] += lanes * slots * tag_bits
            totals["held_flop_bits"] += lanes * slots * (1 + tag_bits)
        else:
            # slot index plus that slot's tag.
            totals["route_io_bits"] += lanes * (sbits + tag_bits)
            totals["legal_wire_bits"] += lanes * sbits
            totals["tags_wire_bits"] += lanes * tag_bits
            totals["held_flop_bits"] += lanes * (sbits + tag_bits)

        totals["lane_grant_wire_bits"] += lanes * slots
        totals["reserved_wire_bits"] += lanes * slots
        totals["payload_wire_bits"] += lanes * flit_bits + slots * flit_bits
        totals["fifo_flop_bits"] += lanes * depth * flit_bits
        totals["queue_modules"] += lanes + slots

        if encoding == "per_slot":
            totals["reduce_gate_nodes"] += slots * lanes      # credit reservation
            totals["reduce_gate_nodes"] += slots * lanes      # stage reservation
            totals["reduce_gate_nodes"] += outputs * lanes    # output lane select
            # The legal mask is a one-hot over slots, so testing it against
            # the free mask is a slots-wide AND plus an OR reduction, and the
            # provider must decode the destination into a one-hot per lane.
            totals["free_extract_nodes"] += lanes * 2 * slots
            totals["oh_decode_nodes"] += lanes * slots
        else:
            # Only the VC chosen by the allocator for an input port can hold a
            # grant, so the reduction is over inputs, not lanes.
            totals["reduce_gate_nodes"] += slots * inputs
            totals["reduce_gate_nodes"] += slots * inputs
            totals["reduce_gate_nodes"] += outputs * inputs
            # The free-slot test becomes one indexed read of the free mask per
            # lane, and the one-hot decode is needed once per input port
            # rather than once per lane.
            totals["free_extract_nodes"] += lanes * slots
            totals["oh_decode_nodes"] += inputs * slots
    return CostModel(encoding=encoding, **totals)


def contract_shape(*, routers: Iterable[Any], shared_links: Iterable[dict],
                   endpoints: Iterable[Any], vc_count: int,
                   endpoint_router_field: str = "router_id") -> list[RouterShape]:
    """Derive router shapes from a compiled revision's topology document."""
    router_list = list(routers)
    router_ids = []
    for entry in router_list:
        router_ids.append(entry["router_id"] if isinstance(entry, dict) else entry)
    count = len(router_ids)
    wires: list[tuple[int, list[int]]] = []
    for link in shared_links:
        src = link["src_router"]
        taps = list(link["taps"])
        wires.append((src, taps))
    owners: list[int] = []
    for endpoint in endpoints:
        if isinstance(endpoint, dict):
            owners.append(endpoint[endpoint_router_field])
        else:
            owners.append(endpoint)
    return router_shapes(routers=count, wires=wires, endpoints=owners,
                         vcs=vc_count)


def measure_firrtl(path: "Path") -> dict[str, Any]:
    """Measure the real cost structure of an emitted FIRRTL IR.

    The Chisel stage writes the IR next to the Verilog.  The IR is what the
    elaborator holds in heap, so its size and statement count are the cost
    that decides whether a design can be emitted at all.

    Returns the total size and statement count, the per-module-family byte
    totals, and the breakdown of primitive statement kinds.
    """
    import collections
    import re

    module_bytes: dict[str, int] = {}
    statement_kinds: collections.Counter[str] = collections.Counter()
    total_bytes = 0
    total_statements = 0
    current: str | None = None
    current_bytes = 0
    module_re = re.compile(r"  module (\w+) :")
    statement_re = re.compile(r"(\w+)")

    with open(path, "r", errors="replace") as handle:
        for line in handle:
            match = module_re.match(line)
            if match:
                if current is not None:
                    module_bytes[current] = current_bytes
                current = match.group(1)
                current_bytes = 0
                continue
            if current is None:
                continue
            current_bytes += len(line)
            total_bytes += len(line)
            stripped = line.strip()
            if stripped and not stripped.startswith("//"):
                kind = statement_re.match(stripped)
                if kind and kind.group(1) not in _STRUCTURAL:
                    statement_kinds[kind.group(1)] += 1
                    total_statements += 1
            if stripped == "endmodule":
                module_bytes[current] = current_bytes
                current = None
    if current is not None:
        module_bytes[current] = current_bytes

    families: collections.Counter[str] = collections.Counter()
    family_counts: collections.Counter[str] = collections.Counter()
    for name, size in module_bytes.items():
        family = re.sub(r"_\d+$", "", name)
        families[family] += size
        family_counts[family] += 1
    return {
        "path": str(path),
        "total_bytes": total_bytes,
        "total_statements": total_statements,
        "module_count": len(module_bytes),
        "families": {
            name: {"bytes": size, "modules": family_counts[name],
                   "share": (size / total_bytes) if total_bytes else 0.0}
            for name, size in families.most_common()
        },
        "statement_kinds": dict(statement_kinds.most_common(16)),
    }
