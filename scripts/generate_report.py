#!/usr/bin/env python3
"""
VeritX Report Generator — aggregates simulation results and generates plots.

Usage: python3 scripts/generate_report.py
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_results(track_dir: Path):
    results = []
    for result_file in track_dir.glob("results/*.json"):
        with open(result_file) as f:
            data = json.load(f)
            results.append(data)
    return results


def plot_latency_vs_injection(results, track_name: str, output_dir: Path):
    """Latency vs injection rate — standard NoC characterization plot."""
    fig, ax = plt.subplots(figsize=(8, 5))
    for result in results:
        inj = np.array(result.get("injection_rates", []))
        lat = np.array(result.get("latencies", []))
        label = result.get("label", "experiment")
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
            print(f"  ⚠  {track}: directory not found, skipping")
            continue
        results = load_results(track_dir)
        if not results:
            print(f"  ⚠  {track}: no results found")
            continue
        plot_latency_vs_injection(results, track, output_dir)
        summary[track] = len(results)
        print(f"  ✓  {track}: {len(results)} result(s) → {output_dir}/{track}_latency.png")

    # Write summary JSON
    summary_path = output_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n✅ Report generated: {output_dir}/")
    print(f"   Summary: {summary_path}")


if __name__ == "__main__":
    generate_report()
