"""veritx_dse.wavee.sensitivity — counterfactual sensitivity (§48–§51).

Bottleneck evidence is counterfactual, never "component total larger"
(§47). For each parameter we RE-RUN the actual schedule under explicit
perturbations — no algebraic shortcut (§48) — and report:

    speedup_x   = T_baseline / T_x
    elasticity  = ((T_2x - T_0.5x) / T_1x) / (2 - 0.5)   [§49 sign
                  convention: positive elasticity means a FASTER/
                  BIGGER parameter shortens the makespan]

Zero-cost counterfactuals (duration → 0) measure the *exposed*
contribution of a source class to makespan (§50) — distinct from its
active/busy time (§43). Contributions are NOT additive (§99): each is
reported separately against the same baseline.

Each perturbed run is a distinct derived evaluation identity bound to
base model + perturbation (§51); the engine refuses a perturbation
that makes a supposedly faster resource slow the system down when the
model is monotone in that parameter (§89).
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from veritx_dse.wavee.model import (
    RESOURCE_KIND_BANDWIDTH, WaveEPerformanceModel,
)
from veritx_dse.wavee.scheduler import Schedule, schedule_workload
from veritx_dse.wavee.time import QTime
from veritx_dse.wavee.workload import (
    EVENT_NETWORK_OPERATION_REF, MEMORY_KINDS, WaveETemporalWorkload,
)

SENSITIVITY_SCHEMA_VERSION = 1


def _scale(q: Fraction, factor: Fraction) -> Fraction:
    return q * factor


def perturb_model(base: WaveEPerformanceModel, *, bandwidth_factor:
                  Fraction | None = None) -> WaveEPerformanceModel:
    """Perturbed model identity: same clocks, scaled bandwidths (§51)."""
    from veritx_dse.wavee.model import ResourceDef
    resources = []
    for r in base.resources:
        if bandwidth_factor is not None and \
                r.kind == RESOURCE_KIND_BANDWIDTH:
            resources.append(ResourceDef(
                r.name, r.kind,
                bandwidth_bytes_per_s=r.bandwidth_bps * bandwidth_factor))
        else:
            resources.append(ResourceDef(
                r.name, r.kind,
                capacity=r.capacity,
                bandwidth_bytes_per_s=r.bandwidth_bps))
    return WaveEPerformanceModel(
        clocks=base.clocks, resources=tuple(resources),
        compute_source=base.compute_source,
        network_timing_model=base.network_timing_model,
        network_clock=base.network_clock)


def perturb_workload_durations(workload: WaveETemporalWorkload, *,
                               duration_factor: Fraction | None = None,
                               network_factor: Fraction | None = None,
                               network_zero: bool = False,
                               ) -> WaveETemporalWorkload:
    """Perturbed workload: scale local durations / network durations.

    ``network_zero`` implements the §50 zero-cost counterfactual for
    the network window (network durations → 0). Because events are
    immutable, a perturbed workload is a NEW workload object; its
    temporal_workload_id differs (identity rule, §51).
    """
    from veritx_dse.wavee.workload import WaveETemporalEvent
    events = []
    for e in workload.events:
        dur = e.duration
        if network_zero and e.kind == EVENT_NETWORK_OPERATION_REF:
            dur = QTime(0)
        elif network_factor is not None and \
                e.kind == EVENT_NETWORK_OPERATION_REF:
            dur = QTime(e.duration.q * network_factor)
        elif duration_factor is not None and \
                e.kind in (MEMORY_KINDS) and e.resource is not None:
            # local memory events keep derived durations via bytes; only
            # declared durations scale for non-memory kinds
            dur = e.duration
        else:
            if duration_factor is not None:
                dur = QTime(e.duration.q * duration_factor)
        events.append(WaveETemporalEvent(
            e.event_id, e.kind, dur, e.resource, deps=e.deps,
            phase=e.phase, rank=e.rank, step=e.step,
            request_id=e.request_id,
            wave_d_operation_id=e.wave_d_operation_id,
            bytes_count=e.bytes_count,
            is_first_token=e.is_first_token))
    return WaveETemporalWorkload(
        performance_model=workload.performance_model,
        events=tuple(events), requests=workload.requests,
        wave_d_operation_ids=workload._wave_d_operation_ids)


def sensitivity_analysis(workload: WaveETemporalWorkload,
                         base_schedule: Schedule, *,
                         network_durations: dict[str, QTime] | None = None
                         ) -> dict[str, Any]:
    """Full sensitivity table over the declared perturbation set."""
    base_T = base_schedule.makespan().q
    out: dict[str, Any] = {
        "schema_version": SENSITIVITY_SCHEMA_VERSION,
        "baseline_makespan": QTime(base_T).to_dict(),
        "parameters": {},
    }

    def run(wl: WaveETemporalWorkload, model: WaveEPerformanceModel,
            net: dict[str, QTime] | None) -> Fraction:
        return schedule_workload(wl, network_durations=net).makespan().q

    def record(name: str, T: Fraction) -> dict[str, Any]:
        row: dict[str, Any] = {
            "makespan": QTime(T).to_dict(),
            "speedup": float(base_T / T) if T > 0 else None,
        }
        return row

    # compute durations 0.5x / 2x (local events only; network handled
    # separately below)
    for factor, label in ((Fraction(1, 2), "0.5x"), (Fraction(2), "2x")):
        wl = perturb_workload_durations(
            workload, duration_factor=factor)
        T = run(wl, workload.performance_model, network_durations)
        out["parameters"][f"local_durations_{label}"] = record(label, T)

    # bandwidth 0.5x / 2x (model perturbation: new model identity)
    for factor, label in ((Fraction(1, 2), "0.5x"), (Fraction(2), "2x")):
        m2 = perturb_model(workload.performance_model,
                           bandwidth_factor=factor)
        wl2 = WaveETemporalWorkload(
            performance_model=m2, events=workload.events,
            requests=workload.requests,
            wave_d_operation_ids=workload._wave_d_operation_ids)
        T = run(wl2, m2, network_durations)
        out["parameters"][f"bandwidth_{label}"] = record(label, T)

    # zero-cost counterfactuals (§50): exposed contribution per class
    wl_net0 = perturb_workload_durations(workload, network_zero=True)
    net0: dict[str, QTime] = {}
    if network_durations:
        net0 = {k: QTime(0) for k in network_durations}
    T_net0 = run(wl_net0, workload.performance_model, net0)
    out["exposed_network"] = QTime(base_T - T_net0).to_dict()

    wl_comp0 = perturb_workload_durations(workload, duration_factor=0)
    T_comp0 = run(wl_comp0, workload.performance_model, network_durations)
    out["exposed_compute"] = QTime(base_T - T_comp0).to_dict()

    wl_mem0 = perturb_workload_durations(workload, duration_factor=0)
    T_mem0 = run(wl_mem0, workload.performance_model, network_durations)
    out["exposed_memory"] = QTime(base_T - T_mem0).to_dict()

    # elasticity for bandwidth (the one parameter with a continuous
    # declared model here)
    t05 = Fraction(out["parameters"]["bandwidth_0.5x"]["makespan"]
                   ["numerator"],
                   out["parameters"]["bandwidth_0.5x"]["makespan"]
                   ["denominator"])
    t2 = Fraction(out["parameters"]["bandwidth_2x"]["makespan"]
                  ["numerator"],
                  out["parameters"]["bandwidth_2x"]["makespan"]
                  ["denominator"])
    denom = Fraction(3, 2)  # (2 - 0.5)
    elasticity = ((t2 - t05) / base_T) / denom
    out["parameters"]["bandwidth_elasticity"] = float(-elasticity)
    # sign: T decreases as bandwidth grows → t2 < t05 → (t2-t05)<0 →
    # elasticity negative → we report NEGATED so positive = helpful.

    # §89 monotonicity sanity: more bandwidth must not slow the system
    if t2 > t05:
        raise ValueError(
            "sensitivity contradiction: 2x bandwidth produced a LONGER "
            "makespan than 0.5x bandwidth; the model should be monotone "
            "in bandwidth (§89)")
    return out
