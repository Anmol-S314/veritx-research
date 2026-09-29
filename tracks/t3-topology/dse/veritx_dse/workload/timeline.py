"""Phase 16 — System Execution / Bottleneck Attribution.

Rationale: docs/decisions/modules/workload.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from dataclasses import dataclass
from typing import Any

from veritx_dse.workload.canonical import WorkloadArtifact, WorkloadOp

MIXED_REL_MARGIN = 0.05
NS_PER_SECOND = 1e9
COMM_DIMS = ("net", "mem", "comp")


class TimelineError(ValueError, SemanticError):
    """The Binding/dimension contract is violated — fail closed, never
    substitute a default service time or clock."""


# ── declared backend bindings (evidence attribution) ─────────────────────

@dataclass(frozen=True)
class BackendBinding:
    """Declared producer + fidelity + clock for one dimension.

Rationale: docs/decisions/modules/workload.md
    """
    producer: str
    fidelity: str
    ns_per_cycle: float | None = None

    def __post_init__(self) -> None:
        if not self.producer or not isinstance(self.producer, str):
            raise TimelineError(
                f"producer must be a non-empty string, got {self.producer!r}")
        if not self.fidelity or not isinstance(self.fidelity, str):
            raise TimelineError(
                f"fidelity must be a non-empty string, got {self.fidelity!r}")
        if self.ns_per_cycle is not None:
            v = self.ns_per_cycle
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                raise TimelineError(
                    "ns_per_cycle must be a positive number or None "
                    f"(rate-form only), got {v!r}")


@dataclass(frozen=True)
class OpService:
    """Declared service legs for one op (evidence attribution metadata).

Rationale: docs/decisions/modules/workload.md
    """
    compute_cycles: int | None = None
    net_cycles: float | None = None
    mem_bw: float | None = None
    comp_bw: float | None = None
    mem_cycles: float | None = None

    def __post_init__(self) -> None:
        if self.net_cycles is not None and \
                (self.mem_bw is not None or self.comp_bw is not None):
            raise TimelineError(
                "OpService: declare EITHER net_cycles OR (mem_bw, comp_bw) "
                "byte rates — providing both is ambiguous")
        for name in ("compute_cycles", "mem_cycles"):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, (int, float)) or
                                  isinstance(v, bool) or v < 0):
                raise TimelineError(f"{name} must be >= 0, got {v!r}")
        for name in ("mem_bw", "comp_bw"):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, (int, float)) or
                                  isinstance(v, bool) or v <= 0):
                raise TimelineError(
                    f"{name} must be a positive bytes/sec rate, got {v!r}")


@dataclass(frozen=True)
class ServiceBinding:
    """Default per-dimension backend binding (producer/fidelity/clock)."""
    compute: BackendBinding | None = None
    net: BackendBinding | None = None
    mem: BackendBinding | None = None
    comp: BackendBinding | None = None


# ── leg resolution (one implementation; canonical ns) ────────────────────

def _clock(default: ServiceBinding | None, dim: str,
           op_id: str) -> BackendBinding:
    """The binding for `dim` — mandatory AND clock-carrying whenever that
    dimension's service is declared in cycles (cycles without a clock are
    not time; a binding with ns_per_cycle=None is a rate-form-only
    binding and must not be silently read as 1.0)."""
    b = getattr(default, dim) if default else None
    if b is None:
        raise TimelineError(
            f"op {op_id!r}: {dim} service is declared in cycles but no "
            f"{dim} binding (clock) exists — cycles without a clock are "
            "not time; declare ServiceBinding." + dim + "=BackendBinding(...)")
    if b.ns_per_cycle is None:
        raise TimelineError(
            f"op {op_id!r}: {dim} service is declared in cycles but the "
            f"{dim} binding carries ns_per_cycle=None (rate-form only) — "
            "declare the clock explicitly; 1 cycle is not silently 1 ns")
    return b


def _legs_for_op(op: WorkloadOp, default: ServiceBinding | None,
                 binding: OpService | None,
                 ) -> tuple[dict[str, float], dict[str, dict[str, str]],
                            list[str]]:
    """Resolve one op's concurrent service legs in CANONICAL NANOSECONDS.

Rationale: docs/decisions/modules/workload.md
    """
    return _legs_for_view(op.op_id, op.kind == "COMPUTE",
                          op.bytes or 0, default, binding)


def _legs_for_view(op_id: str, is_compute: bool, nbytes: int,
                   default: ServiceBinding | None,
                   binding: OpService | None,
                   ) -> tuple[dict[str, float], dict[str, dict[str, str]],
                              list[str]]:
    """Leg core over an op view (one implementation for both workload
    authorities)."""
    evidence: dict[str, dict[str, str]] = {}
    assumptions: list[str] = []

    def ev(dim: str) -> dict[str, str]:
        b = getattr(default, dim) if default else None
        return ({"producer": b.producer, "fidelity": b.fidelity} if b
                else {"producer": "declared", "fidelity": "DECLARED"})

    if is_compute:
        if binding is None or binding.compute_cycles is None:
            raise TimelineError(
                f"op {op_id!r}: COMPUTE op has no declared compute "
                "service (compute_cycles) — refusing to fabricate one")
        clk = _clock(default, "compute", op_id)
        legs: dict[str, float] = {
            "compute": float(binding.compute_cycles) * clk.ns_per_cycle}
        evidence["compute"] = ev("compute")
        if binding.mem_cycles is not None:
            mem_clk = _clock(default, "mem", op_id)
            legs["mem"] = float(binding.mem_cycles) * mem_clk.ns_per_cycle
            evidence["mem"] = ev("mem")
        else:
            assumptions.append(
                f"op {op_id!r}: no memory service declared — operand "
                "memory is unmodeled for this op (absent leg, not zero)")
        return legs, evidence, assumptions

    # comm op
    op_net = binding.net_cycles if binding else None
    op_mem = binding.mem_bw if binding else None
    op_comp = binding.comp_bw if binding else None
    if op_net is not None:
        net_clk = _clock(default, "net", op_id)
        legs = {"net": float(op_net) * net_clk.ns_per_cycle}
        evidence["net"] = ev("net")
        return legs, evidence, assumptions
    if op_mem is None or op_comp is None:
        raise TimelineError(
            f"op {op_id!r}: comm op has no declared service "
            "(net_cycles or mem_bw/comp_bw) — refusing to fabricate one")
    nbytes = nbytes or 0
    # Rate form is SI (bytes/second) — no clock involved: s → ns via 1e9.
    legs = {"mem": nbytes / op_mem * NS_PER_SECOND,
            "comp": nbytes / op_comp * NS_PER_SECOND}
    evidence["mem"] = ev("mem")
    evidence["comp"] = ev("comp")
    return legs, evidence, assumptions


# ── the timeline ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OpRecord:
    """One op's timeline row, all values in canonical ns.

Rationale: docs/decisions/modules/workload.md
    """
    op_id: str
    kind: str
    ready: float
    finish: float
    legs: dict[str, float]
    exposed: dict[str, float]
    exposed_stall: dict[str, float]
    overlap: dict[str, float]
    owners: tuple[str, ...]
    evidence: dict[str, dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {"op_id": self.op_id, "kind": self.kind,
                "ready": self.ready, "finish": self.finish,
                "legs": dict(self.legs), "exposed": dict(self.exposed),
                "exposed_stall": dict(self.exposed_stall),
                "overlap": dict(self.overlap),
                "critical_path_owners": list(self.owners),
                "evidence": {k: dict(v) for k, v in self.evidence.items()}}


@dataclass(frozen=True)
class Attribution:
    """Machine-readable bottleneck verdict (over exposed STALL)."""
    verdict: str
    exposed_totals: dict[str, float]
    exposed_stall_totals: dict[str, float]
    bottleneck: str | None
    margin: float | None
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict,
                "exposed_totals": dict(self.exposed_totals),
                "exposed_stall_totals": dict(self.exposed_stall_totals),
                "bottleneck": self.bottleneck, "margin": self.margin,
                "reasons": list(self.reasons)}


@dataclass(frozen=True)
class Timeline:
    """Dependency-aware timeline + stall attribution over a workload."""
    artifact_hash: str
    ns_per_cycle: dict[str, float]
    ops: tuple[OpRecord, ...]
    service_totals: dict[str, float]
    exposed_totals: dict[str, float]
    exposed_stall_totals: dict[str, float]
    overlap_totals: dict[str, float]
    attribution: Attribution
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "veritx.timeline/2",
            "artifact_hash": self.artifact_hash,
            "ns_per_cycle": dict(self.ns_per_cycle),
            "ops": [o.to_dict() for o in self.ops],
            "service_totals": dict(self.service_totals),
            "exposed_totals": dict(self.exposed_totals),
            "exposed_stall_totals": dict(self.exposed_stall_totals),
            "overlap_totals": dict(self.overlap_totals),
            "attribution": self.attribution.to_dict(),
            "assumptions": list(self.assumptions),
        }


def build_timeline(art: WorkloadArtifact,
                   default: ServiceBinding | None = None,
                   op_services: dict[str, OpService] | None = None,
                   ) -> Timeline:
    """Compose the dependency timeline and attribute stalls.

    Every op must carry declared service legs (op_services overrides the
    default binding per dimension); an op without them raises — a timeline
    with fabricated services would mis-attribute by construction.
    """
    views = [(op.op_id, op.kind, op.kind == "COMPUTE", op.bytes or 0)
             for op in art.ops]
    return _compose_timeline(views, default, op_services or {},
                             source_hash=art.artifact_hash,
                             comm_bytes=art.comm_bytes_total())


def build_timeline_graph(graph: Any,
                         default: ServiceBinding | None = None,
                         op_services: dict[str, OpService] | None = None,
                         ) -> Timeline:
    """Compose the dependency timeline over a canonical WorkloadGraph (M3).

Rationale: docs/decisions/modules/workload.md
    """
    from veritx_dse.core.artifact import thaw
    from veritx_dse.workload.graph import KIND_COMPUTE
    views = []
    for op in graph.require_total_order():
        d = thaw(op.detail)
        kind = op.kind
        if kind == KIND_COMPUTE:
            views.append((op.operation_id, kind, True, 0))
            continue
        if kind in ("COLLECTIVE", "P2P", "MULTICAST"):
            nbytes = d.get("payload_bytes") or 0
        elif kind in ("EXPERT_BEGIN", "EXPERT_END"):
            nbytes = d.get("payload_bytes") or 0
        else:  # PIM_CHANNEL / PIM_END: structural, no bytes
            nbytes = 0
        views.append((op.operation_id, kind, False, nbytes))
    comm_bytes = sum(v[3] for v in views if not v[2])
    return _compose_timeline(views, default, op_services or {},
                             source_hash=graph.workload_id(),
                             comm_bytes=comm_bytes)


def _compose_timeline(views: list[tuple[str, str, bool, int]],
                      default: ServiceBinding | None,
                      services: dict[str, OpService],
                      *, source_hash: str, comm_bytes: int,
                      ) -> Timeline:
    """Shared composition core over (op_id, kind, is_compute, nbytes)."""
    records: list[OpRecord] = []
    service_totals: dict[str, float] = {}
    exposed_totals: dict[str, float] = {}
    stall_totals: dict[str, float] = {}
    overlap_totals: dict[str, float] = {}
    assumptions: list[str] = [
        "op order is the dependency carrier (chain, no invented edges)",
        "sync has no leg in v1 (no barrier ops in the canonical op set) "
        "— SYNC_BOUND is unreachable in v1",
        "all legs normalized to ns: cycles × dimension clock; byte rates "
        "are SI (×1e9 s→ns)",
        "exposed_stall(d) = max(0, leg(d) − max other concurrent leg) — "
        "the counterfactual saving if d were instantaneous",
        "exposed(d) = critical-path ownership: the step span credited to "
        "the longest leg(s); distinct from stall by design",
    ]
    prev_finish = 0.0
    for op_id, kind, is_compute, nbytes in views:
        legs, evidence, asm = _legs_for_view(
            op_id, is_compute, nbytes, default, services.get(op_id))
        assumptions.extend(asm)
        ready = prev_finish
        span = max(legs.values())
        finish = ready + span
        exposed = {d: (v if v == span else 0.0) for d, v in legs.items()}
        owners = tuple(d for d, v in legs.items() if v == span)
        # Counterfactual stall: eliminate d → new span = max(other legs).
        exposed_stall = {
            d: max(0.0, v - max((o for d2, o in legs.items() if d2 != d),
                                default=0.0))
            for d, v in legs.items()}
        overlap = {d: v - exposed_stall[d] for d, v in legs.items()}
        for d, v in legs.items():
            service_totals[d] = service_totals.get(d, 0.0) + v
        for d, v in exposed.items():
            exposed_totals[d] = exposed_totals.get(d, 0.0) + v
        for d, v in exposed_stall.items():
            stall_totals[d] = stall_totals.get(d, 0.0) + v
        for d, v in overlap.items():
            overlap_totals[d] = overlap_totals.get(d, 0.0) + v
        records.append(OpRecord(
            op_id=op_id, kind=kind, ready=ready, finish=finish,
            legs=dict(legs), exposed=exposed,
            exposed_stall=dict(exposed_stall), overlap=dict(overlap),
            owners=owners,
            evidence={k: dict(v) for k, v in evidence.items()}))
        prev_finish = finish

    attribution = _attribute(records, service_totals, exposed_totals,
                             stall_totals, comm_bytes)
    clocks: dict[str, float] = {}
    if default is not None:
        for dim in ("compute", "net", "mem", "comp"):
            b = getattr(default, dim)
            if b is not None:
                clocks[dim] = b.ns_per_cycle
    return Timeline(artifact_hash=source_hash,
                    ns_per_cycle=clocks, ops=tuple(records),
                    service_totals=service_totals,
                    exposed_totals=exposed_totals,
                    exposed_stall_totals=stall_totals,
                    overlap_totals=overlap_totals,
                    attribution=attribution,
                    assumptions=tuple(assumptions))


# ── verdict (§ reviewer spec, on exposed STALL) ──────────────────────────

_BOUND_NAMES = {"compute": "COMPUTE_BOUND", "net": "FABRIC_BOUND",
                "mem": "MEMORY_BOUND", "comp": "COMPUTE_BOUND"}


def _attribute(records: tuple[OpRecord, ...],
               service: dict[str, float],
               ownership: dict[str, float],
               stall: dict[str, float],
               comm_bytes_total: int) -> Attribution:
    reasons: list[str] = [
        "sync leg absent in v1 — synchronization cannot be the verdict",
        "verdict over exposed_stall (counterfactual savings), not "
        "critical-path ownership"]
    if not any(v > 0 for v in service.values()):
        return Attribution(
            verdict="INCONCLUSIVE", exposed_totals=dict(ownership),
            exposed_stall_totals=dict(stall),
            bottleneck=None, margin=None,
            reasons=reasons + [
                "no dimension carries service — the workload does not "
                "exercise a bottleneck under this binding"])

    def stall_of(d: str) -> float:
        return stall.get(d, 0.0)

    # THE one net rule: carried service but zero stall → fabric changes
    # save nothing. (Also covers the all-stalls-0 case when net served.)
    if service.get("net", 0.0) > 0 and stall_of("net") <= 0.0:
        return Attribution(
            verdict="NETWORK_NOT_THE_BOTTLENECK",
            exposed_totals=dict(ownership),
            exposed_stall_totals=dict(stall),
            bottleneck=None, margin=None,
            reasons=reasons + [
                "net carried service but its exposed stall is 0 — the "
                "fabric is fully hidden under a concurrent longer leg; "
                "fabric improvements would not shorten the critical path"])

    # Perfect tie: ≥2 dims served, every stall 0 — eliminating any single
    # subsystem saves nothing anywhere; fall back to ownership for MIXED.
    if all(v <= 0.0 for v in stall.values()):
        mx = max(ownership.values())
        tied = sorted(d for d in service if service.get(d, 0.0) > 0
                      and ownership.get(d, 0.0) == mx)
        return Attribution(
            verdict="MIXED", exposed_totals=dict(ownership),
            exposed_stall_totals=dict(stall),
            bottleneck=None, margin=1.0,
            reasons=reasons + [
                f"perfect tie at max ownership: {tied} — no single "
                "subsystem owns the critical path"])

    positive = sorted((v for v in stall.values() if v > 0), reverse=True)
    mx = positive[0]
    tied = sorted(d for d, v in stall.items() if v == mx)
    runner_up = positive[1] if len(positive) > 1 else 0.0
    margin = runner_up / mx
    if len(tied) > 1:
        return Attribution(
            verdict="MIXED", exposed_totals=dict(ownership),
            exposed_stall_totals=dict(stall),
            bottleneck=None, margin=margin,
            reasons=reasons + [
                f"tie for max exposed stall: {tied} — co-bottlenecks; "
                "improving either tied subsystem alone saves mx ns"])
    if margin >= 1.0 - MIXED_REL_MARGIN:
        return Attribution(
            verdict="MIXED", exposed_totals=dict(ownership),
            exposed_stall_totals=dict(stall),
            bottleneck=None, margin=margin,
            reasons=reasons + [
                f"runner-up stall is within {1.0 - margin:.2%} of the "
                f"leader (mixed margin {MIXED_REL_MARGIN:.0%})"])
    leader = tied[0]
    if leader == "net" and comm_bytes_total == 0:
        reasons.append("fabric leads with zero declared comm bytes — "
                       "verify the binding (bytes are part of op identity)")
    return Attribution(verdict=_BOUND_NAMES[leader],
                       exposed_totals=dict(ownership),
                       exposed_stall_totals=dict(stall),
                       bottleneck=leader, margin=margin, reasons=reasons)
