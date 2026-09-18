"""Phase 16 — System Execution / Bottleneck Attribution.

One dependency-aware timeline over declared per-op backend service legs,
answering the product question: *what actually delayed this workload —
and what would improving each subsystem actually save?*

Relationship to the plan: the CanonicalWorkloadArtifact is the semantic
parent (Phase 9); BookSim/analytical/memory evidence conventions come
from Phases 5/15. Phase 16 does NOT couple simulators (reviewer §Phase
16): it composes DECLARED per-op service legs through the workload's
dependency structure and attributes stalls.

Canonical time unit
-------------------
Every leg is normalized to NANOSECONDS before any comparison:
    compute_ns = compute_cycles × compute.ns_per_cycle
    memory_ns  = mem_cycles     × mem.ns_per_cycle      (the MEM clock)
    network_ns = net_cycles     × net.ns_per_cycle      (the NET clock)
    rate_ns    = bytes / bytes_per_second × 1e9        (SI: no clock)
Cycles without a clock are not time — a service leg in cycles with no
binding for its dimension raises (fail closed; the 2026-09-18 review
found compute-ns, mem-on-compute-clock, raw net cycles, and raw seconds
mixed inside one max()).

Op model (where overlap comes from)
-----------------------------------
- The artifact's op ORDER is the dependency carrier (the ET lowering
  chains nodes positionally): op *i* is released when op *i-1* finishes.
  No dependency edges are invented here.
- One op = one dependency step issuing its service legs CONCURRENTLY:
    finish = ready + max(legs_ns)
- Per op the attribution reports SEPARATE metrics (never overloaded):
    service_ns(d)          the declared leg
    exposed_stall_ns(d)    max(0, leg − max other leg)  — the COUNTER-
                           FACTUAL: runtime saved if dimension d were
                           instantaneous. A 20,000ns compute beside a
                           5,000ns mem fetch → compute stall 15,000
                           (removing compute saves exactly that), mem 0.
    overlap_ns(d)          leg − exposed_stall — the hidden part
    critical_path_owner    dimension(s) whose leg == step span; the
                           step's span is attributed fully to them
                           (ownership, NOT stall — a tie credits each)
- Legs by op kind (all values DECLARED, never defaulted):
    COMPUTE            compute leg (required) + optional memory leg
                       (mem_cycles — operand fetch service, e.g. from a
                       Ramulator evaluation of the operand stream)
    comm (net form)    single net leg (net_cycles, e.g. BookSim evidence)
    comm (rate form)   concurrent mem/comp legs: bytes/mem_bw and
                       bytes/comp_bw (transfer overlaps local work)
  A comm op declares EITHER net_cycles OR the rate pair — both is
  ambiguous, neither is unservable.
- SYNC: the v1 canonical op set has no barrier semantics, so there is no
  sync leg and SYNC_BOUND is unreachable in v1 — recorded as an explicit
  assumption on every attribution, never as a silent zero.

Verdicts (§ reviewer spec, on exposed STALL — the savings question)
-------------------------------------------------------------------
The one rule (2026-09-18 consolidation-2):
    net service > 0 AND net stall == 0  → NETWORK_NOT_THE_BOTTLENECK
    net stall > 0, tied with another dim → MIXED (co-bottlenecks:
        improving either independently still saves runtime)
    net stall unique max                → FABRIC_BOUND
  COMPUTE_BOUND / MEMORY_BOUND          — unique stall leader
  MIXED                                 — tie or leader margin ≤ 0.05
  INCONCLUSIVE                          — no dimension carries service
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.workload.canonical import WorkloadArtifact, WorkloadOp

MIXED_REL_MARGIN = 0.05
NS_PER_SECOND = 1e9
COMM_DIMS = ("net", "mem", "comp")


class TimelineError(ValueError):
    """The Binding/dimension contract is violated — fail closed, never
    substitute a default service time or clock."""


# ── declared backend bindings (evidence attribution) ─────────────────────

@dataclass(frozen=True)
class BackendBinding:
    """Declared producer + fidelity + clock for one dimension.

    ns_per_cycle: REQUIRED for any cycle-denominated service on this
    dimension (cycles without a clock are not time — a default of 1.0
    would silently double time when the real clock is 0.5 ns/c).
    None is legal ONLY for bindings used exclusively with rate-form
    service (bytes/second is SI and needs no clock). No silent default.
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

    net_cycles OR (mem_bw, comp_bw) — never both (ambiguous authority).
    mem_cycles is the COMPUTE-op operand memory leg (explicit None = the
    op declares no memory service; absent is recorded, not zero-filled).
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

    Fail-closed: a COMPUTE op without compute_cycles raises; a comm op
    with neither service form raises; a cycles-denominated leg without
    its dimension's clock raises; values violating OpService invariants
    raise (checked at construction). Memory legs that were not declared
    are ABSENT legs — recorded as assumptions, never zero-filled.
    """
    evidence: dict[str, dict[str, str]] = {}
    assumptions: list[str] = []

    def ev(dim: str) -> dict[str, str]:
        b = getattr(default, dim) if default else None
        return ({"producer": b.producer, "fidelity": b.fidelity} if b
                else {"producer": "declared", "fidelity": "DECLARED"})

    if op.kind == "COMPUTE":
        if binding is None or binding.compute_cycles is None:
            raise TimelineError(
                f"op {op.op_id!r}: COMPUTE op has no declared compute "
                "service (compute_cycles) — refusing to fabricate one")
        clk = _clock(default, "compute", op.op_id)
        legs: dict[str, float] = {
            "compute": float(binding.compute_cycles) * clk.ns_per_cycle}
        evidence["compute"] = ev("compute")
        if binding.mem_cycles is not None:
            mem_clk = _clock(default, "mem", op.op_id)
            legs["mem"] = float(binding.mem_cycles) * mem_clk.ns_per_cycle
            evidence["mem"] = ev("mem")
        else:
            assumptions.append(
                f"op {op.op_id!r}: no memory service declared — operand "
                "memory is unmodeled for this op (absent leg, not zero)")
        return legs, evidence, assumptions

    # comm op
    op_net = binding.net_cycles if binding else None
    op_mem = binding.mem_bw if binding else None
    op_comp = binding.comp_bw if binding else None
    if op_net is not None:
        net_clk = _clock(default, "net", op.op_id)
        legs = {"net": float(op_net) * net_clk.ns_per_cycle}
        evidence["net"] = ev("net")
        return legs, evidence, assumptions
    if op_mem is None or op_comp is None:
        raise TimelineError(
            f"op {op.op_id!r}: comm op has no declared service "
            "(net_cycles or mem_bw/comp_bw) — refusing to fabricate one")
    nbytes = op.bytes or 0
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

    legs          declared service per dimension
    exposed       critical-path OWNERSHIP: the step span credited to the
                  longest leg's dimension(s) (a tie credits each)
    exposed_stall COUNTERFACTUAL savings: max(0, leg − max other leg) —
                  what runtime drops if that dimension were instantaneous
    overlap       legs hidden under a concurrent longer leg
    owners        dimension(s) whose leg == the step span
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
    services = op_services or {}
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
    for op in art.ops:
        legs, evidence, asm = _legs_for_op(
            op, default, services.get(op.op_id))
        assumptions.extend(asm)
        ready = prev_finish
        span = max(legs.values())
        finish = ready + span
        # Ownership: full span to the longest leg(s) — a tie credits each
        # tied leg, so ownership sums may exceed the span exactly when a
        # single-owner verdict must be refused.
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
            op_id=op.op_id, kind=op.kind, ready=ready, finish=finish,
            legs=dict(legs), exposed=exposed,
            exposed_stall=dict(exposed_stall), overlap=dict(overlap),
            owners=owners,
            evidence={k: dict(v) for k, v in evidence.items()}))
        prev_finish = finish

    attribution = _attribute(records, service_totals, exposed_totals,
                             stall_totals, art.comm_bytes_total())
    clocks: dict[str, float] = {}
    if default is not None:
        for dim in ("compute", "net", "mem", "comp"):
            b = getattr(default, dim)
            if b is not None:
                clocks[dim] = b.ns_per_cycle
    return Timeline(artifact_hash=art.artifact_hash,
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
    # A positive tie between net and another dimension is MIXED, never
    # NETWORK_NOT_THE_BOTTLENECK: making the fabric instantaneous saves
    # mx ns — the network clearly matters (consolidation-2 ruling; the
    # old net-tie special case contradicted the counterfactual).
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
