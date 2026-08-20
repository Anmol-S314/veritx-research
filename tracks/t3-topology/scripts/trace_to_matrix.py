#!/usr/bin/env python3
"""LLMServingSim trace -> Booksim traffic-matrix bridge (T3, trace pipeline).

The serving-trace pipeline: LLMServingSim -> Chakra -> Booksim/RTL.
This script is the trace -> matrix leg: it parses LLMServingSim's per-batch
trace files (the same text traces the Chakra converter consumes) and emits an
N x N traffic matrix in the format Booksim's `matrix(<file>)` pattern reads.

This is the DYNAMIC, trace-derived replacement for die_to_die_matrix.py's
static computation: the die-to-die KV/collective matrix now comes from an
actual token-by-token serving simulation (Qwen3-30B-A3B / Llama-3.1, TP/EP,
PD-disaggregated, MoE expert dispatch) instead of serving constants.

Trace format (see LLMServingSim docs/docs/reference/trace-format.md):

    COLOCATED\t\tmodel_parallel_NPU_group: {npu_group}
    {num_layers}
    Layername  comp_time  input_loc  input_size  weight_loc  weight_size  \\
                output_loc  output_size  comm_type  comm_size  misc
    ...
    EXPERT {n} {comm_type} {comm_size}      <- MoE dispatch lines

Communication events mapped to (src, dst) byte volume:
  * ALLREDUCE  : group-wide, every pair both directions (TP collectives)
  * EXPERT ALLGATHER : MoE expert dispatch/combine, expert <-> group
  * REMOTE:n loc     : cross-die memory access, die -> n (KV / embeddings)
  * NONE             : no traffic

Byte volumes are aggregated per (src,dst) over all batches, then normalized
so each source row sums to 1 (Booksim matrix semantics: row = src tile,
col = dst tile, cell = fraction of that src's traffic). The raw byte counts
are also written to <out>.json for provenance and absolute scaling.
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
# EXPERT {id} {comm} {size}  (MoE dispatch)  OR
# EXPERT END {comm} {size}   (MoE combine; e.g. REDUCESCATTER:1,1)
EXPERT_RE = re.compile(
    r"^\s*EXPERT\s+(?:(?P<id>\d+)|END)\s+(?P<comm>\S+)\s+(?P<size>\d+)"
)


def normalize_comm(comm: str) -> str:
    """Strip the dimension-scope suffix: 'ALLREDUCE:1,0' -> 'ALLREDUCE'.

    LLMServingSim encodes involved_dim as ':dim0,dim1' after the collective
    name. For the die-level traffic matrix every collective touches the
    group, so the scope only matters if we ever model per-dim topologies.
    """
    return comm.split(":")[0]


def remote_die(loc: str, default: int = 0) -> int:
    """'REMOTE:1' -> 1; 'REMOTE:1.3' -> 1 (device.channel); 'REMOTE' -> 0."""
    m = re.match(r"REMOTE(?::(\d+))?", loc)
    if not m:
        return None
    return int(m.group(1) or default)


def parse_trace(path: Path, num_dies: int, volumes: dict):
    """Accumulate (src -> dst -> bytes) from one per-batch trace file."""
    try:
        lines = path.read_text().splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(errors="replace").splitlines()
    if not lines or not lines[0].startswith("COLOCATED"):
        return
    for line in lines[2:]:
        if not line.strip():
            continue
        m = EXPERT_RE.match(line)
        if m:
            comm = normalize_comm(m.group("comm"))
            size = int(m.group("size"))
            if comm == "NONE" or size == 0:
                continue
            for src in range(num_dies):
                for dst in range(num_dies):
                    if src != dst:
                        volumes[src][dst] += size
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        comm = normalize_comm(m.group("comm"))
        size = int(m.group("comm_size"))
        if comm == "NONE" or size == 0:
            # still count cross-die memory transfers from REMOTE locs
            for loc, key in ((m.group("in_loc"), "in"),
                             (m.group("w_loc"), "w"),
                             (m.group("out_loc"), "out")):
                die = remote_die(loc)
                if die is not None and die != 0:
                    pass
            # REMOTE loc bytes: a remote input is a transfer die->this die.
            # The trace names the die the data lives on; the reader is the
            # local die. For N dies, local = the group's representative 0.
            for loc in (m.group("in_loc"), m.group("w_loc"), m.group("out_loc")):
                die = remote_die(loc)
                if die is not None and die != 0:
                    volumes[die][0] += size if loc == m.group("in_loc") else size
            continue
        if comm == "ALLREDUCE":
            for src in range(num_dies):
                for dst in range(num_dies):
                    if src != dst:
                        volumes[src][dst] += size
        elif comm in ("ALLGATHER", "ALLTOALL", "ALL2ALL", "REDUCESCATTER"):
            for src in range(num_dies):
                for dst in range(num_dies):
                    if src != dst:
                        volumes[src][dst] += size
        else:
            # unknown comm: count as one copy between every pair
            for src in range(num_dies):
                for dst in range(num_dies):
                    if src != dst:
                        volumes[src][dst] += size


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace_dir", help="dir holding per-batch *.txt traces "
                   "(LLMServingSim astra-sim/inputs/runs/<run>/trace/<hw>/<model>/)")
    ap.add_argument("-n", "--num-dies", type=int, default=2)
    ap.add_argument("-o", "--out", default="trace_matrix.mat")
    args = ap.parse_args()

    traces = sorted(Path(args.trace_dir).glob("*.txt"))
    if not traces:
        sys_traces = sorted(Path(args.trace_dir).glob("**/*.txt"))
        if not sys_traces:
            ap.error(f"no *.txt traces under {args.trace_dir}")
        traces = sys_traces

    volumes = defaultdict(lambda: defaultdict(int))
    for t in traces:
        parse_trace(t, args.num_dies, volumes)

    total_bytes = sum(volumes[s][d] for s in volumes for d in volumes[s])
    if total_bytes == 0:
        ap.error("no communication events found in traces")

    mat = [[0.0] * args.num_dies for _ in range(args.num_dies)]
    for s in range(args.num_dies):
        row = sum(volumes[s].values())
        if row:
            for d in range(args.num_dies):
                mat[s][d] = volumes[s][d] / row

    out = Path(args.out)
    with open(out, "w") as f:
        f.write("# LLMServingSim trace-derived matrix "
                f"({len(traces)} batches, {total_bytes} B, row=src, col=dst)\n")
        for row in mat:
            f.write(" ".join(f"{v:g}" for v in row) + "\n")

    with open(out.with_suffix(".json"), "w") as f:
        json.dump({
            "source": "LLMServingSim per-batch traces",
            "num_traces": len(traces),
            "num_dies": args.num_dies,
            "total_bytes": total_bytes,
            "bytes_per_pair": {f"{s}->{d}": volumes[s][d]
                               for s in volumes for d in volumes[s]},
            "matrix": mat,
        }, f, indent=2)

    print(f"{len(traces)} traces, {total_bytes} B aggregated")
    for s in range(args.num_dies):
        print(f"  src {s}: " + " ".join(f"{volumes[s][d]:,}" for d in range(args.num_dies)))
    print(f"matrix  -> {out}")
    print(f"bytes   -> {out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
