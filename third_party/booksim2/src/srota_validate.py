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
  SB     VC-002    rev 0.3 section 2.3  -- shared side buffer: capture,
                                           drain, backpressure
  ISL    TOPO-003  rev 0.3 section 7.5  -- island class accounting and
                                           rate regulation
  PLANE  TOPO-003  rev 0.3 section 5    -- D / C / T plane configuration

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
{extra}
"""

DEFAULTS = dict(k=4, c=1, mecs=3, path_en=3, policy="rank", islands=0,
                thresh=4, cdg=4, vcs=8, psize=4, rate=0.02,
                warm=1, period=500, extra="")


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
    # Side buffer, VC-002 sections 2.3, 6.4, 10.
    # ------------------------------------------------------------------
    print("\n== SB: Plane D side buffer (VC-002 2.3) ==")
    SB = ("srota_router = sidebuf; vc_buf_size = 2; speculative = 1;")
    out = run(args.booksim, path_en=1, policy="none", vcs=1, rate=0.03,
              extra=SB)
    fill = grab(out, r"sb_fill=(\d+)", int)
    drain = grab(out, r"sb_drain=(\d+)", int)
    R.add("SB", "fill == drain (every capture drains)", "equal",
          "%s/%s" % (fill, drain),
          fill is not None and fill > 0 and fill == drain)

    # A 1-flit side buffer under heavy load must turn losers away
    # (credit withheld) rather than overflow, and the run must finish.
    out = run(args.booksim, path_en=1, policy="none", vcs=1, rate=0.2,
              extra=SB + " srota_sb_depth = 1;")
    rej = grab(out, r"sb_full_reject=(\d+)", int)
    peak = grab(out, r"sb_peak=(\d+)", int)
    R.add("SB", "depth 1 at overload: backpressure", "reject>0 peak<=1",
          "reject=%s peak=%s" % (rej, peak),
          rej is not None and rej > 0 and peak is not None and peak <= 1
          and "Flit buffer overflow" not in out)

    # ------------------------------------------------------------------
    # Islands, TOPO-003 sections 4, 7.5.
    # ------------------------------------------------------------------
    print("\n== ISL: island wrapper (TOPO-003 7.5) ==")
    ISL = SB + (" srota_isl_route = colfirst; classes = 2;"
                " injection_rate = {0.02,0.02};"
                " srota_isl_rate = {0.02,0.2}; srota_isl_burst = 4;")
    out = run(args.booksim, islands=9, path_en=3, policy="rank", vcs=2,
              extra=ISL)
    rows = re.findall(r"island class=(\d+) arrive=(\d+) grant=(\d+) "
                      r"deferred_flits=(\d+)", out)
    cons = bool(rows) and all(a == g for _, a, g, _ in rows)
    R.add("ISL", "class accounting: grant == arrive", "equal",
          " ".join("c%s:%s/%s" % (q, g, a) for q, a, g, _ in rows) or "none",
          cons)
    d = {int(q): int(df) for q, _, _, df in rows}
    R.add("ISL", "slower class deferred more", "c0 > c1",
          "c0=%s c1=%s" % (d.get(0), d.get(1)),
          d.get(0, 0) > d.get(1, 0))

    # The island rule makes I-ISL structural; what TP-V2 still reports is
    # the island-column-source residue, and the model says so.
    R.add("TP-V2", "colfirst rule: residue only", "residue",
          "residue" if "isl_route=colfirst): the rule" in out else "other",
          "isl_route=colfirst): the rule" in out)

    # ...and on a zero-VC Plane D the same rule re-opens RT-R7, even with
    # row-first as the only enabled shape.
    out = run(args.booksim, islands=9, path_en=1, policy="none", vcs=1,
              extra="srota_isl_route = colfirst;")
    R.add("F1/RT-R7", "colfirst rule, policy=none path_en=1", "cycle",
          cdg_verdict(out), cdg_verdict(out) == "cycle")
    out = run(args.booksim, islands=9, path_en=3, policy="rank", vcs=2,
              extra="srota_isl_route = colfirst;")
    R.add("F1/RT-R7", "colfirst rule, policy=rank", "acyclic",
          cdg_verdict(out), cdg_verdict(out) == "acyclic")

    # ------------------------------------------------------------------
    # Planes, TOPO-003 sections 5, 13.2.
    # ------------------------------------------------------------------
    print("\n== PLANE: D / C / T (TOPO-003 5) ==")
    PL = SB + (" srota_planes = 7; subnets = 2; classes = 2;"
               " class_subnet = {0,1}; srota_d_num_vcs = 1;"
               " injection_rate = {0.02,0.01}; packet_size = {4,1};")
    out = run(args.booksim, path_en=1, policy="none", vcs=3, extra=PL)
    rates = [float(x) for x in re.findall(
        r"Accepted packet rate average = ([0-9.e-]+) \(", out)]
    R.add("PLANE", "D+C: both planes deliver", "2 classes > 0",
          ",".join("%.4f" % r for r in rates) or "none",
          len(rates) == 2 and all(r > 0 for r in rates)
          and "Srota Plane C" in out)
    out = run(args.booksim, path_en=1, policy="none", vcs=3,
              extra="srota_planes = 7;")
    R.add("PLANE", "C without a second subnet", "refused",
          "refused" if "config error" in out else "accepted",
          "config error" in out)
    out = run(args.booksim, extra="srota_planes = 6;")
    R.add("PLANE", "planes without D", "refused",
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
