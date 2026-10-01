#!/usr/bin/env python3
"""Srota deflection experiments -- and the buffer-sizing correction they rest on.

The first cross-topology study put the two spec-literal Plane D arms
(srota16_xy, srota16_sb) last on throughput. Two of these four experiments
exist to establish WHY, because the answer is not the topology:

  window    The staging window against the packet size. VC-002 section 13.6
            fixes the staging latch at 2 flits; the sweep ran every arm at
            packet_size=5. A packet that cannot be resident in its own
            credit window serialises against the credit round trip, and
            BookSim's Fragmentation counter reports it directly. This is
            the dominant effect in the original numbers.
  control   The same buffer starvation applied to mesh and torus. If a
            2-flit window costs mesh MORE than it costs Srota, the
            original table was comparing buffer budgets, not topologies.

  deflect   Deflection (srota_deflect) on and off at equal storage. The
            side buffer only ever captures switch-allocation LOSERS, so it
            cannot fill unless allocation contention exists -- and the
            staging window suppresses exactly that. Deflection keeps a
            blocked packet bidding instead of stalling on credit, which is
            what puts contention back. Measures both what it costs and
            whether the side buffer finally does anything.
  budget    srota_deflect_max, the per-packet deflection budget that bounds
            hop count and makes deflection livelock-free. Sweeps the
            trade: more budget = more escape routes = more hops.

Every run's full booksim log is kept under <out>/logs/.

Usage: srota_deflect.py [--booksim PATH] [--out DIR] [--only window,control,...]
"""
import argparse
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib
matplotlib.use(os.environ.get("MPLBACKEND", "Agg"))
import matplotlib.pyplot as plt  # noqa: E402

TRACK = Path(__file__).resolve().parent.parent
REPO = TRACK.parent.parent

# Spec-literal Plane D (VC-002): XY over MECS, 2-flit staging latch,
# 8-flit shared side buffer. srota_cdg_radix=0 only because F1 is an
# elaboration check that the srota16_*.cfg arms already run on every
# sweep run -- repeating it here would add nothing but seconds.
PLANE_D = dict(topology="srota", routing_function="o1turn", k=4, c=1,
               srota_mecs=3, srota_path_en=1, srota_vc_policy="none",
               srota_router="sidebuf", num_vcs=1, vc_buf_size=2,
               srota_sb_depth=8, srota_sb_watermark=6, use_noc_latency=0,
               traffic="uniform", packet_size=5, sim_type="latency",
               sample_period=1000, warmup_periods=3, sim_count=1,
               srota_cdg_radix=0)

MESH = dict(topology="mesh", k=4, n=2, routing_function="dor",
            use_noc_latency=0, traffic="uniform", packet_size=5,
            sim_type="latency", sample_period=1000, warmup_periods=3,
            sim_count=1)

TORUS = dict(MESH, topology="torus", routing_function="dim_order")

RATES = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.13, 0.16, 0.20]


def _cfg_text(params: dict) -> str:
    return "".join(f"{k} = {v};\n" for k, v in params.items())


def run(booksim: str, params: dict, log: Path) -> str:
    log.parent.mkdir(parents=True, exist_ok=True)
    cfg = log.with_suffix(".config")
    cfg.write_text(_cfg_text(params))
    try:
        p = subprocess.run([booksim, str(cfg)], capture_output=True,
                           text=True, timeout=150)
        out = p.stdout + ("\n--- stderr ---\n" + p.stderr if p.stderr else "")
    except subprocess.TimeoutExpired:
        out = "<<TIMEOUT>>"
    log.write_text(out)
    return out


def summary_block(out: str) -> str:
    i = out.rfind("====== Overall Traffic Statistics ======")
    return out[i:] if i >= 0 else out


def stats(out: str) -> dict:
    """Everything one run contributes, from its overall summary."""
    blk = summary_block(out)

    def g(pat):
        m = re.search(pat + r" average = ([0-9.e+-]+)", blk)
        return float(m.group(1)) if m else None

    return dict(latency=g("Packet latency"), accepted=g("Accepted packet rate"),
                acc_flit=g("Accepted flit rate"), hops=g("Hops"),
                frag=g("Fragmentation"),
                deadlock=("Possible network deadlock" in out
                          or "<<TIMEOUT>>" in out),
                unstable=("unstable" in out.lower() or "<<TIMEOUT>>" in out))


def kv(out: str, key: str):
    m = re.search(rf"\b{key}=([-0-9.e]+)", out)
    return float(m.group(1)) if m else None


def sb_stats(out: str) -> dict:
    return {k: kv(out, k) for k in
            ("storage_flits", "alloc_loss", "sb_fill", "sb_peak",
             "sb_full_reject", "sb_mean_occ_per_router", "router_cycles",
             "deflections", "head_hops", "deflected_hops_frac")}


def _pmap(fn, items, jobs):
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(fn, items))


def sweep(bs, out, jobs, arms, rates=RATES, tag="run"):
    """arms: list of (label, params). Returns rows, one per (arm, rate)."""
    grid = [(lbl, p, r) for lbl, p in arms for r in rates]

    def one(item):
        lbl, p, r = item
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", lbl)
        o = run(bs, dict(p, injection_rate=r),
                out / "logs" / f"{tag}_{safe}_{r}.log")
        row = dict(arm=lbl, rate=r)
        row.update(stats(o))
        row.update(sb_stats(o))
        return row

    return _pmap(one, grid, jobs)


def curve(rows, arm, y):
    """(rate, y) pairs for one arm, stopping at the first unstable rate."""
    pts = []
    for r in sorted((x for x in rows if x["arm"] == arm),
                    key=lambda x: x["rate"]):
        if r["unstable"] or r.get("deadlock") or r.get(y) is None:
            break
        pts.append((r["rate"], r[y]))
    return list(zip(*pts)) if pts else ([], [])


def peak(rows, arm, y="acc_flit"):
    vals = [r[y] for r in rows
            if r["arm"] == arm and not r["unstable"] and not r.get("deadlock")
            and r.get(y) is not None]
    return max(vals) if vals else 0.0


# ----------------------------------------------------------------------
def exp_window(bs, out, jobs):
    """Staging window x packet size. The cliff is at window < packet."""
    wins, pkts = (2, 4, 8), (1, 2, 3, 5)
    arms = [(f"w{w}_p{p}", dict(PLANE_D, vc_buf_size=w, packet_size=p))
            for w in wins for p in pkts]
    rows = sweep(bs, out, jobs, arms, tag="window")

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))

    for w in wins:
        ys = [peak(rows, f"w{w}_p{p}") for p in pkts]
        axes[0].plot(pkts, ys, "-o", label=f"staging window {w} flits")
    axes[0].axvline(2, color="gray", ls=":", lw=1)
    axes[0].annotate("VC-002 13.6\nfixes the window at 2", (2, 0.05),
                     fontsize=7, color="gray")
    axes[0].set_xlabel("packet size (flits)")
    axes[0].set_ylabel("peak accepted (flits/node/cycle)")
    axes[0].set_title("Throughput collapses when a packet\ncannot fit its own credit window")
    axes[0].legend(fontsize=8); axes[0].grid(alpha=0.3)

    for w in wins:
        ys = []
        for p in pkts:
            f = [r["frag"] for r in rows
                 if r["arm"] == f"w{w}_p{p}" and not r["unstable"]]
            ys.append(f[0] if f else 0.0)
        axes[1].plot(pkts, ys, "-s", label=f"window {w}")
    axes[1].set_xlabel("packet size (flits)")
    axes[1].set_ylabel("fragmentation (cycles)")
    axes[1].set_title("BookSim's fragmentation counter\nnames the same cliff")
    axes[1].legend(fontsize=8); axes[1].grid(alpha=0.3)

    for w in wins:
        x, y = curve(rows, f"w{w}_p5", "latency")
        if x:
            axes[2].plot(x, y, "-o", label=f"window {w}, 5-flit packets")
    axes[2].set_xlabel("offered load (pkt/node/cycle)")
    axes[2].set_ylabel("packet latency (cycles)")
    axes[2].set_title("Latency curves at the sweep's packet size")
    axes[2].legend(fontsize=8); axes[2].grid(alpha=0.3)

    fig.tight_layout(); fig.savefig(out / "window_vs_packet.png", dpi=140)
    plt.close(fig)
    return rows


def exp_control(bs, out, jobs):
    """The same starvation on mesh and torus. Isolates topology from buffers."""
    # Torus is starved to 2 VCs, not 1: dim_order_torus asserts
    # (available_vcs > 0) with a single VC, because the dateline that
    # breaks its ring cycle IS a VC split. A torus cannot be built at
    # Srota Plane D's buffer configuration at all -- which is worth
    # stating plainly rather than reporting as an unstable run.
    arms = [
        ("mesh stock 4VCx8",      dict(MESH, num_vcs=4, vc_buf_size=8)),
        ("mesh starved 1VCx2",    dict(MESH, num_vcs=1, vc_buf_size=2)),
        ("torus stock 4VCx8",     dict(TORUS, num_vcs=4, vc_buf_size=8)),
        ("torus starved 2VCx2*",  dict(TORUS, num_vcs=2, vc_buf_size=2)),
        ("srota XY stock 4VCx8",  dict(PLANE_D, srota_router="iq", num_vcs=4,
                                       vc_buf_size=8)),
        ("srota XY starved 1VCx2", dict(PLANE_D, num_vcs=1, vc_buf_size=2)),
    ]
    rows = sweep(bs, out, jobs, arms, tag="control")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    for lbl, _ in arms:
        style = "-o" if "stock" in lbl else "--s"
        x, y = curve(rows, lbl, "acc_flit")
        if x:
            axes[0].plot(x, y, style, label=lbl)
    axes[0].set_xlabel("offered load (pkt/node/cycle)")
    axes[0].set_ylabel("accepted (flits/node/cycle)")
    axes[0].set_title("Same buffers, different topologies\n(dashed = 1 VC x 2 flits, 5-flit packets)")
    axes[0].legend(fontsize=8); axes[0].grid(alpha=0.3)

    labels = [l for l, _ in arms]
    ys = [peak(rows, l) for l in labels]
    colors = ["#4878d0" if "stock" in l else "#ee854a" for l in labels]
    axes[1].barh(range(len(labels)), ys, color=colors)
    axes[1].set_yticks(range(len(labels)))
    axes[1].set_yticklabels(labels, fontsize=8)
    axes[1].set_xlabel("peak accepted (flits/node/cycle)")
    axes[1].set_title("Starvation costs mesh and torus MORE\nthan it costs Srota  (* torus needs 2 VCs)")
    axes[1].grid(alpha=0.3, axis="x")
    fig.tight_layout(); fig.savefig(out / "buffer_control.png", dpi=140)
    plt.close(fig)
    return rows


def exp_deflect(bs, out, jobs):
    """Deflection on/off at equal storage: what it does to the side buffer,
    and the load at which it deadlocks.

    Deflection is NOT deadlock-free here -- a wormhole packet spans its own
    deflection and puts the dimension-order violation back into the escape
    subgraph (see the elaboration warning in srota.cpp). The arms below are
    chosen to show both halves of that: what deflection buys below the
    threshold, and where the threshold is as the staging latch deepens.
    """
    two_vc = dict(PLANE_D, num_vcs=2)          # 7x2x2 + 8 = 36 flits/router
    defl = dict(srota_deflect=1, srota_deflect_max=4, srota_deflect_esc_vcs=1)
    arms = [
        ("no deflection, w2 p5",  dict(two_vc, srota_deflect=0)),
        ("deflection, w2 p5",     dict(two_vc, **defl)),
        ("no deflection, w8 p5",  dict(two_vc, srota_deflect=0, vc_buf_size=8)),
        ("deflection, w8 p5",     dict(two_vc, vc_buf_size=8, **defl)),
        ("deflection, w2 p1",     dict(two_vc, packet_size=1, **defl)),
    ]
    rows = sweep(bs, out, jobs, arms, tag="deflect")

    fig, axes = plt.subplots(1, 4, figsize=(20, 4.8))
    for lbl, _ in arms:
        style = "--s" if lbl.startswith("no ") else "-o"
        for ax, key in ((axes[0], "acc_flit"), (axes[1], "latency"),
                        (axes[2], "sb_fill"),
                        (axes[3], "sb_mean_occ_per_router")):
            x, y = curve(rows, lbl, key)
            if x:
                ax.plot(x, y, style, label=lbl)
        # mark where the arm deadlocks
        dls = [r["rate"] for r in rows if r["arm"] == lbl and r.get("deadlock")]
        if dls:
            for ax in axes:
                ax.axvline(min(dls), color="crimson", ls=":", lw=1, alpha=0.5)

    axes[0].set_ylabel("accepted (flits/node/cycle)")
    axes[0].set_title("Throughput\n(dotted red = first deadlocking rate)")
    axes[1].set_ylabel("packet latency (cycles)")
    axes[1].set_title("Latency")
    axes[2].set_ylabel("side-buffer fills (whole run)")
    axes[2].set_yscale("log")
    axes[2].set_title("Does the side buffer fill?\n(log scale)")
    axes[3].set_ylabel("mean occupancy (flits/router)")
    axes[3].set_title("Side-buffer occupancy\n(depth is 8)")
    for ax in axes:
        ax.set_xlabel("offered load (pkt/node/cycle)")
        ax.legend(fontsize=7); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(out / "deflection.png", dpi=140)
    plt.close(fig)
    return rows


def exp_budget(bs, out, jobs):
    """srota_deflect_max: the livelock bound, and what it buys."""
    two_vc = dict(PLANE_D, num_vcs=2, srota_deflect_esc_vcs=1)
    budgets = [0, 1, 2, 4, 8]
    arms = [(f"budget {b}", dict(two_vc, srota_deflect=1, srota_deflect_max=b))
            for b in budgets]
    rows = sweep(bs, out, jobs, arms, tag="budget")

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))
    for b in budgets:
        x, y = curve(rows, f"budget {b}", "acc_flit")
        if x:
            axes[0].plot(x, y, "-o", label=f"max {b}")
    axes[0].set_ylabel("accepted (flits/node/cycle)")
    axes[0].set_title("Throughput vs deflection budget")

    for b in budgets:
        x, y = curve(rows, f"budget {b}", "hops")
        if x:
            axes[1].plot(x, y, "-o", label=f"max {b}")
    axes[1].set_ylabel("hops per packet")
    axes[1].set_title("Deflection buys throughput with hops\n(minimal is 2.6)")

    for b in budgets:
        x, y = curve(rows, f"budget {b}", "sb_fill")
        if x:
            axes[2].plot(x, y, "-o", label=f"max {b}")
    axes[2].set_ylabel("side-buffer fills (whole run)")
    axes[2].set_title("Side-buffer utilisation")

    for ax in axes:
        ax.set_xlabel("offered load (pkt/node/cycle)")
        ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(out / "deflect_budget.png", dpi=140)
    plt.close(fig)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--booksim",
                    default=str(REPO / "third_party/booksim2/src/booksim"))
    ap.add_argument("--out", default=str(TRACK / "results" /
                                         os.environ.get("CONFIG", "baseline") /
                                         "analysis" / "srota_deflect"))
    ap.add_argument("--only", default="window,control,deflect,budget")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    exps = {"window": exp_window, "control": exp_control,
            "deflect": exp_deflect, "budget": exp_budget}
    for name in a.only.split(","):
        print(f"[srota_deflect] {name} ...", flush=True)
        rows = exps[name](a.booksim, out, a.jobs)
        (out / f"{name}.json").write_text(json.dumps(rows, indent=2))
    print(f"Written -> {out}/")


if __name__ == "__main__":
    main()
