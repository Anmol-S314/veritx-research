"""
gen_trace.py -- turns a short workload.yaml into trace.csv for TraceTrafficManager.

Output schema (one time-sorted CSV):

    timestamp,src,dst,type,packet_size,transaction_id,slack,batch,golden_id

The last three are the arbitration header fields (PKT-008 rev 0.3 section
8.2) the three-level arbiter consumes; they are optional on input and any
block may set them with `slack:`, `batch:` and `golden_id:` keys (they
default to 0, i.e. plain round-robin). See
tracks/t3-topology/docs/SROTA-NEXT-STEPS.md.

Node lists (src, dst, group, ...) accept:
  1. Range/list syntax: "0-3", "0-15:4" (start-stop:step), "0-3,8,12-15",
     or a list mixing any of these with bare ints.
  2. Named groups: define once under top-level `groups:`, reference by name.
  3. The literal "all".

Modes
  Point/statistical:  uniform, hotspot, burst, matrix, explicit (CSV passthrough)
  Topology patterns:  ring (TP all-reduce shape), all_to_all (MoE dispatch/combine
                      shape), pipeline_stages (PP boundary hand-off shape)
  Preset:             llm_transformer -- composes the patterns with tp/pp/dp/ep
                      (built on the model-agnostic primitives, not a special case)
  Stub:               from_chakra -- see the note at the bottom of this file.

Every mode honours the arbitration keys, including the pattern primitives and
the llm_transformer preset (the keys then apply to every packet of that block).

Usage:
    python gen_trace.py workload.yaml trace.csv [--seed N]
"""

import argparse
import csv
import random
import re
import sys
from pathlib import Path

import yaml  # pip install pyyaml


# ---------------------------------------------------------------------------
# Node-spec resolution: ranges, groups, "all", ints, and mixtures of all four
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^(\d+)-(\d+)(?::(\d+))?$")

BASE_DIR = Path(".")


def _resolve_path(p):
    """Absolute paths as-is; relative: try yaml's dir first, then cwd."""
    p = Path(p)
    if p.is_absolute():
        return p
    for cand in (BASE_DIR / p, Path.cwd() / p):
        if cand.exists():
            return cand
    raise FileNotFoundError(
        f"{p} not found (looked in {BASE_DIR.resolve()} and {Path.cwd()})")


def _expand_token(token, groups, all_nodes):
    """One comma-separated piece of a node spec -> list[int]."""
    token = str(token).strip()
    if token in groups:
        return list(groups[token])
    if token == "all":
        return list(all_nodes)
    m = _RANGE_RE.match(token)
    if m:
        start, stop, step = m.groups()
        step = int(step) if step else 1
        return list(range(int(start), int(stop) + 1, step))  # inclusive stop
    return [int(token)]


def resolve_nodes(spec, groups, all_nodes):
    """Turns any of the following into a flat list[int], in order given,
    duplicates preserved (callers that need a set can dedupe themselves):
        42                          -> [42]
        "all"                       -> every node
        "0-3"                       -> [0,1,2,3]
        "0-15:4"                    -> [0,4,8,12]
        "0-3,8,12-15"               -> [0,1,2,3,8,12,13,14,15]
        "tp_group_0"                -> whatever groups['tp_group_0'] resolved to
        [0, "4-7", "dram_nodes"]    -> concatenation of each element resolved
    """
    if isinstance(spec, int):
        return [spec]
    if isinstance(spec, (list, tuple)):
        out = []
        for item in spec:
            out.extend(resolve_nodes(item, groups, all_nodes))
        return out
    # string: may itself be comma-combined
    out = []
    for token in str(spec).split(","):
        out.extend(_expand_token(token, groups, all_nodes))
    return out


def resolve_groups(raw_groups, all_nodes):
    """Groups can reference each other or use range syntax too; resolve in
    the order given (a group can only reference groups defined above it)."""
    resolved = {}
    for name, spec in (raw_groups or {}).items():
        resolved[name] = resolve_nodes(spec, resolved, all_nodes)
    return resolved


# ---------------------------------------------------------------------------
# Arbitration header fields (slack / batch / golden_id)
# ---------------------------------------------------------------------------

def _resolve_arb(arb, src):
    """Turn a block's arbitration spec into concrete per-packet values.

    slack      int 0..3, or a list to draw from uniformly.
    batch      int 0..15, or "auto" to advance a counter per packet.
    golden_id  int, or "src" to derive the window from the source node --
               the assignment that gives every source its own bounded-delay
               floor, which is what F3 is for.
    """
    if not arb:
        return {"slack": 0, "batch": 0, "golden_id": 0}

    slack = arb.get("slack", 0)
    if isinstance(slack, (list, tuple)):
        slack = random.choice(list(slack))

    batch = arb.get("batch", 0)
    if batch == "auto":
        arb["_batch_n"] = arb.get("_batch_n", 0) + 1
        batch = (arb["_batch_n"] - 1) % 16

    golden = arb.get("golden_id", 0)
    if golden == "src":
        golden = src

    return {"slack": int(slack), "batch": int(batch), "golden_id": int(golden)}


def _arb_fields(block):
    """Pull the optional arbitration spec out of a workload block.
    Returns a fresh dict per call, so the "auto" batch counter is per block."""
    if not any(k in block for k in ("slack", "batch", "golden_id")):
        return None
    return {k: block[k] for k in ("slack", "batch", "golden_id") if k in block}


# ---------------------------------------------------------------------------
# Emission helpers shared by every mode
# ---------------------------------------------------------------------------

def _emit(rows, timestamp, src, dst, ptype, packet_size, txn_id, arb=None):
    """Append one trace row.

    `arb` carries the three arbitration header fields (PKT-008 rev 0.3
    section 8.2) that the three-level arbiter consumes. It is built once
    per block by _arb_fields() and is None for callers that don't set
    them, in which case all three default to 0 -- the degenerate case
    where every arbiter level falls through, so the arbiter behaves as
    plain round-robin.
    """
    row = {
        "timestamp": int(timestamp),
        "src": int(src),
        "dst": int(dst),
        "type": ptype,
        "packet_size": int(packet_size),
        "transaction_id": txn_id,
    }
    row.update(_resolve_arb(arb, int(src)))
    rows.append(row)


def _emit_ring(rows, group, start, interval, burst_count, size, ptype, next_id, arb=None):
    """Neighbor-to-neighbor around `group`, wrapping -- the shape of a ring
    all-reduce/all-gather. One burst per hop, all hops starting together
    (that's what makes it a *synchronized* collective rather than
    independent point-to-point traffic)."""
    n = len(group)
    if n < 2:
        return
    for hop in range(n):
        s, d = group[hop], group[(hop + 1) % n]
        for i in range(burst_count):
            _emit(rows, start + i * interval, s, d, ptype, size, next_id(), arb)


def _emit_all_to_all(rows, src_group, dst_group, start, interval, burst_count, size, ptype, next_id, arb=None):
    """Every member of src_group to every member of dst_group (self-pairs
    skipped) -- the shape of MoE token dispatch/combine, or any all-to-all
    collective. One (src_group, dst_group)-sized burst is exactly the "16
    burst blocks in the pasted MoE example" collapsed to one call."""
    for s in src_group:
        for d in dst_group:
            if s == d:
                continue
            for i in range(burst_count):
                _emit(rows, start + i * interval, s, d, ptype, size, next_id(), arb)


# ---------------------------------------------------------------------------
# Point / statistical modes (range- and group-aware via resolve_nodes)
# ---------------------------------------------------------------------------

def gen_uniform(block, rows, groups, all_nodes, next_id):
    """`count` packets, each cycle+source+dest independently randomized
    within `duration`, sources drawn from `src` (default: all nodes),
    destinations drawn from `dst` (default: all nodes, excluding self)."""
    srcs = resolve_nodes(block.get("src", "all"), groups, all_nodes)
    dsts = resolve_nodes(block.get("dst", "all"), groups, all_nodes)
    t0, t1 = block["duration"]
    count = block["count"]
    size = block["packet_size"]
    ptype = block.get("type", "OTHER")
    arb = _arb_fields(block)

    for _ in range(count):
        s = random.choice(srcs)
        d_choices = [d for d in dsts if d != s] or dsts
        d = random.choice(d_choices)
        t = random.randint(t0, t1)
        _emit(rows, t, s, d, ptype, size, next_id(), arb)


def gen_hotspot(block, rows, groups, all_nodes, next_id):
    """Many sources hammering one or more destinations -- the classic
    contention stress test. `src` and `dst` are node specs; every packet
    picks a random src and a random dst from them."""
    srcs = resolve_nodes(block["src"], groups, all_nodes)
    dsts = resolve_nodes(block["dst"], groups, all_nodes)
    t0, t1 = block["duration"]
    count = block["count"]
    size = block["packet_size"]
    ptype = block.get("type", "OTHER")
    arb = _arb_fields(block)

    for _ in range(count):
        s = random.choice(srcs)
        d = random.choice(dsts)
        t = random.randint(t0, t1)
        _emit(rows, t, s, d, ptype, size, next_id(), arb)


def gen_burst(block, rows, groups, all_nodes, next_id):
    """`burst_count` back-to-back packets spaced `interval` cycles apart,
    starting at `start`. src/dst can each resolve to several nodes -- every
    (s,d) pair gets its own synchronized burst (all pairs start together).
    For single src/dst this is the original behavior."""
    srcs = resolve_nodes(block["src"], groups, all_nodes)
    dsts = resolve_nodes(block["dst"], groups, all_nodes)
    start = block["start"]
    interval = block["interval"]
    burst_count = block["burst_count"]
    size = block["packet_size"]
    ptype = block.get("type", "OTHER")
    arb = _arb_fields(block)

    for s in srcs:
        for d in dsts:
            if s == d:
                continue
            for i in range(burst_count):
                _emit(rows, start + i * interval, s, d, ptype, size, next_id(), arb)


def gen_explicit(block, rows, groups, all_nodes, next_id):
    """Passthrough: merge in an already-written CSV (same schema, header
    optional) as-is. Useful for hand-authored edge cases alongside
    generated traffic."""
    path = _resolve_path(block["file"])
    with path.open() as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            if not row[0].strip().lstrip("-").isdigit():
                continue  # header row
            timestamp, src, dst, ptype, size = row[:5]
            txn_id = row[5] if len(row) > 5 else next_id()
            # Preserve arbitration columns when the source file has them
            # (an empty cell counts as absent).
            passthru = None
            if len(row) > 6 and row[6].strip():
                passthru = {"slack": int(row[6])}
                if len(row) > 7 and row[7].strip():
                    passthru["batch"] = int(row[7])
                if len(row) > 8 and row[8].strip():
                    passthru["golden_id"] = int(row[8])
            _emit(rows, timestamp, src, dst, ptype, size, txn_id,
                  passthru or _arb_fields(block))


def gen_matrix(block, rows, groups, all_nodes, next_id):
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
    injection-rate-scaled-by-matrix behavior exactly. If you need bit-for-
    bit equivalence with a specific existing sweep's load level, treat
    `count` as your tuning knob and calibrate it against a known-good
    `injection_rate` run rather than assuming a formula.
    """
    path = _resolve_path(block["file"])
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
    arb = _arb_fields(block)

    for (s, d) in random.choices(pairs, weights=weights, k=count):
        t = random.randint(t0, t1)
        _emit(rows, t, s, d, ptype, size, next_id(), arb)


# ---------------------------------------------------------------------------
# Topology-pattern primitives -- one block each instead of N
# ---------------------------------------------------------------------------

def gen_ring(block, rows, groups, all_nodes, next_id):
    """The TP all-reduce shape: a `group` of nodes, all synchronized
    neighbor-to-neighbor hops firing together, repeated `burst_count` times.
    Replaces one hand-written `burst` block per hop."""
    group = resolve_nodes(block["group"], groups, all_nodes)
    _emit_ring(rows, group, block["start"], block["interval"], block["burst_count"],
               block["packet_size"], block.get("type", "WRITE"), next_id,
               _arb_fields(block))


def gen_all_to_all(block, rows, groups, all_nodes, next_id):
    """The MoE dispatch/combine shape: every member of `group` (or
    `src_group`/`dst_group` if they differ) to every other member,
    synchronized. Replaces one hand-written `burst` block per source node."""
    if "group" in block:
        src_group = dst_group = resolve_nodes(block["group"], groups, all_nodes)
    else:
        src_group = resolve_nodes(block["src_group"], groups, all_nodes)
        dst_group = resolve_nodes(block["dst_group"], groups, all_nodes)
    _emit_all_to_all(rows, src_group, dst_group, block["start"], block["interval"],
                     block["burst_count"], block["packet_size"], block.get("type", "WRITE"),
                     next_id, _arb_fields(block))


def gen_pipeline_stages(block, rows, groups, all_nodes, next_id):
    """The PP boundary hand-off shape: `stages` is a list of node-groups in
    pipeline order; traffic fires at each consecutive-stage boundary.
    `boundary: "elementwise"` (default) pairs rank i of stage A with rank i
    of stage B -- the physically accurate case where each TP-rank hands its
    own shard to its counterpart in the next stage, requires equal-size
    stages. `boundary: "funnel"` sends every node in stage A to just the
    first node of stage B (a coarser approximation, but what you'd want if
    you're modeling a single receive point rather than per-shard handoff)."""
    stages = [resolve_nodes(s, groups, all_nodes) for s in block["stages"]]
    boundary = block.get("boundary", "elementwise")
    count = block["count_per_boundary"]
    t0, t1 = block["duration"]
    size = block["packet_size"]
    ptype = block.get("type", "WRITE")
    arb = _arb_fields(block)

    for i in range(len(stages) - 1):
        a, b = stages[i], stages[i + 1]
        if boundary == "elementwise":
            if len(a) != len(b):
                raise ValueError(
                    f"pipeline_stages: boundary='elementwise' needs equal-size "
                    f"stages, got {len(a)} and {len(b)} at boundary {i}. "
                    f"Use boundary='funnel' if that's intentional."
                )
            pairs = list(zip(a, b))
        else:
            pairs = [(s, b[0]) for s in a]
        for _ in range(count):
            s, d = random.choice(pairs)
            t = random.randint(t0, t1)
            _emit(rows, t, s, d, ptype, size, next_id(), arb)


def gen_from_chakra(block, rows, groups, all_nodes, next_id):
    raise NotImplementedError(
        "from_chakra is not a simple ET->CSV parser -- see the note at the "
        "bottom of gen_trace.py before wiring this mode up."
    )


# ---------------------------------------------------------------------------
# LLM preset -- composes the primitives above with tp/pp/dp/ep parameters.
# Not a special case inside the engine; a cnn_data_parallel or moe_only
# preset would be written the exact same way, calling the same _emit_ring /
# _emit_all_to_all helpers.
# ---------------------------------------------------------------------------

def gen_llm_transformer(block, rows, groups, all_nodes, next_id):
    """Rank layout convention used here (documented, not framework-verified --
    adjust if your real framework's rank ordering differs):
        rank = dp_idx * (pp * tp) + pp_idx * tp + tp_idx
    i.e. TP is the fastest-varying index (TP ranks are meant to be your
    highest-bandwidth/lowest-latency neighbors), then PP, then DP outermost.

    Required: tp, num_layers, packet sizes for whichever phases are active
    (tp_packet_size always; pp_packet_size if pp>1; dp_packet_size if dp>1;
    ep_packet_size if ep is set).
    Optional: pp (default 1), dp (default 1), ep (num nodes per expert-parallel
    group; if unset, no MoE traffic is generated), moe_layers (which layer
    indices include an EP phase; default: every other layer),
    layer_interval (cycles between layers, default 40), start (default 0),
    and the arbitration keys slack/batch/golden_id (applied to every packet
    this block generates).
    """
    tp = block["tp"]
    pp = block.get("pp", 1)
    dp = block.get("dp", 1)
    ep = block.get("ep")
    num_layers = block.get("num_layers", 4)
    layer_interval = block.get("layer_interval", 40)
    start = block.get("start", 0)
    moe_layers = set(block.get("moe_layers", range(0, num_layers, 2))) if ep else set()
    arb = _arb_fields(block)

    def rank(dp_i, pp_i, tp_i):
        return dp_i * (pp * tp) + pp_i * tp + tp_i

    # 1. TP ring, twice per layer (attention all-reduce, MLP all-reduce),
    #    within every (dp, pp) group.
    if tp > 1:
        for dp_i in range(dp):
            for pp_i in range(pp):
                tp_group = [rank(dp_i, pp_i, t) for t in range(tp)]
                for layer in range(num_layers):
                    for sub in range(2):
                        t0 = start + layer * layer_interval + sub * (layer_interval // 2)
                        _emit_ring(rows, tp_group, t0, 1, 1,
                                   block["tp_packet_size"], "WRITE", next_id, arb)

    # 2. PP boundary handoff, elementwise across TP ranks, once per layer.
    if pp > 1:
        for dp_i in range(dp):
            for pp_i in range(pp - 1):
                stage_a = [rank(dp_i, pp_i, t) for t in range(tp)]
                stage_b = [rank(dp_i, pp_i + 1, t) for t in range(tp)]
                for layer in range(num_layers):
                    t0 = start + layer * layer_interval
                    for a, b in zip(stage_a, stage_b):
                        _emit(rows, t0, a, b, "WRITE", block["pp_packet_size"], next_id(), arb)

    # 3. EP all-to-all (MoE dispatch + combine), on designated layers only.
    #    Simplification, documented: the expert-parallel group here is taken
    #    to be the TP group at each (dp,pp) position -- i.e. ep == tp is
    #    assumed for this preset. If your real EP group spans differently
    #    (e.g. EP orthogonal to TP), build that case with gen_all_to_all
    #    directly rather than this preset.
    if ep:
        for dp_i in range(dp):
            for pp_i in range(pp):
                ep_group = [rank(dp_i, pp_i, t) for t in range(tp)]
                for layer in moe_layers:
                    t_dispatch = start + layer * layer_interval + layer_interval // 4
                    t_combine = t_dispatch + layer_interval // 4
                    _emit_all_to_all(rows, ep_group, ep_group, t_dispatch, 1, 1,
                                     block["ep_packet_size"], "WRITE", next_id, arb)
                    _emit_all_to_all(rows, ep_group, ep_group, t_combine, 1, 1,
                                     block["ep_packet_size"], "WRITE", next_id, arb)

    # 4. DP gradient all-reduce, ring across replicas, once after all layers.
    if dp > 1:
        t0 = start + num_layers * layer_interval + layer_interval // 4
        for pp_i in range(pp):
            for tp_i in range(tp):
                dp_group = [rank(d, pp_i, tp_i) for d in range(dp)]
                _emit_ring(rows, dp_group, t0, 1, 1,
                           block["dp_packet_size"], "WRITE", next_id, arb)


DISPATCH = {
    "uniform": gen_uniform,
    "hotspot": gen_hotspot,
    "burst": gen_burst,
    "matrix": gen_matrix,
    "explicit": gen_explicit,
    "ring": gen_ring,
    "all_to_all": gen_all_to_all,
    "pipeline_stages": gen_pipeline_stages,
    "llm_transformer": gen_llm_transformer,
    "from_chakra": gen_from_chakra,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workload_yaml")
    ap.add_argument("out_csv")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    global BASE_DIR
    BASE_DIR = Path(args.workload_yaml).resolve().parent

    if args.seed is not None:
        random.seed(args.seed)

    with open(args.workload_yaml) as f:
        workload = yaml.safe_load(f)

    all_nodes = range(workload.get("nodes", 16))
    groups = resolve_groups(workload.get("groups"), all_nodes)
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
        DISPATCH[mode](block, rows, groups, all_nodes, next_id)

    rows.sort(key=lambda r: r["timestamp"])

    with open(args.out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "src", "dst", "type", "packet_size",
                    "transaction_id", "slack", "batch", "golden_id"])
        for r in rows:
            w.writerow([r["timestamp"], r["src"], r["dst"], r["type"],
                        r["packet_size"], r["transaction_id"],
                        r.get("slack", 0), r.get("batch", 0),
                        r.get("golden_id", 0)])

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
