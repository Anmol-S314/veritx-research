#!/usr/bin/env python3
"""
srota_trust_check.py — the MR12 §7 trust methodology as an executable gate.

MR12-TRACE-VALIDATION.md §7 adopted five checks for "all future numbers".
They were applied by hand there. This runs them, so a Srota result either
passes the gate or is not quoted.

    1. Conservation      packets in == packets out; mean injected size
                         matches the input mean (catches parse bugs free).
    2. Two rulers        the same events fed through the CSV dialect and the
                         veritx {cyc src cl dst sz} dialect must produce
                         bit-identical per-packet results. Same physics,
                         two injectors.
    3. Physical bounds   latency >= serialization + hops; completion horizon
                         must cover the trace span.
    4. Determinism       different seeds, bit-identical output.
    5. Ruler awareness   report which baseline produced the numbers, so a
                         pre-fix tail is never quoted as a post-fix one.

Usage:
    python3 srota_trust_check.py --config <booksim.config> --trace <trace.csv>

The config supplies topology and router parameters; this script overrides
trace_file, trace_packet_log and seed per run, so one config serves every
check.
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_BOOKSIM = REPO / "third_party" / "booksim2" / "src" / "booksim"

# Config keys this harness owns; any value for them in the input config is
# replaced, so the caller's config cannot silently fight the checks.
OWNED = ("trace_file", "trace_packet_log", "seed", "sim_type")


def read_trace(path):
    """Load a CSV trace. Returns (events, had_header)."""
    events = []
    had_header = False
    with open(path) as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line[0] in "#%":
                continue
            fields = line.split(",")
            if len(fields) < 5:
                sys.exit(f"{path}:{line_no}: need >=5 comma-separated fields")
            if not fields[0].lstrip("-").isdigit():
                if line_no == 1 or not events:
                    had_header = True
                    continue
                sys.exit(f"{path}:{line_no}: non-numeric timestamp")
            events.append({
                "timestamp": int(fields[0]),
                "src": int(fields[1]),
                "dst": int(fields[2]),
                "type": fields[3],
                "size": int(fields[4]),
                "txn": fields[5] if len(fields) > 5 else str(line_no),
                # Arbitration header fields, optional on input.
                "slack": int(fields[6]) if len(fields) > 6 else 0,
                "batch": int(fields[7]) if len(fields) > 7 else 0,
                "golden_id": int(fields[8]) if len(fields) > 8 else 0,
            })
    return events, had_header


def write_veritx(events, path):
    """Emit the same events in the veritx whitespace dialect: cyc src cl dst sz.

    The loader content-sniffs on the absence of a comma, so this exercises
    the other parser on identical content.
    """
    with open(path, "w") as f:
        for e in events:
            # The arbitration fields are written even when all zero: once
            # the arbiter is active they change the result, so a dialect
            # comparison that dropped them would silently stop comparing
            # the same run.
            f.write(f"{e['timestamp']} {e['src']} 0 {e['dst']} {e['size']} "
                    f"{e['slack']} {e['batch']} {e['golden_id']}\n")


def derive_config(src_config, out_config, trace_file, packet_log, seed):
    """Copy a config, stripping keys this harness owns, then append ours."""
    text = Path(src_config).read_text()
    kept = []
    for line in text.splitlines():
        key = line.split("=")[0].strip()
        if key in OWNED:
            continue
        kept.append(line)
    kept += [
        "",
        "// --- injected by srota_trust_check.py ---",
        "sim_type = trace;",
        f"trace_file = {trace_file};",
        f"trace_packet_log = {packet_log};",
        f"seed = {seed};",
    ]
    Path(out_config).write_text("\n".join(kept) + "\n")


def run_booksim(booksim, config, log_path):
    with open(log_path, "w") as log:
        rc = subprocess.call([str(booksim), str(config)], stdout=log,
                             stderr=subprocess.STDOUT)
    return rc


def read_packet_log(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def percentiles(values):
    """Nearest-rank percentiles, matching how BookSim reports them."""
    if not values:
        return {}
    s = sorted(values)
    def at(p):
        idx = min(len(s) - 1, max(0, int(round(p / 100.0 * len(s) + 0.5)) - 1))
        return s[idx]
    return {"p50": at(50), "p95": at(95), "p99": at(99),
            "min": s[0], "max": s[-1]}


class Report:
    def __init__(self):
        self.rows = []
        self.failed = 0

    def check(self, name, ok, detail):
        self.rows.append((name, "PASS" if ok else "FAIL", detail))
        if not ok:
            self.failed += 1
        return ok

    def note(self, name, detail):
        self.rows.append((name, "INFO", detail))

    def render(self):
        w = max(len(r[0]) for r in self.rows)
        out = ["", f"{'CHECK'.ljust(w)}  RESULT  DETAIL",
               f"{'-' * w}  ------  " + "-" * 46]
        for name, res, detail in self.rows:
            out.append(f"{name.ljust(w)}  {res.ljust(6)}  {detail}")
        out.append("")
        if self.failed:
            out.append(f"{self.failed} check(s) FAILED — do not quote these numbers.")
        else:
            out.append("All checks passed.")
        return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="booksim config (topology + router params)")
    ap.add_argument("--trace", required=True, help="input trace CSV")
    ap.add_argument("--booksim", default=str(DEFAULT_BOOKSIM))
    ap.add_argument("--seeds", default="0,7065408",
                    help="comma-separated seeds for the determinism check")
    ap.add_argument("--workdir", default=None,
                    help="keep intermediates here instead of a temp dir")
    args = ap.parse_args()

    booksim = Path(args.booksim)
    if not booksim.exists():
        sys.exit(f"booksim binary not found: {booksim}\n"
                 f"build it with: make tool-build TOOL=booksim2")

    seeds = [s.strip() for s in args.seeds.split(",") if s.strip()]
    if len(seeds) < 2:
        sys.exit("--seeds needs at least two values for the determinism check")

    events, _ = read_trace(args.trace)
    if not events:
        sys.exit(f"{args.trace}: no events")

    # Self-loops are dropped by the injector (both dialects), so they are not
    # part of the expected population. MR12 §6 flagged that gen_trace.py can
    # emit them; this accounts for them rather than tripping on them.
    self_loops = sum(1 for e in events if e["src"] == e["dst"])
    expected = len(events) - self_loops

    tmp = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="srota_trust_"))
    tmp.mkdir(parents=True, exist_ok=True)
    keep = args.workdir is not None

    rep = Report()
    rep.note("input", f"{len(events)} events, {self_loops} self-loop(s), "
                      f"{expected} expected packets")

    try:
        # ---- Run A: CSV dialect, seed[0] -------------------------------
        csv_trace = tmp / "a.csv"
        shutil.copyfile(args.trace, csv_trace)
        cfg_a, log_a, out_a = tmp / "a.config", tmp / "a.log", tmp / "a_packets.csv"
        derive_config(args.config, cfg_a, csv_trace, out_a, seeds[0])
        rc_a = run_booksim(booksim, cfg_a, log_a)
        rep.check("exit code (csv dialect)", rc_a == 0, f"rc={rc_a}")
        if rc_a != 0:
            print(rep.render())
            print(f"\nlog: {log_a}")
            return 1
        pkts_a = read_packet_log(out_a)

        # ---- 1. Conservation -------------------------------------------
        rep.check("1. conservation: count", len(pkts_a) == expected,
                  f"in {expected}, out {len(pkts_a)}")
        in_mean = sum(e["size"] for e in events if e["src"] != e["dst"]) / max(1, expected)
        out_mean = (sum(int(p["packet_size_flits"]) for p in pkts_a) / len(pkts_a)) if pkts_a else 0
        rep.check("1. conservation: mean size", abs(in_mean - out_mean) < 1e-9,
                  f"in {in_mean:.4f}, out {out_mean:.4f}")

        # ---- 2. Two rulers, one physics --------------------------------
        vx_trace = tmp / "b.txt"
        write_veritx(events, vx_trace)
        cfg_b, log_b, out_b = tmp / "b.config", tmp / "b.log", tmp / "b_packets.csv"
        derive_config(args.config, cfg_b, vx_trace, out_b, seeds[0])
        rc_b = run_booksim(booksim, cfg_b, log_b)
        rep.check("exit code (veritx dialect)", rc_b == 0, f"rc={rc_b}")
        pkts_b = read_packet_log(out_b) if rc_b == 0 else []

        lat_a = [int(p["total_latency"]) for p in pkts_a]
        lat_b = [int(p["total_latency"]) for p in pkts_b]
        pa, pb = percentiles(lat_a), percentiles(lat_b)
        same_pop = len(lat_a) == len(lat_b)
        same_dist = sorted(lat_a) == sorted(lat_b)
        rep.check("2. two rulers: population", same_pop,
                  f"csv {len(lat_a)}, veritx {len(lat_b)}")
        rep.check("2. two rulers: distribution", same_dist,
                  f"csv p50/p95/p99 {pa.get('p50')}/{pa.get('p95')}/{pa.get('p99')}"
                  f"  veritx {pb.get('p50')}/{pb.get('p95')}/{pb.get('p99')}")

        # The arbitration fields must survive both parsers identically, or
        # an arbiter run measured through one dialect is not the run the
        # other dialect reports.
        def arb_sig(pkts):
            if not pkts or "slack" not in pkts[0]:
                return None
            return sorted((p["slack"], p["batch"], p["golden_id"]) for p in pkts)
        sa, sb = arb_sig(pkts_a), arb_sig(pkts_b)
        if sa is not None:
            rep.check("2. two rulers: arbitration fields", sa == sb,
                      f"{len(set(s[0] for s in sa))} slack class(es) present, "
                      + ("identical across dialects" if sa == sb else "DIFFER"))

        # ---- 3. Physical bounds ----------------------------------------
        # A packet cannot beat serialization plus one cycle per hop. The
        # logged hop count includes the injection channel.
        viol, worst = 0, None
        per_hop = {}
        for p in pkts_a:
            size = int(p["packet_size_flits"])
            hops = int(p["hops"])
            lat = int(p["total_latency"])
            floor = (size - 1) + hops
            if lat < floor:
                viol += 1
                worst = (lat, floor, size, hops)
            per_hop.setdefault(hops, []).append(int(p["network_latency"]))
        rep.check("3. bounds: latency >= serialization+hops", viol == 0,
                  f"{viol} violation(s)" + (f", worst {worst}" if worst else ""))

        hop_mins = {h: min(v) for h, v in sorted(per_hop.items())}
        incr = "n/a"
        if len(hop_mins) >= 2:
            hs = sorted(hop_mins)
            incr = f"{hop_mins[hs[-1]] - hop_mins[hs[0]]} cyc over {hs[-1]-hs[0]} hop(s)"
        rep.note("3. bounds: min net latency by hop",
                 ", ".join(f"{h}:{m}" for h, m in hop_mins.items()) + f" (delta {incr})")

        span = max(e["timestamp"] for e in events)
        horizon = max(int(p["arrival_time"]) for p in pkts_a)
        rep.check("3. bounds: completion covers span", horizon >= span,
                  f"trace span {span}, horizon {horizon}")

        # ---- 4. Determinism --------------------------------------------
        cfg_c, log_c, out_c = tmp / "c.config", tmp / "c.log", tmp / "c_packets.csv"
        derive_config(args.config, cfg_c, csv_trace, out_c, seeds[1])
        rc_c = run_booksim(booksim, cfg_c, log_c)
        rep.check("exit code (seed 2)", rc_c == 0, f"rc={rc_c}")
        if rc_c == 0:
            same = Path(out_a).read_text() == Path(out_c).read_text()
            rep.check("4. determinism: seed-invariant", same,
                      f"seed {seeds[0]} vs {seeds[1]}, packet logs "
                      + ("identical" if same else "DIFFER"))

        # ---- 5. Ruler awareness ----------------------------------------
        # The post-fix ruler is arrival - request_time. Confirm the log is
        # actually reporting that, rather than a ctime-derived figure.
        ruler_ok = True
        for p in pkts_a[:200]:
            if int(p["total_latency"]) != int(p["arrival_time"]) - int(p["request_time"]):
                ruler_ok = False
                break
        rep.check("5. ruler: total_latency == arrival - request_time", ruler_ok,
                  "post-fix honest baseline" if ruler_ok
                  else "NOT the request-time ruler — tails are suspect")
        q = [int(p["source_queue_delay"]) for p in pkts_a]
        rep.note("5. ruler: source queue delay",
                 f"mean {sum(q)/len(q):.2f}, max {max(q)}" if q else "n/a")

        rep.note("result", f"p50/p95/p99 = {pa.get('p50')}/{pa.get('p95')}/{pa.get('p99')}"
                           f", n={len(lat_a)}")

        # Per-slack-class results: the M3 headline is critical-class tail
        # latency, not the aggregate.
        if pkts_a and "slack" in pkts_a[0]:
            per = {}
            for p in pkts_a:
                per.setdefault(int(p["slack"]), []).append(int(p["total_latency"]))
            if len(per) > 1:
                for s in sorted(per):
                    q = percentiles(per[s])
                    rep.note(f"result: slack {s}",
                             f"n={len(per[s])}  p50/p95/p99 = "
                             f"{q['p50']}/{q['p95']}/{q['p99']}")

        print(rep.render())
        if keep:
            print(f"\nintermediates kept in {tmp}")
        return 1 if rep.failed else 0
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
