#!/usr/bin/env python3
"""T3 Topology — sweep injection rate across topologies, collect latency data."""
import subprocess, json, os, re, sys, math
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
RESULTS_DIR = Path(__file__).parent.parent / "results"
CONFIGS = sorted(CONFIGS_DIR.glob("*.cfg"))
# Injection rates. RATES="0.05,0.1,..." pins an explicit list; otherwise each
# topology gets an ADAPTIVE ramp (see sweep_adaptive).
#
# A fixed list cannot serve every topology: uniform traffic on a 4x4 mesh knees at
# ~0.15, but the Timeloop matrix (with its memory-controller hotspot) knees at
# ~0.025, and a 64-node mesh lower still. Any single list therefore samples one of
# them almost entirely in the flat low-load regime -- which plots as a straight
# line and hides the saturation cliff the whole experiment is about.
_rates = os.environ.get("RATES")
INJECTION_RATES = [float(x) for x in _rates.split(",")] if _rates else None

RATE_START = float(os.environ.get("RATE_START", 0.002))  # below any knee we've seen
RATE_MAX = float(os.environ.get("RATE_MAX", 0.6))
RATE_STEP = float(os.environ.get("RATE_STEP", 1.3))      # geometric: dense near the knee
# Stop once latency is this many x zero-load. Past saturation Booksim's reported
# average goes non-monotonic (undelivered packets aren't counted, so it can even
# FALL: a 64-node mesh reads 235 cyc then 109 at a higher rate). So we compare the
# running peak, not the current point -- testing the current value lets a dip slip
# under the threshold and drags a tail of meaningless noise onto the plot.
SAT_FACTOR = float(os.environ.get("SAT_FACTOR", 5.0))

# Optional Timeloop-derived traffic matrix (the Timeloop->Booksim bridge). When
# set, topologies are driven by this matrix instead of uniform random traffic.
#
# May contain "{n}" — substituted with each topology's node count, so one sweep
# can mix 16- and 64-node topologies, each driven by a matrix of its own size.
# A plain path (no "{n}") still works and pins the sweep to that one size.
MATRIX = os.environ.get("TRAFFIC_MATRIX")


def matrix_for(nodes):
    """Matrix path for a topology with `nodes` nodes, or None if we have none."""
    if not MATRIX:
        return None
    if "{n}" not in MATRIX:
        return MATRIX
    if not nodes:
        return None  # size unknown -> can't pick a matrix
    p = MATRIX.replace("{n}", str(nodes))
    return p if Path(p).exists() else None


def nodes_from_cfg(cfg: Path):
    """Node count Booksim will build for this config, or None if we can't tell.

    A traffic matrix is defined over N tiles and Booksim *requires* it to be
    exactly N x N, so a matrix sweep can only compare topologies that agree on N.
    Knowing N up front lets us say so, instead of letting Booksim die per-run.
    """
    # Booksim accepts several `key = val;` pairs on one line, so don't anchor to
    # line start. Strip comments first or a stray "n = ..." in one would match.
    txt = re.sub(r"//.*|#.*", "", cfg.read_text())

    def val(key):
        m = re.search(rf"\b{key}\s*=\s*([A-Za-z0-9_]+)\s*;", txt)
        return m.group(1) if m else None

    topo = val("topology")
    try:
        k, n = int(val("k")), int(val("n"))
    except (TypeError, ValueError):
        return None
    # k^n: one node per leaf router.
    if topo in ("mesh", "torus", "fly", "fattree", "qtree", "tree4"):
        return k ** n
    # Concentrated: c nodes hang off each router. Booksim also asserts c == xr*yr.
    if topo in ("cmesh", "flatfly"):
        try:
            return (k ** n) * int(val("c"))
        except (TypeError, ValueError):
            return None
    # dragonflynew's size is a non-obvious function of k (k=4 -> 1056 nodes), and
    # anynet reads its network from a file. Don't guess -- let Booksim speak.
    return None


def matrix_nodes(path: str):
    """N for an N x N matrix file, or None if it isn't square."""
    vals = 0
    for line in Path(path).read_text().splitlines():
        vals += len(line.split("#", 1)[0].split())
    n = math.isqrt(vals)
    return n if n * n == vals else None


def run_one(cfg: Path, rate: float, matrix=None, nodes=None) -> dict:
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    cmd = [booksim, str(cfg), f"injection_rate={rate}"]
    if matrix:
        cmd.append(f"traffic=matrix({matrix})")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    latency = hops = None
    for line in result.stdout.splitlines():
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
    res = {
        "topology": cfg.stem,
        "nodes": nodes,  # lets the dashboard label size; sweeps may now mix them
        "injection_rate": rate,
        "traffic": f"matrix({Path(matrix).name})" if matrix else "uniform",
        "latency_cycles": latency,
        "hops_avg": hops,  # energy proxy = hops_avg * packet_size (Pareto step)
        "status": "ok" if latency is not None else "failed",
        # NB: Booksim exits 255 even on success, so returncode says nothing --
        # a run succeeded iff it printed a latency.
        "returncode": result.returncode,
    }
    if latency is None:
        # Keep Booksim's own words. Without this the run lands in the JSON as a
        # bare null, the dashboard drops it, and the topology just silently
        # vanishes from the plot with no clue why.
        err = next((l for l in (result.stdout + result.stderr).splitlines()
                    if l.strip().startswith("Error")), None)
        res["error"] = err or "booksim printed no latency (crashed, hung, or deadlocked)"
    return res


def sweep(cfg: Path, matrix, nodes):
    """All injection-rate points for one topology.

    Explicit RATES -> just run them. Otherwise ramp geometrically from RATE_START
    until latency crosses SAT_FACTOR x zero-load, so the curve always straddles
    this topology's own knee instead of a rate list guessed in advance. The knee
    is where the interesting answer lives -- a topology that saturates later is
    the one that wins -- and it moves by ~6x between uniform and matrix traffic.
    """
    label = f"{cfg.stem} ({nodes or '?'}n)"

    if INJECTION_RATES:
        out = []
        for rate in INJECTION_RATES:
            print(f"  {label} @ {rate} ...", end=" ")
            res = run_one(cfg, rate, matrix, nodes)
            print(res["latency_cycles"] if res["status"] == "ok"
                  else f"FAILED — {res['error']}")
            out.append(res)
        return out

    out, zero_load, peak, rate = [], None, 0.0, RATE_START
    while rate <= RATE_MAX:
        print(f"  {label} @ {rate:.4g} ...", end=" ")
        res = run_one(cfg, round(rate, 5), matrix, nodes)
        out.append(res)
        lat = res["latency_cycles"]
        if lat is None:
            # Below saturation Booksim always reports a latency. Failing at the
            # very first rate means the config is broken (bad routing function,
            # wrong matrix size); failing later just means we pushed past the
            # point it can drain, which is the end of a useful curve either way.
            print(f"FAILED — {res['error']}")
            break
        if zero_load is None:
            zero_load = lat
        peak = max(peak, lat)
        print(f"{lat:.2f}")
        if peak >= SAT_FACTOR * zero_load:
            print(f"  {label}: saturated at {rate:.4g} "
                  f"({peak:.0f} cyc = {peak / zero_load:.0f}x zero-load) — stopping")
            break
        rate *= RATE_STEP
    return out


def fail(results, failed, cfg, nodes, msg):
    print(f"  {cfg.stem}: SKIPPED — {msg}")
    failed.append(cfg.stem)
    results.append({
        "topology": cfg.stem, "nodes": nodes, "injection_rate": None,
        "traffic": "matrix", "latency_cycles": None, "hops_avg": None,
        "status": "skipped", "error": msg,
    })


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results, failed = [], []
    for cfg in CONFIGS:
        nodes = nodes_from_cfg(cfg)
        matrix = matrix_for(nodes)

        # Pre-flight, so a size problem is one clear line rather than N booksim
        # aborts (or worse, a topology that silently never reaches the dashboard).
        if MATRIX and not matrix:
            if not nodes:
                fail(results, failed, cfg, nodes,
                     "can't derive node count for this topology, so no traffic "
                     "matrix can be matched to it (add it to nodes_from_cfg, or "
                     "sweep it with uniform traffic)")
            else:
                want = MATRIX.replace("{n}", str(nodes))
                fail(results, failed, cfg, nodes,
                     f"needs a {nodes}x{nodes} matrix; {want} does not exist "
                     f"(run `make timeloop` to generate every size in configs/)")
            continue
        if matrix:
            mn = matrix_nodes(matrix)
            if mn is None:
                fail(results, failed, cfg, nodes, f"{matrix} is not square")
                continue
            if nodes and mn != nodes:
                fail(results, failed, cfg, nodes,
                     f"needs a {nodes}x{nodes} matrix, but {Path(matrix).name} "
                     f"is {mn}x{mn}")
                continue

        got = sweep(cfg, matrix, nodes)
        if not any(r["status"] == "ok" for r in got) and cfg.stem not in failed:
            failed.append(cfg.stem)
        results.extend(got)

    report = RESULTS_DIR / "topology_sweep.json"
    with open(report, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  {len(results)} data points → {report}")

    if failed:
        print(f"\n  ⚠  {len(failed)} topology(ies) produced no data and will NOT "
              f"be plotted: {', '.join(failed)}")


def _selfcheck():
    import tempfile
    d = Path(tempfile.mkdtemp())
    # real repo style: one key per line, trailing // comment
    (d / "mesh4x4.cfg").write_text(
        "topology = mesh;\nk = 4;\nn = 2;   // 4x4 = 16 nodes, n is #dims\n"
        "num_vcs = 4;\nvc_buf_size = 8;\n")
    # packed style: booksim accepts it, so we must too
    (d / "mesh8x8.cfg").write_text("topology = mesh; k = 8; n = 2;\n")
    (d / "cmesh.cfg").write_text("topology = cmesh; k = 4; n = 2; c = 4;\n")
    (d / "ft.cfg").write_text("topology = fattree; k = 4; n = 2;\n")
    (d / "df.cfg").write_text("topology = dragonflynew; k = 4; n = 1;\n")
    assert nodes_from_cfg(d / "mesh4x4.cfg") == 16    # comment doesn't confuse it
    assert nodes_from_cfg(d / "mesh8x8.cfg") == 64
    assert nodes_from_cfg(d / "cmesh.cfg") == 64      # concentration applies
    assert nodes_from_cfg(d / "ft.cfg") == 16         # fattree is k^n
    assert nodes_from_cfg(d / "df.cfg") is None       # k=4 -> 1056; don't guess

    (d / "m16.txt").write_text("# c\n" + "\n".join(" ".join("1" for _ in range(16))
                                                   for _ in range(16)))
    (d / "ragged.txt").write_text("1 2 3\n4 5\n")
    assert matrix_nodes(d / "m16.txt") == 16          # comments ignored
    assert matrix_nodes(d / "ragged.txt") is None     # 5 entries -> not square
    print("selfcheck OK")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        main()
