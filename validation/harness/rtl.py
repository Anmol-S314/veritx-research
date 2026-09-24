"""Layer 3 authority: the T3 2D mesh RTL (Verilator trace replay).

This is the first authority that uses a DIFFERENT engine from BookSim.
It drives `tb/noc_tb.sv` in its R1_MODE trace-replay path: per-NIC
`trace_n<N>.hex` stimuli, an eject-stream dump (`rtl_flits.txt`), and a
drain invariant (`ejected == injected`). Its cycle law is
``latency(d) = 7 + 5*d`` where ``d`` is the router-to-router hop count
(tb S2/S3 calibration).

Independence is recorded honestly:

  * route/hop parity and conservation are INDEPENDENT — the RTL routes a
    different implementation.
  * absolute latency parity is SEMI_INDEPENDENT: the tb's calibration
    comment states it was calibrated against the BookSim cycle model, so
    matching latency checks the calibration, not an independent clock.

Domain: 2D unicast mesh only. The audit marks multicast broken (F1-F3)
and 3D/4D unqualified; the corpus refuses those here.

Like `authority.py`, this module imports nothing from the product's
projection/parser; the trace conversion is its own.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

RTL_DIR = "tracks/t3-topology/rtl/t3"
TB_FILE = "tracks/t3-topology/tb/noc_tb.sv"
#: RTL module sources needed for the 2D mesh (unicast)
SOURCES = ("noc_pkg.sv", "mesh.sv", "router.sv", "nic.sv", "islip.sv")

#: calibration law from the testbench (latency = BASE + PER_HOP * d)
LATENCY_BASE = 7
LATENCY_PER_HOP = 5

_TOTALS = re.compile(r"R1 totals: injected=(\d+) ejected=(\d+)")


class RtlError(RuntimeError):
    """The RTL authority could not produce a measurement — fail closed."""


@dataclass(frozen=True)
class RtlPacket:
    atime: int
    cl: int
    src: int
    dst: int
    pid: int
    itime: int

    @property
    def latency(self) -> int:
        return self.atime - self.itime

    @property
    def hops(self) -> int | None:
        delta = self.latency - LATENCY_BASE
        if delta < 0 or delta % LATENCY_PER_HOP != 0:
            return None
        return delta // LATENCY_PER_HOP


@dataclass(frozen=True)
class RtlResult:
    injected_packets: int
    ejected_packets: int
    packets: tuple[RtlPacket, ...]
    run_cycles: int

    @property
    def ejected_flits(self) -> int:
        # the dump carries one line per ejected flit
        return len(self.packets)

    @property
    def max_atime(self) -> int:
        return max((p.atime for p in self.packets), default=0)


def mesh_radix(spec) -> tuple[int, int]:
    tiles = spec.fabric.compute_tiles
    k = int(round(tiles ** 0.5))
    if k * k != tiles:
        raise RtlError(f"mesh tiles must be square, got {tiles}")
    return k, k


def write_traces(trace_text: str, out_dir: Path, *, cycle_offset: int = 1
                 ) -> dict[int, int]:
    """Convert the canonical `cyc src cl dst sz` trace to per-NIC hex.

    The R1 loader treats a cycle field of 0 as a multicast range word, so
    every injection cycle is shifted by ``cycle_offset`` (>= 1). Latency
    (atime - itime) is unaffected by the shift.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    per_nic: dict[int, list[str]] = {}
    for line in trace_text.splitlines():
        if not line.strip():
            continue
        cyc, src, cl, dst, sz = (int(x) for x in line.split())
        entry = ((cyc + cycle_offset) << 32) | (cl << 24) \
            | (dst << 16) | sz
        per_nic.setdefault(src, []).append(f"{entry:016x}")
    max_nic = max(per_nic, default=-1)
    counts: dict[int, int] = {}
    for nic in range(max_nic + 1):
        entries = per_nic.get(nic, [])
        counts[nic] = len(entries)
        body = "\n".join(entries + ["ffffffffffffffff"])
        (out_dir / f"trace_n{nic}.hex").write_text(body + "\n")
    return counts


def build(*, repo_root: Path, build_dir: Path, x_dim: int, y_dim: int,
          vcs: int, t_depth: int) -> Path:
    """Build the RTL testbench in R1_MODE with Verilator (cached by dir)."""
    binary = Path(build_dir) / "noc_tb"
    if binary.is_file():
        return binary
    sources = [str(Path(repo_root) / RTL_DIR / s) for s in SOURCES]
    command = [
        "verilator", "--binary", "-j", "4", "--timing", "-Wno-fatal",
        "-DR1_MODE", f"-I{Path(repo_root) / RTL_DIR}",
        *sources, str(Path(repo_root) / TB_FILE),
        "--top-module", "noc_tb",
        f"-GX_DIM={x_dim}", f"-GY_DIM={y_dim}", f"-GVCS={vcs}",
        f"-GT_DEPTH={t_depth}",
        "--Mdir", str(build_dir), "-o", "noc_tb",
    ]
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0 or not binary.is_file():
        raise RtlError(
            f"verilator build failed ({proc.returncode}); "
            f"{(proc.stderr or '')[-500:]}")
    return binary


def run(*, binary: Path, run_dir: Path, run_cycles: int) -> RtlResult:
    target = Path(run_dir)
    target.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(binary), f"+run_cycles={run_cycles}"], cwd=str(target),
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=600)
    dump = target / "rtl_flits.txt"
    if proc.returncode != 0 or not dump.is_file():
        raise RtlError(
            f"RTL run failed ({proc.returncode}); "
            f"{(proc.stdout or '')[-300:]}{(proc.stderr or '')[-200:]}")
    totals = _TOTALS.search(proc.stdout or "")
    if totals is None:
        raise RtlError("RTL run did not report inject/eject totals")
    packets = []
    for line in dump.read_text().splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 6:
            raise RtlError(f"malformed rtl_flits line: {line!r}")
        atime, cl, src, dst, pid, itime = (int(x) for x in fields)
        packets.append(RtlPacket(atime=atime, cl=cl, src=src, dst=dst,
                                 pid=pid, itime=itime))
    return RtlResult(injected_packets=int(totals.group(1)),
                     ejected_packets=int(totals.group(2)),
                     packets=tuple(packets), run_cycles=run_cycles)


def run_authority(*, spec, built, repo_root: Path, work_root: Path
                  ) -> RtlResult:
    """Full authority run for one experiment (2D unicast mesh only)."""
    x_dim, y_dim = mesh_radix(spec)
    if spec.fabric.num_vcs != 1:
        raise RtlError("the RTL authority currently covers num_vcs == 1 only")
    trace = built.prepared.trace_text
    lines = [ln for ln in trace.splitlines() if ln.strip()]
    max_ts = max(int(ln.split()[0]) for ln in lines)
    run_cycles = max_ts + 1 + 200
    per_nic = len({int(ln.split()[1]) for ln in lines})
    t_depth = max(16, 1 << (per_nic.bit_length()))
    build_dir = Path(work_root) / f"rtlbuild-{x_dim}x{y_dim}-vcs{spec.fabric.num_vcs}-t{t_depth}"
    binary = build(repo_root=repo_root, build_dir=build_dir, x_dim=x_dim,
                   y_dim=y_dim, vcs=spec.fabric.num_vcs, t_depth=t_depth)
    run_dir = Path(work_root) / f"rtlrun-{spec.id}"
    write_traces(trace, run_dir)
    # pad missing NIC trace files so the loader finds every expected file
    for nic in range(x_dim * y_dim):
        path = run_dir / f"trace_n{nic}.hex"
        if not path.exists():
            path.write_text("ffffffffffffffff\n")
    return run(binary=binary, run_dir=run_dir, run_cycles=run_cycles)