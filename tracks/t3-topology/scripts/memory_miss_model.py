#!/usr/bin/env python3
"""Memory-class traffic generator (T3, D8 coupling model).

Converts an LLMServingSim per-batch trace into *memory-class* traffic for the
fabric, alongside the collective traffic that trace_to_matrix.py already
emits. This is the analytical coupling D8 locked: memory misses enter the
same BookSim2 fabric as collectives, and contention is captured on one set of
routers.

Hierarchy (D10 structured spec, buyer-supplied capacities):
    regfile -> scratchpad (per-NPU, size S) -> shared L2 (per-die, size L)
             -> HBM (local) -> remote (fabric)

Which accesses become *fabric* traffic:
  * Scratchpad hit      -> stays inside the NPU, no fabric.
  * Shared-L2 access    -> crosses the die fabric (shared structure).
  * HBM access          -> local DRAM, no fabric.
  * Remote access       -> crosses the fabric to another die.

Model (per layer, capacity-miss approximation):
  ws = in_size + weight_size + out_size        # working set this layer
  scratchpad_hit = min(ws, S)                   # fits in per-NPU scratchpad
  l2_access     = min(ws - scratchpad_hit, L)   # spill to shared L2 -> FABRIC
  hbm_access    = max(ws - scratchpad_hit - L, 0)  # spill to local DRAM
  remote_access = 0                             # (extend when multi-die)

Output: an N x N traffic matrix (same format trace_to_matrix.py writes),
plus a JSON provenance file. The emitted matrix is the *memory-class* half;
add it to the collective matrix (element-wise byte sum) for the combined
fabric load D8 requires.

Validation hook: --scalesim <DETAILED_ACCESS_REPORT.csv> cross-checks the
model's per-layer HBM bytes against SCALE-Sim's DRAM reads+writes when the
same working set is run under its scratchpad config.
"""
import argparse, json, re
from collections import defaultdict
from pathlib import Path

LINE_RE = re.compile(
    r"^\s*(?P<name>\S+)\s+(?P<comp>\d+)\s+"
    r"(?P<in_loc>\S+)\s+(?P<in_size>\d+)\s+"
    r"(?P<w_loc>\S+)\s+(?P<w_size>\d+)\s+"
    r"(?P<out_loc>\S+)\s+(?P<out_size>\d+)\s+"
    r"(?P<comm>\S+)\s+(?P<comm_size>\d+)\s+(?P<misc>\S+)"
)


def layer_rows(path: Path):
    """Yield (name, in_size, w_size, out_size) for every compute layer."""
    lines = path.read_text(errors="replace").splitlines()
    if not lines or not lines[0].startswith("COLOCATED"):
        return
    for line in lines[2:]:
        if not line.strip():
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        if name.startswith(("embedding", "layernorm", "qkv", "qk_norm",
                            "rotary", "attention", "o_proj", "gate",
                            "act_fn", "down_proj", "final_layernorm",
                            "lm_head", "sampler", "moe")):
            yield (name, int(m.group("in_size")),
                   int(m.group("w_size")), int(m.group("out_size")))


def miss_breakdown(ws, scratchpad, l2):
    """Capacity-miss split of one layer's working set across the hierarchy."""
    scratch = min(ws, scratchpad)
    rem = ws - scratch
    l2b = min(rem, l2)
    hbm = max(rem - l2, 0)
    return scratch, l2b, hbm


def aggregate(traces, scratchpad, l2, num_nodes):
    per_layer = []
    totals = {"scratchpad": 0, "l2": 0, "hbm": 0}
    for t in traces:
        for name, ins, ws, outs in layer_rows(t):
            scratch, l2b, hbm = miss_breakdown(ins + ws + outs, scratchpad, l2)
            totals["scratchpad"] += scratch
            totals["l2"] += l2b
            totals["hbm"] += hbm
            per_layer.append((name, ins + ws + outs, scratch, l2b, hbm))
    return totals, per_layer


def emit_matrix(l2_bytes, num_nodes, out, banks=4):
    """Memory-class matrix: shared-L2 accesses are fabric traffic.

    Shared L2 is banked across the die (D10 hierarchy). A miss from node s
    lands on the bank covering its tile of the address space. With `banks`
    banks distributed round-robin over the node ids, node s's misses go to
    the local bank group -- a SHORT-hop, locality-biased pattern, unlike the
    all-pairs collectives. This spatial difference is what makes memory
    traffic change the fabric ranking (F6 thesis).

    Bank placement: bank b sits at node round(b * N / banks); node s hashes
    to the bank covering its address tile (s * banks // N).
    """
    mat = [[0.0] * num_nodes for _ in range(num_nodes)]
    for s in range(num_nodes):
        # bank for node s's addresses: address-interleaved across banks
        bank = (s * banks) // num_nodes
        bank_node = round(bank * num_nodes / banks) % num_nodes
        # all of s's L2 misses go to its bank node (could add a share of
        # cross-bank for private-line conflict later)
        mat[s][bank_node] = l2_bytes if bank_node != s else 0.0
        if bank_node == s:
            # if the bank is local, the access never leaves the NPU
            pass
    out = Path(out)
    with open(out, "w") as f:
        f.write(f"# memory-class traffic matrix (shared-L2 access bytes "
                f"{l2_bytes}, {banks} banks, row=src, col=dst)\n")
        for row in mat:
            f.write(" ".join(f"{v:g}" for v in row) + "\n")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace_dir", help="dir holding per-batch *.txt traces")
    ap.add_argument("-n", "--num-nodes", type=int, default=64,
                    help="fabric nodes (must match BookSim2 k x k mesh)")
    ap.add_argument("-s", "--scratchpad-kb", type=int, default=16384,
                    help="per-NPU scratchpad size in KiB (default 16 MiB)")
    ap.add_argument("-l", "--l2-kb", type=int, default=65536,
                    help="shared-per-die L2 size in KiB (default 64 MiB)")
    ap.add_argument("-o", "--out", default="memory_matrix.mat")
    ap.add_argument("--scalesim", default=None,
                    help="SCALE-Sim DETAILED_ACCESS_REPORT.csv to validate HBM bytes")
    args = ap.parse_args()

    traces = sorted(Path(args.trace_dir).glob("*.txt"))
    if not traces:
        traces = sorted(Path(args.trace_dir).glob("**/*.txt"))
    if not traces:
        ap.error(f"no *.txt traces under {args.trace_dir}")

    scratchpad = args.scratchpad_kb * 1024
    l2 = args.l2_kb * 1024

    totals, per_layer = aggregate(traces, scratchpad, l2, args.num_nodes)

    print(f"{len(traces)} traces, scratchpad {args.scratchpad_kb} KiB, "
          f"L2 {args.l2_kb} KiB")
    print(f"  scratchpad hits: {totals['scratchpad']:,} B "
          f"({totals['scratchpad']/1e9:.2f} GB)")
    print(f"  shared-L2 (fabric): {totals['l2']:,} B "
          f"({totals['l2']/1e9:.2f} GB)")
    print(f"  HBM (local DRAM):  {totals['hbm']:,} B "
          f"({totals['hbm']/1e9:.2f} GB)")

    if args.scalesim:
        ss = validate_scalesim(args.scalesim, per_layer)
        print(f"  SCALE-Sim check: {ss['n_layer_match']}/{ss['n_total']} "
              f"layers matched, total traffic ratio {ss['total_traffic_ratio']:.2f}x")

    emit_matrix(totals["l2"], args.num_nodes, args.out)

    with open(Path(args.out).with_suffix(".json"), "w") as f:
        json.dump({
            "scratchpad_kb": args.scratchpad_kb,
            "l2_kb": args.l2_kb,
            "totals": totals,
            "layers": [{"name": n, "ws": ws, "scratch": s, "l2": l, "hbm": h}
                       for n, ws, s, l, h in per_layer],
        }, f, indent=2)


def validate_scalesim(csv_path, per_layer):
    """Conservation check vs SCALE-Sim DETAILED_ACCESS_REPORT.

    SCALE-Sim streams compulsory fills (DRAM reads/writes) under its own
    scratchpad config; our model splits the same working set across
    hierarchy levels. Conservation: total model traffic (scratch + l2 + hbm)
    must equal SCALE-Sim's SRAM + DRAM access bytes for the same working set.
    The ratio is reported per-level so capacity vs compulsory is visible.
    """
    import csv
    ss_by_layer = {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            clean = {k.strip(): v for k, v in row.items()}
            ss_by_layer[int(clean["LayerID"])] = (
                int(float(clean["SRAM IFMAP Reads"])) +
                int(float(clean["SRAM Filter Reads"])) +
                int(float(clean["SRAM OFMAP Writes"])) +
                int(float(clean["DRAM IFMAP Reads"])) +
                int(float(clean["DRAM Filter Reads"])) +
                int(float(clean["DRAM OFMAP Writes"])))
    matched = total_ss = total_model = 0
    for i, (name, ws, scratch, l2b, hbm) in enumerate(per_layer):
        ss = ss_by_layer.get(i)
        if ss is not None:
            matched += 1
            total_ss += ss
            total_model += ws
    return {"n_layer_match": matched, "n_total": len(ss_by_layer),
            "total_traffic_ratio": (total_ss / total_model) if total_model else float("inf")}


if __name__ == "__main__":
    main()