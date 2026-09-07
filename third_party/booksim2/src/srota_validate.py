#!/usr/bin/env python3
"""
Srota NoC validation suite.

Runs the elaboration-time and simulation checks the hardware sub-documents
ask for, and prints a summary that maps each result back to the obligation
it discharges:

  F1     ROUTE-001 rev 0.3 section 4.4  -- acyclic channel dependency graph
  RT-R7  ROUTE-001 rev 0.3 section 4.5  -- the path-shape mixing hazard
  TP-V2  TOPO-003  rev 0.3 section 15   -- island placement invariant I-ISL
  Reach  TOPO-003  rev 0.3 section 3.2  -- <=2 network hops with MECS on

Usage:  python3 srota_validate.py [--booksim ./booksim] [--quick]
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

BASE = """
topology = srota;
routing_function = o1turn;
k = {k};
c = {c};
srota_mecs = {mecs};
srota_path_en = {path_en};
srota_vc_policy = {policy};
srota_island_col_map = {islands};
srota_cong_thresh = {thresh};
srota_epoch_len = 256;
srota_cdg_radix = {cdg};
num_vcs = {vcs};
vc_buf_size = 8;
wait_for_tail_credit = 0;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters = 1;
routing_delay = 1;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
credit_delay = 1;
st_prepare_delay = 0;
st_final_delay = 1;
input_speedup = 1;
output_speedup = 1;
internal_speedup = 1.0;
hold_switch_for_packet = 0;
buffer_policy = private;
channel_width = 512;
use_noc_latency = 0;
traffic = uniform;
packet_size = {psize};
injection_rate = {rate};
sim_type = latency;
warmup_periods = {warm};
sample_period = {period};
sim_count = 1;
"""

DEFAULTS = dict(k=4, c=1, mecs=3, path_en=3, policy="rank", islands=0,
                thresh=4, cdg=4, vcs=8, psize=4, rate=0.02,
                warm=1, period=500)


def run(booksim, **kw):
    cfg = dict(DEFAULTS)
    cfg.update(kw)
    with tempfile.NamedTemporaryFile("w", suffix=".config", delete=False) as fh:
        fh.write(BASE.format(**cfg))
        path = fh.name
    try:
        p = subprocess.run([booksim, path], capture_output=True, text=True,
                           timeout=900)
        return p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return "<<TIMEOUT>>"
    finally:
        os.unlink(path)


def grab(out, pattern, cast=float):
    m = re.search(pattern, out)
    return cast(m.group(1)) if m else None


class Results:
    def __init__(self):
        self.rows = []
        self.failed = 0

    def add(self, obligation, case, expected, actual, ok):
        self.rows.append((obligation, case, expected, actual, ok))
        if not ok:
            self.failed += 1

    def report(self):
        w = [max(len(str(r[i])) for r in self.rows + [("OBLIGATION", "CASE",
             "EXPECTED", "ACTUAL", "")]) for i in range(4)]
        hdr = ("OBLIGATION", "CASE", "EXPECTED", "ACTUAL")
        print()
        print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr)) + "  RESULT")
        print("-" * (sum(w) + 6 + 8))
        for ob, case, exp, act, ok in self.rows:
            print("  ".join(str(v).ljust(w[i]) for i, v in
                            enumerate((ob, case, exp, act)))
                  + "  " + ("ok" if ok else "FAIL"))
        print()
        if self.failed:
            print("%d check(s) FAILED." % self.failed)
        else:
            print("All %d checks passed." % len(self.rows))
        return 1 if self.failed else 0


def cdg_verdict(out):
    if "<<TIMEOUT>>" in out:
        return "timeout"
    if "config error" in out:
        return "refused"
    if "CYCLE FOUND" in out:
        return "cycle"
    if "CDG check: PASS" in out:
        return "acyclic"
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--booksim", default="./booksim")
    ap.add_argument("--quick", action="store_true",
                    help="skip the 16x16 reach comparison (the slow part)")
    args = ap.parse_args()

    if not os.access(args.booksim, os.X_OK):
        sys.exit("no booksim binary at %s -- run make first" % args.booksim)

    R = Results()

    # ------------------------------------------------------------------
    # F1 / RT-R7. The matrix ROUTE-001 section 4.5.4 asks for: the static
    # CDG check at each VC policy, with one shape, both direct shapes,
    # and all three. "cycle" is the correct answer for the unmitigated
    # case -- it is what confirms the hazard is real, not a failure.
    # ------------------------------------------------------------------
    print("== F1 / RT-R7: static CDG check (ROUTE-001 4.4, 4.5.4) ==")
    expect = {
        # (policy, path_en): expected verdict
        ("none", 1): "acyclic",    # pure XY, the F1 anchor
        ("none", 3): "cycle",      # THE hazard: both shapes, no separation
        ("none", 7): "cycle",
        ("shape", 1): "acyclic",
        ("shape", 3): "acyclic",   # O1TURN's own answer
        ("shape", 7): "refused",   # Valiant turns twice; policy refuses
        ("rank", 1): "acyclic",
        ("rank", 3): "acyclic",
        ("rank", 7): "acyclic",    # the only all-shapes-live safe policy
        ("oneshape", 1): "acyclic",
        ("oneshape", 3): "acyclic",  # 4.5.3 option 1
        ("oneshape", 7): "refused",
    }
    for (pol, pe), want in sorted(expect.items()):
        vcs = 1 if pol in ("none", "oneshape") else 8
        out = run(args.booksim, policy=pol, path_en=pe, vcs=vcs, rate=0.005)
        got = cdg_verdict(out)
        R.add("F1/RT-R7", "policy=%-8s path_en=%d" % (pol, pe), want, got,
              got == want)
        print("   policy=%-8s path_en=%d -> %s" % (pol, pe, got))

    # ------------------------------------------------------------------
    # Reach. TOPO-003 section 3.2: <=2 network hops with express on, up
    # to 2*(k-1) = 30 on the plain concentrated mesh at k=16.
    # ------------------------------------------------------------------
    print("\n== Reach: MECS on vs off (TOPO-003 3.2, 14) ==")
    k = 8 if args.quick else 16
    on = run(args.booksim, k=k, c=4, mecs=3, path_en=1, policy="none",
             vcs=2, rate=0.004, psize=1, period=2000)
    off = run(args.booksim, k=k, c=4, mecs=0, path_en=1, policy="none",
              vcs=2, rate=0.004, psize=1, period=2000)

    for label, out, want_max in (("express on", on, 2),
                                 ("express off", off, 2 * (k - 1))):
        got_max = grab(out, r"max network hops = (\d+)", int)
        R.add("Reach", "%s (k=%d) max hops" % (label, k), want_max, got_max,
              got_max == want_max)

    h_on = grab(on, r"Hops average = ([\d.]+)")
    h_off = grab(off, r"Hops average = ([\d.]+)")
    if h_on and h_off:
        # Both include one injection hop, so subtract it before comparing.
        net_on, net_off = h_on - 1, h_off - 1
        ratio = net_off / net_on if net_on else 0
        print("   measured mean network hops: express on %.2f, off %.2f "
              "-> %.1fx fewer" % (net_on, net_off, ratio))
        R.add("Reach", "mean hop reduction (k=%d)" % k, ">1x",
              "%.1fx" % ratio, ratio > 1.0)

    # ------------------------------------------------------------------
    # TP-V2. Island placement, TOPO-003 section 15.
    # ------------------------------------------------------------------
    print("\n== TP-V2: island placement I-ISL (TOPO-003 4.1, 15) ==")

    # A single island column with column-first only: the invariant holds.
    # Row-first into an island column transits the turn router, which is
    # itself in that column -- two islands on the path. See the diagnosis
    # the model prints; this asserts the finding stays reproduced.
    out = run(args.booksim, k=8, c=1, islands=1 << 3, path_en=1,
              policy="none", vcs=1, rate=0.004)
    R.add("TP-V2", "1 island col, row-first only", "violated",
          "violated" if "TP-V2 FAILED" in out else "verified",
          "TP-V2 FAILED" in out)

    # MECS off with islands is rejected outright (section 4.4).
    out = run(args.booksim, mecs=0, islands=2, policy="none", path_en=1,
              vcs=1)
    R.add("TP-V2", "islands with MECS off (4.4)", "refused",
          "refused" if "config error" in out else "accepted",
          "config error" in out)

    # ------------------------------------------------------------------
    # Config validity rules, ROUTE-001 section 14.3.
    # ------------------------------------------------------------------
    print("\n== Config validity (ROUTE-001 14.3) ==")
    out = run(args.booksim, path_en=6, policy="rank", vcs=8)   # row-first off
    R.add("14.3", "path_en without row-first", "refused",
          "refused" if "config error" in out else "accepted",
          "config error" in out)

    out = run(args.booksim, policy="rank", path_en=7, vcs=2)   # too few VCs
    R.add("14.3", "num_vcs < required VC sets", "refused",
          "refused" if "config error" in out else "accepted",
          "config error" in out)

    return R.report()


if __name__ == "__main__":
    sys.exit(main())
