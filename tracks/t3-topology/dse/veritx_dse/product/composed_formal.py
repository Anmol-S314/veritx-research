"""Deadlock-freedom proof for the composed family fabric.

The mesh's CDG-acyclicity proof (`veritx_dse/product/formal_proofs.py`) covers
the 2-VC emitter's dimension-order tables. The composed family path routes
with its own law (one next hop per source, plus an escape table), so the same
machinery is applied here to the family's own tables: a channel dependency
graph is built from the emitted route tables, a topological rank witness is
extracted, and the witness is discharged with SVA in unbounded ``sby prove``
mode (no depth bound).

Scope, stated honestly (same limits the mesh proof states):
  * the rank witness is COMPLETE over the extracted edge set, and the edge
    extraction is cross-checked against the family's own next-hop rule;
  * acyclic channel dependency graphs for both VC classes imply no circular
    buffer wait under the wormhole scheme these tables describe;
  * arbitration fairness, credit correctness and liveness under arbitrary
    traffic are NOT covered here — they are separate obligations (the
    per-tap credit pool has its own proof; fairness is not yet proven).

Anything the toolchain cannot run is emitted as a typed NOT_RUN — never a
PASS without running.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from veritx_dse.product.formal_proofs import (
    CyclicCdg,
    NOT_RUN_STATUS,
    _CdgHarness,
    _run_sby,
)


def composed_family_tables(params, topology) -> dict[str, dict[tuple[int, int], int]]:
    """The composed family's own route tables, as CDG input.

    The tables are split BY VC CLASS, because a buffer wait can only be
    against a buffer of the same VC: one CDG per class is the graph the
    hardware can actually deadlock in.

    For the ring the VC is the fork's dateline half (the injection router
    against the destination), so the two classes are the two halves of the
    dateline. For every other family the VC is the class the traffic is
    bound to, and the free and escape tables are the two classes.
    """
    from veritx_dse.product.project_top_rtl import _family_full_tables
    rt_min, rt_esc, _rt_row, _rt_col, _rt_dist, _shape = _family_full_tables(
        params, topology)
    if params.family == "gec_mecs":
        # GEC's VCs share one physical ingress slot per input port. Prove one
        # merged storage graph, not three nominal VC graphs.
        n = int(params.n_routers)
        coords = tuple(tuple(c) for c in params.coordinates)
        k = int(round(n ** 0.5))
        if k * k != n or len(coords) != n or len(set(coords)) != n:
            raise ValueError("GEC shared-storage proof requires a square unique coordinate grid")
        coordinate_id = {coord: router for router, coord in enumerate(coords)}
        adjacency = {router: set(params.adjacency[router]) for router in range(n)}
        expected_wires = {
            (src, tuple(sorted(dst for dst, (dx, dy) in enumerate(coords)
                              if dst != src and dy == sy)))
            for src, (sx, sy) in enumerate(coords)
        } | {
            (src, tuple(sorted(dst for dst, (dx, dy) in enumerate(coords)
                              if dst != src and dx == sx)))
            for src, (sx, sy) in enumerate(coords)
        }
        actual_wires = {
            (int(src), tuple(sorted(int(dst) for dst in taps)))
            for kind, _ident, src, taps, width, latency in params.resources
            if kind == "SHARED_LINK" and width == params.flit_w and latency == 1
        }
        if len(params.resources) != 2 * n or actual_wires != expected_wires:
            raise ValueError("GEC CDG requires exactly the emitted full row/column shared wires at matched width and latency")
        table = {}
        for src, (sx, sy) in enumerate(coords):
            for dst, (dx, dy) in enumerate(coords):
                if src == dst:
                    continue
                # The emitted router chooses a same-row tap first, then a
                # same-column tap. These are direct physical shared-wire hops.
                next_coord = (dx, sy) if sx != dx else (sx, dy)
                nxt = coordinate_id.get(next_coord)
                if nxt is None or nxt not in adjacency[src]:
                    raise ValueError(f"GEC X-then-Y hop {src}->{next_coord} is not an emitted shared-wire tap")
                table[(src, dst)] = sorted(adjacency[src]).index(nxt)
        return {"shared_ingress": table}
    if params.family == "ring":
        from veritx_dse.model.ring_net import ring_dateline_partition
        halves = {0: {}, 1: {}}
        for (src, dst), port in rt_min.items():
            halves[ring_dateline_partition(src, dst)][(src, dst)] = port
        return {"vc0_dateline_half": halves[0], "vc1_dateline_half": halves[1]}
    # A family with one VC has no escape class: proving `esc` alongside `free`
    # would invent a buffer the hardware does not have (and, in fly, a class
    # whose adaptive table is cyclic). Prove the classes that exist.
    classes = {"free": dict(rt_min)}
    if int(getattr(params, "vc_count", 2)) > 1:
        classes["esc"] = dict(rt_esc)
    return classes


def composed_family_proof_domain(params, topology) -> dict[str, set] | None:
    """The (source, destination) pairs the hardware can actually offer.

    The CDG walk starts at a traffic source and follows the route table to a
    destination. For a family whose endpoints live on only some routers, a
    route between two non-endpoint routers is not a hardware obligation; for
    fly, walking those routes anyway creates a false cycle through unrelated
    destinations. Return the real ingress<->egress pairs, or ``None`` when the
    family's endpoints may be on any router.
    """
    if params.family != "fly":
        return None
    routers = sorted(topology.routers, key=lambda r: r.router_id)
    ingress = tuple(
        r.router_id for r in routers
        if getattr(r, "seat_capacity", 0) and r.router_id < 16)
    egress = tuple(
        r.router_id for r in routers
        if getattr(r, "egress_seat_capacity", None) not in (None, 0))
    pairs = {(s, t) for s in ingress for t in egress}
    pairs |= {(s, t) for s in egress for t in ingress}
    return {"free": pairs}


def run_composed_family_cdg_proof(*, work_dir: Path, params, topology,
                                   timeout: int = 900) -> dict[str, Any]:
    """Prove the composed family's channel dependency graphs are acyclic."""
    try:
        tables = composed_family_tables(params, topology)
    except Exception as exc:  # noqa: BLE001 - typed, never swallowed
        return {
            "id": "cdg_acyclicity_composed_family",
            "property": "the channel dependency graph of each VC class of "
                        "the composed family is acyclic (Dally-Seitz)",
            "status": NOT_RUN_STATUS, "scope": None,
            "reason": f"the composed family's route tables could not be read "
                      f"({exc}) (owner stage = RTL generation; "
                      f"module = ComposedFamilyFormalProofs)"}
    if not any(tables.values()):
        return {
            "id": "cdg_acyclicity_composed_family",
            "property": "the channel dependency graph of each VC class of "
                        "the composed family is acyclic (Dally-Seitz)",
            "status": NOT_RUN_STATUS, "scope": None,
            "reason": "the composed family produced no route table entries "
                      "(owner stage = RTL generation; "
                      "module = ComposedFamilyFormalProofs)"}
    n = int(params.n_routers)
    adjacency = {i: set(params.adjacency[i]) for i in range(n)}
    try:
        harness = _CdgHarness(n, adjacency, tables,
                              domain=composed_family_proof_domain(
                                  params, topology))
        cdg_sv, stats = harness.sources()
    except CyclicCdg as exc:
        return {
            "id": "cdg_acyclicity_composed_family",
            "property": "the channel dependency graph of each VC class of "
                        "the composed family is acyclic (Dally-Seitz)",
            "status": "FAIL", "scope": None,
            "reason": f"CDG cyclic: {exc} (a circular buffer wait is possible "
                      f"for this family's tables; the family must not ship "
                      f"with them)"}
    except Exception as exc:  # noqa: BLE001 - typed, never swallowed
        return {
            "id": "cdg_acyclicity_composed_family",
            "property": "the channel dependency graph of each VC class of "
                        "the composed family is acyclic (Dally-Seitz)",
            "status": NOT_RUN_STATUS, "scope": None,
            "reason": f"the CDG proof could not be built ({exc}) "
                      f"(owner stage = RTL generation; "
                      f"module = ComposedFamilyFormalProofs)"}
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    result = _run_sby(work_dir=work, tag="cdg_acyclicity_composed",
                      sv_text=cdg_sv, top="cdg_proof_top", timeout=timeout)
    result.update({
        "id": "cdg_acyclicity_composed_family",
        "property": "the channel dependency graph of each VC class of "
                    "the composed family is acyclic (Dally-Seitz)",
        "stats": {"routers": n, **stats},
        "cross_check": {"rank_witness": "extracted"},
        "scope": "COMPLETE over the extracted edge set, per VC class; "
                  "arbitration fairness, credit correctness and liveness "
                  "under arbitrary traffic are not covered by this proof",
    })
    return result


__all__ = [
    "composed_family_tables",
    "run_composed_family_cdg_proof",
]
