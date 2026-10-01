#!/usr/bin/env python3
"""
Srota NoC injection-rate sweep.

Runs a load sweep over one or more Srota configurations and prints
latency / accepted-throughput per rate, plus the saturation point (the
last rate that stayed stable). Use it to compare arms of an experiment on
identical traffic -- VC policies, MECS on/off, path-shape sets, radix.

Examples:

  # default: compare the RT-R7 resolutions at k=8
  python3 srota_sweep.py --compare vc_policy

  # express layer vs the ablation baseline
  python3 srota_sweep.py --compare mecs --k 16 --c 4

  # path-shape diversity under skewed traffic (the MoE hot-column case)
  python3 srota_sweep.py --compare path_en --traffic transpose

  # one config, fine rate steps
  python3 srota_sweep.py --rates 0.02,0.04,0.06,0.08,0.10

Anything not swept is held fixed across every arm, so the comparison is
apples to apples. Every arm's config is printed with --verbose.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

CONFIG = """
topology = srota;
routing_function = o1turn;
k = {k};
c = {c};
srota_mecs = {mecs};
srota_path_en = {path_en};
srota_vc_policy = {vc_policy};
srota_island_col_map = {islands};
srota_cong_thresh = {thresh};
srota_epoch_len = {epoch};
srota_drop_latency = {drop_lat};
srota_tel_period = 4;
srota_tel_latency = 8;
srota_cdg_radix = {cdg};
num_vcs = {vcs};
vc_buf_size = {buf};
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
traffic = {traffic};
packet_size = {psize};
injection_rate = {rate};
sim_type = latency;
warmup_periods = 3;
sample_period = {period};
sim_count = 1;
"""

BASE = dict(k=8, c=4, mecs=3, path_en=7, vc_policy="rank", islands=0,
            thresh=8, epoch=1024, drop_lat=1, cdg=4, vcs=8, buf=8,
            traffic="uniform", psize=5, period=1000)

# Each comparison names the key it varies and the arms to run. vcs is
# raised where a policy needs more VC sets; everything else is held fixed.
COMPARISONS = {
    "vc_policy": [
        ("none (unmitigated, RT-R7)", dict(vc_policy="none",  path_en=3, vcs=1)),
        ("oneshape (4.5.3 opt 1)",    dict(vc_policy="oneshape", path_en=3, vcs=1)),
        ("shape (4.5.3 opt 2)",       dict(vc_policy="shape", path_en=3, vcs=8)),
        ("rank (all shapes live)",    dict(vc_policy="rank",  path_en=7, vcs=8)),
    ],
    "mecs": [
        ("MECS on (express)",  dict(mecs=3, path_en=7, vc_policy="rank", vcs=8)),
        ("MECS off (ablation)", dict(mecs=0, path_en=3, vc_policy="rank", vcs=8)),
    ],
    "path_en": [
        ("row-first only",      dict(path_en=1, vc_policy="rank", vcs=8)),
        ("row + column",        dict(path_en=3, vc_policy="rank", vcs=8)),
        ("row + column + valiant", dict(path_en=7, vc_policy="rank", vcs=8)),
    ],
    "drop_latency": [
        ("1-cycle drop",            dict(drop_lat=1)),
        ("2-cycle (repeatered)",    dict(drop_lat=2)),
    ],
}

DEFAULT_RATES = [0.005, 0.01, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.20]


def run_one(booksim, cfg, verbose=False):
    text = CONFIG.format(**cfg)
    if verbose:
        print(text)
    with tempfile.NamedTemporaryFile("w", suffix=".config", delete=False) as fh:
        fh.write(text)
        path = fh.name
    try:
        p = subprocess.run([booksim, path], capture_output=True, text=True,
                           timeout=1800)
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        out = "<<TIMEOUT>>"
    finally:
        os.unlink(path)

    def last(pattern, cast=float):
        m = re.findall(pattern, out)
        return cast(m[-1]) if m else None

    return dict(
        latency=last(r"Packet latency average = ([\d.]+) \("),
        p99=last(r"p99 = ([\d.]+)"),
        hops=last(r"Hops average = ([\d.]+)"),
        accepted=last(r"Accepted flit rate average\s*=\s*([\d.]+)"),
        unstable=("unstable" in out.lower() or "<<TIMEOUT>>" in out),
        cycle=("CYCLE FOUND" in out),
        error=("config error" in out),
        raw=out,
    )


def sweep(booksim, label, overrides, rates, fixed, verbose):
    cfg = dict(BASE)
    cfg.update(fixed)
    cfg.update(overrides)

    print("\n--- %s ---" % label)
    # The CDG verdict is a property of the configuration, not the load, so
    # report it once rather than per rate.
    probe = run_one(booksim, dict(cfg, rate=rates[0]), verbose)
    if probe["error"]:
        print("   config refused:")
        for line in probe["raw"].splitlines():
            if "config error" in line or line.startswith("   "):
                print("     " + line.strip())
        return None
    print("   F1 CDG: %s" % ("CYCLE (deadlock reachable)" if probe["cycle"]
                             else "acyclic"))

    print("   %-8s %10s %10s %10s %8s" %
          ("rate", "lat(avg)", "lat(p99)", "accepted", "stable"))
    sat = None
    for r in rates:
        res = probe if r == rates[0] else run_one(booksim, dict(cfg, rate=r))
        if res["latency"] is None:
            print("   %-8s %10s" % (r, "no data"))
            continue
        stable = not res["unstable"]
        if stable:
            sat = r
        print("   %-8s %10.1f %10s %10.4f %8s" %
              (r, res["latency"],
               ("%.0f" % res["p99"]) if res["p99"] else "-",
               res["accepted"] or 0.0,
               "yes" if stable else "NO"))
    print("   saturation: last stable rate = %s" % (sat if sat else "none"))
    return sat


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--booksim", default="./booksim")
    ap.add_argument("--compare", choices=sorted(COMPARISONS),
                    help="run a predefined multi-arm comparison")
    ap.add_argument("--rates", help="comma-separated injection rates")
    ap.add_argument("--k", type=int)
    ap.add_argument("--c", type=int)
    ap.add_argument("--traffic")
    ap.add_argument("--packet-size", type=int, dest="psize")
    ap.add_argument("--vc-policy", dest="vc_policy")
    ap.add_argument("--path-en", type=int, dest="path_en")
    ap.add_argument("--num-vcs", type=int, dest="vcs")
    ap.add_argument("--period", type=int, help="sample period (default 1000)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not os.access(args.booksim, os.X_OK):
        sys.exit("no booksim binary at %s -- run make first" % args.booksim)

    rates = ([float(x) for x in args.rates.split(",")]
             if args.rates else DEFAULT_RATES)

    fixed = {k: v for k, v in vars(args).items()
             if v is not None and k in BASE}

    if args.compare:
        arms = COMPARISONS[args.compare]
        print("== Srota sweep: comparing %s ==" % args.compare)
        print("   held fixed: " + ", ".join(
            "%s=%s" % (k, dict(BASE, **fixed)[k])
            for k in ("k", "c", "traffic", "psize", "buf")))
        results = []
        for label, ov in arms:
            results.append((label, sweep(args.booksim, label, ov, rates,
                                         fixed, args.verbose)))
        print("\n== saturation summary ==")
        for label, sat in results:
            print("   %-28s %s" % (label, sat if sat else "refused/none"))
    else:
        sweep(args.booksim, "single config", {}, rates, fixed, args.verbose)

    return 0


if __name__ == "__main__":
    sys.exit(main())
