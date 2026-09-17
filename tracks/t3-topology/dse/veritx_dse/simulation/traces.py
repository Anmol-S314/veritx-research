"""veritx_dse.traces — Trace validation, analysis, extraction, and conversion.

All functions are pure (no side effects beyond file I/O).
Every function receives Ctx for logging and returns structured results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import TraceError


# ── Validation ──────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Result of trace validation."""
    valid: bool
    file: str
    packets: int = 0
    sources: int = 0
    dests: int = 0
    classes: int = 0
    sizes: list[int] = field(default_factory=list)
    time_range: list[int] = field(default_factory=lambda: [0, 0])
    span: int = 0
    injection_rate: float = 0.0
    self_loops: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "file": self.file,
            "packets": self.packets,
            "sources": self.sources,
            "dests": self.dests,
            "classes": self.classes,
            "sizes": self.sizes,
            "time_range": self.time_range,
            "span": self.span,
            "injection_rate": self.injection_rate,
            "self_loops": self.self_loops,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_trace(trace_path: str) -> ValidationResult:
    """Validate trace format and sanity-check before expensive BookSim runs.

    Returns ValidationResult with errors/warnings lists.
    Does NOT call sys.exit — caller decides what to do with failures.
    """
    path = Path(trace_path)
    if not path.exists():
        return ValidationResult(valid=False, file=str(path), errors=[f"Not found: {path}"])

    errors: list[str] = []
    warnings: list[str] = []
    pkts = 0
    srcs: set[int] = set()
    dsts: set[int] = set()
    classes: set[int] = set()
    sizes: set[int] = set()
    min_t = 999999999
    max_t = 0
    max_src = 0
    max_dst = 0
    self_loops = 0
    negative_times = 0
    short_lines = 0
    comment_lines = 0
    empty_lines = 0
    prev_t = None
    non_monotonic = 0

    with open(path) as f:
        for line_no, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                empty_lines += 1
                continue
            if stripped.startswith("#"):
                comment_lines += 1
                continue
            parts = stripped.split()
            if len(parts) < 5:
                short_lines += 1
                errors.append(f"Line {line_no}: expected >=5 fields, got {len(parts)}: {stripped[:60]}")
                if len(errors) > 20:
                    errors.append("... (stopping after 20 errors)")
                    break
                continue
            try:
                t, src, cl, dst, sz = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
            except ValueError as e:
                errors.append(f"Line {line_no}: non-integer field: {e}")
                if len(errors) > 20:
                    break
                continue

            pkts += 1
            if src < 0 or dst < 0:
                errors.append(f"Line {line_no}: negative node ID (src={src}, dst={dst})")
            if sz <= 0:
                errors.append(f"Line {line_no}: packet size must be > 0, got {sz}")
            if cl < 0:
                errors.append(f"Line {line_no}: class must be >= 0, got {cl}")
            srcs.add(src)
            dsts.add(dst)
            classes.add(cl)
            sizes.add(sz)
            if t < min_t:
                min_t = t
            if t > max_t:
                max_t = t
            if src > max_src:
                max_src = src
            if dst > max_dst:
                max_dst = dst
            if t < 0:
                negative_times += 1
            if src == dst:
                self_loops += 1
            if prev_t is not None and t < prev_t:
                non_monotonic += 1
            prev_t = t

    # Sanity checks
    if pkts == 0:
        errors.append("No packets found in trace")
    if negative_times > 0:
        errors.append(f"{negative_times} packets have negative timestamps")
    if max_src >= pkts and pkts > 100:
        warnings.append(f"Max source ID ({max_src}) >= packet count ({pkts}) — sparse node usage?")
    if max_dst >= pkts and pkts > 100:
        warnings.append(f"Max dest ID ({max_dst}) >= packet count ({pkts}) — sparse node usage?")
    if len(sizes) == 1:
        warnings.append(f"All packets have same size ({sizes}) — unusual for real traffic")
    if self_loops > pkts * 0.1 and pkts > 10:
        warnings.append(f"{self_loops} self-loops ({self_loops/pkts*100:.1f}%) — check trace source")
    if short_lines > 0:
        warnings.append(f"{short_lines} malformed lines skipped")

    span = max_t - min_t + 1 if pkts > 0 else 0
    ir = pkts / max(span, 1)

    return ValidationResult(
        valid=len(errors) == 0,
        file=str(path),
        packets=pkts,
        sources=len(srcs),
        dests=len(dsts),
        classes=len(classes),
        sizes=sorted(sizes),
        time_range=[min_t, max_t],
        span=span,
        injection_rate=ir,
        self_loops=self_loops,
        errors=errors,
        warnings=warnings,
    )


# ── Info / Analysis ─────────────────────────────────────────────────────────

@dataclass
class TraceInfo:
    """Detailed trace analysis: burst structure, IR, sources, profile."""
    file: str
    file_size: int
    packets: int
    sources: int
    classes: int
    max_cycle: int
    span: int
    ir: float
    bursts: list[dict]  # [{start, end, count}]
    avg_burst_size: float
    max_burst_size: int
    avg_gap: float
    top_srcs: list[tuple[int, int]]
    top_dsts: list[tuple[int, int]]
    profile: str
    burst_ir: float
    burst_mode: str

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "file_size": self.file_size,
            "packets": self.packets,
            "sources": self.sources,
            "classes": self.classes,
            "max_cycle": self.max_cycle,
            "span": self.span,
            "ir": self.ir,
            "bursts": self.bursts,
            "avg_burst_size": self.avg_burst_size,
            "max_burst_size": self.max_burst_size,
            "avg_gap": self.avg_gap,
            "top_srcs": self.top_srcs,
            "top_dsts": self.top_dsts,
            "profile": self.profile,
            "burst_ir": self.burst_ir,
            "burst_mode": self.burst_mode,
        }


def analyze_trace(trace_path: str) -> TraceInfo:
    """Analyze trace characteristics: burst structure, IR, sources, profile.

    Malformed lines are NOT silently skipped: any parse failure aborts the
    analysis — a profile computed from partial data is a lie, not an estimate.
    """
    path = Path(trace_path)
    file_size = path.stat().st_size

    ts: list[int] = []
    src_pkts: dict[int, int] = {}
    dst_pkts: dict[int, int] = {}
    max_cycle = 0
    num_classes = 1
    num_packets = 0
    srcs: set[int] = set()
    bad_lines: list[str] = []

    with open(path) as f:
        for line_no, line in enumerate(f, 1):
            if line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 5:
                bad_lines.append(f"line {line_no}: expected >=5 fields, got {len(parts)}")
                continue
            try:
                t, src, cl, dst = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            except ValueError:
                bad_lines.append(f"line {line_no}: non-integer field: {line.strip()[:60]}")
                continue
            ts.append(t)
            src_pkts[src] = src_pkts.get(src, 0) + 1
            dst_pkts[dst] = dst_pkts.get(dst, 0) + 1
            num_packets += 1
            srcs.add(src)
            if t > max_cycle:
                max_cycle = t
            if cl > 0 and num_classes <= cl:
                num_classes = cl + 1

    if bad_lines:
        preview = "; ".join(bad_lines[:5])
        raise TraceError(
            f"{trace_path}: {len(bad_lines)} malformed line(s) — "
            f"refusing to analyze a corrupt trace ({preview})")
    if num_packets == 0:
        raise TraceError(f"{trace_path}: no packets found (empty or comments only)")

    span = max_cycle + 1
    ir = num_packets / max(span, 1)

    # Burst analysis (gap > 100 cycles = new burst)
    ts_sorted = sorted(ts)
    bursts = []
    burst_start = 0
    for i in range(1, len(ts_sorted)):
        if ts_sorted[i] - ts_sorted[i - 1] > 100:
            bursts.append({
                "start": ts_sorted[burst_start],
                "end": ts_sorted[i - 1],
                "count": i - burst_start,
            })
            burst_start = i
    bursts.append({
        "start": ts_sorted[burst_start] if ts_sorted else 0,
        "end": ts_sorted[-1] if ts_sorted else 0,
        "count": len(ts_sorted) - burst_start,
    })

    avg_burst = sum(b["count"] for b in bursts) / len(bursts) if bursts else 0
    max_burst = max((b["count"] for b in bursts), default=0)
    avg_gap = 0.0
    if len(bursts) > 1:
        gaps = [bursts[i + 1]["start"] - bursts[i]["end"] for i in range(len(bursts) - 1)]
        avg_gap = sum(gaps) / len(gaps)

    # Profile classification
    if ir > 1.0:
        profile = "SATURATED (IR>1.0) — topology likely irrelevant"
    elif ir > 0.1:
        profile = "MODERATE (0.1<IR<1.0) — topology may matter"
    elif ir > 0.01:
        profile = "SPARSE (0.01<IR<0.1) — topology matters if bursty"
    else:
        profile = "VERY SPARSE (IR<0.01) — network mostly idle"

    # Burst IR during max burst
    burst_ir = ir * 10  # fallback
    burst_mode = "UNKNOWN"
    if max_burst > 0 and len(ts_sorted) > 1:
        # Find the max burst's time span
        for b in bursts:
            if b["count"] == max_burst:
                bspan = b["end"] - b["start"] + 1
                burst_ir = b["count"] / max(bspan, 1)
                break
        if burst_ir > 1.0:
            burst_mode = "INJECTION-LIMITED — NIC injection is bottleneck"
        elif burst_ir > 0.3:
            burst_mode = "CONTENTION-LIMITED — topology matters"
        else:
            burst_mode = "LATENCY-LIMITED — hop count dominates"

    top_src = sorted(src_pkts.items(), key=lambda x: -x[1])[:5]
    top_dst = sorted(dst_pkts.items(), key=lambda x: -x[1])[:5]

    return TraceInfo(
        file=str(path),
        file_size=file_size,
        packets=num_packets,
        sources=len(srcs),
        classes=num_classes,
        max_cycle=max_cycle,
        span=span,
        ir=ir,
        bursts=bursts,
        avg_burst_size=avg_burst,
        max_burst_size=max_burst,
        avg_gap=avg_gap,
        top_srcs=top_src,
        top_dsts=top_dst,
        profile=profile,
        burst_ir=burst_ir,
        burst_mode=burst_mode,
    )


# ── Extraction ──────────────────────────────────────────────────────────────

@dataclass
class ExtractResult:
    """Result of trace extraction."""
    output_file: str
    packets: int
    mode: str  # "burst" or "uniform"
    spacing: int | None = None  # for uniform mode

    def to_dict(self) -> dict:
        d = {"output_file": self.output_file, "packets": self.packets, "mode": self.mode}
        if self.spacing is not None:
            d["spacing"] = self.spacing
        return d


def extract_burst(trace_path: str, count: int, output_path: str) -> ExtractResult:
    """Extract first N packets (single burst) from a trace.

    Times are shifted to start at t=0.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with open(trace_path) as fin, open(out, "w") as fout:
        for line in fin:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 5:
                fout.write(line)
                written += 1
                if written >= count:
                    break

    # Shift times to t=0
    _shift_times_to_zero(out)

    return ExtractResult(output_file=str(out), packets=written, mode="burst")


def extract_uniform(trace_path: str, output_path: str) -> ExtractResult:
    """Redistribute packets uniformly across the time range."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    packets = []
    with open(trace_path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 5:
                packets.append(parts)

    if not packets:
        return ExtractResult(output_file=str(out), packets=0, mode="uniform")

    max_t = max(int(p[0]) for p in packets)
    spacing = max(1, max_t // len(packets))

    with open(out, "w") as fo:
        for i, parts in enumerate(packets):
            parts[0] = str(i * spacing)
            fo.write(" ".join(parts) + "\n")

    return ExtractResult(output_file=str(out), packets=len(packets), mode="uniform", spacing=spacing)


def _shift_times_to_zero(path: Path):
    """Shift all timestamps in a trace file so the minimum is 0."""
    mint = 999999999
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 5:
                t = int(parts[0])
                if t < mint:
                    mint = t

    if mint > 0:
        lines = []
        with open(path) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 5:
                    parts[0] = str(int(parts[0]) - mint)
                    lines.append(" ".join(parts))
        with open(path, "w") as fo:
            fo.write("\n".join(lines) + "\n")


# ── Slicing ─────────────────────────────────────────────────────────────────

@dataclass
class SliceResult:
    """Result of trace slicing."""
    output_file: str
    kept: int
    dropped: int

    def to_dict(self) -> dict:
        return {"output_file": self.output_file, "kept": self.kept, "dropped": self.dropped}


def slice_trace(trace_path: str, classes: set[int], output_path: str,
                renumber: bool = False) -> SliceResult:
    """Slice an existing trace by traffic class (per-phase analysis)."""
    src = Path(trace_path)
    if not src.exists():
        raise FileNotFoundError(f"Trace not found: {src}")

    kept = 0
    dropped = 0
    with open(src) as fin, open(output_path, "w") as fout:
        fout.write(f"# Sliced from {src.name}: classes {sorted(classes)}\n")
        for line in fin:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            if len(p) < 5:
                continue
            if int(p[2]) in classes:
                if renumber:
                    p[2] = "0"
                fout.write(" ".join(p) + "\n")
                kept += 1
            else:
                dropped += 1

    return SliceResult(output_file=output_path, kept=kept, dropped=dropped)


# ── Traffic-matrix aggregation ──────────────────────────────────────────────
#
# The N×N bytes-per-pair matrix is the shared currency of the pipeline: MILP
# synthesis, the deadlock CDG certificate, and spec_translate all consume the
# same shape. These helpers let `veritx run` derive it from any ingested
# trace, so every source funnels into one representation.

def trace_num_nodes(trace_path: str) -> int:
    """Highest node id appearing in the trace, + 1 (the implied matrix dim).

    Tolerates malformed lines here (aggregate_matrix reports them precisely);
    this scan only needs the endpoint range.
    """
    mx = -1
    with open(trace_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split()
            if len(p) < 5:
                continue
            try:
                s, d = int(p[1]), int(p[3])
            except ValueError:
                continue
            mx = max(mx, s, d)
    return mx + 1 if mx >= 0 else 0


def aggregate_matrix(trace_path: str, num_nodes: int) -> Any:
    """Aggregate a DSE .trace into an N×N bytes-per-pair matrix (row=src).

    Raises TraceError on malformed lines — same contract as analyze_trace:
    never silently drop traffic, because a hole in the matrix would
    synthesize a topology calibrated to missing data.
    """
    import numpy as np
    T = np.zeros((num_nodes, num_nodes), dtype=np.float64)
    with open(trace_path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split()
            if len(p) < 5:
                raise TraceError(
                    f"{trace_path}: line {lineno}: expected >=5 fields "
                    f"(cyc src cl dst sz), got {len(p)}")
            try:
                src, dst, sz = int(p[1]), int(p[3]), int(p[4])
            except ValueError as e:
                raise TraceError(f"{trace_path}: line {lineno}: {e}") from e
            if not (0 <= src < num_nodes) or not (0 <= dst < num_nodes):
                raise TraceError(
                    f"{trace_path}: line {lineno}: endpoint out of range "
                    f"[0,{num_nodes}) — src={src} dst={dst}")
            T[src][dst] += sz
    return T


def save_matrix(T: Any, mat_path: Path) -> None:
    """Write the .mat format milp_topology_v2.load_matrix reads: N rows of N
    whitespace-separated numbers (comment lines allowed, we write none)."""
    import numpy as np
    np.savetxt(str(mat_path), np.asarray(T, dtype=np.float64), fmt="%.6f")


def matrix_to_trace(T: Any, trace_path: Path, flit_bytes: int = 64,
                    cap_per_pair: int = 1024) -> dict:
    """Traffic matrix → DSE .trace (BookSim input): one 64B packet per flit.

    Per-pair packet counts are capped to keep BookSim replay tractable for
    very large matrices; when the cap binds, packet counts no longer encode
    absolute bytes — the caller records `scaled` so downstream numbers are
    read as relative, not absolute. Cycles are serialized (1 packet/cycle)
    to keep injection far below saturation for any topology.
    """
    import math
    n = len(T)
    cyc = 0
    total = 0
    pairs = 0
    capped = False
    with open(trace_path, "w") as f:
        for s in range(n):
            for d in range(n):
                if s == d:
                    continue
                b = float(T[s][d])
                if b <= 0:
                    continue
                k = math.ceil(b / flit_bytes)
                if k > cap_per_pair:
                    k = cap_per_pair
                    capped = True
                for _ in range(k):
                    f.write(f"{cyc} {s} 0 {d} {flit_bytes}\n")
                    cyc += 1
                total += k
                pairs += 1
    return {"packets": total, "pairs": pairs, "cycles": cyc, "scaled": capped}
