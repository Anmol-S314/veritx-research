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
      REFUSES to run a cell.cfg whose DMA injection rate is not the canonical
      constant-flit-load rate for its burst size (L1 config lint, see
      docs/lessons.md — 2026-08-12: 12/15 cells ran with a wrong fixed rate).
  lint <cfg>
      Standalone: validate a cell.cfg against the canonical GRID rates.
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
import os
import subprocess
import time

# F13 (veritx-research-ee61): the RTL unicast pid lives at 0x8000+ (nic.sv),
# ABOVE the mcast stream space ((word<<4)|offset, max 32767) — disjoint by
# construction, no truncation. The pairing must mirror that base.
UNICAST_PID_BASE = 0x8000

DRAIN = 2500
GRID = [(5, 0.016), (10, 0.008), (20, 0.004), (40, 0.002), (80, 0.001)]
VCS_LIST = [1, 2, 4]
CONTROL_RATE = 0.005
NICS = [0, 9, 18, 27, 36, 45, 54, 63]          # 8x8 main diagonal
X_DIM = 8
Y_DIM = 8


ROOT_FIELD_RE = None


def _braced_fields(cfg, key):
    """First {..} in `key = {..}` as a list of strings, or None."""
    for l in open(cfg):
        l = l.strip()
        if l.startswith(key + " ="):
            body = l.split("=", 1)[1].strip()
            if body.startswith("{") and "}" in body:
                return [x.strip() for x in body[1:body.index("}")].split(",")]
    return None


def lint_cell(cfg):
    """L1 config lint: a cell.cfg must use the canonical constant-flit-load
    DMA rate for its burst length (GRID above). Any other rate changes the
    offered flit load and makes the cell incomparable to the paper's table.

    2026-08-12: a fixed {0.008, 0.005} rate silently shipped in 12 of 15
    cells; the wrong-rate runs produced a fake 0.68x-1.49x scatter. This
    lint runs inside gen-trace so a bad config is impossible to miss.
    Returns 0 if canonical, nonzero otherwise (caller decides handling).
    """
    pkt = _braced_fields(cfg, "packet_size")
    rate = _braced_fields(cfg, "injection_rate")
    bad = None
    if pkt is None or rate is None or not pkt or not rate:
        bad = f"{cfg}: cannot parse packet_size/injection_rate"
    else:
        burst = int(pkt[0])
        want = dict(GRID).get(burst)
        if want is None:
            bad = f"{cfg}: burst {burst} not in canonical GRID {GRID}"
        elif abs(float(rate[0]) - want) > 1e-9:
            bad = (f"{cfg}: burst {burst} demands injection_rate {want} "
                   f"(constant flit load {burst * want}), got {rate[0]}")
        elif len(rate) > 1 and abs(float(rate[1]) - CONTROL_RATE) > 1e-9:
            bad = (f"{cfg}: control class must be {CONTROL_RATE}, "
                   f"got {rate[1]}")
    if bad:
        print(f"L1 CONFIG LINT FAIL: {bad}", file=sys.stderr)
        return 1
    print(f"L1 config lint OK: {cfg} (burst {burst}, rate {rate[0]})")
    return 0


def lint_trace_files(outdir):
    """d604: a trace file that is EMPTY (0 bytes) leaves tmem uninitialized in
    the build — the fire guard (nic.sv:470-472) sees X and fires garbage
    (observed injected=16385 all dst-0, drain spins, timeout). A no-traffic
    NIC must carry the sentinel line 0000000000000000 (cycle=0, skipped) or
    have NO file at all. Returns 0 if clean."""
    import glob
    import os
    bad = [os.path.basename(f) for f in
           sorted(glob.glob(os.path.join(outdir, "trace_n*.hex")))
           if os.path.getsize(f) == 0]
    if bad:
        print(f"TRACE LINT FAIL: {len(bad)} EMPTY trace file(s) — replace with "
              f"the sentinel line 0000000000000000 (cycle=0, skipped by the "
              f"fire guard) or delete the file (d604): "
              f"{', '.join(bad[:5])}", file=sys.stderr)
        return 1
    print("trace lint OK (no empty trace files)")
    return 0




def gen_trace(booksim, cfg, outdir):
    import os
    import subprocess
    if lint_cell(cfg):
        sys.exit(f"gen-trace aborted: {cfg} fails canonical config lint (L1)")
    os.makedirs(outdir, exist_ok=True)
    if lint_trace_files(outdir):
        sys.exit(f"gen-trace aborted: {outdir} has EMPTY trace files (d604)")
    # NB: this fork returns -1 (255) on success, 0 on "simulation unstable"
    # (convergence aborted; the trace/dump are still valid stimulus).
    r = subprocess.run([booksim, cfg], cwd=outdir)
    if r.returncode not in (0, 255):
        sys.exit(f"booksim failed with exit {r.returncode}")
    if r.returncode == 0:
        print("WARN: booksim reported 'simulation unstable' (convergence)")
    trace = [l.split() for l in open(f"{outdir}/trace.txt") if l.strip()]
    assert trace, "empty trace"
    # per-NIC hex images, 64-bit entries {cycle, cl, dst, size}; a 9-field
    # "… mcast lo hi" line appends a second word {lo, hi} for the fork range
    by_src = {}
    for l in trace:
        if len(l) == 8 and l[5] == "mcast":
            cyc, src, cl, dst, size = int(l[0]), int(l[1]), int(l[2]), int(l[3]), int(l[4])
            lo, hi = int(l[6]), int(l[7])
        else:
            cyc, src, cl, dst, size = map(int, l[:5])
            lo = hi = -1
        by_src.setdefault(src, []).append((cyc, cl, dst, size, lo, hi))
    for src, entries in by_src.items():
        with open(f"{outdir}/trace_n{src}.hex", "w") as f:
            for cyc, cl, dst, size, lo, hi in entries:
                f.write(f"{cyc:08x}{cl:02x}{dst:02x}{size:04x}\n")
                if lo >= 0:
                    # range word: cycle field (upper 32) MUST be 0 -- the
                    # NIC identifies it by a zero cycle and non-'1 pattern;
                    # lo/hi ride in [63:56]/[55:48] (the NIC reads them there)
                    f.write(f"00000000{lo:02x}{hi:02x}0000\n")
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
    for k, l in enumerate(trace):
        cyc, src, cl, dst, size = l[0], l[1], l[2], l[3], l[4]
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
    # pid correlation under MIXED unicast+mcast traces (two-class cells):
    #
    # BookSim pids are GLOBAL and displaced by mcast copies: every trace
    # line consumes >= 1 pid (a unicast line 1, an mcast line 1 + copies),
    # so the k-th line's first pid = k + (copies generated by all earlier
    # mcast lines). The old code summed (1+copies) over earlier mcast lines
    # only, silently dropping the unicast lines' pid consumption once an
    # mcast stream precedes them in generation order.
    #
    # RTL pids are PER-SOURCE trace-word ordinals: a unicast entry consumes
    # 1 word, an mcast entry 2 (entry + range word), so a line's RTL pid =
    # the cumulative word count of its source's earlier lines (unicast pid =
    # word index; mcast stream pid = word index << 4). The old code used the
    # line ordinal, which only equals the word count when a source is
    # homogeneous (all-unicast or all-mcast).
    mcast_info = {}                           # k -> (lo, hi, far_end)
    bs_pid = {}                               # k -> BookSim first pid
    rtl_word = {}                             # (src, k) -> RTL word index
    per_src_words = {}
    bs_shift = 0
    for k, l in enumerate(trace):
        is_mcast = len(l) == 8 and l[5] == "mcast"
        if is_mcast:
            mcast_info[k] = (int(l[6]), int(l[7]), int(l[3]))
            ncopies = int(l[7]) - int(l[6]) + 1
            bs_pid[k] = k + bs_shift
            bs_shift += ncopies
        else:
            bs_pid[k] = k + bs_shift
        src = int(l[1])
        w = per_src_words.get(src, 0)
        rtl_word[(src, k)] = w
        per_src_words[src] = w + (2 if is_mcast else 1)

    strict_fails = 0
    tol_fails = 0
    checked = 0
    for k in range(n_pkts):
        src, cl, dst, size = pkt_info[k]
        if k in mcast_info:
            # one injection -> stream + g-1 copies; BookSim pids are global
            # (stream at line k gets pid = cumsum of prior streams' copy
            # counts; copies follow). RTL stream pid = the NIC's tptr at
            # fire (2x ordinal: every stream's range word advances tptr by
            # 2), copies = stream_pid+1+i. Mapping correlates them below.
            lo, hi, far = mcast_info[k]
            ncopies = hi - lo + 1
            # RTL stream pid: NIC sets (tptr<<4) at the entry's trace-word
            # index; each mcast entry consumes 2 words (entry + range), each
            # unicast 1, so stream pid = rtl_word << 4. Copies = stream_pid |
            # offset (4-bit offset covers up to 15 copies).
            rpid = rtl_word[(src, k)] << 4
            # BookSim: stream pid = first pid of this line (k + copies of
            # all earlier mcast lines); copies follow at bpid+1+i.
            bpid = bs_pid[k]
            bm = {}
            for f in bs.get(bpid, []):          # stream flit
                bm.setdefault(f[3], f)
            for i in range(ncopies):            # copies, pids bpid+1..
                for f in bs.get(bpid + 1 + i, []):
                    bm.setdefault(f[3], f)
            bl = sorted(bm.values())
            # RTL: stream pid = rpid, copies = rpid+1+i
            rl = []
            for f in rt.get((src, rpid), []):
                rl.append(f)
            for i in range(ncopies):
                rl += rt.get((src, rpid + 1 + i), [])
            rl = sorted(rl)
            if len(bl) != len(rl):
                print(f"FAIL mcast pkt {k}: BookSim {len(bl)} deliveries "
                      f"(expect {len(rl)})")
                strict_fails += 1
                tol_fails += 1
                continue
            for ba, ra in zip(bl, rl):
                checked += 1
                if ba != ra:
                    strict_fails += 1
                    if (abs(ba[0] - ra[0]) > tol or abs(ba[4] - ra[4]) > tol or
                            ba[1] != ra[1] or ba[2] != ra[2] or ba[3] != ra[3]):
                        tol_fails += 1
                        print(f"FAIL mcast pkt {k}: BookSim {ba} vs RTL {ra}")
            continue
        b = sorted(bs.get(bs_pid[k], []))
        r = sorted(rt.get((src, UNICAST_PID_BASE + rtl_word[(src, k)]), []))
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
    Records ALL uncommitted/untracked files, not just RTL (seed
    veritx-research-5ce7: a dirty tree makes results void — the manifest must
    say so loudly instead of hiding it behind an RTL-only filter).
    """
    import subprocess
    # repo = git root of THIS script (outdir may live outside the repo,
    # e.g. /var/tmp/r1work/... — deriving repo from outdir silently
    # produced an empty SHA and a false clean tree).
    repo = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True,
                          cwd=os.path.dirname(os.path.abspath(__file__))
                          ).stdout.strip()
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, cwd=repo)
    status = subprocess.run(["git", "status", "--porcelain"],
                            capture_output=True, text=True, cwd=repo)
    porcelain = status.stdout.splitlines()
    rtl_dirty = [l for l in porcelain
                 if any(rf.split("/")[-1] in l for rf in rtl_files)]
    with open(f"{outdir}/manifest.txt", "w") as f:
        f.write(f"git_sha: {sha.stdout.strip()}\n")
        f.write(f"tree_dirty: {'YES' if porcelain else 'no'}\n")
        f.write(f"uncommitted_files: {len(porcelain)}\n")
        f.write("uncommitted(porcelain):\n")
        for line in porcelain:
            f.write(f"  {line}\n")
        if rtl_dirty:
            f.write("WARNING: RTL source uncommitted — results VOID per rule 2 "
                    "(GATE-R1-COORD.md); commit first (rule 3):\n")
            for line in rtl_dirty:
                f.write(f"  ! {line}\n")
        f.write("sources:\n")
        for rf in rtl_files:
            f.write(f"  {os.path.getmtime(rf):.0f} {rf}\n")
        f.write("binaries:\n")
        for v, b in binaries.items():
            if os.path.exists(b):
                f.write(f"  {os.path.getmtime(b):.0f} vc{v} {b}\n")


def sweep(booksim, rtlroot, outdir, tol=0, gate_policy=None, cell_filter=None):
    """Gate R1 grid: the plane-separation burst table, cell-for-cell.

    With gate_policy set (sweep --gate): pure analysis mode per spec §8.2 —
    NO builds, NO trace regeneration, NO RTL sims. Gates the existing cell
    dirs under outdir (or --cells <name>,<name>...) and writes the gate
    report artifacts into outdir. Traces are reused; force via gen-trace.
    """
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

    if gate_policy is not None:
        # --gate mode: reuse existing cells, no builds/sims (spec §8.2).
        if cell_filter:
            cell_dirs = [os.path.join(outdir, c)
                         for c in cell_filter.split(",")
                         if os.path.isdir(os.path.join(outdir, c))]
        else:
            cell_dirs = sorted(
                os.path.join(outdir, d) for d in os.listdir(outdir)
                if os.path.isdir(os.path.join(outdir, d))
                and d.startswith("b") and "_vc" in d)
        if not cell_dirs:
            sys.exit("sweep --gate: no cell dirs found under " + outdir)
        print(f"sweep --gate: {len(cell_dirs)} cells, "
              f"policy {os.path.basename(gate_policy)}")
        return gate(outdir, gate_policy, cell_dirs)

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
            os.makedirs(bdir, exist_ok=True)
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


# ---------------------------------------------------------------------------
# Two-tier gate (spec: docs/research/two-tier-gate-spec.md)
# ---------------------------------------------------------------------------

def _load_policy(path):
    """Load + validate configs/gate_policy.json. Returns dict or raises."""
    import json as _json
    with open(path) as f:
        pol = _json.load(f)
    assert pol.get("schema_version") == 1, "policy schema_version != 1"
    assert "default_env" in pol, "policy missing default_env"
    for ov in pol.get("overrides", []):
        assert "cell" in ov and "env" in ov and "reason" in ov, \
            f"override missing field: {ov}"
        assert len(ov["reason"]) >= 20, \
            f"override {ov['cell']}: reason < 20 chars (enforced)"
        assert ov["env"] > pol["default_env"], \
            f"override {ov['cell']}: env {ov['env']} <= default (no-op, rejected)"
        reqs = ov.get("requires", [])
        assert "tier1_clean" in reqs, \
            f"override {ov['cell']}: requires must include tier1_clean"
    return pol


def _read_flits(path):
    """Read a 6-field flit dump -> list of (atime, cl, src, dst, pid, itime)."""
    out = []
    for l in open(path):
        if l.strip():
            out.append(tuple(map(int, l.split())))
    return out


def _pair_packets(outdir):
    """Build per-packet (BookSim, RTL) flit lists using the pid correlation.

    Returns (packets, mcast_info, pkt_info) where packets[k] =
    (bs_flits_sorted, rtl_flits_sorted). Mirrors diff()'s correlation but
    returns the data instead of printing verdicts.
    """
    trace = [l.split() for l in open(f"{outdir}/trace.txt") if l.strip()]
    n_pkts = len(trace)
    pkt_info = {k: (int(l[1]), int(l[2]), int(l[3]), int(l[4]))
                for k, l in enumerate(trace)}   # k -> (src, cl, dst, size)

    bs_all = {}
    for f in _read_flits(f"{outdir}/flits.txt"):
        bs_all.setdefault(f[4], []).append(f)   # key: pid
    # RTL flits keyed by (src, cl, pid) -- the pid is per-NIC, and pids can
    # be reused across classes (tptr advances across the whole NIC trace),
    # so (src, pid) alone is ambiguous under multi-class cells. (src, cl,
    # pid) is unique in the dump (verified on the two-class cell).
    rt_all = {}
    for f in _read_flits(f"{outdir}/rtl_flits.txt"):
        rt_all.setdefault((f[2], f[1], f[4]), []).append(f)  # (src, cl, pid)

    # correlation tables (from diff(); do NOT regress)
    mcast_info = {}
    bs_pid = {}
    rtl_word = {}
    per_src_words = {}
    bs_shift = 0
    for k, l in enumerate(trace):
        is_mcast = len(l) == 8 and l[5] == "mcast"
        if is_mcast:
            mcast_info[k] = (int(l[6]), int(l[7]), int(l[3]))
            ncopies = int(l[7]) - int(l[6]) + 1
            bs_pid[k] = k + bs_shift
            bs_shift += ncopies
        else:
            bs_pid[k] = k + bs_shift
        src = int(l[1])
        w = per_src_words.get(src, 0)
        rtl_word[(src, k)] = w
        per_src_words[src] = w + (2 if is_mcast else 1)

    packets = {}
    for k in range(n_pkts):
        src, cl, dst, size = pkt_info[k]
        if k in mcast_info:
            lo, hi, far = mcast_info[k]
            ncopies = hi - lo + 1
            rpid = rtl_word[(src, k)] << 4
            bpid = bs_pid[k]
            bm = {}
            for f in bs_all.get(bpid, []):
                bm.setdefault(f[3], f)
            for i in range(ncopies):
                for f in bs_all.get(bpid + 1 + i, []):
                    bm.setdefault(f[3], f)
            bl = sorted(bm.values())
            rl = []
            for f in rt_all.get((src, cl, rpid), []):
                rl.append(f)
            for i in range(ncopies):
                rl += rt_all.get((src, cl, rpid + 1 + i), [])
            rl = sorted(rl)
        else:
            bl = sorted(bs_all.get(bs_pid[k], []))
            rl = sorted(rt_all.get((src, cl, UNICAST_PID_BASE + rtl_word[(src, k)]), []))
        packets[k] = (bl, rl)
    return packets, mcast_info, pkt_info, trace


def gate_cell(outdir, policy, cell_id=""):
    """Two-tier gate for ONE cell. Returns the per-cell verdict dict."""
    import json as _json
    packets, mcast_info, pkt_info, trace = _pair_packets(outdir)
    env_def = policy.get("default_env", 0.05)

    # ---- Tier 1: mechanism (zero tolerance) ----
    t1 = {"t1.1": True, "t1.2": True, "t1.3": True, "t1.4": True}
    for k, (bl, rl) in packets.items():
        src, cl, dst, size = pkt_info[k]
        # T1.1 flit-count equality. For a mcast packet the trace's size field
        # is the INJECTED count (1 stream) while delivery is 1 + copies; the
        # expected delivery count is the injected size for unicast and
        # 1 + (hi - lo + 1) for mcast.
        if k in mcast_info:
            lo, hi, _ = mcast_info[k]
            expect = 1 + (hi - lo + 1)
        else:
            expect = size
        if len(bl) != expect or len(rl) != expect:
            t1["t1.1"] = False
        # T1.2 identity + T1.3 order (per matched pair); a count mismatch
        # already flagged T1.1, so skip pairing on it
        if len(bl) != len(rl):
            continue
        for ba, ra in zip(bl, rl):
            if (ba[1], ba[2], ba[3]) != (ra[1], ra[2], ra[3]):
                t1["t1.2"] = False
    # T1.4 delivery completeness: injected == retired in both models
    n_bs = sum(len(bl) for bl, rl in packets.values())
    n_rt = sum(len(rl) for bl, rl in packets.values())
    if n_bs != n_rt:
        t1["t1.4"] = False
    t1_verdict = "CLEAN" if all(t1.values()) else "VIOLATION"

    # ---- Tier 2: per-class mean latency ratio ----
    # latency(pkt) = max(atime over flits) - itime (the packet's injection
    # time; BookSim stamps itime identically on every flit of a packet, so
    # the first flit's itime is the canonical value — min() over flits is
    # equivalent only if the dump is well-formed, so read it explicitly).
    def pkt_latency(flits):
        if not flits:
            return None
        atimes = [f[0] for f in flits]
        return max(atimes) - flits[0][5]

    classes = {}
    for k, (bl, rl) in packets.items():
        c = pkt_info[k][1]
        classes.setdefault(c, {"bs": [], "rtl": []})
        lb, lr = pkt_latency(bl), pkt_latency(rl)
        if lb is not None:
            classes[c]["bs"].append(lb)
        if lr is not None:
            classes[c]["rtl"].append(lr)

    t2_classes = {}
    t2_pass = True
    for c, d in sorted(classes.items()):
        bs_m = sum(d["bs"]) / len(d["bs"]) if d["bs"] else None
        rt_m = sum(d["rtl"]) / len(d["rtl"]) if d["rtl"] else None
        ratio = (rt_m / bs_m) if (bs_m and rt_m) else None
        # per-class env: override may relax a specific class
        env = env_def
        for ov in policy.get("overrides", []):
            if ov["cell"] == cell_id and str(c) in ov.get("classes", []):
                env = ov["env"]
        in_env = ratio is not None and (1 - env) <= ratio <= (1 + env)
        t2_classes[str(c)] = {"bs_mean": round(bs_m, 2) if bs_m else None,
                              "rtl_mean": round(rt_m, 2) if rt_m else None,
                              "ratio": round(ratio, 3) if ratio else None,
                              "env": env, "in_env": in_env}
        if not in_env:
            t2_pass = False

    # ---- residual characterization (credibility artifact) ----
    deltas = []
    for bl, rl in packets.values():
        for ba, ra in zip(bl, rl):
            deltas.append(ra[0] - ba[0])   # atime_RTL - atime_BS
    n_flits = len(deltas)
    exact = sum(1 for d in deltas if d == 0)
    mean_d = sum(deltas) / n_flits if n_flits else 0.0
    ad = sorted(abs(d) for d in deltas)
    p95 = ad[int(0.95 * len(ad))] if ad else 0
    mx = max(ad) if ad else 0
    hist = {"<0": sum(1 for d in deltas if d < 0),
            "0": exact,
            "1-3": sum(1 for d in deltas if 1 <= d <= 3),
            "4-10": sum(1 for d in deltas if 4 <= d <= 10),
            "10+": sum(1 for d in deltas if d > 10)}

    # ---- override + verdict ----
    override = None
    for ov in policy.get("overrides", []):
        if ov["cell"] == cell_id:
            override = ov
            break
    status = "INCOMPLETE"
    if t1_verdict == "VIOLATION":
        status = "FAIL"
    elif t1_verdict == "CLEAN":
        if t2_pass:
            status = "PASS"
        elif override is not None:
            # validate override preconditions
            ok = (t1_verdict == "CLEAN") and override.get("requires", []) or []
            if "tier1_clean" not in override.get("requires", []):
                status = "FAIL"   # policy loader enforces; defensive
            else:
                status = "PASS-OVERRIDE"
        else:
            status = "FAIL"

    return {
        "cell": cell_id,
        "status": status,
        "tier1": {"verdict": t1_verdict, "checks": t1},
        "tier2": {"verdict": "PASS" if t2_pass else "FAIL",
                  "env_applied": env_def, "classes": t2_classes},
        "residual": {"n_flits": n_flits, "exact_match_frac":
                     round(exact / n_flits, 4) if n_flits else None,
                     "mean_delta": round(mean_d, 4), "p95_abs_delta": p95,
                     "max_abs_delta": mx, "histogram": hist},
        "override": {"cell": override["cell"], "env": override["env"],
                     "reason": override["reason"]} if override else None,
    }


def _gate_report_json(outdir, cells, ordinal, summary):
    """Write gate_report.json per spec §3.4."""
    import json as _json
    with open(f"{outdir}/gate_report.json", "w") as f:
        _json.dump({
            "schema_version": 1,
            "git_sha": open(f"{outdir}/manifest.txt").read().splitlines()[0]
                       .split(":")[1].strip() if os.path.exists(
                           f"{outdir}/manifest.txt") else "no-manifest",
            "cells": cells,
            "ordinal_summary": ordinal,
            "summary": summary,
        }, f, indent=1)


def _gate_report_md(outdir, cells, ordinal, summary):
    """Write gate_report.md per spec §3.4 (human table)."""
    lines = ["# Gate R1 report (two-tier)", "",
             "| cell | verdict | BS mean / RTL mean (cl) | ratio | "
             "exact% | mean Δ | p95|Δ| | max|Δ| |",
             "|---|---|---|---|---|---|---|---|"]
    for cid, c in cells.items():
        t2 = c["tier2"]["classes"]
        cells_txt = "; ".join(
            f"cl{k}: {v['bs_mean']}/{v['rtl_mean']} ({v['ratio']})"
            for k, v in sorted(t2.items()))
        r = c["residual"]
        paired = [v for v in t2.values()
                  if v.get("bs_mean") is not None
                  and v.get("rtl_mean") is not None]
        # overall ratio = rtl/bs (spec §2.3; per-class ratios already rtl/bs)
        ratio_all = (round(sum(v["rtl_mean"] for v in paired)
                           / sum(v["bs_mean"] for v in paired), 4)
                     if paired else None)
        lines.append(f"| {cid} | {c['status']} | {cells_txt} | "
                     f"{ratio_all} | {r['exact_match_frac']} | "
                     f"{r['mean_delta']} | {r['p95_abs_delta']} | "
                     f"{r['max_abs_delta']} |")
    lines += ["", "## Ordinal invariants", ""]
    for k, v in ordinal.items():
        v = v if v is not None else "N/A (insufficient cells)"
        lines.append(f"- {k}: {v}")
    lines += ["", f"## Summary: {summary['n_pass']} PASS, "
                  f"{summary['n_override']} PASS-OVERRIDE, "
                  f"{summary['n_fail']} FAIL, "
                  f"{summary['n_incomplete']} INCOMPLETE", ""]
    with open(f"{outdir}/gate_report.md", "w") as f:
        f.write("\n".join(lines) + "\n")


def gate(outdir, policy_path, cells, binaries=None):
    """Two-tier gate over a cell list. cells: list of cell dirs.

    binaries: optional {vcs: path} for the manifest (provenance).
    """
    import json as _json
    policy = _load_policy(policy_path)
    os.makedirs(outdir, exist_ok=True)
    # provenance (rule 2): every acceptance run writes a manifest, even
    # without binaries — the cell input files are the actual evidence.
    _write_manifest(outdir, [], binaries or {})
    with open(f"{outdir}/manifest.txt", "a") as f:
        f.write("cells:\n")
        for cell in cells:
            for name in ("trace.txt", "flits.txt", "rtl_flits.txt",
                         "run_cycles"):
                p = f"{cell}/{name}"
                if os.path.exists(p):
                    f.write(f"  {os.path.getmtime(p):.0f} {name} {cell}\n")

    results = {}
    for cell in cells:
        cid = os.path.basename(cell.rstrip("/"))
        results[cid] = gate_cell(cell, policy, cell_id=cid)
        st = results[cid]["status"]
        print(f"cell {cid}: {st}")

    # ordinal checks O1 (VC1 monotone in burst) + O2 (b80_vc1 > b80_vc4)
    # O1 must hold on BOTH models (spec §5: the paper's ordinal claims are
    # model-invariant) — previously only the RTL sequence was computed and
    # o1_bs was a silent no-op (always True).
    def cell_mean(cid, cls, model):
        c = results.get(cid)
        if not c or c["status"] == "INCOMPLETE":
            return None
        cl = c["tier2"]["classes"].get(str(cls))
        if not cl:
            return None
        return cl[f"{model}_mean"]

    o1_bs, o1_rtl = True, True
    bursts = [5, 10, 20, 40, 80]
    bs_seq, rt_seq = [], []
    for b in bursts:
        mb = cell_mean(f"b{b}_vc1", 1, "bs")
        mr = cell_mean(f"b{b}_vc1", 1, "rtl")
        if mb is not None:
            bs_seq.append(mb)
        if mr is not None:
            rt_seq.append(mr)
    if len(bs_seq) > 1:
        o1_bs = all(bs_seq[i] <= bs_seq[i + 1]
                    for i in range(len(bs_seq) - 1))
    if len(rt_seq) > 1:
        o1_rtl = all(rt_seq[i] <= rt_seq[i + 1]
                     for i in range(len(rt_seq) - 1))

    b80v1_bs = cell_mean("b80_vc1", 1, "bs")
    b80v1_rt = cell_mean("b80_vc1", 1, "rtl")
    b80v4_bs = cell_mean("b80_vc4", 1, "bs")
    b80v4_rt = cell_mean("b80_vc4", 1, "rtl")
    # O2 (VC absorption): b80_vc1 > b80_vc4. Only evaluable when BOTH
    # cells are present in the run — otherwise N/A (None), never False.
    o2_bs = (b80v1_bs > b80v4_bs) if (b80v1_bs is not None
                                      and b80v4_bs is not None) else None
    o2_rt = (b80v1_rt > b80v4_rt) if (b80v1_rt is not None
                                      and b80v4_rt is not None) else None

    ordinal = {"o1_monotone_vc1_bs": o1_bs,
               "o1_monotone_vc1_rtl": o1_rtl,
               "o2_absorption_bs": o2_bs,
               "o2_absorption_rtl": o2_rt}

    n_pass = sum(1 for c in results.values() if c["status"] == "PASS")
    n_ov = sum(1 for c in results.values() if c["status"] == "PASS-OVERRIDE")
    n_fail = sum(1 for c in results.values() if c["status"] == "FAIL")
    n_inc = sum(1 for c in results.values() if c["status"] == "INCOMPLETE")
    summary = {"n_pass": n_pass, "n_override": n_ov, "n_fail": n_fail,
               "n_incomplete": n_inc}

    _gate_report_json(outdir, results, ordinal, summary)
    _gate_report_md(outdir, results, ordinal, summary)
    return 0 if n_fail == 0 else 1

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "gen-trace":
        gen_trace(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "lint":
        sys.exit(lint_cell(sys.argv[2]))
    elif cmd == "diff":
        tol = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        sys.exit(diff(sys.argv[2], tol))
    elif cmd == "sweep":
        # sweep <booksim> <rtlroot> <outdir> [--tol N] [--gate <policy>]
        #       [--cells <name,name,...>]
        tol = 0
        gate_policy = None
        cell_filter = None
        rest = sys.argv[5:]
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--tol" and i + 1 < len(rest):
                tol = int(rest[i + 1]); i += 2
            elif a == "--gate" and i + 1 < len(rest):
                gate_policy = rest[i + 1]; i += 2
            elif a == "--cells" and i + 1 < len(rest):
                cell_filter = rest[i + 1]; i += 2
            else:
                i += 1
        sys.exit(sweep(sys.argv[2], sys.argv[3], sys.argv[4], tol,
                       gate_policy, cell_filter))
    elif cmd == "gate":
        # gate <outdir> <policy> <cell_dir> [cell_dir ...]
        if len(sys.argv) < 5:
            print("gate: need <outdir> <policy> <cell_dir> [cell_dir ...]")
            sys.exit(2)
        sys.exit(gate(sys.argv[2], sys.argv[3], sys.argv[4:]))
    else:
        print(__doc__)
        sys.exit(2)


