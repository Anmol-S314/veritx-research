"""veritx_dse.application.requirements — RequirementEvaluator (P1C).

Evaluates v3 requirements over an ALREADY-VERIFIED PerformanceResult
(performance/result.py authority — this module never builds, schedules,
or re-verifies results; it reads the verified document). No backend, no
spawn, no optimization: one pure function of (request, workload,
performance).

Measurement honesty (binding — every rule enforced below):

* **Aggregate evidence, attributed honestly.** BookSim yields ONE global
  traffic window, never per-operation or per-class completion. A global
  completion time is a SOUND UPPER BOUND on any class's completion
  (class traffic completes no later than window drain), so:
    - aggregate latency <= ceiling -> class SATISFIED (proven);
    - aggregate latency > ceiling with several classes in play ->
      UNMEASURABLE (the excess cannot be attributed — a class VIOLATED
      from aggregate data would be fabricated);
    - fabric-wide (or single-class, where aggregate == class evidence)
      requirements evaluate directly to SATISFIED / VIOLATED.
* **Bandwidth needs bytes.** A bandwidth floor measures iff attributable
  byte movement exists (BANDWIDTH utilization entries) over a known
  window: fabric-wide or single-class aggregates evaluate; class-scoped
  requirements over multi-class workloads are UNMEASURABLE (per-class
  bytes are not evidenced). Absent bytes are absent, never zero-filled.
* **Cycles are compared to cycles.** A latency ceiling is declared in
  fabric cycles, so it is compared against the fabric cycles the bound
  network window AUTHENTICATED: the binding records the exact pair
  (duration seconds, network_clock_hz) produced by
  completion_time / network_clock_hz, so multiplying them recovers the
  backend's completion_time exactly and the CALLER's clock cancels. A
  caller clock can rescale the wall duration but never the authenticated
  cycles. When no network window is bound, the makespan (compute+network
  wall-time superset) is converted with the DESIGN's own clock and the
  authority string says so — a documented conservative fallback, never a
  caller-clock rescale.
* **Wall-time stays wall-time.** Cycles-only evidence (no valid network
  clock) still refuses wall-time claims upstream (FabricEvaluator
  UNSUPPORTED, cycles-only window); requirement evaluation never
  invents the missing frequency.
* **Binding + UNMEASURABLE never passes.** report_passes() is False
  unless every BINDING entry is SATISFIED. Non-binding entries are
  advisory. A requirement with no thresholds at all is NOT_APPLICABLE,
  not satisfied.
* **Wrong workload refuses.** The workload geometry must equal the
  request geometry (same TP/PP/EP/DP law as the traffic seam: equal
  world size is not equivalence); a class-scoped requirement naming a
  class outside the request's intent registry refuses fail-closed.
* **The triple must belong to one design.** Geometry equality alone
  admits a same-shape transplant: two v3 requests with identical
  TP/PP/EP/DP but different payloads/semantics lower to same-geometry
  graphs. The workload must be EXACTLY this request's re-derived
  lowering (provenance is metadata, not authority — it is excluded from
  workload_id()), and the performance result must have passed the
  verified boundary (``verify_performance_result`` -> a
  ``VerifiedPerformanceResult``); its Wave-D chain must bind BOTH this
  workload's workload_id() AND this request's design_hash (traffic-class
  semantics live in the lowering sidecar, not in the canonical graph
  identity, so two designs differing only in traffic class share a
  workload_id). A naked result dict, a missing chain binding or a
  foreign graph refuses — an absent binding is not a pass.

Report shape follows contracts/srota/v1/requirement.report.schema.json
(contract_version 1): per-requirement {requirement_index,
traffic_class, qos_class, verdict, binding, required, measured,
metric_authority, performance_result_id, reason}.
"""
from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import (
    EvidenceInvalid,
    InvalidInput,
    MappingInvalid,
)
from veritx_dse.model.compile_model import (
    CompileRequestV3,
    RequirementV3,
    derive_v3_traffic_classes,
)
from veritx_dse.performance.result import ResultError, reverify_result
from veritx_dse.performance.workload import TemporalWorkload
from veritx_dse.workload.canonical_graph import WorkloadGraph
from veritx_dse.workload.intent_lowering import lower_compile_workload

REQUIREMENT_REPORT_CONTRACT_VERSION = 1
REQUIREMENT_REPORT_DOMAIN = "veritx/requirement-report/v1"

VERDICT_SATISFIED = "SATISFIED"
VERDICT_VIOLATED = "VIOLATED"
VERDICT_UNMEASURABLE = "UNMEASURABLE"
VERDICT_NOT_APPLICABLE = "NOT_APPLICABLE"


class VerifiedPerformanceResult(dict):
    """A PerformanceResult document that passed ``reverify_result``.

    The authoritative input to :meth:`RequirementEvaluator.evaluate`: a
    naked dict is NOT authentication — a nonempty ``resource_id`` proves
    nothing about the persisted content — so the evaluator refuses one
    and requires this wrapper. The evaluator re-runs ``reverify_result``
    on every call, so even a hand-constructed wrapper whose content was
    mutated after verification refuses. ``temporal_workload`` is the
    verified parent the result was re-derived against.
    """

    __slots__ = ("temporal_workload",)

    def __init__(self, document: Mapping[str, Any], *,
                 temporal_workload: TemporalWorkload) -> None:
        super().__init__(document)
        self.temporal_workload = temporal_workload


def verify_performance_result(
        document: Any, *, workload: TemporalWorkload,
        ) -> VerifiedPerformanceResult:
    """The verified boundary: raw result -> ``reverify_result`` -> wrapper.

    Re-derives the event graph, the deterministic schedule and every
    summary from the supplied verified TemporalWorkload. A document that
    no longer matches its own ``resource_id`` (stale ID after mutation)
    refuses here — before any requirement is adjudicated.
    """
    if not isinstance(document, Mapping):
        raise InvalidInput(
            f"verify_performance_result takes a result document mapping, "
            f"got {type(document).__name__}")
    if not isinstance(workload, TemporalWorkload):
        raise InvalidInput(
            f"verify_performance_result takes a TemporalWorkload, got "
            f"{type(workload).__name__}")
    try:
        reverify_result(document, workload=workload)
    except ResultError as exc:
        raise EvidenceInvalid(
            f"performance result failed reverify_result: {exc} — a stale "
            f"resource_id is not authentication; refusing the persisted "
            f"content") from exc
    return VerifiedPerformanceResult(document, temporal_workload=workload)


def _qtime_fraction(d: Any, what: str) -> Fraction:
    """Exact seconds from a persisted QTime {numerator, denominator}."""
    if not isinstance(d, dict) or set(d) != {"numerator", "denominator"}:
        raise InvalidInput(
            f"performance result {what} must be a QTime "
            f"{{numerator, denominator}} dict, got {d!r}")
    n, den = d["numerator"], d["denominator"]
    if not isinstance(n, int) or not isinstance(den, int) or den <= 0:
        raise InvalidInput(
            f"performance result {what} has non-integral QTime {d!r}")
    return Fraction(n, den)


def _bytes_fraction(v: Any) -> Fraction | None:
    """Byte counts out of result docs (Fraction, int, or {num,den})."""
    if v is None:
        return None
    if isinstance(v, Fraction):
        return v
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return Fraction(v) if v >= 0 else None
    if isinstance(v, float):
        return Fraction(v) if v >= 0 else None
    if isinstance(v, dict):
        if set(v) == {"num", "den"}:
            n, den = v["num"], v["den"]
        elif set(v) == {"numerator", "denominator"}:
            n, den = v["numerator"], v["denominator"]
        else:
            return None
        if isinstance(n, int) and isinstance(den, int) and den > 0 \
                and n >= 0:
            return Fraction(n, den)
        return None
    if isinstance(v, str):
        try:
            f = Fraction(v)
        except (ValueError, ZeroDivisionError):
            return None
        return f if f >= 0 else None
    return None


def _design_clock_hz(request: CompileRequestV3) -> Fraction:
    """The design's own clock (exact Hz) — the only legal converter for
    the makespan fallback (never a caller-supplied network clock)."""
    mhz = request.physical.default_clock_freq_mhz
    return Fraction(str(mhz)) * 10 ** 6


def _binding_clock_hz(raw: Any) -> Fraction | None:
    """The binding's recorded network clock as exact Hz, or None if the
    persisted field is null (cycles-only binding)."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, Fraction, dict)):
        raise EvidenceInvalid(
            f"network_binding.network_clock_hz must be null, an exact "
            f"number or {{num, den}}, got {raw!r}")
    if isinstance(raw, dict):
        if set(raw) != {"num", "den"}:
            raise EvidenceInvalid(
                f"network_binding.network_clock_hz must have exactly "
                f"{{num, den}}, got {sorted(raw)}")
        n, den = raw["num"], raw["den"]
        if not isinstance(n, int) or isinstance(n, bool) or \
                not isinstance(den, int) or isinstance(den, bool) \
                or den <= 0:
            raise EvidenceInvalid(
                f"network_binding.network_clock_hz has a malformed value "
                f"{raw!r}")
        hz = Fraction(n, den)
    else:
        hz = Fraction(raw)
    if hz <= 0:
        raise EvidenceInvalid(
            f"network_binding.network_clock_hz must be > 0, got {raw!r}")
    return hz


def _authenticated_latency_cycles(
        performance: dict[str, Any]) -> tuple[Fraction | None, str]:
    """The bound network window's authenticated completion cycles.

    The binding is the only source of AUTHENTICATED fabric cycles: it
    records (duration, network_clock_hz) as the exact image of the
    backend's integer completion_time under that clock. Multiplying the
    pair recovers that integer exactly — the caller's clock cancels —
    and a pair that does not reconstruct an integer cycle count is
    refused rather than measured. Returns (None, "") when no window
    duration is bound (cycles-only or compute-only evidence).
    """
    binding = performance.get("network_binding")
    if not isinstance(binding, dict) or binding.get("duration") is None:
        return None, ""
    seconds = _qtime_fraction(binding["duration"],
                              "network_binding.duration")
    hz = _binding_clock_hz(binding.get("network_clock_hz"))
    if hz is None:
        raise EvidenceInvalid(
            "network_binding.duration is recorded without the network "
            "clock that produced it — a wall duration without its clock "
            "cannot authenticate cycles, and the missing clock is not "
            "a pass")
    cycles = seconds * hz
    if cycles.denominator != 1:
        raise EvidenceInvalid(
            f"network_binding duration {seconds} s x clock {hz} Hz is "
            f"not an integer cycle count ({cycles}); BookSim "
            f"completion_time is integral, so this pair cannot be the "
            f"authenticated window — refusing to measure it")
    return (cycles,
            "performance_result.network_binding.duration x "
            "network_binding.network_clock_hz (authenticated "
            "completion_time cycles)")


def _makespan_latency_seconds(performance: dict[str, Any]
                              ) -> tuple[Fraction, str]:
    """(seconds, authority) for the wall-time fallback.

    The bound network window is measured as AUTHENTICATED CYCLES
    (``_authenticated_latency_cycles``); this fallback is reached only
    when no window duration is bound. The verified makespan
    (compute+network superset) is wall time, converted by the DESIGN's
    clock at the call site — conservative: may false-violate, never
    false-pass, and never driven by a caller clock.
    """
    makespan = performance.get("makespan")
    if makespan is None:
        raise InvalidInput(
            "performance result carries neither a bound network window "
            "nor makespan — no latency evidence at all")
    return (_qtime_fraction(makespan, "makespan"),
            "performance_result.makespan (conservative: compute+network)")


def _measured_bandwidth_bps(performance: dict[str, Any]
                            ) -> tuple[Fraction | None, str]:
    """Aggregate bytes/window over BANDWIDTH utilization entries.

    Returns (bps or None, authority). None = no attributable byte
    movement evidenced (never zero-filled downstream).
    """
    utilization = performance.get("utilization") or {}
    if not isinstance(utilization, dict):
        raise InvalidInput("performance result utilization must be an object")
    total_bytes = Fraction(0)
    window_s: Fraction | None = None
    entries = 0
    for name, entry in utilization.items():
        if not isinstance(entry, dict) or entry.get("kind") != "BANDWIDTH":
            continue
        moved = _bytes_fraction(entry.get("bytes_moved"))
        if moved is None:
            continue
        entries += 1
        total_bytes += moved
        if window_s is None and entry.get("window") is not None:
            try:
                window_s = _qtime_fraction(entry["window"],
                                           f"utilization.{name}.window")
            except InvalidInput:
                window_s = None
    if entries == 0:
        return None, "performance_result.utilization (no BANDWIDTH entries)"
    if window_s is None:
        makespan = performance.get("makespan")
        if makespan is None:
            return None, ("performance_result.utilization (no window and "
                          "no makespan)")
        window_s = _qtime_fraction(makespan, "makespan")
    if window_s <= 0:
        return None, "performance_result.utilization (degenerate window)"
    return (total_bytes / window_s,
            "performance_result.utilization BANDWIDTH bytes_moved/window")


def _evaluate_latency(*, requirement: RequirementV3,
                      measured_cycles: Fraction,
                      measured_authority: str,
                      rescaled_fallback: bool,
                      scoped_conservative: bool,
                      intent_classes: tuple[str, ...],
                      ) -> tuple[str, float, float, str, str]:
    """(verdict, required_cycles, measured_cycles, authority, reason)."""
    ceiling = requirement.latency_ceiling_cycles
    assert ceiling is not None
    required_cycles = Fraction(str(ceiling))
    authority = measured_authority
    if rescaled_fallback:
        authority = (f"{measured_authority} @ "
                     f"design.physical.default_clock_freq_mhz "
                     f"(wall-time superset, conservative)")
    scope_note = ""
    if requirement.traffic_class is not None:
        if scoped_conservative:
            scope_note = (
                f" class-scoped to {requirement.traffic_class!r} over a "
                f"multi-class workload {list(intent_classes)}: the "
                f"aggregate window is a sound upper bound only")
        else:
            scope_note = (
                f" class-scoped to {requirement.traffic_class!r} "
                f"(single-class workload: aggregate == class evidence)")
    if measured_cycles <= required_cycles:
        return (VERDICT_SATISFIED, float(ceiling), float(measured_cycles),
                authority,
                f"measured {measured_cycles} cycles <= ceiling {ceiling} "
                f"cycles via {measured_authority}.{scope_note}")
    if scoped_conservative:
        return (VERDICT_UNMEASURABLE, float(ceiling),
                float(measured_cycles), authority,
                f"aggregate {measured_cycles} cycles exceeds ceiling "
                f"{ceiling} cycles, but the excess cannot be attributed "
                f"to {requirement.traffic_class!r} from aggregate window "
                f"evidence — UNMEASURABLE, never a fabricated VIOLATED."
                f"{scope_note}")
    return (VERDICT_VIOLATED, float(ceiling), float(measured_cycles),
            authority,
            f"measured {measured_cycles} cycles > ceiling {ceiling} "
            f"cycles via {measured_authority}.{scope_note}")


def _evaluate_bandwidth(*, requirement: RequirementV3,
                        measured_bps: Fraction | None,
                        measured_authority: str,
                        attributable: bool,
                        ) -> tuple[str, float | None, float | None, str, str]:
    """(verdict, required_gbps, measured_gbps|None, authority, reason)."""
    floor = requirement.bandwidth_floor_gbps
    assert floor is not None
    if not attributable:
        return (VERDICT_UNMEASURABLE, float(floor), None,
                measured_authority,
                f"class-scoped to {requirement.traffic_class!r} over a "
                f"multi-class workload: per-class byte movement is not "
                f"evidenced by the aggregate result — UNMEASURABLE, never "
                f"zero-filled")
    if measured_bps is None:
        return (VERDICT_UNMEASURABLE, float(floor), None,
                measured_authority,
                "no BANDWIDTH byte movement evidenced in the result "
                "(absent metrics are absent, never zero) — UNMEASURABLE")
    measured_gbps = measured_bps / Fraction(10 ** 9)
    if measured_gbps >= Fraction(str(floor)):
        return (VERDICT_SATISFIED, float(floor), float(measured_gbps),
                measured_authority,
                f"measured {float(measured_gbps)} Gbps >= floor {floor} "
                f"Gbps via {measured_authority}")
    return (VERDICT_VIOLATED, float(floor), float(measured_gbps),
            measured_authority,
            f"measured {float(measured_gbps)} Gbps < floor {floor} Gbps "
            f"via {measured_authority}")


class RequirementEvaluator:
    """Evaluates v3 requirements over a verified PerformanceResult."""

    @staticmethod
    def evaluate(request: CompileRequestV3, workload: WorkloadGraph,
                 performance: dict[str, Any]) -> dict[str, Any]:
        """Build the RequirementReport for one (request, workload, result).

        Refuses (typed): non-v3 request, non-graph workload, geometry
        mismatch between request and workload, a workload that is not
        exactly this request's re-derived lowering, a naked performance
        result (the verified boundary is required), a performance result
        whose Wave-D chain binds another workload or another design (or
        that carries no chain binding), unknown class scope, or a result
        missing its identity/makespan spine. Per-metric gaps become
        UNMEASURABLE entries, never exceptions and never passes.
        """
        if not isinstance(request, CompileRequestV3):
            raise InvalidInput(
                f"RequirementEvaluator takes a CompileRequestV3, got "
                f"{type(request).__name__}")
        if not isinstance(workload, WorkloadGraph):
            raise InvalidInput(
                f"RequirementEvaluator takes a WorkloadGraph, got "
                f"{type(workload).__name__}")
        if not isinstance(performance, VerifiedPerformanceResult):
            raise InvalidInput(
                "RequirementEvaluator takes a VerifiedPerformanceResult "
                "produced by verify_performance_result(); a naked result "
                "dict is not authenticated content — a nonempty "
                "resource_id is not authentication")
        try:
            reverify_result(performance,
                            workload=performance.temporal_workload)
        except ResultError as exc:
            raise EvidenceInvalid(
                f"performance result no longer re-verifies: {exc} — "
                f"refusing mutated persisted content") from exc
        req_shape = (request.workload.tp, request.workload.pp,
                     request.workload.ep, request.workload.dp)
        graph_shape = workload.parallelism.sizes()
        if req_shape != graph_shape:
            raise MappingInvalid(
                f"workload geometry TP={graph_shape} does not match the "
                f"request geometry TP={req_shape} — equal world size is "
                f"not semantic equivalence; refusing a transposed "
                f"evaluation")
        result_id = performance.get("resource_id")
        if not isinstance(result_id, str) or not result_id:
            raise InvalidInput(
                "performance result carries no resource_id — cannot bind "
                "report entries to evidence")

        # ── the workload must be exactly this request's lowering ────
        # Provenance is metadata, not authority: it is excluded from
        # workload_id() by canonical law, so any caller can forge a
        # matching design_hash onto a foreign semantic graph. Re-derive
        # what the request must have produced and compare content
        # identity — never ask the workload who its parent is.
        request_design_hash = request.design_hash()
        expected = lower_compile_workload(request)
        workload_id = workload.workload_id()
        if workload_id != expected.graph.workload_id():
            raise MappingInvalid(
                f"workload {workload_id!r} is not the lowering of this "
                f"request ({expected.graph.workload_id()!r}) — refusing "
                f"a semantic transplant; provenance cannot bind a "
                f"foreign graph")
        chain = performance.get("wave_d_chain")
        if not isinstance(chain, Mapping):
            raise EvidenceInvalid(
                "performance result carries no wave_d_chain block — the "
                "measurements cannot be bound to this workload, and a "
                "missing binding is not a pass")
        chain_workload_id = chain.get("workload_graph_id")
        if not isinstance(chain_workload_id, str) or not chain_workload_id:
            raise EvidenceInvalid(
                f"performance wave_d_chain declares no workload_graph_id "
                f"(has {sorted(chain)}); refusing an unbindable result")
        if chain_workload_id != workload_id:
            raise MappingInvalid(
                f"performance wave_d_chain.workload_graph_id "
                f"{chain_workload_id!r} is not this workload's id "
                f"{workload_id!r} — refusing measurements transplanted "
                f"from another workload")
        # The workload graph identity deliberately excludes traffic-class
        # semantics (the lowering sidecar carries them), so two designs
        # differing ONLY in traffic class lower to the same workload_id.
        # The chain must therefore name the design it measured; a chain
        # without that binding is not a pass.
        chain_design_hash = chain.get("design_hash")
        if not isinstance(chain_design_hash, str) or not chain_design_hash:
            raise EvidenceInvalid(
                f"performance wave_d_chain declares no design_hash (has "
                f"{sorted(chain)}); the measurements cannot be bound to "
                f"this design, and a missing binding is not a pass")
        if chain_design_hash != request_design_hash:
            raise MappingInvalid(
                f"performance wave_d_chain.design_hash "
                f"{chain_design_hash!r} does not match request design "
                f"hash {request_design_hash!r} — refusing measurements "
                f"taken for another design (same-geometry graphs with "
                f"different traffic-class semantics share a "
                f"workload_id)")

        intent_classes = derive_v3_traffic_classes(request)
        single_class = len(intent_classes) <= 1
        clock_hz = _design_clock_hz(request)
        design_hash = "sha256:" + request.design_hash()

        entries: list[dict[str, Any]] = []
        for i, req in enumerate(request.requirements):
            if not isinstance(req, RequirementV3):
                raise InvalidInput(
                    f"requirements[{i}] must be a RequirementV3")
            if req.traffic_class is not None and intent_classes \
                    and req.traffic_class not in intent_classes:
                raise InvalidInput(
                    f"requirements[{i}] constrains traffic class "
                    f"{req.traffic_class!r}, which no workload intent "
                    f"declares (registry: {list(intent_classes)}) — "
                    f"refusing a constraint over absent traffic")
            scoped_conservative = (req.traffic_class is not None
                                   and not single_class)
            parts: list[tuple[str, Any, Any, str, str]] = []
            if req.latency_ceiling_cycles is not None:
                measured_cycles, cycles_authority = \
                    _authenticated_latency_cycles(performance)
                if measured_cycles is None:
                    # No bound network window: the verified makespan
                    # (compute+network wall-time superset) converted by
                    # the DESIGN's own clock. Never the caller's clock.
                    measured_s, authority = _makespan_latency_seconds(
                        performance)
                    measured_cycles = measured_s * clock_hz
                    parts.append(_evaluate_latency(
                        requirement=req, measured_cycles=measured_cycles,
                        measured_authority=authority,
                        rescaled_fallback=True,
                        scoped_conservative=scoped_conservative,
                        intent_classes=intent_classes))
                else:
                    parts.append(_evaluate_latency(
                        requirement=req, measured_cycles=measured_cycles,
                        measured_authority=cycles_authority,
                        rescaled_fallback=False,
                        scoped_conservative=scoped_conservative,
                        intent_classes=intent_classes))
            if req.bandwidth_floor_gbps is not None:
                measured_bps, bw_authority = _measured_bandwidth_bps(
                    performance)
                parts.append(_evaluate_bandwidth(
                    requirement=req, measured_bps=measured_bps,
                    measured_authority=bw_authority,
                    attributable=not scoped_conservative))
            if not parts:
                entries.append({
                    "requirement_index": i,
                    "traffic_class": req.traffic_class,
                    "qos_class": req.qos_class.value,
                    "verdict": VERDICT_NOT_APPLICABLE,
                    "binding": req.binding,
                    "required": None,
                    "measured": None,
                    "metric_authority": "none (no bound declared)",
                    "performance_result_id": result_id,
                    "reason": ("requirement declares neither a latency "
                               "ceiling nor a bandwidth floor — nothing "
                               "to measure"),
                })
                continue
            verdicts = [p[0] for p in parts]
            if VERDICT_VIOLATED in verdicts:
                verdict = VERDICT_VIOLATED
            elif VERDICT_UNMEASURABLE in verdicts:
                verdict = VERDICT_UNMEASURABLE
            else:
                verdict = VERDICT_SATISFIED
            if len(parts) == 1:
                v, required, measured, authority, reason = parts[0]
                del v
            else:
                required = "; ".join(
                    f"{'latency<=' if k == 0 else 'bw>='}{p[1]}"
                    f"{'c' if k == 0 else 'gbps'}" for k, p in enumerate(parts))
                measured = "; ".join(
                    f"{'latency=' if k == 0 else 'bw='}"
                    f"{p[2] if p[2] is not None else 'UNMEASURABLE'}"
                    f"{'c' if k == 0 else 'gbps'}" for k, p in enumerate(parts))
                authority = " | ".join(p[3] for p in parts)
                reason = " | ".join(f"[{p[0]}] {p[4]}" for p in parts)
            entries.append({
                "requirement_index": i,
                "traffic_class": req.traffic_class,
                "qos_class": req.qos_class.value,
                "verdict": verdict,
                "binding": req.binding,
                "required": required,
                "measured": measured,
                "metric_authority": authority,
                "performance_result_id": result_id,
                "reason": reason,
            })
        return {
            "contract_version": REQUIREMENT_REPORT_CONTRACT_VERSION,
            "design_hash": design_hash,
            "performance_result_id": result_id,
            "entries": entries,
        }


def report_identity(report: dict[str, Any]) -> str:
    """Bare domain-separated digest of a RequirementReport.

    The report contract carries no ID field; this is its
    identity-equivalent, used to bind requirement provenance into
    optimization records (CandidateRecord.requirement_report_id).
    """
    return content_id(REQUIREMENT_REPORT_DOMAIN, report)


def report_passes(report: dict[str, Any]) -> bool:
    """Consumer rule: binding + UNMEASURABLE never passes.

    True iff every BINDING entry is SATISFIED. Non-binding entries are
    advisory (a non-binding VIOLATED warns, never fails). NOT_APPLICABLE
    binding entries... declare no bound: vacuously they constrain
    nothing, but a binding entry that constrains nothing is a spec
    smell — it does NOT fail the gate (fail-closed applies to evidence,
    not to vacuous specs).
    """
    for entry in report.get("entries", []):
        if entry.get("binding") and entry.get("verdict") != VERDICT_SATISFIED:
            return False
    return True


__all__ = [
    "REQUIREMENT_REPORT_CONTRACT_VERSION",
    "REQUIREMENT_REPORT_DOMAIN",
    "RequirementEvaluator",
    "VERDICT_NOT_APPLICABLE",
    "VERDICT_SATISFIED",
    "VERDICT_UNMEASURABLE",
    "VERDICT_VIOLATED",
    "report_identity",
    "report_passes",
]
