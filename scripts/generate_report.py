#!/usr/bin/env python3
"""
VeritX Report Generator — aggregates simulation results and generates plots.

Input format: a list of {"injection_rate": ..., "latency_cycles": ..., "topology": "..."}
records (T3 topology_sweep.json, T2 experiments.json).
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_results(track_dir: Path):
    datasets = []
    for result_file in sorted(track_dir.glob("results/*.json")):
        if result_file.name == "history.json":
            continue
        with open(result_file) as f:
            data = json.load(f)
        # List-of-records format (T3 topology_sweep.json, T2 experiments.json)
        if isinstance(data, list):
            by_topology = {}
            for record in data:
                topo = record.get("topology") or record.get("config", "default")
                rate = record.get("injection_rate")
                lat = record.get("latency_cycles") or record.get("latency")
                if rate is not None and lat is not None:
                    by_topology.setdefault(topo, {"rates": [], "lats": []})
                    by_topology[topo]["rates"].append(rate)
                    by_topology[topo]["lats"].append(lat)
            for topo, pts in by_topology.items():
                # sort by rate
                pairs = sorted(zip(pts["rates"], pts["lats"]))
                datasets.append({
                    "injection_rates": [p[0] for p in pairs],
                    "latencies": [p[1] for p in pairs],
                    "label": topo,
                })
    return datasets


def plot_latency_vs_injection(results, track_name: str, output_dir: Path):
    """Latency vs injection rate — standard NoC characterization plot."""
    if not results:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    for result in results:
        inj = result.get("injection_rates", [])
        lat = result.get("latencies", [])
        label = result.get("label", "experiment")
        if inj and lat:
            ax.plot(inj, lat, marker="o", label=label)
    ax.set_xlabel("Injection Rate (flits/node/cycle)")
    ax.set_ylabel("Average Latency (cycles)")
    ax.set_title(f"{track_name} — Latency vs Injection Rate")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.savefig(output_dir / f"{track_name}_latency.png", dpi=150)
    plt.close(fig)


def generate_report():
    tracks_dir = Path("tracks")
    output_dir = Path("report")
    output_dir.mkdir(exist_ok=True)

    track_names = ["t1-kvcache", "t2-deadlock", "t3-topology", "t4-formal"]
    summary = {}

    for track in track_names:
        track_dir = tracks_dir / track
        if not track_dir.exists():
            print(f"  ?  {track}: directory not found, skipping")
            continue
        results = load_results(track_dir)
        if not results:
            print(f"  ?  {track}: no results found")
            continue
        plot_latency_vs_injection(results, track, output_dir)
        summary[track] = len(results)
        print(f"  v  {track}: {len(results)} dataset(s) -> {output_dir}/{track}_latency.png")

    summary_path = output_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nReport generated: {output_dir}/")


if __name__ == "__main__":
    generate_report()
