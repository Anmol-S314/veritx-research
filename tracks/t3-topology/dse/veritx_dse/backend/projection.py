"""veritx_dse.backend.projection — derived-traffic backend input.

Rationale: docs/decisions/modules/backend.md
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

PhysicalTrafficArtifact = PhysicalTrafficArtifactV2


WAVED_TRACE_DIALECT = "waved-derived-whitespace-v1"


def render_waved_trace(pt: PhysicalTrafficArtifact) -> bytes:
    """Render the canonical Wave-D traffic as a BookSim trace.

Rationale: docs/decisions/modules/backend.md
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

Rationale: docs/decisions/modules/backend.md
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
