#!/usr/bin/env python3
"""Gate R1 co-sim driver (RTL-ARC.md section 8).

BookSim (fork, trace_out + flit_dump) <-> Verilator (trace replay + eject dump).

Subcommands:
  gen-trace <booksim> <cfg> <outdir>
      Run BookSim, write:
        <outdir>/trace.txt      the stimulus  (cycle src cl dst size, gen order)
        <outdir>/flits.txt      BookSim per-flit retire dump (atime cl src dst pid itime)
        <outdir>/trace_n%d.hex  per-NIC BRAM images for the RTL replay
        <outdir>/run_cycles     RTL run length = last retire + drain margin
  diff <outdir> [tol]
      Match <outdir>/flits.txt (BookSim) against <outdir>/rtl_flits.txt (RTL),
      per flit. pid correlation:
        BookSim pid == trace line index (global generation order)
        RTL     pid == per-NIC entry index (the NIC's own trace order)
      Strict (tol=0, default): every flit must match (atime, cl, src, dst,
      itime) exactly. With tol=N: (cl, src, dst) exact, |Δatime| and
      |Δitime| <= N. The strict count is ALWAYS reported alongside the
      tolerant one -- the tolerance is a documented fidelity bound, not a
      way to hide timing drift (PITFALLS 24, policy 2026-08-10).
      Exit 0 iff no flit exceeds the tolerance.

Failure => nonzero exit (the gate FAILS; nothing is averaged away).

  sweep <booksim> <rtlroot> <outdir> [grid]
      Gate R1 sweep grid: burst x VC-count cells on the 8x8 mesh (the
      plane-separation burst table: B in {5,10,20,40,80} at B*r = 0.08,
      VCs in {1,2,4}, seed 1, control class 0.005). For each cell:
      gen-trace, (re)build the RTL binary for its VC count if missing,
      run the Verilator replay, diff. Prints a per-cell PASS/FAIL table;
      exit 0 iff every cell passes.
"""

import sys

DRAIN = 2500
GRID = [(5, 0.016), (10, 0.008), (20, 0.004), (40, 0.002), (80, 0.001)]
VCS_LIST = [1, 2, 4]
CONTROL_RATE = 0.005
NICS = [0, 9, 18, 27, 36, 45, 54, 63]          # 8x8 main diagonal
X_DIM = 8
Y_DIM = 8


def gen_trace(booksim, cfg, outdir):
    import os
    import subprocess
    os.makedirs(outdir, exist_ok=True)
    # NB: this fork returns -1 (255) on success, 0 on "simulation unstable"
    # (convergence aborted; the trace/dump are still valid stimulus).
    r = subprocess.run([booksim, cfg], cwd=outdir)
    if r.returncode not in (0, 255):
        sys.exit(f"booksim failed with exit {r.returncode}")
    if r.returncode == 0:
        print("WARN: booksim reported 'simulation unstable' (convergence)")
    trace = [l.split() for l in open(f"{outdir}/trace.txt") if l.strip()]
    assert trace, "empty trace"
    # per-NIC hex images, 64-bit entries {cycle, cl, dst, size}
    by_src = {}
    for cyc, src, cl, dst, size in trace:
        by_src.setdefault(int(src), []).append(
            (int(cyc), int(cl), int(dst), int(size)))
    for src, entries in by_src.items():
        with open(f"{outdir}/trace_n{src}.hex", "w") as f:
            for cyc, cl, dst, size in entries:
                f.write(f"{cyc:08x}{cl:02x}{dst:02x}{size:04x}\n")
    # run the RTL until every BookSim flit has retired (plus margin): if the
    # RTL were slower than BookSim it would fail the TB's drain check.
    last_atime = 0
    for l in open(f"{outdir}/flits.txt"):
        if l.strip():
            last_atime = max(last_atime, int(l.split()[0]))
    open(f"{outdir}/run_cycles", "w").write(str(last_atime + DRAIN) + "\n")
    print(f"gen-trace: {len(trace)} packets, last cycle {trace[-1][0]}, "
          f"last retire {last_atime}, run {last_atime + DRAIN}")


def diff(outdir, tol=0):
    trace = [l.split() for l in open(f"{outdir}/trace.txt") if l.strip()]
    n_pkts = len(trace)
    # per-(src, cl) ordered packet lists -> seq mapping
    seq_map = {}                      # (src, cl) -> list of packet indices
    for k, (cyc, src, cl, dst, size) in enumerate(trace):
        seq_map.setdefault((int(src), int(cl)), []).append(k)
    pkt_info = {k: (int(l[1]), int(l[2]), int(l[3]), int(l[4]))
                for k, l in enumerate(trace)}   # k -> (src, cl, dst, size)

    def read_dump(path):
        out = {}
        for l in open(path):
            if not l.strip():
                continue
            a, cl, src, dst, pid, it = map(int, l.split())
            out.setdefault(pid, []).append((a, cl, src, dst, it))
        return out

    bs = read_dump(f"{outdir}/flits.txt")
    rt = {}
    for l in open(f"{outdir}/rtl_flits.txt"):
        if not l.strip():
            continue
        a, cl, src, dst, pid, it = map(int, l.split())
        rt.setdefault((src, pid), []).append((a, cl, src, dst, it))
    # RTL pid is the per-NIC trace entry index, i.e. the ordinal of that
    # packet within its source NIC's trace lines (global order -> ordinal).
    src_ordinal = {}                          # (src, global_idx) -> rtl pid
    per_src = {}
    for k, (cyc, src, cl, dst, size) in enumerate(trace):
        per_src.setdefault(int(src), []).append(k)
    for src, idxs in per_src.items():
        for j, k in enumerate(idxs):
            src_ordinal[(src, k)] = j

    strict_fails = 0
    tol_fails = 0
    checked = 0
    for k in range(n_pkts):
        src, cl, dst, size = pkt_info[k]
        b = sorted(bs.get(k, []))
        r = sorted(rt.get((src, src_ordinal[(src, k)]), []))
        if len(b) != size or len(r) != size:
            print(f"FAIL pkt {k} (src {src} cl {cl} dst {dst}): "
                  f"BookSim {len(b)}/{size} flits, RTL {len(r)}/{size}")
            strict_fails += 1
            tol_fails += 1
            continue
        for i, (ba, ra) in enumerate(zip(b, r)):
            checked += 1
            # strict: (atime, cl, src, dst, itime) all equal; tolerant: ids
            # exact, |Δatime|,|Δitime| <= tol. tol=0 collapses to strict.
            if ba != ra:
                strict_fails += 1
                if (abs(ba[0] - ra[0]) > tol or abs(ba[4] - ra[4]) > tol or
                        ba[1] != ra[1] or ba[2] != ra[2] or ba[3] != ra[3]):
                    tol_fails += 1
                    print(f"FAIL pkt {k} flit {i}: BookSim {ba} vs RTL {ra}"
                          f" (outside ±{tol})")
    print(f"diff: {checked} flits compared, {n_pkts} packets, "
          f"strict mismatches {strict_fails}, tolerance ±{tol} mismatches "
          f"{tol_fails}")
    if tol_fails:
        print(f"GATE R1 (tol ±{tol}): {tol_fails} MISMATCH(ES)")
        return 1
    if strict_fails:
        print(f"GATE R1 (tol ±{tol}): PASS -- {strict_fails} timing-only "
              f"mismatch(es) within tolerance")
        return 0
    print("GATE R1: per-flit match, ZERO mismatches")
    return 0


def _avail_gb():
    """Available RAM in GB from /proc/meminfo (no psutil dependency)."""
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // (1024 * 1024)
    return 0


def _write_manifest(outdir, rtl_files, binaries):
    """Provenance record for a sweep: git SHA + source/binary mtimes.

    Results produced without this file are void (rule 2, GATE-R1-COORD.md).
    """
    import subprocess
    repo = os.path.dirname(os.path.abspath(outdir))
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, cwd=repo)
    status = subprocess.run(["git", "status", "--porcelain"],
                            capture_output=True, text=True, cwd=repo)
    with open(f"{outdir}/manifest.txt", "w") as f:
        f.write(f"git_sha: {sha.stdout.strip()}\n")
        f.write("uncommitted(porcelain):\n")
        hits = [l for l in status.stdout.splitlines()
                if any(rf.split("/")[-1] in l for rf in rtl_files)]
        for line in hits or ["  (clean)" if False else ""]:
            if line:
                f.write(f"  {line}\n")
        f.write("sources:\n")
        for rf in rtl_files:
            f.write(f"  {os.path.getmtime(rf):.0f} {rf}\n")
        f.write("binaries:\n")
        for v, b in binaries.items():
            if os.path.exists(b):
                f.write(f"  {os.path.getmtime(b):.0f} vc{v} {b}\n")


def sweep(booksim, rtlroot, outdir, tol=0):
    """Gate R1 grid: the plane-separation burst table, cell-for-cell."""
    import os
    import subprocess
    import time
    # Verilator -j spawns one g++ per job; the full noc_tb rebuild can exceed
    # the RAM/tmpfs budget of small machines. VERILATOR_JOBS (default 2) caps
    # it -- safe on 14GB hosts, where -j 8 OOMs cc1plus mid-build.
    vjobs = os.environ.get("VERILATOR_JOBS", "2")
    if _avail_gb() < 3:
        sys.exit(f"sweep aborted: only {_avail_gb()}GB available RAM "
                 "(GATE-R1-COORD rule 1)")

    base_cfg = f"""{rtlroot}/configs/plane_shared.cfg"""
    rtl_files = [
        f"{rtlroot}/rtl/noc_pkg.sv", f"{rtlroot}/rtl/islip.sv",
        f"{rtlroot}/rtl/router.sv", f"{rtlroot}/rtl/mesh.sv",
        f"{rtlroot}/rtl/nic.sv", f"{rtlroot}/tb/noc_tb.sv",
    ]
    os.makedirs(outdir, exist_ok=True)
    # one RTL binary per VC count (Verilator -G overrides the TB params)
    binaries = {}
    for v in VCS_LIST:
        bdir = f"{outdir}/vbuild_vc{v}"
        bin_ = f"{bdir}/Vnoc_tb"
        needs_rebuild = not os.path.exists(bin_)
        if not needs_rebuild:
            bin_mtime = os.path.getmtime(bin_)
            for rf in rtl_files:
                if os.path.getmtime(rf) > bin_mtime:
                    needs_rebuild = True
                    break

        if needs_rebuild:
            t0 = time.time()
            # VCS=8 (vc4) elaboration peaks hard; cap its jobs at 1 so a
            # 14GB host never OOM-kills the build silently (seen twice).
            build_jobs = "1" if v == 4 else vjobs
            total_vcs = v * 2
            r = subprocess.run(
                ["verilator", "-j", build_jobs, "--skip-identical", "-Wall",
                 "-Wno-fatal", "-DR1_MODE", "--binary",
                 "--top-module", "noc_tb",
                 f"-GVCS={total_vcs}", f"-GX_DIM={X_DIM}", f"-GY_DIM={Y_DIM}",
                 "--Mdir", bdir] + rtl_files,
                capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"verilator vc{v} failed:\n{r.stderr[-3000:]}")
            print(f"build vc{v}: {time.time() - t0:.0f}s")
        binaries[v] = bin_

    _write_manifest(outdir, rtl_files, binaries)

    cells = [(b, r, v) for (b, r) in GRID for v in VCS_LIST]
    fails = 0
    for b, rate, v in cells:
        cell = f"{outdir}/b{b}_vc{v}"
        os.makedirs(cell, exist_ok=True)
        with open(f"{cell}/cell.cfg", "w") as f:
            f.write(f"""
topology = mesh;
k = {X_DIM};
n = 2;
routing_function = dor;
num_vcs = {v};
vc_buf_size = 8;
classes = 2;
traffic = {{hotspot({','.join(map(str, NICS))}),uniform}};
packet_size = {{{b},1}};
injection_rate = {{{rate},{CONTROL_RATE}}};
sim_type = latency;
sample_period = 1000;
warmup_periods = 3;
max_samples = 30;
latency_thres = {{5000,500}};
seed = 1;
trace_out = trace.txt;
flit_dump = flits.txt;
""")
        t0 = time.time()
        gen_trace(booksim, f"{cell}/cell.cfg", cell)
        r = subprocess.run(
            [binaries[v], f"+run_cycles={open(f'{cell}/run_cycles').read().strip()}"],
            cwd=cell, capture_output=True, text=True)
        if "R1 SIM COMPLETE" not in r.stdout:
            print(f"FAIL b{b} vc{v}: RTL sim aborted:\n{r.stdout[-1500:]}"
                  f"{r.stderr[-1500:]}")
            fails += 1
            continue
        ok = diff(cell, tol) == 0
        if not ok:
            fails += 1
        print(f"cell b{b} vc{v}: {'PASS' if ok else 'FAIL'} "
              f"(tol ±{tol}, {time.time() - t0:.0f}s)")
    print(f"SWEEP: {len(cells) - fails}/{len(cells)} cells pass")
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "gen-trace":
        gen_trace(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "diff":
        tol = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        sys.exit(diff(sys.argv[2], tol))
    elif cmd == "sweep":
        tol = int(sys.argv[5]) if len(sys.argv) > 5 else 0
        sys.exit(sweep(sys.argv[2], sys.argv[3], sys.argv[4], tol))
    else:
        print(__doc__)
        sys.exit(2)
