"""formal_proofs — sby (Yosys + z3) proofs for M1 and the 2-VC mesh.

Two complete (unbounded, ``sby prove`` mode) proof obligations over real
emitted artifacts:

* M1 address-decode exclusivity. The emitted ``addr_decode.sv``
  (``render_addr_decode``) computes ``overlap = (hit_count > 1)``; the
  property proved is ``!overlap`` for every 64-bit address, i.e. at most
  one range hits at a time. Combinational and unbounded, so the result
  scope is COMPLETE. A map whose ranges overlap is a real FAIL
  (counterexample), never a faked PASS.

* 2-VC mesh deadlock-freedom via CDG acyclicity. For the emitter's own
  free (dim-order/up-down) and escape (tree) route tables on the mesh
  anynet, the channel dependency graph is built with the same edge rules
  as the emitter's ``cdg_has_cycle``; a topological rank witness
  (channel -> strictly increasing rank along every dependency edge) is
  extracted in Python and checked by SVA assertions in ``sby prove``
  mode. Hardest part honestly labelled: the rank witness is COMPLETE
  for the emitted edge set, but edge extraction itself is Python, so
  the scope is COMPLETE-over-the-edge-set with a Python cross-check
  (``cdg_has_cycle`` must agree). Under Dally-Seitz, acyclic CDGs for
  both VC classes imply no circular buffer wait under the certified
  2-VC wormhole scheme; arbitration fairness, credit correctness and
  liveness under arbitrary traffic patterns are outside this proof.

Nothing here claims a bounded result: every PASS below is a complete
``prove`` (no depth bound). Anything sby/yosys/z3 cannot run, times
out on, or rejects is emitted as a typed NOT_RUN with the harness
reason (never PASS without running).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any

#: Proof result scopes. COMPLETE means an unbounded `sby prove` discharged
#: every assertion. No bounded scope is used: a bounded run would be
#: labelled BOUNDED and rooted at BMC depth, but the tractable proofs
#: here are small enough to complete.
COMPLETE_SCOPE = "COMPLETE"
BOUNDED_SCOPE = "BOUNDED"  # reserved; unused results are never labelled COMPLETE
NOT_RUN_STATUS = "NOT_RUN"

#: Formal tools the proofs need (owner stage = RTL generation).
REQUIRED_TOOLS = ("sby", "yosys", "z3")

# sby status lines: "DONE (PASS, rc=0)" / "DONE (FAIL, rc=2)" / errors rc>2.
_SBY_DONE_RE = re.compile(r"DONE \((PASS|FAIL|ERROR), rc=(\d+)\)")


def _emitter_seam() -> Any | None:
    """Import the gen_rtl seam (route tables + CDG helpers) without editing it.

    Read-only import of ``tracks/t3-topology/scripts/rtlgen/gen_rtl.py`` so
    the proof covers the emitter's own tables, not a reimplementation.
    """
    # Resolve relative to this file: <dse>/veritx_dse/product/formal_proofs.py
    dse_root = Path(__file__).resolve().parents[2]
    rtlgen = dse_root.parent / "scripts" / "rtlgen"
    if rtlgen.is_dir() and str(rtlgen) not in sys.path:
        sys.path.insert(0, str(rtlgen))
    try:
        import gen_rtl  # type: ignore
    except Exception:  # noqa: BLE001 - seam unavailable is a typed NOT_RUN
        return None
    return gen_rtl


def cdg_edges(n: int, adj: dict[int, set[int]],
              tbl: dict[tuple[int, int], int],
              pairs: set[tuple[int, int]] | None = None
              ) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """CDG edges with the emitter's rules (same as ``cdg_has_cycle``).

    Nodes are directed channels ``(prev, cur)``; an edge
    ``(prev, cur) -> (cur, nxt)`` exists when a route takes consecutive
    hops ``prev->cur`` then ``cur->nxt``. Returns sorted unique edges.

    ``pairs`` restricts the *starting* (source, destination) pairs. The walk
    still reads the whole table for intermediate hops — restricting the table
    itself would stop every route after its first hop.
    """
    alist = {i: sorted(adj[i]) for i in range(n)}
    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    starts = (pairs if pairs is not None
              else ((s, d) for s in range(n) for d in range(n)))
    for src, dst in starts:
        if dst == src:
            continue
        cur = src
        prev = None
        for _ in range(4 * n):
            port = tbl.get((cur, dst))
            if port is None:
                break
            nxt = alist[cur][port]
            if prev is not None:
                edges.add(((prev, cur), (cur, nxt)))
            prev, cur = cur, nxt
            if cur == dst:
                break
    return sorted(edges)


def topo_ranks(edges: list[tuple[tuple[int, int], tuple[int, int]]]
               ) -> dict[tuple[int, int], int] | None:
    """Kahn topological ranks; ``None`` when the CDG is cyclic.

    Ranks are pop-order indices, so ``rank[u] < rank[v]`` for every edge
    ``u -> v`` whenever the graph is acyclic.
    """
    nodes = sorted({node for edge in edges for node in edge})
    indegree = {node: 0 for node in nodes}
    successors: dict[tuple[int, int], list[tuple[int, int]]] = {
        node: [] for node in nodes}
    for u, v in edges:
        successors[u].append(v)
        indegree[v] += 1
    queue: deque[tuple[int, int]] = deque(
        sorted(node for node in nodes if indegree[node] == 0))
    rank: dict[tuple[int, int], int] = {}
    counter = 0
    while queue:
        node = queue.popleft()
        rank[node] = counter
        counter += 1
        for nxt in sorted(successors[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(rank) != len(nodes):
        return None  # cyclic: nodes never reached
    return rank


def render_cdg_sv(n: int, adj: dict[int, set[int]],
                  tables: dict[str, dict[tuple[int, int], int]]) -> str:
    """Render the checking module; raises :class:`CyclicCdg` when cyclic."""
    harness = _CdgHarness(n, adj, tables)
    return harness.sources()[0]


class CyclicCdg(ValueError):
    """The CDG has no topological rank (proof obligation FAIL)."""


class _CdgHarness:
    """Pure CDG edge/rank machinery shared by renderers and tests."""

    def __init__(self, n: int, adj: dict[int, set[int]],
                 tables: dict[str, dict[tuple[int, int], int]],
                 domain: dict[str, set[tuple[int, int]]] | None = None):
        if not isinstance(n, int) or n < 1:
            raise ValueError("n must be a positive int")
        if not tables:
            raise ValueError("route tables must be a non-empty mapping")
        self.n = n
        self.adj = {int(k): set(int(x) for x in v) for k, v in adj.items()}
        self.tables = {str(k): dict(v) for k, v in tables.items()}
        self.domain = {str(k): set(v) for k, v in (domain or {}).items()}
        self._edges: dict[str, list] = {}
        self._ranks: dict[str, dict | None] = {}
        for label, tbl in self.tables.items():
            edges = cdg_edges(n, self.adj, tbl, self.domain.get(label))
            self._edges[label] = edges
            self._ranks[label] = topo_ranks(edges)

    def cyclic_classes(self) -> list[str]:
        return sorted(label for label, rank in self._ranks.items()
                      if rank is None)

    def sources(self) -> tuple[str, dict[str, Any]]:
        cyclic = self.cyclic_classes()
        if cyclic:
            raise CyclicCdg(
                f"CDG cyclic for {cyclic}: no topological rank exists")
        lines = [
            "// Generated by formal_proofs: CDG acyclicity witnesses.",
            "// Each dependency edge must strictly increase the channel rank",
            "// (Dally-Seitz): a rank satisfying every edge cannot wrap a cycle.",
            "`default_nettype none",
            "module cdg_proof_top ( input logic [0:0] dummy );",
        ]
        stats: dict[str, Any] = {}
        for label in sorted(self.tables):
            rank = self._ranks[label] or {}
            edges = self._edges[label]
            stats[label] = {"edges": len(edges), "channels": len(rank)}
            lines.append(f"  // class {label}: {len(edges)} dependency edges, "
                         f"{len(rank)} channels")
            lines.extend([
                f"  function [31:0] {label}_rank;",
                "    input [31:0] idx;",
                "    begin",
                "      case (idx)",
            ])
            for (a, b) in sorted(rank):
                lines.append(
                    f"        {a * self.n + b}: {label}_rank = {rank[(a, b)]};")
            lines.extend([
                f"        default: {label}_rank = 0;",
                "      endcase",
                "    end",
                "  endfunction",
                "  always @* begin",
            ])
            for (u, v) in edges:
                lines.append(
                    f"    assert({label}_rank({u[0] * self.n + u[1]}) "
                    f"< {label}_rank({v[0] * self.n + v[1]}));")
            lines.append("  end")
        lines.extend(["endmodule", "`default_nettype wire", ""])
        return "\n".join(lines), stats


def render_m1_exclusivity_sv(decode: Any, windows: Any = ()) -> str:
    """Wrap the emitted decoder with the M1 exclusivity assertions.

    The wrapper drives one free 64-bit address, so the unbounded prove
    quantifies over the whole address space (COMPLETE scope).
    """
    from veritx_dse.product.addr_decode_rtl import render_addr_decode
    body = render_addr_decode(decode, module="addr_decode", windows=windows)
    # target_oh width is an emit-time constant; read it off the emission.
    match = re.search(r"parameter int N_ENDPOINTS = (\d+)", body)
    n_endpoints = max(1, int(match.group(1)) if match else 1)
    wrapper = [
        "`default_nettype none",
        "module m1_exclusivity_top (",
        "  input  logic [63:0] addr,",
    ]
    if windows:
        wrapper.append("  input  logic req_write,")
    wrapper.extend([
        "  output logic top_overlap",
        ");",
        "  logic hit_w, miss_w, overlap_w;",
    ])
    if windows:
        wrapper.append("  logic allow_w, perm_violation_w;")
    wrapper.append(f"  logic [{n_endpoints - 1}:0] target_oh_w;")
    if windows:
        wrapper.append(
            "  addr_decode dut (.addr(addr), .req_write(req_write), "
            ".target_oh(target_oh_w), .hit(hit_w), .miss(miss_w), "
            ".overlap(overlap_w), .allow(allow_w), "
            ".perm_violation(perm_violation_w));")
        wrapper.extend([
            "  assign top_overlap = overlap_w;",
            "  // M1 exclusivity: at most one entry may hit (ranges disjoint).",
            "  always @* assert(!overlap_w);",
            "  // Permission firewall: denied hit <=> violation.",
            "  always @* assert(hit_w == !miss_w);",
            "  always @* assert(perm_violation_w == (hit_w && !allow_w));",
        ])
    else:
        wrapper.append(
            "  addr_decode dut (.addr(addr), .target_oh(target_oh_w), "
            ".hit(hit_w), .miss(miss_w), .overlap(overlap_w));")
        wrapper.extend([
            "  assign top_overlap = overlap_w;",
            "  // M1 exclusivity: at most one entry may hit (ranges disjoint).",
            "  always @* assert(!overlap_w);",
            "  // hit/miss complement sanity.",
            "  always @* assert(hit_w == !miss_w);",
        ])
    wrapper.extend(["endmodule", "`default_nettype wire", ""])
    return body + "\n" + "\n".join(wrapper)


def _sby_available() -> tuple[bool, str | None]:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        return False, "formal harness unavailable: missing " + ", ".join(
            missing) + " (owner stage = RTL generation; module = FormalProofs)"
    return True, None


def _run_sby(*, work_dir: Path, tag: str, sv_text: str, top: str,
             timeout: int) -> dict[str, Any]:
    """Run one sby prove task; returns the typed sub-result (never guessed)."""
    job_dir = Path(work_dir) / tag
    job_dir.mkdir(parents=True, exist_ok=True)
    sv_name = f"{tag}.sv"
    (job_dir / sv_name).write_text(sv_text)
    sby_text = (
        "[options]\nmode prove\nmulticlock off\n\n"
        "[engines]\nsmtbmc z3\n\n"
        "[script]\n"
        f"read -formal {sv_name}\nprep -top {top}\n\n"
        f"[files]\n{sv_name}\n\n[tasks]\nprove\n"
    )
    (job_dir / f"{tag}.sby").write_text(sby_text)
    try:
        proc = subprocess.run(
            ["sby", "-f", f"{tag}.sby", "prove"],
            cwd=job_dir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": NOT_RUN_STATUS, "scope": None,
                "reason": f"sby timed out after {timeout}s on {tag} "
                          "(owner stage = RTL generation; module = FormalProofs)"}
    output = (proc.stdout or "") + (proc.stderr or "")
    match = _SBY_DONE_RE.search(output)
    if match is None:
        return {"status": NOT_RUN_STATUS, "scope": None,
                "reason": f"sby did not return a DONE status on {tag} "
                          f"(rc={proc.returncode}; tail: {output[-600:]}) "
                          "(owner stage = RTL generation; module = FormalProofs)"}
    verdict, _rc = match.group(1), match.group(2)
    if verdict == "PASS":
        return {"status": "PASS", "scope": COMPLETE_SCOPE,
                "reason": f"sby prove passed all assertions on {tag} "
                          "(unbounded; no depth bound applied)"}
    if verdict == "FAIL":
        return {"status": "FAIL", "scope": COMPLETE_SCOPE,
                "reason": f"sby prove found a counterexample on {tag} "
                          "(property refuted; see sby trace artifacts in "
                          f"{job_dir})"}
    return {"status": NOT_RUN_STATUS, "scope": None,
            "reason": f"sby returned ERROR on {tag} (tail: {output[-600:]}) "
                      "(owner stage = RTL generation; module = FormalProofs)"}


def run_decode_exclusivity_proof(*, work_dir: Path, decode: Any,
                                windows: Any = (),
                                timeout: int = 300) -> dict[str, Any]:
    """Unbounded proof of the emitted decoder's exclusive/permission contract."""
    ok, unavailable = _sby_available()
    if not ok:
        return {"status": NOT_RUN_STATUS, "scope": None,
                "reason": unavailable,
                "id": "m1_address_decode_exclusivity"}
    try:
        sv_text = render_m1_exclusivity_sv(decode, windows=windows)
    except ValueError as exc:
        return {"status": "FAIL", "scope": None,
                "reason": f"M1 proof harness refused the artifact: {exc}",
                "id": "m1_address_decode_exclusivity"}
    result = _run_sby(work_dir=Path(work_dir), tag="m1_exclusivity",
                      sv_text=sv_text, top="m1_exclusivity_top",
                      timeout=timeout)
    result.update({"id": "m1_address_decode_exclusivity",
                  "property": "at most one decoder entry hits per address, "
                              "with hit/miss and permission-firewall consistency"})
    return result


def run_formal_proofs(*, work_dir: Path, decode: Any = None,
                      windows: Any = (), anynet_text: str | None = None,
                      timeout: int = 300) -> dict[str, Any]:
    """Run the M1 + CDG proofs; returns the formal manifest.

    ``decode`` is an ``AddressDecodeArtifact`` (duck-typed). ``anynet_text``
    defaults to the 4x4 mesh. Any missing tool yields a typed NOT_RUN.
    """
    ok, unavailable = _sby_available()
    if not ok:
        return {"status": NOT_RUN_STATUS, "code": "FORMAL_HARNESS_UNAVAILABLE",
                "reason": unavailable, "proofs": []}
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    proofs: list[dict[str, Any]] = []

    # ---- M1: address-decode exclusivity over the emitted decoder ----
    if decode is None:
        from veritx_dse.model.address_decode import (
            AddressDecodeArtifact, AddressDecodeEntry, AddressTransform,
            UnmatchedAddressPolicy,
        )
        decode = AddressDecodeArtifact(
            attachment_hash="a" * 64,
            entries=(
                AddressDecodeEntry(name="HBM0", base=0x1000, size=0x1000,
                                   target_agent_group=0,
                                   target_endpoint_id=0),
                AddressDecodeEntry(name="KV", base=0x8000_0000, size=0x4000,
                                   target_agent_group=0,
                                   target_endpoint_id=1),
            ),
            address_transform=AddressTransform.IDENTITY,
            unmatched_address_policy=UnmatchedAddressPolicy.ERROR,
            schema_version=3)
    try:
        m1_sv = render_m1_exclusivity_sv(decode, windows=windows)
        m1 = _run_sby(work_dir=work, tag="m1_exclusivity", sv_text=m1_sv,
                      top="m1_exclusivity_top", timeout=timeout)
    except ValueError as exc:
        m1 = {"status": "FAIL", "scope": None,
              "reason": f"M1 proof harness refused the artifact: {exc}"}
    m1.update({"id": "m1_address_decode_exclusivity",
               "property": "at most one decoder entry hits per address "
                           "(!overlap for all 64-bit addresses)",
               "artifact": "addr_decode.sv (render_addr_decode) + "
                           "m1_exclusivity_top assertions"})
    proofs.append(m1)

    # ---- CDG acyclicity on the 2-VC mesh (free dim-order + escape tree) ----
    seam = _emitter_seam()
    if seam is None or not hasattr(seam, "dim_order_tables"):
        proofs.append({
            "id": "cdg_acyclicity_2vc_mesh",
            "property": "channel dependency graphs of the free and escape "
                        "route tables are acyclic (Dally-Seitz)",
            "status": NOT_RUN_STATUS, "scope": None,
            "reason": "formal harness unavailable: gen_rtl emitter seam "
                      "not importable (owner stage = RTL generation; "
                      "module = FormalProofs)"})
    else:
        if anynet_text is None:
            anynet_text = _mesh_anynet_text(4)
        anynet_path = work / "formal-mesh.anynet"
        anynet_path.write_text(anynet_text)
        try:
            n, adj = seam.parse_anynet(anynet_path)
            tbl_free = seam.dim_order_tables(n, adj)
            if tbl_free is None:
                tbl_free = seam.up_down_tables(
                    n, adj, seam._best_escape_root(n, adj))
            tbl_esc = seam.tree_tables(n, adj, root=seam._best_escape_root(n, adj))
            if tbl_free is None or tbl_esc is None:
                raise ValueError("emitter produced no route tables for this mesh")
            harness = _CdgHarness(n, adj, {"free": tbl_free, "esc": tbl_esc})
            cdg_sv, stats = harness.sources()
            # Cross-check: Python acyclicity verdict must agree with the
            # rank witness extraction (both false here) and with the emitter.
            emitter_cyclic = seam.cdg_has_cycle(n, adj, tbl_free) or \
                seam.cdg_has_cycle(n, adj, tbl_esc)
            if emitter_cyclic:
                raise ValueError("emitter cdg_has_cycle reports a cycle but "
                                 "rank extraction succeeded (inconsistent)")
            cdg = _run_sby(work_dir=work, tag="cdg_acyclicity",
                           sv_text=cdg_sv, top="cdg_proof_top",
                           timeout=timeout)
            cdg.update({"id": "cdg_acyclicity_2vc_mesh",
                        "property": "channel dependency graphs of the free "
                                    "and escape route tables are acyclic "
                                    "(Dally-Seitz)",
                        "stats": {"routers": n, **stats},
                        "cross_check": {"cdg_has_cycle_emitter": bool(emitter_cyclic),
                                        "rank_witness": "extracted"}})
            proofs.append(cdg)
        except CyclicCdg as exc:
            proofs.append({
                "id": "cdg_acyclicity_2vc_mesh",
                "property": "channel dependency graphs of the free and "
                            "escape route tables are acyclic (Dally-Seitz)",
                "status": "FAIL", "scope": None,
                "reason": f"CDG cyclic: {exc} (deadlock possible; "
                          "the mesh must not ship with these tables)"})
        except Exception as exc:  # noqa: BLE001 - typed, never swallowed
            proofs.append({
                "id": "cdg_acyclicity_2vc_mesh",
                "property": "channel dependency graphs of the free and "
                            "escape route tables are acyclic (Dally-Seitz)",
                "status": NOT_RUN_STATUS, "scope": None,
                "reason": f"formal harness could not build the CDG proof "
                          f"({exc}) (owner stage = RTL generation; "
                          "module = FormalProofs)"})

    statuses = {proof["status"] for proof in proofs}
    if statuses == {"PASS"}:
        status, code = "PASS", "FORMAL_PASS"
        reason = ("M1 exclusivity and 2-VC mesh CDG acyclicity both proved "
                  "by unbounded sby prove (COMPLETE scope).")
    elif "FAIL" in statuses:
        status, code = "FAIL", "FORMAL_FAIL"
        reason = "at least one formal obligation was refuted (counterexample)"
    else:
        status, code = NOT_RUN_STATUS, "FORMAL_NOT_RUN"
        reason = ("formal harness unavailable or inconclusive "
                  "(see per-proof reasons)")
    return {
        "status": status,
        "code": code,
        "reason": reason,
        "proofs": proofs,
        "not_established": [
            "Deadlock-freedom conclusion assumes the certified 2-VC "
            "wormhole scheme (VC0 free dim-order/up-down, VC1 escape tree) "
            "and fair arbitration; credit management, cache coherence "
            "and liveness under arbitrary traffic are not proved.",
            "M1 exclusivity is proved for the emitted artifact's ranges; "
            "the compiler's range-overlap refusal remains the first line, "
            "this proof is the RTL-level backstop.",
        ],
    }


def _mesh_anynet_text(side: int) -> str:
    n = side * side
    lines = []
    for router in range(n):
        row, col = divmod(router, side)
        neighbours = []
        if col > 0:
            neighbours.append(router - 1)
        if col < side - 1:
            neighbours.append(router + 1)
        if row > 0:
            neighbours.append(router - side)
        if row < side - 1:
            neighbours.append(router + side)
        lines.append(f"router {router} node {router}"
                     + "".join(f" router {n_}" for n_ in sorted(neighbours)))
    return "\n".join(lines) + "\n"


__all__ = [
    "COMPLETE_SCOPE", "NOT_RUN_STATUS", "REQUIRED_TOOLS", "CyclicCdg",
    "cdg_edges", "topo_ranks", "render_m1_exclusivity_sv",
    "render_cdg_sv", "run_formal_proofs",
]
