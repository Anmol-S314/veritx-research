"""Phase 16 — System Execution / Bottleneck Attribution.

One dependency-aware timeline over declared per-op backend service legs,
answering the product question: *what actually delayed this workload?*

Relationship to the plan: the CanonicalWorkloadArtifact is the semantic
parent (Phase 9); BookSim/analytical/memory evidence conventions come
from Phases 5/15. Phase 16 does NOT couple simulators (reviewer §Phase
16): it composes DECLARED per-op service legs through the workload's
dependency structure and attributes stalls. Service is what a backend
charged; **exposed stall** is what the critical path actually waited.

Op model (where overlap comes from)
-----------------------------------
- The artifact's op ORDER is the dependency carrier (the ET lowering
  chains nodes positionally): op *i* is released when op *i-1* finishes.
  No dependency edges are invented here.
- One op = one dependency step issuing its service legs CONCURRENTLY:
    finish = ready + max(legs)
  This is what makes hidden time representable: a 5,000-cycle memory
  fetch under a 20,000-cycle compute finishes with the compute, and its
  exposed stall is 0 — never "compute + memory".
- Per-dimension exposed stall (critical-path attribution): the step's
  span (its max leg) is credited to the longest leg's dimension(s);
  strictly-shorter concurrent legs are fully hidden by definition.
  Under a tie, EACH tied leg is credited the full span — either could
  be the critical path — so the exposed sum may exceed the chain
  advance exactly when a single-bottleneck verdict must be refused.
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

Verdicts (§ reviewer spec)
--------------------------
  COMPUTE_BOUND / MEMORY_BOUND / FABRIC_BOUND
  NETWORK_NOT_THE_BOTTLENECK — net tied for max exposed with another dim
  MIXED                       — tie or relative margin <= 0.05
  INCONCLUSIVE                — no dimension has exposed > 0 (fully
                                overlapped / zero-service workload)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.workload.canonical import WorkloadArtifact, WorkloadOp

MIXED_REL_MARGIN = 0.05
COMM_DIMS = ("net", "mem", "comp")


class TimelineError(ValueError):
    """The Binding/dimension contract is violated — fail closed, never
    substitute a default service time."""


# ── declared backend bindings (evidence attribution) ─────────────────────

@dataclass(frozen=True)
class BackendBinding:
    """Declared producer + fidelity + clock for one dimension."""
    producer: str
    fidelity: str
    ns_per_cycle: float = 1.0

    def __post_init__(self) -> None:
        if not self.producer or not isinstance(self.producer, str):
            raise TimelineError(
                f"producer must be a non-empty string, got {self.producer!r}")
        if not self.fidelity or not isinstance(self.fidelity, str):
            raise TimelineError(
                f"fidelity must be a non-empty string, got {self.fidelity!r}")
        if not isinstance(self.ns_per_cycle, (int, float)) or \
                isinstance(self.ns_per_cycle, bool) or self.ns_per_cycle <= 0:
            raise TimelineError(
                "ns_per_cycle must be a positive number, got "
                f"{self.ns_per_cycle!r}")


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


# ── leg resolution (one implementation) ──────────────────────────────────

def _legs_for_op(op: WorkloadOp, default: ServiceBinding | None,
                 binding: OpService | None,
                 ) -> tuple[dict[str, float], dict[str, dict[str, str]],
                            list[str]]:
    """Resolve one op's concurrent service legs in final cycle units.

    Fail-closed: a COMPUTE op without compute_cycles raises; a comm op
    with neither service form raises; values violating OpService invariants
    raise (checked at construction). Memory legs that were not declared
    are ABSENT legs — recorded as assumptions, never zero-filled.
    """
    evidence: dict[str, dict[str, str]] = {}
    assumptions: list[str] = []

    def ev(dim: str, binding_key: str) -> dict[str, str]:
        b = getattr(default, binding_key) if default else None
        return ({"producer": b.producer, "fidelity": b.fidelity} if b
                else {"producer": "declared", "fidelity": "DECLARED"})

    if op.kind == "COMPUTE":
        if binding is None or binding.compute_cycles is None:
            raise TimelineError(
                f"op {op.op_id!r}: COMPUTE op has no declared compute "
                "service (compute_cycles) — refusing to fabricate one")
        clk = default.compute.ns_per_cycle if (default and default.compute) \
            else 1.0
        legs: dict[str, float] = {
            "compute": float(binding.compute_cycles) * clk}
        evidence["compute"] = ev("compute", "compute")
        if binding.mem_cycles is not None:
            legs["mem"] = float(binding.mem_cycles) * clk
            evidence["mem"] = ev("mem", "mem")
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
        legs = {"net": float(op_net)}
        evidence["net"] = ev("net", "net")
        return legs, evidence, assumptions
    if op_mem is None or op_comp is None:
        raise TimelineError(
            f"op {op.op_id!r}: comm op has no declared service "
            "(net_cycles or mem_bw/comp_bw) — refusing to fabricate one")
    nbytes = op.bytes or 0
    legs = {"mem": nbytes / op_mem, "comp": nbytes / op_comp}
    evidence["mem"] = ev("mem", "mem")
    evidence["comp"] = ev("comp", "comp")
    return legs, evidence, assumptions


# ── the timeline ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OpRecord:
    """One op's timeline row: ready/finish plus concurrent service legs,
    per-dimension exposed stall, and evidence attribution per leg."""
    op_id: str
    kind: str
    ready: float
    finish: float
    legs: dict[str, float]
    exposed: dict[str, float]
    evidence: dict[str, dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {"op_id": self.op_id, "kind": self.kind,
                "ready": self.ready, "finish": self.finish,
                "legs": dict(self.legs), "exposed": dict(self.exposed),
                "evidence": {k: dict(v) for k, v in self.evidence.items()}}


@dataclass(frozen=True)
class Attribution:
    """Machine-readable bottleneck verdict."""
    verdict: str
    exposed_totals: dict[str, float]
    bottleneck: str | None
    margin: float | None
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict,
                "exposed_totals": dict(self.exposed_totals),
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
    attribution: Attribution
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "veritx.timeline/1",
            "artifact_hash": self.artifact_hash,
            "ns_per_cycle": dict(self.ns_per_cycle),
            "ops": [o.to_dict() for o in self.ops],
            "service_totals": dict(self.service_totals),
            "exposed_totals": dict(self.exposed_totals),
            "attribution": self.attribution.to_dict(),
            "assumptions": list(self.assumptions),
        }


def build_timeline(art: WorkloadArtifact,
                   default: ServiceBinding | None = None,
                   op_services: dict[str, OpService] | None = None,
                   ) -> Timeline:
    """Compose the dependency timeline and attribute exposed stalls.

    Every op must carry declared service legs (op_services overrides the
    default binding per dimension); an op without them raises — a timeline
    with fabricated services would mis-attribute by construction.
    """
    services = op_services or {}
    records: list[OpRecord] = []
    service_totals: dict[str, float] = {}
    exposed_totals: dict[str, float] = {}
    assumptions: list[str] = [
        "op order is the dependency carrier (chain, no invented edges)",
        "sync has no leg in v1 (no barrier ops in the canonical op set) "
        "— SYNC_BOUND is unreachable in v1",
        "exposed(d) = max(0, leg(d) - max other concurrent leg)",
    ]
    prev_finish = 0.0
    for op in art.ops:
        legs, evidence, asm = _legs_for_op(
            op, default, services.get(op.op_id))
        assumptions.extend(asm)
        ready = prev_finish
        finish = ready + max(legs.values())
        longest = max(legs.values())
        # Critical-path attribution: the step's span (its max leg) is
        # attributed to the longest leg's dimension(s); strictly-shorter
        # concurrent legs are fully hidden by definition. Sum of exposed
        # across dimensions == step span == chain advance. (Leg-difference
        # attribution — max(0, leg - max other) — would under-credit the
        # critical path: a 20000c compute leg next to a 5000c mem leg
        # would read 15000c exposed, which is wrong: remove the compute
        # and the step finishes 20000c earlier.)
        exposed = {d: (v if v == longest else 0.0)
                   for d, v in legs.items()}
        for d, v in legs.items():
            service_totals[d] = service_totals.get(d, 0.0) + v
        for d, v in exposed.items():
            exposed_totals[d] = exposed_totals.get(d, 0.0) + v
        records.append(OpRecord(
            op_id=op.op_id, kind=op.kind, ready=ready, finish=finish,
            legs=dict(legs), exposed=exposed,
            evidence={k: dict(v) for k, v in evidence.items()}))
        prev_finish = finish

    attribution = _attribute(records, exposed_totals,
                             art.comm_bytes_total())
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
                    attribution=attribution,
                    assumptions=tuple(assumptions))


# ── verdict (§ reviewer spec) ────────────────────────────────────────────

_BOUND_NAMES = {"compute": "COMPUTE_BOUND", "net": "FABRIC_BOUND",
                "mem": "MEMORY_BOUND", "comp": "COMPUTE_BOUND"}


def _attribute(records: tuple[OpRecord, ...],
               exposed: dict[str, float],
               comm_bytes_total: int) -> Attribution:
    reasons: list[str] = [
        "sync leg absent in v1 — synchronization cannot be the verdict"]
    if not any(v > 0 for v in exposed.values()):
        return Attribution(
            verdict="INCONCLUSIVE", exposed_totals=dict(exposed),
            bottleneck=None, margin=None,
            reasons=reasons + [
                "no dimension has exposed stall > 0 — every leg is covered "
                "by a concurrent longer leg or carries no service; the "
                "workload does not exercise a bottleneck under this binding"])
    mx = max(exposed.values())
    tied = sorted(d for d, v in exposed.items() if v == mx)
    positive = sorted((v for v in exposed.values() if v > 0), reverse=True)
    runner_up = positive[1] if len(positive) > 1 else 0.0
    margin = runner_up / mx
    if len(tied) > 1:
        if "net" in tied:
            return Attribution(
                verdict="NETWORK_NOT_THE_BOTTLENECK",
                exposed_totals=dict(exposed), bottleneck=None, margin=margin,
                reasons=reasons + [
                    "net tied for max exposed with " +
                    ", ".join(d for d in tied if d != "net") +
                    " — fabric improvements would not shorten the "
                    "critical path"])
        return Attribution(
            verdict="MIXED", exposed_totals=dict(exposed),
            bottleneck=None, margin=margin,
            reasons=reasons + [f"tie for max exposed: {tied}"])
    if margin >= 1.0 - MIXED_REL_MARGIN:
        return Attribution(
            verdict="MIXED", exposed_totals=dict(exposed),
            bottleneck=None, margin=margin,
            reasons=reasons + [
                f"runner-up exposed is within {1.0 - margin:.2%} of the "
                f"leader (mixed margin {MIXED_REL_MARGIN:.0%})"])
    leader = tied[0]
    if leader == "net" and comm_bytes_total == 0:
        reasons.append("fabric leads with zero declared comm bytes — "
                       "verify the binding (bytes are part of op identity)")
    return Attribution(verdict=_BOUND_NAMES[leader],
                       exposed_totals=dict(exposed), bottleneck=leader,
                       margin=margin, reasons=reasons)
