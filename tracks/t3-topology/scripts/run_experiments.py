#!/usr/bin/env python3
"""T3 Topology — sweep injection rate across topologies, collect latency data."""
import subprocess, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONFIG = os.environ.get("CONFIG", "baseline")

CONFIGS_DIR = ROOT / "configs"
RESULTS_DIR = ROOT / "results" / CONFIG
CONFIGS = sorted(CONFIGS_DIR.glob("*.cfg"))

# CI sweep (coarse). Override for local/matrix runs: RATES="0.002,0.005,0.01,0.02"
# (matrix patterns with a hotspot saturate at much lower rates than uniform).
_rates = os.environ.get("RATES")
INJECTION_RATES = [float(x) for x in _rates.split(",")] if _rates else [0.05, 0.1, 0.2, 0.3, 0.4]

# Optional Timeloop-derived traffic matrix (the Timeloop->Booksim bridge). When
# set, every topology is driven by this matrix instead of uniform random traffic.
MATRIX = os.environ.get("TRAFFIC_MATRIX")

# Extra Booksim parameter overrides applied to EVERY config, space-separated,
# e.g. BOOKSIM_EXTRA="use_noc_latency=0 num_vcs=8".
#
# This exists because cross-topology latency numbers are only comparable when
# the arms agree on how channel latency is priced. The configs in configs/ do
# not all set use_noc_latency, so most inherit Booksim's default of 1 while
# srota16.cfg must set 0 (that model prices express channels itself and
# refuses 1). Measured spread on the Timeloop matrix at rate=0.01:
# cmesh16 16.82 -> 16.00, torus4x4 21.44 -> 19.77, mesh4x4 unchanged. Setting
# it uniformly here is what makes a ranking mean anything.
EXTRA = [x for x in os.environ.get("BOOKSIM_EXTRA", "").split() if x]


def run_one(cfg: Path, rate: float) -> dict:
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    cmd = [booksim, str(cfg), f"injection_rate={rate}"] + EXTRA
    if MATRIX:
        cmd.append(f"traffic=matrix({MATRIX})")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out, err = result.stdout, result.stderr
        rc = result.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = "", "timeout", -1

    latency = hops = None
    for line in out.splitlines():
        parts = line.split()
        if "Packet latency average" in line:
            for p in parts:
                try:
                    latency = float(p)
                    break
                except ValueError:
                    pass
        elif "Hops average" in line:
            for p in parts:
                try:
                    hops = float(p)
                    break
                except ValueError:
                    pass

    # Classify failures instead of reporting a bare None. The common one is a
    # node-count mismatch: several configs here are not the size their name
    # suggests (qtree16 and tree4 are 64 nodes, dragonfly16 is 72), so a 16x16
    # matrix cannot drive them and the run is not comparable rather than
    # broken. Booksim says so explicitly; surface that instead of swallowing it.
    blob = out + err
    if latency is not None:
        status = "unstable" if "unstable" in blob.lower() else "ok"
        note = None
    elif "must match topology node count" in blob:
        status, note = "skipped_node_mismatch", _mismatch_note(blob)
    elif rc == -1:
        status, note = "timeout", "exceeded 300s"
    else:
        status = "no_output"
        note = next((l.strip() for l in blob.splitlines()
                     if l.lower().startswith("error")), None)

    return {
        "topology": cfg.stem,
        "injection_rate": rate,
        "traffic": f"matrix({Path(MATRIX).name})" if MATRIX else "uniform",
        "latency_cycles": latency,
        "hops_avg": hops,  # energy proxy = hops_avg * packet_size (Pareto step)
        "status": status,
        "note": note,
        "returncode": rc,
    }


def _mismatch_note(blob: str) -> str:
    for line in blob.splitlines():
        if "must match topology node count" in line:
            return line.strip().lstrip("Error: ")
    return "traffic matrix size does not match this topology's node count"

def main():

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Using configuration: {CONFIG}")

    if EXTRA:
        print("Applying to every config: " + " ".join(EXTRA))
    if MATRIX:
        print(f"Traffic: matrix({MATRIX})")

    results = []
    skipped = {}
    for cfg in CONFIGS:
        # A topology whose node count does not match the matrix fails
        # identically at every rate, so probe once and skip the rest rather
        # than emitting the same error N times.
        if MATRIX:
            probe = run_one(cfg, INJECTION_RATES[0])
            if probe["status"] == "skipped_node_mismatch":
                skipped[cfg.stem] = probe["note"]
                print(f"  {cfg.stem}: SKIPPED — {probe['note']}")
                results.append(probe)
                continue

        for rate in INJECTION_RATES:
            print(f"  {cfg.stem} @ {rate} ...", end=" ")
            res = run_one(cfg, rate)
            flag = "" if res["status"] == "ok" else f"  [{res['status']}]"
            print(f"{res['latency_cycles']}{flag}")
            results.append(res)

    report = RESULTS_DIR / "topology_sweep.json"
    with open(report, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  {len(results)} data points → {report}")

    _print_comparison(results, skipped)


def _print_comparison(results, skipped):
    """Rank the comparable topologies at each rate.

    Only rows with status 'ok' are ranked: an 'unstable' run is past
    saturation and its latency counts completed packets only, so it can
    read LOWER than a slower stable run. Ranking those together would
    invert the result.
    """
    ok = [r for r in results if r["status"] == "ok"]
    if not ok:
        print("\n  no stable data points to compare")
        return

    rates = sorted({r["injection_rate"] for r in ok})
    print("\n  Stable-region latency by topology (lower is better)")
    print("  " + "-" * 62)
    header = "  %-14s" % "topology"
    for rt in rates:
        header += "%11s" % rt
    print(header)

    tops = sorted({r["topology"] for r in ok})
    table = {}
    for t in tops:
        row = "  %-14s" % t
        for rt in rates:
            v = next((r["latency_cycles"] for r in ok
                      if r["topology"] == t and r["injection_rate"] == rt), None)
            table[(t, rt)] = v
            row += "%11s" % ("%.2f" % v if v is not None else "-")
        print(row)

    # Where does srota sit, if it ran?
    if any(t.startswith("srota") for t in tops):
        st = next(t for t in tops if t.startswith("srota"))
        print()
        for rt in rates:
            vals = [(t, table[(t, rt)]) for t in tops if table.get((t, rt))]
            if not vals:
                continue
            vals.sort(key=lambda kv: kv[1])
            pos = [i for i, (t, _) in enumerate(vals) if t == st]
            if not pos:
                continue
            i = pos[0]
            best_t, best_v = vals[0]
            print("  rate=%-8s %s ranks %d/%d (%.2f); best %s (%.2f)"
                  % (rt, st, i + 1, len(vals), vals[i][1], best_t, best_v))

    if skipped:
        print("\n  Not comparable at this matrix size:")
        for t, why in sorted(skipped.items()):
            print("    %-14s %s" % (t, why))

if __name__ == "__main__":
    main()