#!/usr/bin/env python3
"""PA-12 — Energy validation: proxy ranking vs real Booksim power.

Compares the energy proxy ranking (hops_avg × packet_size) against
real Booksim total_power, and documents whether the Pareto frontier
shifts when using real power numbers instead of the proxy.

Produces:
  - Spearman rank correlation between energy_proxy and total_power
  - Per-topology ranking comparison table
  - Top-3 analysis: does the cheapest-energy topology change?
  - A short validation note (output/energy_validation.md)

Usage
-----
    python3 scripts/energy_validate.py                  # print + write report
    python3 scripts/energy_validate.py --selfcheck      # regression tests
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

HERE    = Path(__file__).parent
TRACK   = HERE.parent
RESULTS = TRACK / "results"
OUTPUT  = TRACK / "output"


def compute_rank_correlation(
    df: pd.DataFrame,
    col_a: str = "energy_proxy",
    col_b: str = "total_power",
) -> dict:
    """Compute Spearman rank correlation between two energy metrics.

    Only uses status == 'ok' rows where both columns are non-NaN.
    Groups by topology (uses the zero-load / minimum injection rate row).

    Returns dict with: rho, p_value, n_topologies, ranking_a, ranking_b,
                        top3_a, top3_b, pareto_shifts
    """
    ok = df[df["status"] == "ok"].copy()

    # Take the lowest injection rate per topology (zero-load → least noisy)
    summary = (ok.sort_values("injection_rate")
               .groupby("topology")
               .first()
               .reset_index())

    # Filter to rows where both metrics are available
    valid = summary.dropna(subset=[col_a, col_b])
    if len(valid) < 3:
        return {
            "rho": None, "p_value": None, "n_topologies": len(valid),
            "ranking_a": [], "ranking_b": [],
            "top3_a": [], "top3_b": [], "pareto_shifts": True,
            "note": "insufficient data for correlation",
        }

    # Rank by each metric (lower = better for energy)
    valid = valid.copy()
    valid["rank_proxy"] = valid[col_a].rank(method="min")
    valid["rank_power"] = valid[col_b].rank(method="min")

    ranking_a = valid.sort_values("rank_proxy")["topology"].tolist()
    ranking_b = valid.sort_values("rank_power")["topology"].tolist()

    top3_a = ranking_a[:3]
    top3_b = ranking_b[:3]

    # Spearman rho (manual, no scipy dependency)
    n = len(valid)
    d_sq = ((valid["rank_proxy"] - valid["rank_power"]) ** 2).sum()
    rho = 1.0 - (6.0 * d_sq) / (n * (n * n - 1))

    # Check if Pareto shifts: are the top-3 the same topologies (in any order)?
    pareto_shifts = set(top3_a) != set(top3_b)

    return {
        "rho": round(rho, 4),
        "p_value": None,  # would need scipy for exact p-value
        "n_topologies": n,
        "ranking_a": ranking_a,
        "ranking_b": ranking_b,
        "top3_a": top3_a,
        "top3_b": top3_b,
        "pareto_shifts": pareto_shifts,
        "table": valid[["topology", col_a, "rank_proxy", col_b, "rank_power"]].sort_values("rank_proxy"),
    }


def format_report(result: dict) -> str:
    """Format the validation result as a markdown report."""
    lines = [
        "# PA-12: Energy Proxy vs Real Power — Validation Report",
        "",
    ]

    if result["rho"] is None:
        lines.append(f"> {result.get('note', 'insufficient data')}")
        return "\n".join(lines)

    rho = result["rho"]
    n = result["n_topologies"]
    shifts = result["pareto_shifts"]

    # ------------------------------------------------------------------
    # Rank correlation
    # ------------------------------------------------------------------
    lines.append("## Rank Correlation")
    lines.append("")
    lines.append(f"- **Spearman ρ**: {rho:.4f} (n={n} topologies)")

    if rho > 0.8:
        lines.append(
            "- Interpretation: **strong** positive correlation — "
            "proxy tracks real power well"
        )
    elif rho > 0.5:
        lines.append(
            "- Interpretation: **moderate** correlation — "
            "proxy is a reasonable approximation"
        )
    else:
        lines.append(
            "- Interpretation: **weak** correlation — "
            "proxy may be misleading"
        )

    lines.append("")

    # ------------------------------------------------------------------
    # Top-3 comparison
    # ------------------------------------------------------------------
    lines.append("## Top-3 Comparison")
    lines.append("")
    lines.append("| Rank | By Proxy (`energy_proxy`) | By Real Power (`total_power`) |")
    lines.append("|:----:|:-------------------------|:------------------------------|")

    for i in range(3):
        a = result["top3_a"][i] if i < len(result["top3_a"]) else "—"
        b = result["top3_b"][i] if i < len(result["top3_b"]) else "—"
        match = "✓" if a == b else "✗"

        lines.append(
            f"| {i + 1} | `{a}` | `{b}` {match} |"
        )

    lines.append("")

    same_membership = set(result["top3_a"]) == set(result["top3_b"])
    same_order = result["top3_a"] == result["top3_b"]

    if shifts:
        lines.append(
            "> ⚠ **Top-3 membership changed**: the cheapest three topologies "
            "differ between proxy and real power."
        )
        lines.append(
            "> Use `total_power` for final energy rankings."
        )
    elif same_order:
        lines.append(
            "> ✓ **Exact top-3 agreement**: proxy and real power select "
            "the same topologies in the same order."
        )
    elif same_membership:
        lines.append(
            "> ✓ **No top-3 membership shift**: both metrics select the same "
            "three topologies, although their internal ordering differs."
        )

    lines.append("")

    # ------------------------------------------------------------------
    # Full ranking table
    # ------------------------------------------------------------------
    lines.append("## Full Ranking Table")
    lines.append("")

    if "table" in result:
        tbl = result["table"]

        lines.append(
            "| Topology | Energy Proxy | Proxy Rank | Real Power | Power Rank |"
        )
        lines.append(
            "|:---------|-------------:|-----------:|-----------:|-----------:|"
        )

        for _, row in tbl.iterrows():
            ep = (
                f"{row['energy_proxy']:.2f}"
                if pd.notna(row["energy_proxy"])
                else "—"
            )

            tp = (
                f"{row['total_power']:.3f}"
                if pd.notna(row["total_power"])
                else "—"
            )

            lines.append(
                f"| `{row['topology']}` "
                f"| {ep} "
                f"| {int(row['rank_proxy'])} "
                f"| {tp} "
                f"| {int(row['rank_power'])} |"
            )

    lines.append("")

    return "\n".join(lines)

def format_terminal_report(result: dict) -> str:
    """Format the validation result for clean fixed-width terminal output."""
    lines = [
        "# PA-12: Energy Proxy vs Real Power — Validation Report",
        "",
    ]

    if result["rho"] is None:
        lines.append(
            f"  {result.get('note', 'insufficient data')}"
        )
        return "\n".join(lines)

    rho = result["rho"]
    n = result["n_topologies"]
    shifts = result["pareto_shifts"]

    # ------------------------------------------------------------------
    # Rank correlation
    # ------------------------------------------------------------------
    lines.append("## Rank Correlation")
    lines.append("")
    lines.append(f"  Spearman rho : {rho:.4f}  (n={n} topologies)")

    if rho > 0.8:
        interpretation = (
            "strong positive correlation — proxy tracks real power well"
        )
    elif rho > 0.5:
        interpretation = (
            "moderate correlation — proxy is a reasonable approximation"
        )
    else:
        interpretation = (
            "weak correlation — proxy may be misleading"
        )

    lines.append(f"  Interpretation: {interpretation}")
    lines.append("")

    # ------------------------------------------------------------------
    # Top-3 comparison
    # ------------------------------------------------------------------
    lines.append("## Top-3 Comparison")
    lines.append("")

    rank_w = 6
    proxy_w = 24
    power_w = 24
    match_w = 7

    separator = (
        "+"
        + "-" * (rank_w + 2)
        + "+"
        + "-" * (proxy_w + 2)
        + "+"
        + "-" * (power_w + 2)
        + "+"
        + "-" * (match_w + 2)
        + "+"
    )

    header = (
        f"| {'Rank':^{rank_w}} "
        f"| {'By Proxy':^{proxy_w}} "
        f"| {'By Real Power':^{power_w}} "
        f"| {'Match':^{match_w}} |"
    )

    lines.append(separator)
    lines.append(header)
    lines.append(separator)

    for i in range(3):
        a = result["top3_a"][i] if i < len(result["top3_a"]) else "—"
        b = result["top3_b"][i] if i < len(result["top3_b"]) else "—"
        match = "YES" if a == b else "NO"

        lines.append(
            f"| {i + 1:^{rank_w}} "
            f"| {a:<{proxy_w}} "
            f"| {b:<{power_w}} "
            f"| {match:^{match_w}} |"
        )

    lines.append(separator)
    lines.append("")

    # ------------------------------------------------------------------
    # Top-3 interpretation
    # ------------------------------------------------------------------
    same_membership = set(result["top3_a"]) == set(result["top3_b"])
    same_order = result["top3_a"] == result["top3_b"]

    if shifts:
        lines.append(
            "  WARNING: Top-3 membership changed between proxy and real power."
        )
        lines.append(
            "  Use total_power for final energy rankings."
        )
    elif same_order:
        lines.append(
            "  Exact agreement: same top-3 topologies in the same order."
        )
    elif same_membership:
        lines.append(
            "  No top-3 membership shift: same three topologies,"
        )
        lines.append(
            "  but their internal ordering differs."
        )

    lines.append("")

    # ------------------------------------------------------------------
    # Full ranking table
    # ------------------------------------------------------------------
    lines.append("## Full Ranking Table")
    lines.append("")

    if "table" in result:
        tbl = result["table"]

        topology_w = max(
            len("Topology"),
            max(len(str(x)) for x in tbl["topology"])
        )

        proxy_val_w = max(len("Energy Proxy"), 12)
        proxy_rank_w = max(len("Proxy Rank"), 10)
        power_val_w = max(len("Real Power"), 10)
        power_rank_w = max(len("Power Rank"), 10)

        separator = (
            "+"
            + "-" * (topology_w + 2)
            + "+"
            + "-" * (proxy_val_w + 2)
            + "+"
            + "-" * (proxy_rank_w + 2)
            + "+"
            + "-" * (power_val_w + 2)
            + "+"
            + "-" * (power_rank_w + 2)
            + "+"
        )

        header = (
            f"| {'Topology':<{topology_w}} "
            f"| {'Energy Proxy':>{proxy_val_w}} "
            f"| {'Proxy Rank':>{proxy_rank_w}} "
            f"| {'Real Power':>{power_val_w}} "
            f"| {'Power Rank':>{power_rank_w}} |"
        )

        lines.append(separator)
        lines.append(header)
        lines.append(separator)

        for _, row in tbl.iterrows():
            topology = str(row["topology"])

            ep = (
                f"{row['energy_proxy']:.2f}"
                if pd.notna(row["energy_proxy"])
                else "—"
            )

            tp = (
                f"{row['total_power']:.3f}"
                if pd.notna(row["total_power"])
                else "—"
            )

            proxy_rank = (
                str(int(row["rank_proxy"]))
                if pd.notna(row["rank_proxy"])
                else "—"
            )

            power_rank = (
                str(int(row["rank_power"]))
                if pd.notna(row["rank_power"])
                else "—"
            )

            lines.append(
                f"| {topology:<{topology_w}} "
                f"| {ep:>{proxy_val_w}} "
                f"| {proxy_rank:>{proxy_rank_w}} "
                f"| {tp:>{power_val_w}} "
                f"| {power_rank:>{power_rank_w}} |"
            )

        lines.append(separator)

    lines.append("")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression tests."""
    # Create synthetic data where proxy and power rank differently
    sample = pd.DataFrame([
        # fly4: low hops (2.0), lowest power (3.72) — #1 in both
        {"topology": "fly4",      "injection_rate": 0.01, "hops_avg": 2.00,
         "energy_proxy": 256.0,   "total_power": 3.72, "status": "ok"},
        # cmesh: low hops (2.01) → #2 by proxy, but high power (8.40) → #4 by power
        {"topology": "cmesh",     "injection_rate": 0.01, "hops_avg": 2.01,
         "energy_proxy": 257.3,   "total_power": 8.40, "status": "ok"},
        # fattree: medium hops (2.44) → #3 by proxy, low power (5.07) → #2 by power
        {"topology": "fattree",   "injection_rate": 0.01, "hops_avg": 2.44,
         "energy_proxy": 312.3,   "total_power": 5.07, "status": "ok"},
        # flatfly: medium hops (2.49) → #4 by proxy, highest power (9.99) → #5
        {"topology": "flatfly",   "injection_rate": 0.01, "hops_avg": 2.49,
         "energy_proxy": 318.7,   "total_power": 9.99, "status": "ok"},
        # mesh4x4: high hops (3.48) → #5 by proxy, moderate power (5.48) → #3 by power
        {"topology": "mesh4x4",   "injection_rate": 0.01, "hops_avg": 3.48,
         "energy_proxy": 445.4,   "total_power": 5.48, "status": "ok"},
        # Failed topology — should be excluded
        {"topology": "anynet16",  "injection_rate": 0.01, "hops_avg": None,
         "energy_proxy": None,    "total_power": None, "status": "no_output"},
    ])

    result = compute_rank_correlation(sample)

    # Should have 5 valid topologies
    assert result["n_topologies"] == 5, f"expected 5, got {result['n_topologies']}"

    # Rho should be computable
    assert result["rho"] is not None
    assert -1.0 <= result["rho"] <= 1.0, f"rho out of range: {result['rho']}"

    # Proxy ranking: fly4 < cmesh < fattree < flatfly < mesh4x4
    assert result["ranking_a"] == ["fly4", "cmesh", "fattree", "flatfly", "mesh4x4"], \
        f"unexpected proxy ranking: {result['ranking_a']}"

    # Power ranking: fly4 < fattree < mesh4x4 < cmesh < flatfly
    assert result["ranking_b"] == ["fly4", "fattree", "mesh4x4", "cmesh", "flatfly"], \
        f"unexpected power ranking: {result['ranking_b']}"

    # Top-3 by proxy = {fly4, cmesh, fattree}
    # Top-3 by power = {fly4, fattree, mesh4x4}
    # mesh4x4 replaces cmesh → Pareto shift
    assert result["pareto_shifts"] is True, "expected Pareto shift"

    # Report should be valid markdown
    report = format_report(result)
    assert "Spearman" in report
    assert "Pareto shift detected" in report

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--sweep",
        default=None,
        help="path to topology_sweep.json",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="output report path (default: output/energy_validation.md)",
    )
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    sys.path.insert(0, str(HERE))
    from analysis import load_sweep_df

    df = load_sweep_df(args.sweep)
    result = compute_rank_correlation(df)

    # --------------------------------------------------------------
    # 1. Clean fixed-width report for the terminal
    # --------------------------------------------------------------
    terminal_report = format_terminal_report(result)
    print(terminal_report)

    # --------------------------------------------------------------
    # 2. Markdown report for the .md output file
    # --------------------------------------------------------------
    markdown_report = format_report(result)

    out = Path(args.out) if args.out else OUTPUT / "energy_validation.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown_report, encoding="utf-8")

    print(f"  → {out}")


if __name__ == "__main__":
    main()
