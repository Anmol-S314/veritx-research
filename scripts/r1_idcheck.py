#!/usr/bin/env python3
"""R1 per-flit diff analyzer, keyed by (src, pid-ordinal) — preserved from the
Gate R1 session (seed aaf6; originally r1_idcheck.sh).

WHY THIS IS KEPT: it encodes lesson L2 (docs/lessons.md) — BookSim's flits.txt
uses a GLOBAL packet id while the RTL dump uses a PER-NIC ordinal, so diffs
must pair on (src, ordinal), never pid alone. The R1 pid-correlation fix
(T3-001, fa99a9b) is verified with this pairing.

USAGE: python3 scripts/r1_idcheck.py <cell_dir> [<cell_dir> ...]
Each cell dir must contain flits.txt (BookSim), rtl_flits.txt (RTL), and
trace.txt. Output: per-cell mismatch counts split into id-mismatch (class/
src/dst differ), order-mismatch (counts differ), and timing-only (same
identity, different atime/itime — the envelope tier's domain).

Note: the original one-off invoked hardcoded /tmp cell paths (wiped). The
tool is parameterized now; the R1 cells themselves are gone, so this is a
reference implementation for future per-flit diffs, not a live check.
"""

import sys


def analyze(cell):
    bs = {}
    for l in open(f"{cell}/flits.txt"):
        if l.strip():
            a, cl, s, d, p, it = map(int, l.split())
            bs.setdefault(p, []).append((a, cl, s, d, it))
    rt = {}
    for l in open(f"{cell}/rtl_flits.txt"):
        if l.strip():
            a, cl, s, d, p, it = map(int, l.split())
            rt.setdefault((s, p), []).append((a, cl, s, d, it))
    trace = [l.split() for l in open(f"{cell}/trace.txt") if l.strip()]
    per_src = {}
    for k, (c, s, cl, d, sz) in enumerate(trace):
        per_src.setdefault(int(s), []).append(k)
    ordmap = {}
    for s, idxs in per_src.items():
        for j, k in enumerate(idxs):
            ordmap[(s, k)] = j
    total = n_id = n_ord = n_time = 0
    id_samples = []
    for k, (c, s, cl, d, sz) in enumerate(trace):
        b = sorted(bs.get(k, []))
        r = sorted(rt.get((int(s), ordmap[(int(s), k)]), []))
        if len(b) != len(r):
            n_ord += 1
            continue
        for (ba, bcl, bsrc, bdst, bit), (ra, rcl, rsrc, rdst, rit) in zip(b, r):
            total += 1
            if (bcl, bsrc, bdst) != (rcl, rsrc, rdst):
                n_id += 1
                if len(id_samples) < 5:
                    id_samples.append((k, (ba, bcl, bsrc, bdst, bit),
                                      (ra, rcl, rsrc, rdst, rit)))
            elif ba != ra or bit != rit:
                n_time += 1
    print(f"{cell}: flits={total} id-mismatch={n_id} order-mismatch={n_ord} "
          f"timing-only={n_time}")
    for s in id_samples:
        print("   ID SAMPLE:", s)
    return n_id + n_ord


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for cell in sys.argv[1:]:
        analyze(cell)
