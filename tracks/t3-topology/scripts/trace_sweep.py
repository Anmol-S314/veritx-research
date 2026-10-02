#!/usr/bin/env python3
"""Workload x topology sweep: gen trace -> booksim -> visualize."""
import argparse, os, shlex, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml
import re


REPO = Path(__file__).resolve().parents[3]
DEFAULT_CFG = REPO / "tracks/t3-topology/configs/trace_sweep.yaml"


def make_cfg(base_cfg, trace_rel, pkts_rel, dest, bs):
    """Copy base config, drop hardcoded trace keys, append per-run ones."""
    keys = (bs["trace_key"], bs["packets_out_key"])
    pat = re.compile(r"^\s*(%s)\s*=.*$" % "|".join(keys))
    lines = [l for l in open(base_cfg).read().splitlines() if not pat.match(l)]
    lines += [
        "",
        "// --- injected by trace_sweep.py ---",
        "sim_type = trace;",
        f"{bs['trace_key']} = {trace_rel};",
        f"{bs['packets_out_key']} = {pkts_rel};",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")

def sh(cmd, log=None, dry=False):
    print("  $", " ".join(shlex.quote(str(c)) for c in cmd))
    if dry:
        return 0
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "w") as f:
            return subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT).returncode
    return subprocess.run(cmd, cwd=REPO).returncode


def pick(spec, avail, kind):
    if spec in (None, "all"):
        return list(avail)
    names = [s.strip() for s in spec.split(",") if s.strip()]
    bad = [n for n in names if n not in avail]
    if bad:
        sys.exit(f"unknown {kind}: {bad}\navailable: {list(avail)}")
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-c", "--config", default=str(DEFAULT_CFG))
    ap.add_argument("-w", "--workloads", help="comma list or 'all' (default all)")
    ap.add_argument("-t", "--topologies", help="comma list or 'all' (default all)")
    ap.add_argument("--stages", default="gen,sim,viz")
    ap.add_argument("-j", "--jobs", type=int, default=1)
    ap.add_argument("-o", "--out", help="override output_root")
    ap.add_argument("--force", action="store_true", help="redo even if outputs exist")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.config))
    out = REPO / (a.out or cfg["output_root"])
    topos = cfg["topologies"]
    wls = {}
    for g in cfg.get("workload_globs", []):
        for p in sorted(REPO.glob(g)):
            wls[p.stem] = str(p.relative_to(REPO))
    wls.update(cfg.get("workloads") or {})

    if a.list:
        print("workloads:", *wls, sep="\n  ")
        print("topologies:", *[f"{k} ({v['nodes']} nodes)" for k, v in topos.items()], sep="\n  ")
        return

    sel_w = pick(a.workloads, wls, "workload")
    sel_t = pick(a.topologies, topos, "topology")
    stages = set(a.stages.split(","))
    bs = cfg["booksim"]
    bs_base = REPO / bs["base_dir"]
    rel = lambda p: os.path.relpath(p, bs_base)

    def wl_yaml(w, nodes):
        e = wls[w]
        if isinstance(e, dict):
            e = e.get(nodes)
        return REPO / e if e else None

    def trace_csv(w, nodes):
        return out / "traces" / f"{w}_n{nodes}.csv"

    def pkts(w, t):
        return out / "sim" / w / t / "packets_out.csv"

    # ---- gen ----
    jobs, status = [], {}
    if "gen" in stages:
        done = set()
        for w in sel_w:
            for t in sel_t:
                n = topos[t]["nodes"]
                if (w, n) in done:
                    continue
                done.add((w, n))
                y, c = wl_yaml(w, n), trace_csv(w, n)
                if y is None:
                    print(f"[skip] {w}: no yaml for {n} nodes")
                    continue
                yn = yaml.safe_load(open(y)).get("nodes")
                if yn is not None and yn != n and not (c.exists() and not a.force):
                    sys.exit(f"{w}: yaml says nodes={yn} but topology '{t}' needs {n}. "
                             f"Edit {y.relative_to(REPO)} (and its matrix file) first.")
                if c.exists() and not a.force:
                    print(f"[have] {c.relative_to(REPO)}")
                    continue
                c.parent.mkdir(parents=True, exist_ok=True)
                cmd = shlex.split(cfg["gen_cmd"].format(yaml=y.relative_to(REPO), csv=c.relative_to(REPO), nodes=n))
                if sh(cmd, dry=a.dry_run):
                    sys.exit(f"gen failed for {w} @ {n} nodes")

    # ---- sim ----
    if "sim" in stages:
        def one(wt):
            w, t = wt
            n, tc = topos[t]["nodes"], topos[t]
            c, p = trace_csv(w, n), pkts(w, t)
            if not c.exists() and not a.dry_run:
                return wt, "no-trace"
            if p.exists() and not a.force:
                return wt, "cached"
            p.parent.mkdir(parents=True, exist_ok=True)
            cfg_copy = p.parent / "run.cfg"
            if not a.dry_run:
                make_cfg(REPO / tc["config"], rel(c), rel(p), cfg_copy, bs)
            cmd = shlex.split(bs["cmd"]) + [rel(cfg_copy)]
            rc = sh(cmd, log=p.parent / "booksim.log", dry=a.dry_run)
            return wt, "ok" if rc == 0 and (p.exists() or a.dry_run) else f"FAIL(rc={rc})"

        pairs = [(w, t) for w in sel_w for t in sel_t]
        with ThreadPoolExecutor(a.jobs) as ex:
            for wt, s in ex.map(one, pairs):
                status[wt] = s
        print("\nsim summary")
        for (w, t), s in status.items():
            print(f"  {w:24s} {t:10s} {s}")

    # ---- viz (one report per workload) ----
    if "viz" in stages:
        for w in sel_w:
            runs = []
            for t in sel_t:
                n = topos[t]["nodes"]
                if pkts(w, t).exists() and trace_csv(w, n).exists():
                    runs += ["--run", f"{topos[t]['label']}:{trace_csv(w, n).relative_to(REPO)}:{pkts(w, t).relative_to(REPO)}"]
            if not runs:
                print(f"[skip] viz {w}: no results")
                continue
            rep = out / "reports" / f"{w}.html"
            rep.parent.mkdir(parents=True, exist_ok=True)
            sh(shlex.split(cfg["viz_cmd"]) + runs + ["--out", str(rep.relative_to(REPO)), "--offline"], dry=a.dry_run)
            print(f"[report] {rep.relative_to(REPO)}")


if __name__ == "__main__":
    main()