#!/usr/bin/env python3
"""Srota feature experiments -- the claims a topology sweep cannot reach.

Four experiments, each tied to the spec item it answers:

  sidebuf   VC-002 VC-R1: side-buffer capacity sweep (4-16 flits), and the
            staging-window sensitivity VC-002 section 13.6 fixes at 2.
            Run at k=8, c=4 (256 tiles): an interior router has
            c + 2(k-1) = 18 inputs, enough simultaneous losers to fill an
            8-flit buffer. At the t3 sweep's k=4, c=1 it never fills.
  qos       TOPO-003 section 7.5: island rate regulators. Two tenants share
            the island (resource) columns; the bulk tenant floods them.
            Without regulation the critical tenant queues behind it; with
            the bulk class capped, its latency is protected.
  planes    TOPO-003 section 5 / VC-002 section 3: control traffic on its
            own Plane C versus sharing Plane D with bulk data.
  pipeline  Router pipeline sensitivity: BookSim's default 3-stage
            router against the spec's ST0/ST1/ST2 (speculative VA+SA).

Every run's full booksim log is kept under <out>/logs/.

Usage: srota_features.py [--booksim PATH] [--out DIR] [--only sidebuf,qos,...]
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

# Spec-literal Plane D (VC-002): one VC, 2-flit staging, 8-flit side
# buffer, XY over MECS. Everything else is BookSim's default router.
PLANE_D = dict(topology="srota", routing_function="o1turn", srota_mecs=3,
               srota_path_en=1, srota_vc_policy="none", srota_router="sidebuf",
               num_vcs=1, vc_buf_size=2, srota_sb_depth=8,
               srota_sb_watermark=6, use_noc_latency=0, traffic="uniform",
               packet_size=5, sim_type="latency", sample_period=1000,
               warmup_periods=3, sim_count=1, srota_cdg_radix=0)


def _cfg_text(params: dict) -> str:
    return "".join(f"{k} = {v};\n" for k, v in params.items())


def run(booksim: str, params: dict, log: Path) -> str:
    log.parent.mkdir(parents=True, exist_ok=True)
    cfg = log.with_suffix(".config")
    cfg.write_text(_cfg_text(params))
    try:
        p = subprocess.run([booksim, str(cfg)], capture_output=True,
                           text=True, timeout=1800)
        out = p.stdout + ("\n--- stderr ---\n" + p.stderr if p.stderr else "")
    except subprocess.TimeoutExpired:
        out = "<<TIMEOUT>>"
    log.write_text(out)
    return out


def summary_block(out: str) -> str:
    """The final per-class summary, after the last sample period."""
    i = out.rfind("====== Overall Traffic Statistics ======")
    return out[i:] if i >= 0 else out


def class_stats(out: str) -> dict:
    """class -> {latency, accepted} from the overall summary."""
    blk = summary_block(out)
    res = {}
    for m in re.finditer(r"====== Traffic class (\d+) ======(.*?)(?======|\Z)",
                         blk, re.S):
        cl, body = int(m.group(1)), m.group(2)
        lat = re.search(r"Packet latency average = ([0-9.e+-]+)", body)
        acc = re.search(r"Accepted packet rate average = ([0-9.e+-]+)", body)
        res[cl] = {"latency": float(lat.group(1)) if lat else None,
                   "accepted": float(acc.group(1)) if acc else None}
    res["unstable"] = "unstable" in out.lower()
    return res


def kv(out: str, key: str):
    m = re.search(rf"{key}=([-0-9.e]+)", out)
    return float(m.group(1)) if m else None


def _pmap(fn, items, jobs):
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(fn, items))


# ----------------------------------------------------------------------
def exp_sidebuf(bs, out, jobs):
    rates = [0.01, 0.02, 0.03, 0.04]
    base = dict(PLANE_D, k=8, c=4, srota_cdg_radix=0)
    grid = [("sb", d, 2, r) for d in (1, 4, 8, 16) for r in rates] + \
           [("stage", 8, w, r) for w in (4, 8) for r in rates]

    def one(item):
        kind, depth, win, rate = item
        p = dict(base, srota_sb_depth=depth, vc_buf_size=win,
                 injection_rate=rate)
        o = run(bs, p, out / "logs" / f"sidebuf_{kind}_sb{depth}_w{win}_{rate}.log")
        cs = class_stats(o)
        return dict(kind=kind, sb_depth=depth, window=win, rate=rate,
                    latency=cs.get(0, {}).get("latency"),
                    accepted=cs.get(0, {}).get("accepted"),
                    unstable=cs["unstable"],
                    sb_fill=kv(o, "sb_fill"), sb_peak=kv(o, "sb_peak"),
                    sb_full_reject=kv(o, "sb_full_reject"),
                    sb_mean=kv(o, "sb_mean_occ_per_router"),
                    alloc_loss=kv(o, "alloc_loss"),
                    storage=kv(o, "storage_flits"))
    rows = _pmap(one, grid, jobs)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for d in (1, 4, 8, 16):
        pts = sorted((r["rate"], r["accepted"]) for r in rows
                     if r["kind"] == "sb" and r["sb_depth"] == d)
        axes[0].plot(*zip(*pts), "-o", label=f"side buffer {d} flits (staging 2)")
    for w in (4, 8):
        pts = sorted((r["rate"], r["accepted"]) for r in rows
                     if r["kind"] == "stage" and r["window"] == w)
        axes[0].plot(*zip(*pts), "--s", label=f"staging {w} flits (side buffer 8)")
    axes[0].plot(rates, rates, ":", color="gray", label="offered")
    axes[0].set_xlabel("offered load (pkt/node/cycle)")
    axes[0].set_ylabel("accepted throughput (pkt/node/cycle)")
    axes[0].set_title("VC-R1: side-buffer depth vs staging window\nk=8 c=4 (256 tiles), XY, 1 VC")
    axes[0].legend(fontsize=8); axes[0].grid(alpha=0.3)
    for d in (1, 4, 8, 16):
        pts = sorted((r["rate"], r["sb_peak"] or 0) for r in rows
                     if r["kind"] == "sb" and r["sb_depth"] == d)
        axes[1].plot(*zip(*pts), "-o", label=f"depth {d}")
    axes[1].set_xlabel("offered load (pkt/node/cycle)")
    axes[1].set_ylabel("peak side-buffer occupancy (flits)")
    axes[1].set_title("Does the side buffer fill?")
    axes[1].legend(fontsize=8); axes[1].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(out / "sidebuf_vcr1.png", dpi=140); plt.close(fig)
    return rows


def exp_qos(bs, out, jobs):
    # Two tenants on a k=4 fabric with island columns 0 and 3. Class 0
    # (bulk) offers the load on the x axis; class 1 (critical) a fixed
    # light load. Regulator: class 0 capped per island router.
    base = dict(PLANE_D, k=4, c=1, srota_island_col_map=9,
                srota_isl_route="colfirst", srota_path_en=3,
                srota_vc_policy="rank", num_vcs=2, classes=2,
                packet_size="{5,5}", srota_isl_burst=4)
    bulk = [0.01, 0.02, 0.03, 0.04, 0.05]
    grid = [(reg, b) for reg in (False, True) for b in bulk]

    def one(item):
        reg, b = item
        p = dict(base, injection_rate="{%s,0.005}" % b)
        if reg:
            p["srota_isl_rate"] = "{0.08,0}"      # cap bulk; critical free
        o = run(bs, p, out / "logs" / f"qos_{'reg' if reg else 'free'}_{b}.log")
        cs = class_stats(o)
        isl = re.findall(r"island class=(\d+) arrive=(\d+) grant=(\d+) "
                         r"deferred_flits=(\d+)", o)
        return dict(regulated=reg, bulk_rate=b,
                    bulk_lat=cs.get(0, {}).get("latency"),
                    crit_lat=cs.get(1, {}).get("latency"),
                    bulk_acc=cs.get(0, {}).get("accepted"),
                    crit_acc=cs.get(1, {}).get("accepted"),
                    unstable=cs["unstable"],
                    island=[dict(cls=int(a), arrive=int(b_), grant=int(c),
                                 deferred=int(d)) for a, b_, c, d in isl])
    rows = _pmap(one, grid, jobs)

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for reg, ls in ((False, "-"), (True, "--")):
        tag = "regulated (bulk capped 0.08 flit/cyc/island)" if reg else "unregulated"
        pts = sorted((r["bulk_rate"], r["crit_lat"]) for r in rows if r["regulated"] == reg)
        ax.plot(*zip(*pts), ls + "o", color="#c0392b", label=f"critical tenant — {tag}")
        pts = sorted((r["bulk_rate"], r["bulk_lat"]) for r in rows if r["regulated"] == reg)
        ax.plot(*zip(*pts), ls + "s", color="#2c3e50", label=f"bulk tenant — {tag}")
    ax.set_yscale("log")
    ax.set_xlabel("bulk tenant offered load (pkt/node/cycle)")
    ax.set_ylabel("mean packet latency (cycles, log)")
    ax.set_title("QoS islands (TOPO-003 7.5): island columns 0,3, k=4")
    ax.legend(fontsize=7); ax.grid(alpha=0.3, which="both")
    fig.tight_layout(); fig.savefig(out / "qos_islands.png", dpi=140); plt.close(fig)
    return rows


def exp_planes(bs, out, jobs):
    # Control traffic (class 1, 1-flit) at a fixed light load; bulk data
    # (class 0, 5-flit) swept. Shared: both on Plane D. Split: control on
    # Plane C.
    common = dict(PLANE_D, k=4, c=1, classes=2, packet_size="{5,1}")
    shared = dict(common, srota_planes=5, subnets=1, num_vcs=1)
    split = dict(common, srota_planes=7, subnets=2, class_subnet="{0,1}",
                 num_vcs=3, srota_d_num_vcs=1)
    data = [0.005, 0.01, 0.02, 0.03, 0.035, 0.04]
    grid = [(name, cfg, d) for name, cfg in (("shared", shared), ("split", split))
            for d in data]

    def one(item):
        name, cfg, d = item
        p = dict(cfg, injection_rate="{%s,0.01}" % d)
        o = run(bs, p, out / "logs" / f"planes_{name}_{d}.log")
        cs = class_stats(o)
        return dict(arrangement=name, data_rate=d,
                    data_lat=cs.get(0, {}).get("latency"),
                    ctrl_lat=cs.get(1, {}).get("latency"),
                    unstable=cs["unstable"])
    rows = _pmap(one, grid, jobs)

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for name, ls, lab in (("shared", "-", "control shares Plane D"),
                          ("split", "--", "control on Plane C")):
        pts = sorted((r["data_rate"], r["ctrl_lat"]) for r in rows if r["arrangement"] == name)
        ax.plot(*zip(*pts), ls + "o", color="#c0392b", label=f"control latency — {lab}")
        pts = sorted((r["data_rate"], r["data_lat"]) for r in rows if r["arrangement"] == name)
        ax.plot(*zip(*pts), ls + "s", color="#2c3e50", label=f"data latency — {lab}")
    ax.set_yscale("log")
    ax.set_xlabel("data-plane offered load (pkt/node/cycle)")
    ax.set_ylabel("mean packet latency (cycles, log)")
    ax.set_title("Planes: control traffic isolation (k=4, c=1)")
    ax.legend(fontsize=7); ax.grid(alpha=0.3, which="both")
    fig.tight_layout(); fig.savefig(out / "planes_isolation.png", dpi=140); plt.close(fig)
    return rows


def exp_pipeline(bs, out, jobs):
    arms = {
        "srota16_xy (sidebuf, 2-flit staging)": dict(PLANE_D, k=4, c=1),
        "srota16 (4 VC x 8, rank)": dict(PLANE_D, k=4, c=1, srota_router="iq",
                                         srota_path_en=3, srota_vc_policy="rank",
                                         num_vcs=4, vc_buf_size=8),
        "mesh4x4 (4 VC x 8)": dict(topology="mesh", k=4, n=2,
                                   routing_function="dor", num_vcs=4,
                                   vc_buf_size=8, use_noc_latency=0,
                                   traffic="uniform", packet_size=5,
                                   sim_type="latency", sample_period=1000,
                                   warmup_periods=3, sim_count=1),
    }
    rates = [0.01, 0.03, 0.05, 0.08, 0.11]
    grid = [(a, spec, r) for a in arms for spec in (0, 1) for r in rates]

    def one(item):
        a, spec, r = item
        p = dict(arms[a], speculative=spec, injection_rate=r)
        slug = re.sub(r"[^a-z0-9]+", "_", a.lower())[:24]
        o = run(bs, p, out / "logs" / f"pipeline_{slug}_spec{spec}_{r}.log")
        cs = class_stats(o)
        return dict(arm=a, speculative=spec, rate=r,
                    latency=cs.get(0, {}).get("latency"),
                    accepted=cs.get(0, {}).get("accepted"),
                    unstable=cs["unstable"])
    rows = _pmap(one, grid, jobs)

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    colors = ["#c0392b", "#e67e22", "#2c3e50"]
    for a, col in zip(arms, colors):
        for spec, ls in ((0, "-"), (1, "--")):
            pts = sorted((r["rate"], r["accepted"]) for r in rows
                         if r["arm"] == a and r["speculative"] == spec)
            ax.plot(*zip(*pts), ls + "o", color=col,
                    label=f"{a} — {'spec ST0/ST1/ST2' if spec else 'default 3-stage'}")
    ax.plot(rates, rates, ":", color="gray", label="offered")
    ax.set_xlabel("offered load (pkt/node/cycle)")
    ax.set_ylabel("accepted throughput (pkt/node/cycle)")
    ax.set_title("Router pipeline sensitivity (uniform, k=4)")
    ax.legend(fontsize=7); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(out / "pipeline_sensitivity.png", dpi=140); plt.close(fig)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--booksim", default=str(REPO / "third_party/booksim2/src/booksim"))
    ap.add_argument("--out", default=str(TRACK / "results" /
                                         os.environ.get("CONFIG", "baseline") /
                                         "analysis" / "srota_features"))
    ap.add_argument("--only", default="sidebuf,qos,planes,pipeline")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    exps = {"sidebuf": exp_sidebuf, "qos": exp_qos, "planes": exp_planes,
            "pipeline": exp_pipeline}
    results = {}
    for name in a.only.split(","):
        print(f"[srota_features] {name} ...", flush=True)
        results[name] = exps[name](a.booksim, out, a.jobs)
        (out / f"{name}.json").write_text(json.dumps(results[name], indent=2))
    print(f"Written -> {out}/")


if __name__ == "__main__":
    main()
