#!/usr/bin/env python3
"""
MoE expert-parallel traffic matrices for the T3 Booksim sweep.

WHY THIS EXISTS
---------------
timeloop_to_matrix.py's build_traffic_matrix() is, by its own docstring, a
"PLACEHOLDER spatial model" -- 60% nearest-neighbour ring plus 40% to node
0. That pattern structurally favours a nearest-neighbour mesh: the local
share mostly never leaves its own concentrator, and the rest is a
single-node incast. Measured on the Srota model at 1024 nodes, MECS
express wins on hops (1.4 vs 2.0) and loses on latency (81 vs 63), which
says more about the traffic than about the topology.

An express layer exists for traffic that is *not* nearest-neighbour. The
two patterns Srota is explicitly designed around are:

  - MoE expert-parallel all-to-all with hot-expert skew. SSM-UARCH-
    ROUTE-001 rev 0.3 section 5 exists entirely to relieve this: the
    injection-time overlay picks a path shape per flow-epoch from Plane-T
    congestion, and section 6.1's worked example is literally "an MoE
    decode phase where column 9 is a hot-expert column".

  - Weight broadcast. SSM-UARCH-TOPO-003 rev 0.3 section 3.2 calls the
    multidrop channel's broadcast behaviour "the topology choice and the
    collective requirement solve each other -- the parent spec's single
    most important co-design decision", and section 14 claims ~16x
    reduction in injected bandwidth from it.

This module generates both, in the Booksim `matrix(<file>)` format, so
the existing spine (TRAFFIC_MATRIX=... run_experiments.py) can drive any
topology with them, unchanged.

WHAT IT MODELS
--------------
Expert-parallel MoE, one layer, steady state:

  dispatch  Each tile holds seq_len/N tokens. The router picks
            num_experts_per_tok experts per token; the token's hidden
            vector is sent to whichever tile hosts each chosen expert.
            This is the all-to-all.
  combine   The reverse edge: expert outputs return to the owning tile.
            Same volume, transposed.
  broadcast One memory node sends the same weight block to every tile.
            On a multidrop fabric this is one channel transaction per row
            (TOPO-003 section 9.3); on a switch-centric fabric it is N
            unicasts. A traffic matrix cannot express "one transaction,
            many acceptors", so this emits the UNICAST-EQUIVALENT volume
            -- see the caveat in --help and in the header comment written
            into every broadcast matrix.

Expert popularity is skewed by a Zipf law (--skew). skew=0 is a perfectly
balanced router; real MoE routers are not balanced, and the imbalance is
the whole reason the adaptive overlay exists.

Expert placement is topology-aware when --grid-k is given: --hot-column
concentrates the most popular experts into one mesh column, which builds
ROUTE-001 section 6.1's scenario directly.

USAGE
-----
  # balanced all-to-all on a 1024-node fabric
  python3 scripts/moe_traffic.py --nodes 1024 --pattern a2a -o a2a.txt

  # hot-expert skew concentrated in mesh column 9 of a k=16,c=4 Srota fabric
  python3 scripts/moe_traffic.py --nodes 1024 --grid-k 16 --grid-c 4 \\
      --pattern a2a --skew 1.2 --hot-column 9 -o a2a_hot.txt

  # weight broadcast from an HBM node
  python3 scripts/moe_traffic.py --nodes 1024 --pattern broadcast -o bcast.txt

  # then, in the existing spine:
  TRAFFIC_MATRIX=a2a_hot.txt python3 scripts/run_experiments.py
"""

import argparse
import json
import sys
from pathlib import Path


# ----------------------------------------------------------------------
#  Model spec
# ----------------------------------------------------------------------
def load_moe_spec(config_path, seq_len, dtype_bytes):
    """HF config.json -> the fields this generator needs.

    Accepts Mixtral-style MoE configs (num_local_experts,
    num_experts_per_tok). A dense config has neither; rather than silently
    inventing an MoE structure for a dense model, that is an error the
    caller has to resolve with --experts / --top-k.
    """
    with open(config_path) as f:
        cfg = json.load(f)

    experts = cfg.get("num_local_experts") or cfg.get("num_experts")
    top_k = cfg.get("num_experts_per_tok")
    if experts is None or top_k is None:
        raise SystemExit(
            "%s has no MoE fields (num_local_experts / num_experts_per_tok).\n"
            "It looks like a dense model. Either point --model-config at an "
            "MoE config (timeloop/experiment_configs/mixtral_8x7b_hf_config.json)\n"
            "or give --experts and --top-k explicitly." % config_path
        )

    return dict(
        hidden_size=cfg["hidden_size"],
        ffn=cfg.get("intermediate_size"),
        experts=experts,
        top_k=top_k,
        layers=cfg.get("num_hidden_layers", 1),
        seq_len=seq_len,
        dtype_bytes=dtype_bytes,
    )


# ----------------------------------------------------------------------
#  Expert popularity and placement
# ----------------------------------------------------------------------
def expert_popularity(num_experts, skew):
    """Zipf popularity, normalised to sum to 1.

    skew=0 -> uniform (every expert equally chosen). Larger skew ->
    p(rank r) proportional to 1/(r+1)^skew, so expert 0 is hottest. This
    is a stand-in for a real router's load imbalance; the point is not the
    exact distribution but that SOME experts are hot, because a balanced
    router makes the adaptive overlay pointless by construction.
    """
    if skew <= 0:
        return [1.0 / num_experts] * num_experts
    w = [1.0 / ((r + 1) ** skew) for r in range(num_experts)]
    total = sum(w)
    return [x / total for x in w]


def place_experts(num_experts, num_nodes, grid_k, grid_c, hot_column):
    """expert index -> list of node ids hosting it.

    Default placement spreads experts evenly over the node space, so
    expert e owns a contiguous block of nodes. With --hot-column (and a
    grid), the experts are instead placed so the most popular ones land in
    the named mesh column -- ROUTE-001 section 6.1's "column 9 is a
    hot-expert column".
    """
    if hot_column is None:
        # Even spread: expert e owns nodes [e*N/E, (e+1)*N/E).
        out = []
        for e in range(num_experts):
            lo = (e * num_nodes) // num_experts
            hi = ((e + 1) * num_nodes) // num_experts
            out.append(list(range(lo, max(hi, lo + 1))))
        return out

    if grid_k is None:
        raise SystemExit("--hot-column needs --grid-k (and --grid-c) to know "
                         "which nodes are in which mesh column.")

    # Node -> (router, tile) -> (x, y), matching the Srota/cmesh convention:
    # node = router*c + tile, router = y*k + x.
    col_nodes, other_nodes = [], []
    for n in range(num_nodes):
        router = n // grid_c
        x = router % grid_k
        (col_nodes if x == hot_column else other_nodes).append(n)

    if not col_nodes:
        raise SystemExit("--hot-column %d selects no nodes at k=%d c=%d n=%d"
                         % (hot_column, grid_k, grid_c, num_nodes))

    # Hottest experts first into the hot column, the rest spread elsewhere.
    out = [None] * num_experts
    per = max(1, len(col_nodes) // max(1, min(num_experts, len(col_nodes))))
    ci = 0
    placed_in_col = 0
    for e in range(num_experts):
        if ci + per <= len(col_nodes) and placed_in_col < len(col_nodes):
            out[e] = col_nodes[ci:ci + per]
            ci += per
            placed_in_col += per
        else:
            break

    remaining = [e for e in range(num_experts) if out[e] is None]
    if remaining:
        for i, e in enumerate(remaining):
            lo = (i * len(other_nodes)) // len(remaining)
            hi = ((i + 1) * len(other_nodes)) // len(remaining)
            out[e] = other_nodes[lo:max(hi, lo + 1)]
    return out


# ----------------------------------------------------------------------
#  Traffic construction
# ----------------------------------------------------------------------
def build_a2a(spec, num_nodes, placement, popularity, include_combine):
    """All-to-all dispatch (+ optional combine).

    Every node owns seq_len/N tokens. Each token goes to top_k experts,
    chosen with probability `popularity`. Expected bytes from node s to
    node d = tokens_per_node * top_k * P(expert on d) * hidden * dtype,
    spread over the nodes hosting that expert.

    Self-traffic (s == d) is kept: a token whose expert lives on its own
    node generates no NoC traffic, and dropping it here rather than
    zeroing it later is what keeps the row sums meaningful.
    """
    mat = [[0.0] * num_nodes for _ in range(num_nodes)]

    tokens_per_node = spec["seq_len"] / num_nodes
    bytes_per_token = spec["hidden_size"] * spec["dtype_bytes"]

    for e, nodes in enumerate(placement):
        if not nodes:
            continue
        # Expected number of (token, expert e) selections per source node.
        sel = tokens_per_node * spec["top_k"] * popularity[e]
        per_dst = sel * bytes_per_token / len(nodes)
        for s in range(num_nodes):
            for d in nodes:
                mat[s][d] += per_dst
                if include_combine:
                    # Expert output returns to the token's owner. Same
                    # volume, opposite direction.
                    mat[d][s] += per_dst

    # A token routed to an expert on its own node never enters the NoC.
    for i in range(num_nodes):
        mat[i][i] = 0.0
    return mat


def build_broadcast(spec, num_nodes, src_node):
    """One memory node sends the same weight block to every tile.

    IMPORTANT CAVEAT, repeated in the file header of every emitted matrix:
    a traffic matrix has one entry per (src, dst) pair and cannot express
    "one channel transaction that N drops accept simultaneously". What
    this emits is the UNICAST-EQUIVALENT volume -- N separate transfers.

    That is exactly the baseline TOPO-003 section 14 measures its ~16x
    claim against ("16 unicasts on a switch-centric fabric"), so this
    matrix is the right *denominator*. It is not the multicast case
    itself: measuring that needs the multicast fork path, which the Srota
    routing model does not implement (SROTA.md, departure 5). Do not read
    a broadcast run as evidence for or against the 16x claim.
    """
    mat = [[0.0] * num_nodes for _ in range(num_nodes)]
    # One expert's FFN weights, the unit a broadcast actually moves.
    w = spec["ffn"] or spec["hidden_size"]
    block = spec["hidden_size"] * w * spec["dtype_bytes"]
    per_dst = block / max(1, num_nodes - 1)
    for d in range(num_nodes):
        if d != src_node:
            mat[src_node][d] = per_dst
    return mat


def add(a, b, wa=1.0, wb=1.0):
    return [[a[i][j] * wa + b[i][j] * wb for j in range(len(a))]
            for i in range(len(a))]


def normalize(mat, peak):
    """Scale so the largest row sum equals `peak`.

    Booksim's matrix pattern reads each row as relative destination
    weights and scales by injection_rate, so absolute magnitude here is
    arbitrary -- but keeping the peak row at a known value makes matrices
    from different patterns comparable at the same injection_rate.
    """
    m = max(sum(r) for r in mat)
    if m <= 0:
        return mat
    s = peak / m
    return [[v * s for v in r] for r in mat]


def write_matrix(mat, path, header_lines):
    with open(path, "w") as f:
        for line in header_lines:
            f.write("# " + line + "\n")
        for row in mat:
            f.write(" ".join("%g" % v for v in row) + "\n")


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--nodes", type=int, required=True,
                    help="NoC node count; must equal the topology's")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--pattern", default="a2a",
                    choices=["a2a", "dispatch", "broadcast", "mixed"],
                    help="a2a = dispatch+combine (default); dispatch = one "
                         "direction only; broadcast = weight broadcast "
                         "(unicast-equivalent); mixed = a2a + broadcast")
    ap.add_argument("--model-config",
                    default="timeloop/experiment_configs/mixtral_8x7b_hf_config.json")
    ap.add_argument("--seq-len", type=int, default=2048)
    ap.add_argument("--dtype-bytes", type=int, default=2)
    ap.add_argument("--experts", type=int,
                    help="override num_local_experts from the config")
    ap.add_argument("--top-k", type=int,
                    help="override num_experts_per_tok from the config")
    ap.add_argument("--skew", type=float, default=0.0,
                    help="Zipf exponent for expert popularity. 0 = balanced "
                         "router (default); ~1.0-1.5 is a realistically "
                         "imbalanced one. The overlay in ROUTE-001 section 5 "
                         "only has a job to do when this is non-zero")
    ap.add_argument("--grid-k", type=int,
                    help="mesh radix, for topology-aware expert placement")
    ap.add_argument("--grid-c", type=int, default=1,
                    help="concentration, for topology-aware placement")
    ap.add_argument("--hot-column", type=int,
                    help="place the most popular experts in this mesh column "
                         "(ROUTE-001 section 6.1's worked example)")
    ap.add_argument("--broadcast-src", type=int, default=0,
                    help="node the weight broadcast originates from")
    ap.add_argument("--broadcast-weight", type=float, default=0.5,
                    help="broadcast share of total volume when --pattern mixed")
    ap.add_argument("--peak-row", type=float, default=1.0,
                    help="normalise so the busiest row sums to this")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    cfg_path = Path(args.model_config)
    if not cfg_path.is_absolute():
        cfg_path = root / cfg_path

    if args.experts and args.top_k:
        spec = dict(hidden_size=4096, ffn=14336, experts=args.experts,
                    top_k=args.top_k, layers=1, seq_len=args.seq_len,
                    dtype_bytes=args.dtype_bytes)
        src_desc = "explicit --experts/--top-k"
    else:
        spec = load_moe_spec(cfg_path, args.seq_len, args.dtype_bytes)
        if args.experts:
            spec["experts"] = args.experts
        if args.top_k:
            spec["top_k"] = args.top_k
        src_desc = str(cfg_path.relative_to(root)) if cfg_path.is_relative_to(root) \
            else str(cfg_path)

    n = args.nodes
    pop = expert_popularity(spec["experts"], args.skew)
    placement = place_experts(spec["experts"], n, args.grid_k, args.grid_c,
                              args.hot_column)

    hdr = [
        "MoE expert-parallel traffic matrix (row=src node, col=dst node)",
        "generated by scripts/moe_traffic.py -- NOT the placeholder model in",
        "timeloop_to_matrix.py; see that script's header for why.",
        "model=%s  experts=%d top_k=%d hidden=%d seq_len=%d dtype=%dB"
        % (src_desc, spec["experts"], spec["top_k"], spec["hidden_size"],
           spec["seq_len"], spec["dtype_bytes"]),
        "nodes=%d pattern=%s skew=%.2f%s"
        % (n, args.pattern, args.skew,
           (" hot_column=%d (k=%s c=%d)" % (args.hot_column, args.grid_k,
                                            args.grid_c))
           if args.hot_column is not None else ""),
    ]

    if args.pattern in ("a2a", "dispatch"):
        mat = build_a2a(spec, n, placement, pop,
                        include_combine=(args.pattern == "a2a"))
    elif args.pattern == "broadcast":
        mat = build_broadcast(spec, n, args.broadcast_src)
        hdr.append("CAVEAT: unicast-equivalent volume. A traffic matrix cannot")
        hdr.append("express one multidrop transaction accepted by N drops, so")
        hdr.append("this is the switch-centric BASELINE that TOPO-003 section")
        hdr.append("14's ~16x claim is measured against, not the multicast case.")
    else:
        a = normalize(build_a2a(spec, n, placement, pop, True), 1.0)
        b = normalize(build_broadcast(spec, n, args.broadcast_src), 1.0)
        mat = add(a, b, 1.0 - args.broadcast_weight, args.broadcast_weight)
        hdr.append("mixed: %.0f%% all-to-all + %.0f%% broadcast (see broadcast caveat)"
                   % (100 * (1 - args.broadcast_weight),
                      100 * args.broadcast_weight))

    mat = normalize(mat, args.peak_row)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_matrix(mat, out, hdr)

    # Report the load imbalance the topology will actually see -- the
    # number that says whether this matrix exercises the overlay at all.
    col = [sum(mat[s][d] for s in range(n)) for d in range(n)]
    hot = max(col) if col else 0
    mean = (sum(col) / len(col)) if col else 0
    print("wrote %s" % out)
    print("  %d nodes, pattern=%s, skew=%.2f" % (n, args.pattern, args.skew))
    print("  destination load imbalance: hottest/mean = %.2fx"
          % (hot / mean if mean else 0))
    if args.pattern != "broadcast" and args.skew == 0 and args.hot_column is None:
        print("  note: skew=0 and no hot column -- this is a BALANCED "
              "all-to-all.\n"
              "        ROUTE-001 section 5's overlay has nothing to relieve "
              "here.\n"
              "        Add --skew 1.2 (and optionally --hot-column) to "
              "exercise it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
