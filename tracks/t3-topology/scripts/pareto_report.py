#!/usr/bin/env python3
"""PA-04 — multi-objective Pareto analysis across topologies.

Reads one or more sweep JSONs written by run_experiments.py and reduces
each topology to four objectives:

  zero_load_latency  cycles, lowest swept rate with a stable run   (min)
  energy_flit_hops   hops_avg x packet_size at that rate           (min)
                     -- or noc_energy.json's pJ when the Accelergy
                        bridge has run, reported alongside
  storage_flits      input buffering summed over routers           (min)
                     (booksim "Network cost" line: the area proxy)
  peak_throughput    highest accepted packet rate over the sweep   (max)

It marks the non-dominated set in all four at once, plots the 2-D
projections a reader actually looks at, and writes a table + markdown
summary. Nothing here knows about any particular topology.

Caveat printed into every summary: energy_flit_hops counts router
traversals, not wire length. A MECS express hop spans up to k-1 tile
pitches in one router traversal, so this proxy flatters express
topologies on wire energy; it is fair on router (buffer + crossbar)
energy, which is what it measures.

Usage:
  pareto_report.py --sweep results/X/topology_sweep.json [--sweep ...]
                   --labels matrix,uniform --out results/X/analysis/pareto
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import saturation_point, sat_k  # noqa: E402

import matplotlib
matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
import matplotlib.pyplot as plt  # noqa: E402

TRACK = Path(__file__).resolve().parent.parent

# Srota arms are drawn in one colour family so the comparison reads at a
# glance; everything else gets a neutral palette.
SROTA_COLORS = ["#c0392b", "#e67e22", "#8e44ad", "#d35400"]
OTHER_COLORS = ["#2c3e50", "#16a085", "#2980b9", "#7f8c8d", "#27ae60",
                "#34495e", "#95a5a6", "#1abc9c"]


def _packet_size(topology: str) -> int:
    cfg = TRACK / "configs" / f"{topology}.cfg"
    if not cfg.exists():
        return 1
    for line in cfg.read_text().splitlines():
        line = line.split("//")[0].strip().rstrip(";")
        if line.startswith("packet_size") and "=" in line:
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return 1
    return 1


def summarise(rows: list) -> dict:
    """topology -> objective dict. Skipped/failed arms are dropped."""
    by = {}
    for r in rows:
        if r.get("status") not in ("ok", "unstable"):
            continue
        by.setdefault(r["topology"], []).append(r)

    out = {}
    for topo, rs in by.items():
        rs.sort(key=lambda r: r["injection_rate"])
        stable = [r for r in rs if r["status"] == "ok"
                  and r.get("latency_cycles") is not None]
        if not stable:
            continue
        z = stable[0]
        rates = [r["injection_rate"] for r in stable]
        lats = [r["latency_cycles"] for r in stable]
        sat = saturation_point(rates, lats, sat_k())
        # A run that went unstable is saturated by definition; the first
        # such rate bounds saturation even when latency never crossed k x.
        first_unstable = next((r["injection_rate"] for r in rs
                               if r["status"] == "unstable"), None)
        if sat is None or (first_unstable is not None and first_unstable < sat):
            sat = first_unstable
        thr = [r["accepted_rate"] for r in rs
               if r.get("accepted_rate") is not None]
        psize = _packet_size(topo)
        out[topo] = {
            "zero_load_rate": z["injection_rate"],
            "zero_load_latency": z["latency_cycles"],
            "hops_avg": z.get("hops_avg"),
            "energy_flit_hops": (z["hops_avg"] * psize
                                 if z.get("hops_avg") is not None else None),
            "storage_flits": z.get("storage_flits"),
            "crosspoints": z.get("crosspoints"),
            "routers": z.get("routers"),
            "peak_throughput": max(thr) if thr else None,
            "saturation_rate": sat,
            "max_rate_swept": rs[-1]["injection_rate"],
            "curve": [(r["injection_rate"], r["latency_cycles"], r["status"])
                      for r in rs if r.get("latency_cycles") is not None],
            "srota": next((r.get("srota") for r in reversed(rs)
                           if r.get("srota")), None),
        }
    return out


OBJ = [("zero_load_latency", "min"), ("energy_flit_hops", "min"),
       ("storage_flits", "min"), ("peak_throughput", "max")]


def pareto_set(summary: dict, objectives=OBJ) -> set:
    """Topologies not dominated on `objectives` (missing values excluded)."""
    pts = {t: s for t, s in summary.items()
           if all(s.get(k) is not None for k, _ in objectives)}

    def better_eq(a, b, sense):
        return a <= b if sense == "min" else a >= b

    def strictly(a, b, sense):
        return a < b if sense == "min" else a > b

    front = set()
    for t, s in pts.items():
        dominated = False
        for u, o in pts.items():
            if u == t:
                continue
            if all(better_eq(o[k], s[k], d) for k, d in objectives) and \
               any(strictly(o[k], s[k], d) for k, d in objectives):
                dominated = True
                break
        if not dominated:
            front.add(t)
    return front


def _colors(topos):
    cmap, si, oi = {}, 0, 0
    for t in sorted(topos):
        if t.startswith("srota"):
            cmap[t] = SROTA_COLORS[si % len(SROTA_COLORS)]; si += 1
        else:
            cmap[t] = OTHER_COLORS[oi % len(OTHER_COLORS)]; oi += 1
    return cmap


def plot_curves(summary: dict, title: str, path: Path, cmap: dict):
    fig, ax = plt.subplots(figsize=(8, 5))
    for t in sorted(summary):
        c = summary[t]["curve"]
        xs = [p[0] for p in c]
        ys = [p[1] for p in c]
        ax.plot(xs, ys, "-o", ms=4, lw=2.2 if t.startswith("srota") else 1.4,
                color=cmap[t], label=t)
        uns = [(x, y) for x, y, st in c if st == "unstable"]
        if uns:
            ax.scatter(*zip(*uns), marker="x", s=60, color=cmap[t])
    ax.set_yscale("log")
    ax.set_xlabel("offered load (packets/node/cycle)")
    ax.set_ylabel("mean packet latency (cycles, log)")
    ax.set_title(title + "  (x = unstable / past saturation)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_front(summary, front2d, xk, yk, xs_sense, ys_sense, xl, yl,
               title, path, cmap, logx=False):
    pts = {t: s for t, s in summary.items()
           if s.get(xk) is not None and s.get(yk) is not None}
    if not pts:
        return
    fig, ax = plt.subplots(figsize=(7, 5))
    for t, s in pts.items():
        on = t in front2d
        ax.scatter(s[xk], s[yk], s=140 if on else 60, color=cmap[t],
                   edgecolors="black" if on else "none", linewidths=1.5,
                   zorder=3)
        ax.annotate(t, (s[xk], s[yk]), textcoords="offset points",
                    xytext=(6, 5), fontsize=8)
    fr = sorted((pts[t][xk], pts[t][yk]) for t in front2d if t in pts)
    if len(fr) > 1:
        if ys_sense == "max":
            fr = sorted(fr)
        ax.step([p[0] for p in fr], [p[1] for p in fr], where="post",
                color="black", lw=1, ls="--", alpha=0.6, zorder=2)
    if logx:
        ax.set_xscale("log")
    ax.set_xlabel(xl + ("  (lower is better)" if xs_sense == "min" else "  (higher is better)"))
    ax.set_ylabel(yl + ("  (lower is better)" if ys_sense == "min" else "  (higher is better)"))
    ax.set_title(title + "\noutlined = Pareto-optimal in this projection")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _fmt(v, nd=3):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}g}" if abs(v) < 1e4 else f"{v:.0f}"
    return str(v)


def write_outputs(label: str, summary: dict, out: Path, energy_pj: dict):
    out.mkdir(parents=True, exist_ok=True)
    cmap = _colors(summary)
    front = pareto_set(summary)

    plot_curves(summary, f"Latency vs load — {label}",
                out / f"latency_curves_{label}.png", cmap)
    two = [
        ("storage_flits", "zero_load_latency", "min", "min",
         "input storage (flits, area proxy)", "zero-load latency (cycles)",
         "latency_vs_storage", True),
        ("storage_flits", "peak_throughput", "min", "max",
         "input storage (flits, area proxy)", "peak accepted throughput (pkt/node/cycle)",
         "throughput_vs_storage", True),
        ("energy_flit_hops", "zero_load_latency", "min", "min",
         "energy proxy (flit-hops per packet)", "zero-load latency (cycles)",
         "latency_vs_energy", False),
    ]
    for xk, yk, xs, ys, xl, yl, name, logx in two:
        f2 = pareto_set(summary, [(xk, xs), (yk, ys)])
        plot_front(summary, f2, xk, yk, xs, ys, xl, yl,
                   f"{name.replace('_', ' ')} — {label}",
                   out / f"pareto_{name}_{label}.png", cmap, logx)

    cols = ["topology", "pareto_4d", "zero_load_latency", "hops_avg",
            "energy_flit_hops", "energy_pJ", "storage_flits", "crosspoints",
            "routers", "peak_throughput", "saturation_rate"]
    lines = [",".join(cols)]
    md = [f"### {label}", "",
          "| topology | Pareto (4-D) | zero-load lat | hops | energy (flit-hops) | "
          "energy (pJ, Accelergy) | storage (flits) | crosspoints | peak thr | sat. rate |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(summary, key=lambda t: summary[t]["zero_load_latency"]):
        s = summary[t]
        epj = energy_pj.get(t)
        sat = s["saturation_rate"]
        sat_s = _fmt(sat) if sat is not None else f"> {s['max_rate_swept']}"
        row = [t, "yes" if t in front else "no", s["zero_load_latency"],
               s["hops_avg"], s["energy_flit_hops"], epj, s["storage_flits"],
               s["crosspoints"], s["routers"], s["peak_throughput"], sat]
        lines.append(",".join("" if v is None else str(v) for v in row))
        md.append(f"| {'**'+t+'**' if t.startswith('srota') else t} | "
                  f"{'✔' if t in front else ''} | {_fmt(s['zero_load_latency'])} | "
                  f"{_fmt(s['hops_avg'])} | {_fmt(s['energy_flit_hops'])} | "
                  f"{_fmt(epj)} | {_fmt(s['storage_flits'])} | "
                  f"{_fmt(s['crosspoints'])} | {_fmt(s['peak_throughput'])} | {sat_s} |")
    (out / f"pareto_{label}.csv").write_text("\n".join(lines) + "\n")
    return md, front


def _load_energy(sweep_path: Path) -> dict:
    """topology -> pJ per packet at the lowest rate, from noc_energy.json."""
    p = sweep_path.parent / "noc_energy.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {}
    out = {}
    for t, pts in (data.get("per_topology") or {}).items():
        if pts:
            out[t] = sorted(pts)[0][2]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sweep", action="append", required=True)
    ap.add_argument("--labels", default=None,
                    help="comma-separated, one per --sweep")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    labels = (a.labels.split(",") if a.labels
              else [Path(s).parent.name for s in a.sweep])
    out = Path(a.out)
    md_all = ["# Topology Pareto analysis", "",
              f"Objectives: zero-load latency (min), energy proxy (min), "
              f"input storage (min), peak accepted throughput (max). "
              f"Saturation = first rate with latency > {sat_k()}x zero-load, "
              f"or the first unstable run. Srota arms in bold.", "",
              "> Energy proxy counts router traversals (flit-hops), not wire "
              "length: a MECS express hop crosses up to k-1 tile pitches in one "
              "traversal, so express topologies are flattered on wire energy "
              "and measured fairly on router energy.", ""]
    for sweep, label in zip(a.sweep, labels):
        rows = json.loads(Path(sweep).read_text())
        summary = summarise(rows)
        md, front = write_outputs(label, summary, out, _load_energy(Path(sweep)))
        md_all += md + ["", f"Pareto-optimal (all four objectives): "
                        f"{', '.join(sorted(front)) or 'none'}", ""]
        srows = [(t, s["srota"]) for t, s in sorted(summary.items()) if s["srota"]]
        if srows:
            md_all += ["Srota side-buffer / island counters (highest swept rate, "
                       "whole run):", ""]
            for t, st in srows:
                keep = {k: v for k, v in st.items() if k != "island"}
                md_all.append(f"- `{t}`: " + ", ".join(f"{k}={v}" for k, v in keep.items()))
                for isl in st.get("island", []):
                    md_all.append(f"  - island {isl}")
            md_all.append("")
        print(f"[{label}] {len(summary)} topologies; Pareto-optimal: "
              f"{', '.join(sorted(front))}")
    (out / "pareto_summary.md").write_text("\n".join(md_all) + "\n")
    print(f"Written -> {out}/")


if __name__ == "__main__":
    main()
