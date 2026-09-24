"""veritx_dse.backend.projection — derived-traffic backend input.

(Formerly veritx_dse.waved.backend; slice 2b moved it here by ownership.)

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
provenance; the trace is never promoted to semantic authority (§21).

Injection order: packets are emitted in (message seq, packet index)
order — deterministic from the artifact, no wall-clock input.

Quiescence counters (§21): the qualified fork exposes ``delivered``
packets and ``flits_injected``/``flits_accepted`` flit totals at trace
drain — all sealed Wave-B evidence fields. Wave D therefore proves
``delivered_packets == expected_packets`` and
``flits_injected == flits_accepted == expected_flits`` and never needs a
backend-injected packet counter (the sealed Wave-B evidence schema is
not modified by Wave D). Counters the backend does not print are
recorded as ``None``, never fabricated as zero.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from veritx_dse.backend.booksim import (
    PreparedBackend, prepare_booksim_standalone, run_qualified_booksim,
)
from veritx_dse.core.errors import BackendFailure, EvidenceInvalid
from veritx_dse.verification.gates import (
    assert_workload_ready, verify_backend_quiescence,
)
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2

# Canonical adapter (veritx-integrate §4/§7): the RT candidate bound this
# seam to the v1 PhysicalTrafficArtifact; the v1 authority was deleted
# and the canonical PhysicalTrafficArtifactV2 carries the same
# traffic/bundle surface the renderer consumes, so the seam binds V2.
PhysicalTrafficArtifact = PhysicalTrafficArtifactV2



WAVED_TRACE_DIALECT = "waved-derived-whitespace-v1"


def render_waved_trace(pt: PhysicalTrafficArtifact) -> bytes:
    """Render the canonical Wave-D traffic as a BookSim trace.

    The fork's cycle-accurate injection path (veritx_ext.cpp
    TraceTrafficPattern) parses the WHITESPACE dialect
    ``cyc src cl dst sz`` — one line per physical packet, packet size in
    FLITS (trafficmanager.cpp: "trace size is in flits"). The class
    column is 0: single-class certified runs (§21). Deterministic
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


def prepare_waved_booksim(pt: PhysicalTrafficArtifact,
                          *, seed: int | None = None
                          ) -> tuple[PreparedBackend, dict[str, Any]]:
    """Sealed Wave-B preparation of the Wave-D canonical traffic."""
    summary = assert_projection_ready(pt)
    trace = render_waved_trace(pt)
    prepared = prepare_booksim_standalone(pt.bundle, workload_trace=trace,
                                          seed=seed)
    return prepared, summary


def run_waved_booksim(prepared: PreparedBackend, *, run_dir: Path,
                      repo_root: Path, timeout: int, binary: Path,
                      summary: dict[str, Any] | None = None
                      ) -> dict[str, Any]:
    """Sealed execution + Wave-D conservation summary (§21)."""
    evidence = run_qualified_booksim(
        prepared, run_dir=run_dir, repo_root=repo_root, timeout=timeout,
        binary=binary)
    if evidence.exit_status != 0:
        raise BackendFailure(
            f"qualified BookSim execution failed with exit status "
            f"{evidence.exit_status}")
    stats = evidence.stats or {}
    counters = {
        # Counters the qualified fork actually prints; absent counters
        # stay None — never fabricated (§21).
        "delivered_packets": stats.get("delivered"),
        "flits_injected": stats.get("flits_injected"),
        "flits_accepted": stats.get("flits_accepted"),
        "drain_verdict": stats.get("drain_verdict"),
    }
    if summary is not None:
        verify_backend_quiescence(summary, counters)
    return {"evidence": evidence, "backend_counters": counters}


__all__ = [
    "assert_waved_ready", "prepare_waved_booksim", "render_waved_trace",
    "run_waved_booksim", "verify_backend_quiescence",
    "verify_trace_projection", "WAVED_TRACE_DIALECT",
]


def verify_trace_projection(pt: PhysicalTrafficArtifact) -> dict[str, Any]:
    """Mechanical losslessness proof for the representable fields (§21).

    Parses back the rendered trace and compares it against the artifact:
    line count, endpoint pairs, per-line flit counts, and ordering.

    Owned by the renderer, not by verification: it needs the trace
    grammar and the scanner, both of which live in the backend. The
    reference differentials live in verification/reference_semantics.py.
    """
    from veritx_dse.backend.booksim import _scan_trace
    trace = render_waved_trace(pt)
    # V2 canonical traffic exposes children directly; historical v1
    # nests them under .bundle (same objects, same hashes).
    attachment = getattr(pt, "attachment", None) or pt.bundle.attachment
    packet_format = getattr(pt, "packet_format", None) \
        or pt.bundle.packet_format
    summary = _scan_trace(
        trace, endpoint_count=attachment.endpoint_count,
        max_packet_flits=packet_format.max_packet_flits)
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


def assert_projection_ready(pt: PhysicalTrafficArtifact) -> dict[str, Any]:
    """Every pre-spawn gate: workload gates, then the projection check."""
    assert_workload_ready(pt)
    return verify_trace_projection(pt)


__all__ = [
    "assert_projection_ready", "prepare_waved_booksim",
    "render_waved_trace", "run_waved_booksim", "verify_trace_projection",
    "WAVED_TRACE_DIALECT",
]
