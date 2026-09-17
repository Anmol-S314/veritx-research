#!/usr/bin/env python3
"""T3 Topology — sweep injection rate across topologies, collect latency data.

Live progress: prints a per-point line the moment each BookSim run finishes,
and rewrites results/<CONFIG>/topology_sweep.json incrementally so a long
sweep can be Ctrl-C'd without losing the points already measured.
"""
import subprocess, json, os, sys, time, shutil, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.t3log import SweepLogger, log_crash

ROOT = Path(__file__).resolve().parent.parent

CONFIG = os.environ.get("CONFIG", "baseline")

# Node-honest sweep sets (scripts/gen_sweep_configs.py): _N64/_N16 CONFIG
# suffixes route to configs/n64|n16; anything else keeps the legacy mixed
# configs/ dir (16+64+72-node topos under one roof) for back-compat.
# Explicit --configs always wins.
CONFIGS_DIR = ROOT / "configs"
RESULTS_DIR = ROOT / "results" / CONFIG

# CI sweep (coarse). Override for local/matrix runs: RATES="0.002,0.005,0.01,0.02"
# (matrix patterns with a hotspot saturate at much lower rates than uniform).
_rates = os.environ.get("RATES")
# Default mirrors t3:64 container default (RATES="0.002,0.005,0.01,0.02,0.03").
# Keep both in sync: matrix patterns with a hotspot saturate at much lower
# rates than uniform, so the old [0.05..0.4] grid measured saturation, not ranking.
def _parse_rates(rates_str: str | None) -> list[float]:
    """RATES csv -> floats. A bad value is a user typo: fail with an
    actionable message instead of a raw ValueError traceback mid-argparse."""
    if not rates_str:
        return [0.002, 0.005, 0.01, 0.02, 0.03]
    try:
        out = [float(x) for x in rates_str.split(",")]
    except ValueError:
        print(f"  ✗ RATES={rates_str!r} is not a comma-separated list of numbers "
              f'(e.g. RATES="0.002,0.005,0.01")', file=sys.stderr)
        raise SystemExit(2)
    bad = [x for x in out if not (0.0 < x < 1.0)]
    if bad:
        print(f"  ✗ RATES out of range (0,1): {bad} — injection_rate is per-node "
              f"flits/cycle, values >= 1 are unphysical", file=sys.stderr)
        raise SystemExit(2)
    return out


INJECTION_RATES = _parse_rates(_rates)

# Optional Timeloop-derived traffic matrix (the Timeloop->Booksim bridge). When
# set, every topology is driven by this matrix instead of uniform random traffic.
MATRIX = os.environ.get("TRAFFIC_MATRIX")

REPORT = RESULTS_DIR / "topology_sweep.json"


def _matrix_entries(path):
    """Total numeric entries in a BookSim matrix file (None if unreadable).

    Skips `#` comments and blanks. BookSim itself demands entries ==
    nodes² and errors loudly otherwise (verified live); this preflight only
    saves burning runs on the guaranteed mismatch.
    """
    try:
        n = 0
        with open(path) as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#"):
                    n += len(s.split())
        return n
    except OSError:
        return None


def _cfg_usable(cfg: Path) -> bool:
    """Preflight: anynet cfgs need their network_file to resolve.

    BookSim resolves network_file against its cwd, so an anynet cfg is a
    guaranteed failure unless the file exists relative to the cfg dir or
    the cwd. Skip loudly instead of burning runs on no_output rows.
    (Canonical copy; sanity_test.py carries the same lines to stay
    dependency-free.)
    """
    import re
    try:
        text = cfg.read_text()
    except OSError:
        return True  # unreadable cfg: let BookSim report the real error
    if "topology = anynet" not in text:
        return True
    m = re.search(r"network_file\s*=\s*([^;\s]+)", text)
    if not m:
        print(f"  ⚠ skipping {cfg.name}: anynet without network_file")
        return False
    if (cfg.parent / m.group(1)).exists() or Path(m.group(1)).exists():
        return True
    print(f"  ⚠ skipping {cfg.name}: network_file {m.group(1)} resolves nowhere "
          f"(tried cfg dir + cwd)")
    return False


def run_one(cfg: Path, rate: float, nodes=None) -> dict:
    booksim = os.environ.get("BOOKSIM_BIN") or "booksim"
    # Fail loudly (exit 2) instead of a FileNotFoundError traceback — or
    # worse, 55 "no_output" rows that look like measured data.
    _hit = Path(booksim) if "/" in booksim else shutil.which(booksim)
    if _hit is None or not os.access(_hit, os.X_OK):
        print(f"  \u2717 booksim binary not found or not executable: {booksim!r}",
              file=sys.stderr)
        print("    resolve it via run/env.sh (BOOKSIM_BIN), or build it:",
              file=sys.stderr)
        print("      cd third_party/booksim2/src && make -j$(nproc)", file=sys.stderr)
        raise SystemExit(2)
    cmd = [booksim, str(cfg), f"injection_rate={rate}"]
    if MATRIX:
        cmd.append(f"traffic=matrix({MATRIX})")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {
            "topology": cfg.stem,
            "nodes": nodes,
            "injection_rate": rate,
            "traffic": f"matrix({Path(MATRIX).name})" if MATRIX else "uniform",
            "latency_cycles": None,
            "hops_avg": None,
            "status": "timeout",
            "returncode": -1,
            "error": f"booksim timed out after 300s",
        }
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
    import math
    # A parsed latency is only a measurement if the run COMPLETED. A crashed
    # or failed sim can still print a partial-stats latency line — recording
    # it as ok turned a die() mid-Run() into plausible data (rc was recorded
    # but ignored). Nonzero rc or nonfinite metrics => explicit failed row.
    _finite = latency is not None and math.isfinite(latency) \
        and (hops is None or math.isfinite(hops))
    if result.returncode == 0 and _finite:
        status = "ok"
    elif result.returncode != 0:
        status = f"failed (rc={result.returncode})"
    elif latency is None:
        status = "no_output"
    else:  # parsed values exist but are nonfinite (inf/nan)
        status = "nonfinite_output"
    return {
        "topology": cfg.stem,
        "nodes": nodes,  # from sizes.json; None for legacy mixed sets
        "injection_rate": rate,
        "traffic": f"matrix({Path(MATRIX).name})" if MATRIX else "uniform",
        "latency_cycles": latency if status == "ok" else None,
        "hops_avg": hops if status == "ok" else None,
        "status": status,
        "returncode": result.returncode,
    }


def _save(results: list) -> None:
    tmp = REPORT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(results, indent=2))
    tmp.rename(REPORT)  # atomic on POSIX


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--configs", default=None,
                    help="cfg directory (default: from CONFIG suffix — *_N64 → configs/n64, "
                         "*_N16 → configs/n16, else legacy configs/)")
    a = ap.parse_args()
    if a.configs:
        configs_dir = Path(a.configs)
    elif CONFIG.upper().endswith("_N64"):
        configs_dir = CONFIGS_DIR / "n64"
    elif CONFIG.upper().endswith("_N16"):
        configs_dir = CONFIGS_DIR / "n16"
    else:
        configs_dir = CONFIGS_DIR
        print("  note: legacy mixed-size configs/ (16+64+72-node topos); "
              "use CONFIG=*_N64|*_N16 or --configs for a size-honest set")
    CONFIGS = sorted(configs_dir.glob("*.cfg"))
    sizes = {}
    _sizes_json = configs_dir / "sizes.json"
    if _sizes_json.is_file():
        try:
            sizes = json.loads(_sizes_json.read_text())
        except (json.JSONDecodeError, OSError):
            sizes = {}
    # Quarantine: anynet cfgs whose network_file resolves nowhere are
    # guaranteed no_output rows, not measurements. Skip loudly up front
    # instead of burning (topos × rates) runs on them.
    CONFIGS = [c for c in CONFIGS if _cfg_usable(c)]
    # Matrix-size guard: one shared matrix must match each topo's node
    # count (N² entries; (N+1)² allowed for DRAM-augmented spatial
    # matrices). BookSim errors loudly on mismatch too — this just skips
    # before burning runs. Topos without sizes.json coverage can't be
    # checked here; BookSim remains the backstop.
    if MATRIX:
        _entries = _matrix_entries(MATRIX)
        if _entries is None:
            print(f"  ⚠ cannot read matrix {MATRIX} — BookSim will report")
        else:
            _kept = []
            for c in CONFIGS:
                _n = sizes.get(c.stem)
                if _n is not None and _entries not in (_n * _n, (_n + 1) * (_n + 1)):
                    print(f"  ⚠ skipping {c.stem}: matrix has {_entries} entries, "
                          f"needs {_n * _n} (or {(_n + 1) * (_n + 1)} with DRAM node)")
                    continue
                _kept.append(c)
            CONFIGS = _kept
    if not CONFIGS:
        # Empty selection is a typo/quarantine-everything, never a result:
        # fail loudly instead of writing a valid-looking empty report (rc 0
        # here once produced an "all green, 0 runs" artifact).
        print("  ✗ no usable topology configs — nothing to sweep "
              "(bad --configs dir? every cfg quarantined?)", file=sys.stderr)
        raise SystemExit(2)
    total = len(CONFIGS) * len(INJECTION_RATES)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Using configuration: {CONFIG}")
    print(f"  {len(CONFIGS)} topologies x {len(INJECTION_RATES)} rates = {total} runs"
          + (f"  [matrix: {Path(MATRIX).name}]" if MATRIX else "  [uniform traffic]"))
    print("  (each line lands the moment its BookSim run finishes)")

    results: list = []
    if REPORT.exists():
        try:
            results = json.loads(REPORT.read_text())
            print(f"  resuming: {len(results)} points already in {REPORT.name}")
        except (json.JSONDecodeError, OSError):
            results = []

    # Set-change guard: resuming across different topology sets would mix
    # sizes in one file (the old mixed-dir rows next to n64 rows). When the
    # on-disk set doesn't match this run's set, archive it aside and start
    # fresh — loudly, never by silent merge.
    _want = {c.stem for c in CONFIGS}
    _have = {r.get("topology") for r in results if r.get("status") == "ok"}
    if _have and _have != _want:
        _ts = time.strftime("%Y%m%d_%H%M%S")
        # Archives live in archive/ (NOT next to the live file): aggregate
        # ingests every top-level *.json in results/, so a same-dir backup
        # would silently re-merge the superseded set into the report.
        _archdir = REPORT.parent / "archive"
        _archdir.mkdir(parents=True, exist_ok=True)
        _arch = _archdir / f"topology_sweep.prev_{_ts}.json"
        _arch.write_text(json.dumps(results, indent=2))
        print(f"  topology set changed ({sorted(_have)} → {sorted(_want)}): "
              f"archived {len(results)} old points to {_arch.name}, starting fresh")
        results = []

    # Structured session log: logs/<sweep_id>/events.ndjson + sweep.log.
    slog = SweepLogger("sim", CONFIG, extra={"rates": os.environ.get("RATES", ""),
                                             "topo": os.environ.get("TOPO", ""),
                                             "matrix": Path(MATRIX).name if MATRIX else ""})
    slog.log_event("resume_state", points_already=len(results))

    done = {  # skip (topo, rate) pairs already measured
        (r["topology"], float(r["injection_rate"]))
        for r in results if r.get("status") == "ok"
    }

    n = 0
    t0 = time.time()
    ok_count = skip_count = fail_count = 0
    try:
        for cfg in CONFIGS:
            for rate in INJECTION_RATES:
                n += 1
                if (cfg.stem, rate) in done:
                    skip_count += 1
                    _skip_line = f"  [{n:>3}/{total}] {cfg.stem:<16} @ {rate:<6g}  ─ already measured, skip"
                    print(_skip_line)
                    slog.session_log(_skip_line)
                    slog.log_event("point", topology=cfg.stem, injection_rate=rate,
                                   status="skip")
                    continue
                tag = "  "  # placeholder so the except-branch can reference it
                _ts = time.time()
                try:
                    res = run_one(cfg, rate, nodes=sizes.get(cfg.stem))
                except subprocess.TimeoutExpired:
                    res = {
                        "topology": cfg.stem, "injection_rate": rate,
                        "traffic": f"matrix({Path(MATRIX).name})" if MATRIX else "uniform",
                        "latency_cycles": None, "hops_avg": None,
                        "status": "timeout", "returncode": -1,
                    }
                dt = time.time() - _ts
                results.append(res)
                _save(results)
                if res["status"] == "ok":
                    ok_count += 1
                    lat = res["latency_cycles"]
                    lat_s = f"{lat:.2f}c" if isinstance(lat, float) else str(lat)
                    _line = f"  \033[32m✓\033[0m [{n:>3}/{total}] {cfg.stem:<16} @ {rate:<6g} → {lat_s}  ({dt:.1f}s)"
                else:
                    fail_count += 1
                    _line = f"  \033[31m✗\033[0m [{n:>3}/{total}] {cfg.stem:<16} @ {rate:<6g} → {res['status']}  ({dt:.1f}s)"
                print(_line)
                slog.session_log(_line)
                slog.log_event("point", topology=cfg.stem, injection_rate=rate,
                               status=("ok" if res["status"] == "ok" else "error"),
                               detail=str(res["status"]),
                               latency_cycles=res.get("latency_cycles"),
                               elapsed_ms=int(dt * 1000))
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n  interrupted — partial results saved")
        slog.session_log("interrupted — partial results saved")
        slog.finish("interrupted", {"ok": ok_count, "skipped": skip_count,
                                    "failed": fail_count})
    except (OSError, subprocess.SubprocessError) as e:
        log_crash(e)  # tool missing / sim crashed out — record, re-raise
        raise
    elapsed = time.time() - t0
    print(f"\n  {ok_count} new + {skip_count} skipped ({fail_count} failed) → {REPORT}")
    if elapsed > 0.5:
        print(f"  elapsed {elapsed:.0f}s")
    slog.session_log(f"done: {ok_count} new + {skip_count} skipped "
                     f"({fail_count} failed)")
    slog.finish("done", {"ok": ok_count, "skipped": skip_count,
                         "failed": fail_count})
    if fail_count:
        # A sweep with failed points is not a successful sweep: the partial
        # JSON stays on disk (for triage) but the command fails, so CI / make
        # never read failed points as data. Previously rc stayed 0 and a
        # BookSim that exited 7 mid-Run produced `status: ok` rows.
        print(f"  ✗ {fail_count} sweep point(s) failed — see status fields in {REPORT.name}",
              file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
