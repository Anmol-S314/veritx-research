#!/usr/bin/env python3
"""Summarize Timeloop's energy model for the T3 workload.

Parses a Timeloop stats file's "Summary Stats" block into a per-component
pJ/Compute breakdown + total energy + energy-delay product, prints it, and
writes results/energy.json. This is the *accelerator-side* energy (which tile
level burns the most) — the *NoC-side* energy proxy is hops x packet_size from
the Booksim sweep. Together they feed the Wk13 energy-vs-latency Pareto analysis.

  python3 scripts/energy_report.py results/timeloop.stats.txt
"""
import re, json, sys
from pathlib import Path


def parse_energy(text):
    def scalar(pat, cast=float, default=None):
        m = re.search(pat, text)
        return cast(m.group(1)) if m else default

    stats = {
        "utilization": scalar(r"Utilization:\s*([\d.]+)"),
        "cycles": scalar(r"Cycles:\s*(\d+)", int),
        "energy_uJ": scalar(r"Energy:\s*([\d.]+)\s*uJ"),
        "area_mm2": scalar(r"Area:\s*([\d.]+)\s*mm\^2"),
    }
    # per-component pJ/Compute — the "Actual" block (not "Algorithmic")
    tail = text.split("Actual Computes")[-1]
    m = re.search(r"pJ/Compute\s*\n(.*?)(?:\n\s*\n|\Z)", tail, re.S)
    breakdown = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"\s*(\S.*?)\s*=\s*([\d.]+)\s*$", line)
            if mm:
                breakdown[mm.group(1).strip()] = float(mm.group(2))
    stats["total_pj_per_compute"] = breakdown.pop("Total", None)
    stats["pj_per_compute"] = breakdown
    if stats["energy_uJ"] is not None and stats["cycles"]:
        stats["edp_uJ_cycles"] = round(stats["energy_uJ"] * stats["cycles"], 4)  # lower = better
    return stats


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "results/timeloop.stats.txt"
    if arg == "--selfcheck":
        return _selfcheck()
    p = Path(arg)
    if not p.exists():
        sys.exit(f"  no {p} — run the Timeloop spine first (make ... CMD=timeloop)")

    e = parse_energy(p.read_text())

    # Timeloop's own Area is always 0.00 here (its ART hook needs an Accelergy ERT
    # v0.3 and Accelergy 0.4 emits v0.4), so area comes from area_report.py, which
    # queries Accelergy directly -- and unlike Timeloop it also prices the routers.
    m = re.search(r"timeloop_(\d+)\.stats", p.name)
    if m:
        e["nodes"] = int(m.group(1))
        area = p.parent / f"area_{m.group(1)}.json"
        if area.exists():
            e["area"] = json.loads(area.read_text())
            e["area_mm2"] = e["area"]["total_area_mm2"]
        else:
            print(f"  ⚠  no {area.name} — run `make area` for real die area "
                  f"(Timeloop alone reports 0.00)")

    out = p.parent / (f"energy_{e['nodes']}.json" if e.get("nodes") else "energy.json")
    out.write_text(json.dumps(e, indent=2))

    print(f"  Total energy: {e['energy_uJ']} uJ over {e['cycles']} cycles"
          f"  |  EDP {e.get('edp_uJ_cycles')} uJ·cyc  |  util {e['utilization']}")
    bd = e["pj_per_compute"]
    mx = max(bd.values()) if bd else 0
    if bd:
        print("  pJ/compute by component (dominant first — this is your bottleneck):")
        for name, v in sorted(bd.items(), key=lambda kv: -kv[1]):
            bar = "#" * int(round(v / mx * 30)) if mx else ""
            print(f"    {name:<32}{v:8.2f}  {bar}")
        print(f"    {'Total':<32}{e['total_pj_per_compute']:8.2f}")
    if e.get("area"):
        a = e["area"]
        print(f"  Die area: {a['total_area_mm2']} mm^2 — dominated by "
              + ", ".join(f"{k} {v['area_um2_total']/a['total_area_um2']*100:.0f}%"
                          for k, v in sorted(a["components"].items(),
                                             key=lambda kv: -kv[1]["area_um2_total"])[:2]))
    print(f"  -> {out}")


def _selfcheck():
    sample = """Summary Stats
--------------
Utilization: 1.00
Cycles: 256
Energy: 0.08 uJ
Area: 0.00 mm^2

Algorithmic Computes = 4096
pJ/Algorithmic-Compute
    __ARITH__                      = 0.25
    DRAM                           = 18.75
    Total                          = 20.50

Actual Computes = 4096
pJ/Compute
    __ARITH__                      = 0.25
    RegisterFile                   = 1.50
    DRAM                           = 18.75
    Total                          = 20.50
"""
    e = parse_energy(sample)
    assert e["cycles"] == 256 and e["energy_uJ"] == 0.08, e
    assert e["pj_per_compute"]["DRAM"] == 18.75, e                       # dominant component parsed
    assert "Total" not in e["pj_per_compute"], e                        # Total split out, not a component
    assert e["total_pj_per_compute"] == 20.50, e
    assert e["edp_uJ_cycles"] == round(0.08 * 256, 4), e
    print("selfcheck OK")


if __name__ == "__main__":
    main()
