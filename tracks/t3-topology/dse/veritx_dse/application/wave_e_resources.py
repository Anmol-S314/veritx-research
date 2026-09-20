"""veritx_dse.application.wave_e_resources — persisted Wave-E resources.

Wave-E temporal workloads are scientific resources under the SAME
contract as Wave-D ones (§56/§149):

    requested filename ID == embedded resource_id == recomputed ID

plus verified Wave-D parents where cited, closed field sets, and
semantic revalidation. Raw ``store.get()`` is inspection-only.

The store carries:

    waveeworkload   WaveETemporalWorkload (model content + events +
                    requests + declared Wave-D operation ids)

A Wave-E performance result is NOT a separate loose resource: it rides
inside the EvaluationResult ``wave_e`` block, verified against the plan
binding and the authenticated BookSim evidence (§71).
"""
from __future__ import annotations

from typing import Any

from veritx_dse.wavee.result import reverify_result
from veritx_dse.wavee.workload import WaveETemporalWorkload

from .errors import ControlPlaneError, ErrorCode
from .resources import RESOURCE_SCHEMA_VERSION, check_envelope

WAVE_E_RESOURCE_KINDS = ("waveeworkload",)

# Plan-level Wave-E binding: the minimal identity-bearing parents a
# Wave-E evaluation must pin BEFORE any execution (§69).
PLAN_WAVE_E_KEYS = (
    "temporal_workload_id",
    "performance_model_id",
)

# Result-level Wave-E block: provenance chain + the derived timing
# claims a consumer may rely on. Everything here is re-derivable.
RESULT_WAVE_E_KEYS = PLAN_WAVE_E_KEYS + (
    "wave_d_chain",          # the full Wave-D chain (§71 provenance)
    "network_binding",       # §42 evidence binding (None if no network)
    "makespan",              # {numerator, denominator} exact seconds
    "network_window",        # {numerator, denominator} or None
    "metrics_warning",       # fidelity classification (§64)
)


# ── records (write side) ─────────────────────────────────────────────────

def _record(kind: str, resource_id: str,
            artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_type": kind,
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "resource_id": resource_id,
        "artifact": artifact,
    }


def wave_e_workload_record(art: WaveETemporalWorkload) -> dict[str, Any]:
    return _record("waveeworkload", art.temporal_workload_id(), art.to_dict())


# ── load side (verified) ─────────────────────────────────────────────────

def load_verified_wave_e_workload(store: Any, workload_id: str
                                  ) -> WaveETemporalWorkload:
    """Load and re-verify a persisted WaveETemporalWorkload.

    Envelope check, filename/embedded/recomputed ID agreement, semantic
    revalidation (constructor laws run again), and identity stability.
    """
    if not isinstance(workload_id, str) or not workload_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"invalid waveeworkload link {workload_id!r}",
            operation="verify_resource")
    try:
        record = store.get("waveeworkload", workload_id)
        check_envelope(record, "waveeworkload")
    except ControlPlaneError as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"persisted waveeworkload {workload_id} fails envelope: "
            f"{exc.message}",
            operation="verify_resource", resource_id=workload_id) from exc
    if record.get("resource_id") != workload_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"waveeworkload filename/id mismatch: {workload_id} vs "
            f"{record.get('resource_id')}",
            operation="verify_resource", resource_id=workload_id)
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"waveeworkload {workload_id} artifact is not a mapping",
            operation="verify_resource", resource_id=workload_id)
    try:
        workload = WaveETemporalWorkload.from_dict(artifact)
    except Exception as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"waveeworkload {workload_id} does not re-validate: {exc}",
            operation="verify_resource",
            resource_id=workload_id) from exc
    recomputed = workload.temporal_workload_id()
    if recomputed != workload_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"waveeworkload {workload_id} recomputes to {recomputed}: "
            f"content does not match its identity",
            operation="verify_resource", resource_id=workload_id)
    return workload


def wave_e_result_block(*, workload: WaveETemporalWorkload,
                        performance_result: dict[str, Any],
                        wave_d_chain: dict[str, Any] | None,
                        metrics_warning: str) -> dict[str, Any]:
    """The result-level ``wave_e`` block (§66/§71).

    ``performance_result`` is the verified document produced by
    ``build_performance_result``; only the identity-bearing summary
    fields are retained (the full schedule stays in the temporal
    workload resource and is re-derived on load, §74).
    """
    network_binding = performance_result.get("network_binding")
    block = {
        "temporal_workload_id": workload.temporal_workload_id(),
        "performance_model_id":
            workload.performance_model.performance_model_id(),
        "wave_d_chain": (dict(wave_d_chain) if wave_d_chain else None),
        "network_binding": (dict(network_binding)
                            if network_binding is not None else None),
        "makespan": dict(performance_result["makespan"]),
        "network_window": (
            dict(network_binding["duration"])
            if isinstance(network_binding, dict)
            and network_binding.get("duration") is not None else None),
        "metrics_warning": metrics_warning,
    }
    if set(block) != set(RESULT_WAVE_E_KEYS):  # pragma: no cover - guard
        raise ControlPlaneError(
            ErrorCode.INTERNAL_ERROR,
            "wave_e result block does not match RESULT_WAVE_E_KEYS: "
            f"{sorted(block)} vs {sorted(RESULT_WAVE_E_KEYS)}",
            operation="verify_resource")
    return block


def wave_e_metrics_warning(model: Any) -> str:
    """The ONE fidelity classification for a Wave-E result (§64).

    A pure function of the verified performance model, so the verifier
    re-derives it instead of trusting persisted text: a forged
    "VALIDATED against H100" claim cannot survive a load.
    """
    return (f"compute={model.compute_source} "
            f"network={model.network_timing_model} "
            f"all=UNCALIBRATED "
            f"(analytical/explicit models; no hardware dataset in repo)")


def verify_wave_e_result_block(
        store: Any, wave_e: dict[str, Any],
        plan_wave_e: dict[str, Any] | None,
        plan_wave_d: dict[str, Any] | None,
        result_wave_d: dict[str, Any] | None,
        evidence: dict[str, Any],
        evidence_sha256: str | None,
        backend_config_hash: str | None,
        backend_input_hash: str | None,
        result_id: str) -> None:
    """Re-derive a persisted ``wave_e`` block or refuse (§74/§133).

    The verified plan is the authority for the performance semantics and
    for the Wave-D chain; the authenticated evidence is the authority
    for network timing. Nothing in the block is trusted as copied text:
    the schedule is re-run and every summary compared. Checks, in order:

      1. schema closure against RESULT_WAVE_E_KEYS,
      2. the block claims the PLAN's temporal-workload/model binding,
      3. the temporal workload resource re-verifies from the store,
      4. the Wave-D chain IS the plan's chain (transplant refusal),
      5. the network binding cites THIS run's authenticated evidence,
         backend hashes, Wave-D chain, clock and window kind,
      6. the schedule is re-run from the verified workload + binding and
         ``makespan``/``network_window`` must match,
      7. the fidelity warning is re-derived from the verified model.
    """
    if set(wave_e) != set(RESULT_WAVE_E_KEYS):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} wave_e block has the wrong field set: "
            f"unknown {sorted(set(wave_e) - set(RESULT_WAVE_E_KEYS))}, "
            f"missing {sorted(set(RESULT_WAVE_E_KEYS) - set(wave_e))}",
            operation="verify_result", resource_id=result_id)
    if plan_wave_e is None:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} carries a wave_e block but its plan "
            f"binds none: refusing orphaned performance semantics",
            operation="verify_result", resource_id=result_id)
    for key in PLAN_WAVE_E_KEYS:
        if wave_e.get(key) != plan_wave_e.get(key):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} wave_e.{key} "
                f"({wave_e.get(key)!r}) does not match the plan "
                f"binding ({plan_wave_e.get(key)!r}): refusing "
                f"transplanted performance semantics",
                operation="verify_result", resource_id=result_id)
    # 3. The temporal workload must re-verify from the store.
    workload = load_verified_wave_e_workload(
        store, wave_e["temporal_workload_id"])
    model = workload.performance_model
    if model.performance_model_id() != wave_e["performance_model_id"]:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} performance_model_id does not match "
            f"the verified workload's model",
            operation="verify_result", resource_id=result_id)
    # 4. Wave-D provenance (§71): timing never replaces communication,
    #    and the timing block may not cite a DIFFERENT valid chain.
    from .waved_resources import PLAN_CHAIN_KEYS
    if plan_wave_d is None or result_wave_d is None:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} carries Wave-E timing without a Wave-D "
            f"chain: timing cannot stand without its communication "
            f"parents (§71)",
            operation="verify_result", resource_id=result_id)
    chain = wave_e.get("wave_d_chain")
    if chain is None:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} wave_e.wave_d_chain is missing",
            operation="verify_result", resource_id=result_id)
    if set(chain) != set(PLAN_CHAIN_KEYS):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} wave_e.wave_d_chain has the wrong "
            f"field set for a Wave-D chain block",
            operation="verify_result", resource_id=result_id)
    for key in PLAN_CHAIN_KEYS:
        if chain.get(key) != plan_wave_d.get(key):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} wave_e.wave_d_chain.{key} "
                f"({chain.get(key)!r}) is not the plan's chain "
                f"({plan_wave_d.get(key)!r}): refusing transplanted "
                f"communication provenance",
                operation="verify_result", resource_id=result_id)
    # 5. Network binding: THIS run's evidence, chain, clock, kind.
    from veritx_dse.wavee.network import (
        WINDOW_KIND_BARRIER, NetworkWindowBinding, stats_sha256,
    )
    binding = wave_e.get("network_binding")
    network_events = sorted(
        e.event_id for e in workload.events
        if e.kind == "NETWORK_OPERATION_REF")
    if binding is None:
        if network_events:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} has {len(network_events)} network "
                f"events but no evidence-bound window: refusing to "
                f"treat the network as free (§36/§42)",
                operation="verify_result", resource_id=result_id)
        if wave_e.get("network_window") is not None:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} binds a network window without a "
                f"binding: internal contradiction",
                operation="verify_result", resource_id=result_id)
        rebuilt = None
    else:
        if not isinstance(binding, dict):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} network_binding is not an object",
                operation="verify_result", resource_id=result_id)
        try:
            rebuilt = NetworkWindowBinding.from_dict(binding)
        except Exception as exc:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} network_binding does not parse: "
                f"{exc}",
                operation="verify_result", resource_id=result_id) from exc
        if not evidence_sha256:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} has no authenticated evidence "
                f"digest to bind network timing against (§42)",
                operation="verify_result", resource_id=result_id)
        if rebuilt.evidence_sha256 != evidence_sha256:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} network_binding.evidence_sha256 "
                f"({rebuilt.evidence_sha256}) is not this run's "
                f"authenticated evidence ({evidence_sha256}): refusing "
                f"transplanted network timing (§42)",
                operation="verify_result", resource_id=result_id)
        stats = evidence.get("stats") or {}
        if rebuilt.stats_sha256 != stats_sha256(stats):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} network_binding.stats_sha256 does "
                f"not match this run's authenticated stats",
                operation="verify_result", resource_id=result_id)
        if rebuilt.window_kind != WINDOW_KIND_BARRIER:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} network_binding.window_kind "
                f"({rebuilt.window_kind!r}) is not the supported "
                f"{WINDOW_KIND_BARRIER}",
                operation="verify_result", resource_id=result_id)
        for key, expected in (
                ("operation_graph_id", plan_wave_d["operation_graph_id"]),
                ("physical_traffic_id", plan_wave_d["physical_traffic_id"]),
                ("backend_config_hash", backend_config_hash),
                ("backend_input_hash", backend_input_hash)):
            if getattr(rebuilt, key) != expected:
                raise ControlPlaneError(
                    ErrorCode.EVIDENCE_INVALID,
                    f"result {result_id} network_binding.{key} "
                    f"({getattr(rebuilt, key)!r}) does not match its "
                    f"authority ({expected!r})",
                    operation="verify_result", resource_id=result_id)
        expected_hz = model.clock_hz(model.network_clock)
        if rebuilt.network_clock_hz is None or \
                rebuilt.network_clock_hz != expected_hz:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} network_binding.network_clock_hz "
                f"({rebuilt.network_clock_hz!r}) is not the model's "
                f"declared network clock ({expected_hz!r})",
                operation="verify_result", resource_id=result_id)
        if rebuilt.duration is None:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} binds a clock but carries no "
                f"window duration: cross-domain timing without time",
                operation="verify_result", resource_id=result_id)
        if wave_e.get("network_window") != rebuilt.duration.to_dict():
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"result {result_id} wave_e.network_window "
                f"({wave_e.get('network_window')!r}) is not the "
                f"binding's duration ({rebuilt.duration.to_dict()!r})",
                operation="verify_result", resource_id=result_id)
    # 6. Re-run the schedule from verified inputs and compare summaries.
    from veritx_dse.wavee.result import WaveEEventGraph
    from veritx_dse.wavee.scheduler import schedule_workload
    egraph = WaveEEventGraph(workload=workload, network_binding=rebuilt,
                             wave_d_chain=dict(plan_wave_d))
    try:
        schedule = schedule_workload(
            workload, network_durations=egraph.network_durations())
    except Exception as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} wave_e schedule cannot be re-derived "
            f"from the verified workload and binding: {exc}",
            operation="verify_result", resource_id=result_id) from exc
    recomputed_makespan = schedule.makespan().to_dict()
    if wave_e.get("makespan") != recomputed_makespan:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} wave_e.makespan "
            f"({wave_e.get('makespan')!r}) disagrees with the re-derived "
            f"schedule ({recomputed_makespan!r}): refusing a summary that "
            f"does not follow from its parents (§74/§133)",
            operation="verify_result", resource_id=result_id)
    # 7. Fidelity classification is a function of the verified model.
    expected_warning = wave_e_metrics_warning(model)
    if wave_e.get("metrics_warning") != expected_warning:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} wave_e.metrics_warning is not the "
            f"model's declared fidelity classification: refusing a "
            f"forged accuracy claim (§64)",
            operation="verify_result", resource_id=result_id)
