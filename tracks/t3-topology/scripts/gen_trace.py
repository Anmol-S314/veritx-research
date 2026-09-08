"""
gen_trace.py — turns a short workload.yaml into trace.csv for TraceTrafficManager.

Design goal: write one block per traffic pattern instead of one script per
experiment. Each block in workload.yaml picks a `mode`; this script dispatches
to the matching generator and merges everything into one time-sorted CSV in
the schema TraceTrafficManager expects:

    timestamp,src,dst,type,packet_size,transaction_id

Usage:
    python gen_trace.py workload.yaml trace.csv

Supported modes today: uniform, hotspot, burst, explicit (passthrough of an
existing CSV/list). `from_chakra` is stubbed — see the note at the bottom of
this file for why that one isn't a simple parser and what it actually needs.
"""

import argparse
import csv
import random
import sys
from pathlib import Path

import yaml  # pip install pyyaml


def _emit(rows, timestamp, src, dst, ptype, packet_size, txn_id):
    rows.append({
        "timestamp": int(timestamp),
        "src": int(src),
        "dst": int(dst),
        "type": ptype,
        "packet_size": int(packet_size),
        "transaction_id": txn_id,
    })


def _as_list(x, all_nodes):
    """Accept a single int, a list, or the literal 'all'."""
    if x == "all":
        return list(all_nodes)
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def gen_uniform(block, rows, all_nodes, next_id):
    """`count` packets, each cycle+source+dest independently randomized
    within `duration`, sources drawn from `src` (default: all nodes),
    destinations drawn from `dst` (default: all nodes, excluding self)."""
    srcs = _as_list(block.get("src", "all"), all_nodes)
    dsts = _as_list(block.get("dst", "all"), all_nodes)
    t0, t1 = block["duration"]
    count = block["count"]
    size = block["packet_size"]
    ptype = block.get("type", "OTHER")

    for _ in range(count):
        s = random.choice(srcs)
        d_choices = [d for d in dsts if d != s] or dsts
        d = random.choice(d_choices)
        t = random.randint(t0, t1)
        _emit(rows, t, s, d, ptype, size, next_id())


def gen_hotspot(block, rows, all_nodes, next_id):
    """Many sources hammering one destination — the classic contention
    stress test. `src` is the list of contributing nodes, `dst` is the
    single hot node."""
    srcs = _as_list(block["src"], all_nodes)
    dst = block["dst"]
    t0, t1 = block["duration"]
    count = block["count"]
    size = block["packet_size"]
    ptype = block.get("type", "OTHER")

    for _ in range(count):
        s = random.choice(srcs)
        t = random.randint(t0, t1)
        _emit(rows, t, s, dst, ptype, size, next_id())


def gen_burst(block, rows, all_nodes, next_id):
    """One src->dst pair firing `burst_count` back-to-back packets spaced
    `interval` cycles apart, starting at `start`."""
    src = block["src"]
    dst = block["dst"]
    start = block["start"]
    interval = block["interval"]
    burst_count = block["burst_count"]
    size = block["packet_size"]
    ptype = block.get("type", "OTHER")

    for i in range(burst_count):
        _emit(rows, start + i * interval, src, dst, ptype, size, next_id())


def gen_explicit(block, rows, all_nodes, next_id):
    """Passthrough: merge in an already-written CSV (same schema, header
    optional) as-is. Useful for hand-authored edge cases alongside
    generated traffic."""
    path = Path(block["file"])
    with path.open() as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if not row[0].strip().lstrip("-").isdigit():
                continue  # header row
            timestamp, src, dst, ptype, size = row[:5]
            txn_id = row[5] if len(row) > 5 else next_id()
            _emit(rows, timestamp, src, dst, ptype, size, txn_id)


def gen_matrix(block, rows, all_nodes, next_id):
    """Draws `count` packets from a weighted (src,dst) distribution built
    out of a Timeloop-style traffic matrix file (whitespace-separated,
    row=src, col=dst, cell=weight; '#' comment lines allowed).

    IMPORTANT: this does NOT try to bit-for-bit reproduce whatever
    Bernoulli/injection_rate process originally consumed that matrix in
    BookSim's native `traffic = matrix(file)` pattern -- that pattern is
    not stock BookSim2 (not present in traffic.cpp's factory; it's a
    local addition), and its exact semantics (per-cycle probability?
    row-normalized then scaled by injection_rate?) weren't available to
    check. Instead the matrix cells are treated as *relative volume
    weights* between (src,dst) pairs: `count` packets are drawn
    proportional to those weights and spread uniformly across
    `duration`. This is a deliberate shift from "statistical process" to
    "explicit deterministic trace" -- the same shift the rest of this
    framework makes elsewhere -- not an attempt to match the old
    injection-rate-scaled-by-matrix behavior exactly. If you need bitfor-
    bit equivalence with a specific existing sweep's load level, treat
    `count` as your tuning knob and calibrate it against a known-good
    `injection_rate` run rather than assuming a formula.
    """
    path = Path(block["file"])
    matrix = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            matrix.append([float(x) for x in line.split()])

    pairs, weights = [], []
    for i, row in enumerate(matrix):
        for j, w in enumerate(row):
            if w > 0:
                pairs.append((i, j))
                weights.append(w)
    if not pairs:
        return

    t0, t1 = block["duration"]
    count = block["count"]
    size = block["packet_size"]
    ptype = block.get("type", "OTHER")

    for (s, d) in random.choices(pairs, weights=weights, k=count):
        t = random.randint(t0, t1)
        _emit(rows, t, s, d, ptype, size, next_id())


def gen_from_chakra(block, rows, all_nodes, next_id):
    raise NotImplementedError(
        "from_chakra is not a simple ET->CSV parser -- see the note at the "
        "bottom of gen_trace.py before wiring this mode up."
    )


DISPATCH = {
    "uniform": gen_uniform,
    "hotspot": gen_hotspot,
    "burst": gen_burst,
    "explicit": gen_explicit,
    "matrix": gen_matrix,
    "from_chakra": gen_from_chakra,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workload_yaml")
    ap.add_argument("out_csv")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    with open(args.workload_yaml) as f:
        workload = yaml.safe_load(f)

    all_nodes = range(workload.get("nodes", 16))
    rows = []
    _counter = {"n": 0}

    def next_id():
        _counter["n"] += 1
        return _counter["n"]

    for block in workload["sources"]:
        mode = block["mode"]
        if mode not in DISPATCH:
            print(f"unknown mode: {mode}", file=sys.stderr)
            sys.exit(1)
        DISPATCH[mode](block, rows, all_nodes, next_id)

    rows.sort(key=lambda r: r["timestamp"])

    with open(args.out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "src", "dst", "type", "packet_size", "transaction_id"])
        for r in rows:
            w.writerow([r["timestamp"], r["src"], r["dst"], r["type"],
                        r["packet_size"], r["transaction_id"]])

    print(f"wrote {len(rows)} events to {args.out_csv}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Note on from_chakra (why it isn't implemented above)
# ---------------------------------------------------------------------------
# Verified against the real mlcommons/chakra schema (schema/protobuf/et_def.proto)
# and src/converter/pytorch_converter.py:
#
#   COMM_SEND_NODE / COMM_RECV_NODE carry `comm_size` (bytes) and `pg_name`
#   (process group), but no explicit peer-rank attribute in the standard
#   PyTorch converter output.
#
#   COMM_COLL_NODE (AllReduce, AllGather, AllToAll, ...) carries `comm_type`
#   and `comm_size` for the WHOLE collective op — it is NOT already a list of
#   point-to-point transfers. Turning "rank 3 does an AllReduce of 4MB over
#   its process group" into actual src/dst/bytes/cycle rows requires picking
#   a collective algorithm (ring, halving-doubling, tree, ...), which depends
#   on your topology and rank layout — the same thing a NoC-level trace needs
#   to reason about. A hand-rolled Chakra ET parser would have to
#   re-implement that decomposition itself.
#
# ASTRA-sim already does this decomposition (verified against
# astra-sim/astra-sim/common/AstraNetworkAPI.hh): its System layer consumes
# Chakra ETs, runs the appropriate collective algorithm, and issues plain
# point-to-point sim_send(count, dst, ...) / sim_recv(count, src, ...) calls
# against an AstraNetworkAPI backend -- exactly src/dst/bytes/time. ASTRA-sim
# already ships Garnet/NS3/Analytical backends behind that same interface.
#
# The right integration is therefore a small custom AstraNetworkAPI backend
# (same shape as astra-sim/network_frontend/analytical/congestion_unaware/)
# that, instead of modeling the network, appends
# (sim_get_time(), rank, dst, count) to a CSV -- getting correct collective
# decomposition, topology awareness, and rank->node mapping for free from
# ASTRA-sim, instead of re-deriving it.
#
# One real wrinkle, also confirmed from source: sim_send/sim_recv take a
# msg_handler callback that the backend must eventually invoke so ASTRA-sim's
# workload replay keeps advancing -- a "just log and return" backend isn't
# quite enough; it needs the same minimal event-scheduling scaffolding the
# existing backends have (they use sim_schedule for this). That makes this a
# self-contained but real C++ build task -- on the order of the
# TraceTrafficManager work already done, not a one-line hook. Good candidate
# for a follow-up session with the astra-sim source in front of us, the same
# way this one had booksim2 in front of us.
# ---------------------------------------------------------------------------
