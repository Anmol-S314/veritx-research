"""veritx_dse.waved.backend — backend projection (D5, §46–§50).

Wave D contributes TRAFFIC semantics; Wave B/C remain the execution and
evidence authorities. This module renders the canonical Wave-D physical
traffic into the qualified standalone-BookSim workload input and hands
it to the sealed Wave-B chain:

    render_waved_trace(pt)  → trace bytes (lossless, see below)
    prepare_waved_booksim(pt) → PreparedBackend (Wave-B prepare path)
    run_waved_booksim(...)    → evidence + Wave-D conservation summary

The rendered trace is a DERIVED, lossy-for-provenance backend input: the
5-column BookSim trace grammar (timestamp, src, dst, type,
packet_size_flits) cannot carry operation ids or phase. Losslessness is
therefore claimed ONLY for the fields the grammar can carry — source
endpoint, destination endpoint, packet/flit counts, packet ordering —
and is proven mechanically by ``verify_trace_projection``. The persisted
higher-level artifact (``PhysicalTrafficArtifact``) retains full
provenance; the trace is never promoted to semantic authority (§48).

Injection order: packets are emitted in (message seq, packet index)
order — deterministic from the artifact, no wall-clock input.

Quiescence counters (§49): the qualified fork exposes ``delivered``
packets and ``flits_injected``/``flits_accepted`` flit totals at trace
drain. Counters the backend does not print are recorded as ``None``,
never fabricated as zero.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from veritx_dse.backend.booksim import (
    PreparedBackend, prepare_booksim_standalone, run_qualified_booksim,
)

from .errors import BackendFailure, EvidenceInvalid
from .traffic import PhysicalTrafficArtifact

WAVED_TRACE_DIALECT = "waved-derived-whitespace-v1"


def render_waved_trace(pt: PhysicalTrafficArtifact) -> bytes:
    """Render the canonical Wave-D traffic as a BookSim trace.

    The fork's cycle-accurate injection path (veritx_ext.cpp
    TraceTrafficPattern) parses the WHITESPACE dialect
    ``cyc src cl dst sz`` — one line per physical packet, packet size in
    FLITS (trafficmanager.cpp: "trace size is in flits"). The class
    column is 0: single-class certified runs (§46). Deterministic
    timestamps in emission order keep packet ordering semantic.
    """
    lines: list[str] = []
    ts = 0
    for t in pt.traffic:            # deterministic: message seq order
        for p in t.packets:         # deterministic: packet index order
            lines.append(f"{ts} {p.src_endpoint} 0 {p.dst_endpoint} "
                         f"{p.flit_count}")
            ts += 1
    return ("\n".join(lines) + "\n").encode()


def verify_trace_projection(pt: PhysicalTrafficArtifact) -> dict[str, Any]:
    """Mechanical losslessness proof for the representable fields (§48).

    Parses back the rendered trace and compares it against the artifact:
    line count, endpoint pairs, per-line flit counts, and ordering.
    """
    from veritx_dse.backend.booksim import _scan_trace
    trace = render_waved_trace(pt)
    summary = _scan_trace(
        trace, endpoint_count=pt.bundle.attachment.endpoint_count,
        max_packet_flits=pt.bundle.packet_format.max_packet_flits)
    expected_lines = sum(len(t.packets) for t in pt.traffic)
    if summary.num_packets != expected_lines:
        raise EvidenceInvalid(
            f"trace projection lost packets: {summary.num_packets} != "
            f"{expected_lines}")
    rendered = [line.split() for line in trace.decode().splitlines()]
    flat = [(t.message_id, p.packet_index, p.src_endpoint, p.dst_endpoint,
             p.flit_count)
            for t in pt.traffic for p in t.packets]
    if len(rendered) != len(flat):
        raise EvidenceInvalid("trace projection line count mismatch")
    for i, (line, (mid, pidx, se, de, flits)) in enumerate(zip(rendered,
                                                               flat)):
        if len(line) != 5:
            raise EvidenceInvalid(
                f"trace projection line {i} is not 5-column")
        if int(line[0]) != i:
            raise EvidenceInvalid(
                f"trace timestamp not deterministic at line {i}")
        if int(line[1]) != se or int(line[3]) != de:
            raise EvidenceInvalid(
                f"trace projection endpoint mismatch at message {mid} "
                f"packet {pidx}")
        if int(line[4]) != flits:
            raise EvidenceInvalid(
                f"trace projection flit count mismatch at message {mid} "
                f"packet {pidx}")
    return {
        "dialect": WAVED_TRACE_DIALECT,
        "num_packets": summary.num_packets,
        "flits_total": sum(p.flit_count for t in pt.traffic
                           for p in t.packets),
        "endpoint_count": summary.endpoint_count,
    }


def prepare_waved_booksim(pt: PhysicalTrafficArtifact,
                          *, seed: int | None = None
                          ) -> tuple[PreparedBackend, dict[str, Any]]:
    """Sealed Wave-B preparation of the Wave-D canonical traffic."""
    summary = verify_trace_projection(pt)
    trace = render_waved_trace(pt)
    prepared = prepare_booksim_standalone(pt.bundle, workload_trace=trace,
                                          seed=seed)
    return prepared, summary


def run_waved_booksim(prepared: PreparedBackend, *, run_dir: Path,
                      repo_root: Path, timeout: int, binary: Path
                      ) -> dict[str, Any]:
    """Sealed execution + Wave-D conservation summary (§49)."""
    evidence = run_qualified_booksim(
        prepared, run_dir=run_dir, repo_root=repo_root, timeout=timeout,
        binary=binary)
    if evidence.exit_status != 0:
        raise BackendFailure(
            f"qualified BookSim execution failed with exit status "
            f"{evidence.exit_status}")
    stats = evidence.stats or {}
    return {
        "evidence": evidence,
        "backend_counters": {
            # Counters the qualified fork actually prints; absent
            # counters stay None — never fabricated (§49).
            "injected_packets": evidence.injected_packets,
            "delivered_packets": stats.get("delivered"),
            "flits_injected": stats.get("flits_injected"),
            "flits_accepted": stats.get("flits_accepted"),
            "drain_verdict": stats.get("drain_verdict"),
        },
    }


__all__ = [
    "prepare_waved_booksim", "render_waved_trace", "run_waved_booksim",
    "verify_trace_projection", "WAVED_TRACE_DIALECT",
]
