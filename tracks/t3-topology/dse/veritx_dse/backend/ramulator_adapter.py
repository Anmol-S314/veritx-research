"""The certified Ramulator2 HBM3 backend adapter.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from veritx_dse.application.evaluation_context import (
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import (
    BackendAdapter, BackendAssessment, BackendCapability, BackendReadiness,
    ModelFidelity, PreparedExecution, SupportLevel,
)

BACKEND_ID = "RAMULATOR2_HBM3_V1"

RAMULATOR_MODEL_FIDELITY = ModelFidelity.MEMORY_CYCLE_SIMULATION

QUALIFICATION_PROFILE = "CERTIFIED_RAMULATOR_HBM3_V1"
MULTI_HBM_DISPATCH_PROFILE = "DIAGNOSTIC_MULTI_HBM_CALLBACK_DISPATCH_V1"

class RamulatorSemanticRefusal(ValueError):
    """The workload has no representation on the certified Ramulator path.

Rationale: docs/decisions/modules/backend.md
    """

class RamulatorBackendAbsent(Exception):
    """The compiled Ramulator extension is absent: preparation succeeded
    but there is no backend to execute on. Maps to UNAVAILABLE, never to
    a semantic verdict and never to a fabrication."""

@dataclass(frozen=True)
class MemoryGeometryProfile:
    profile_id: str
    channels: int
    envelope: str

MEMORY_GEOMETRY_PROFILES: dict[str, MemoryGeometryProfile] = {
    "CERTIFIED_RAMULATOR_HBM3_V1": MemoryGeometryProfile(
        profile_id="CERTIFIED_RAMULATOR_HBM3_V1", channels=1,
        envelope="single HBM3 channel (51.2 GB/s peak at 6400 MT/s x 8 B)"),
    "CERTIFIED_RAMULATOR_HBM3_8CH_V1": MemoryGeometryProfile(
        profile_id="CERTIFIED_RAMULATOR_HBM3_8CH_V1", channels=8,
        envelope="8 independent HBM3 channels (409.6 GB/s peak)"),
}

DEFAULT_MEMORY_PROFILE = "CERTIFIED_RAMULATOR_HBM3_V1"
# Ramulator's HBM3_16Gb_8hi controller reports 32-byte native transactions.
# The older trace lowerer retains its independent 64-byte semantic granule.
NATIVE_HBM3_TRANSACTION_BYTES = 32

def memory_geometry_profile(
        profile_id: str = DEFAULT_MEMORY_PROFILE) -> MemoryGeometryProfile:
    try:
        return MEMORY_GEOMETRY_PROFILES[profile_id]
    except KeyError:
        raise RamulatorSemanticRefusal(
            f"unknown memory geometry profile {profile_id!r}; audited "
            f"profiles: {sorted(MEMORY_GEOMETRY_PROFILES)}") from None

def memory_assumption(profile_id: str = DEFAULT_MEMORY_PROFILE) -> str:
    p = memory_geometry_profile(profile_id)
    return (f"DRAM timing assumes the certified {p.profile_id} profile: "
            f"{p.envelope}. It is not a user-authored memory-system "
            "design.")

def memory_limitations(profile_id: str = DEFAULT_MEMORY_PROFILE,
                       ) -> tuple[str, ...]:
    p = memory_geometry_profile(profile_id)
    channels = ("one native channel/controller per logical HBM pool; "
                "explicit multi-pool placements use the shared callback "
                "dispatcher"
                if p.channels == 1 else
                f"{p.channels} native channels per logical HBM pool "
                "(channels are not distinct pool placements)")
    return (memory_assumption(profile_id),
            "memory cycle simulation over a recorded request stream: "
            "row/queue timing is simulated, request generation is assumed "
            "(see the memory artifact assumptions)",
            channels)

MODEL_ASSUMPTION = memory_assumption(DEFAULT_MEMORY_PROFILE)
RAMULATOR_LIMITATIONS = memory_limitations(DEFAULT_MEMORY_PROFILE)

def certified_memory_design() -> Any:
    """The audited single-pool memory design (device 0), for contexts
    that carry no declared hardware — test stand-ins and legacy callers.

    Product code must prefer memory_design_for_request: resolving demand
    against a phantom device the design never declared is exactly the
    silent wrongness this module refuses everywhere else."""
    from veritx_dse.workload.memory_lowering import MemorySystemDesign
    return MemorySystemDesign(hbm_devices=(0,))


def memory_design_for_request(request: Any) -> Any:
    """HBM devices from the design's declared controllers — never phantom.

    Device ids are positional over the declared HBM_CONTROLLER agents, so
    demand resolves against hardware the design actually contains. Zero
    declared controllers with memory demand refuses in the constructor
    ("nowhere to live"); more than one refuses without an explicit
    tensor-sharding policy (placement across pools cannot be invented).
    A request that carries no agents block refuses: ownership against
    undeclared hardware is unestablishable."""
    from veritx_dse.model.compile_model import AgentKind
    from veritx_dse.workload.memory_lowering import MemorySystemDesign
    agents = getattr(request, "agents", None)
    if not isinstance(agents, (list, tuple)) or not agents:
        from veritx_dse.workload.memory_lowering import LoweringError
        raise LoweringError(
            "memory demand resolves against declared HBM controllers, "
            "but the request carries no agents block — HBM ownership "
            "is unestablishable")
    hbm = 0
    for agent in agents:
        kind = getattr(agent, "kind", None)
        name = getattr(kind, "value", kind)
        if name in ("hbm_controller", AgentKind.HBM_CONTROLLER):
            hbm += int(getattr(agent, "count", 0) or 0)
    return MemorySystemDesign(hbm_devices=tuple(range(hbm)))

def certified_mapping_policy(profile_id: str = DEFAULT_MEMORY_PROFILE) -> Any:
    """The audited address-mapping policy (a model assumption).

    Logical address SEMANTICS do not change with a memory profile, so this
    stays the frozen v1 policy. The addr-vec ORDER — the thing that decides
    whether channels are used in parallel — is carried by the lowering's
    ``mapping_algorithm`` and recorded in the manifest, not here: a policy
    name is a semantics claim, and the interleave makes no new one.
    """
    from veritx_dse.core.memory import AddressMappingPolicy
    return AddressMappingPolicy(
        name="contiguous_aligned_v1", version=1, alignment_bytes=64,
        parameters={})

def certified_geometry(profile_id: str = DEFAULT_MEMORY_PROFILE) -> Any:
    """The audited HBM3 geometry transcription for a profile."""
    from veritx_dse.workload.memory_lowering import (
        hbm3_16gb_8hi_geometry,
    )
    return hbm3_16gb_8hi_geometry(
        num_channels=memory_geometry_profile(profile_id).channels)

def ramulator_evidence_id(evidence: Any) -> str:
    """Content identity of native Ramulator evidence.

Rationale: docs/decisions/modules/backend.md
    """
    metrics = {
        key: value for key, value in
        (getattr(evidence, "metrics", None) or {}).items()
        if key != "wall_time_s"
    }
    dispatch_raw = (getattr(evidence, "raw", None) or {})
    is_dispatch = "dispatcher" in dispatch_raw
    identity = {
        "type": "veritx/ramulator-memory-evidence",
        "version": 2 if is_dispatch else 1,
        "status": evidence.status,
        "producer": evidence.producer,
        "fidelity": evidence.fidelity,
        "memory_artifact_hash": evidence.memory_artifact_hash,
        "lowering_manifest_hash": evidence.lowering_manifest_hash,
        "backend_input_hash": evidence.backend_input_hash,
        "backend_config_hash": evidence.backend_config_hash,
        "metrics": metrics,
        "assumptions": list(evidence.assumptions),
        "semantic_losses": list(evidence.semantic_losses),
        "failure_reason": evidence.failure_reason,
    }
    if is_dispatch:
        identity.update({
            "dispatch_controller_stats": dispatch_raw.get("controller_stats"),
            "dispatch_events": dispatch_raw.get("events"),
            "dispatch_backpressure_retries": dispatch_raw.get(
                "backpressure_retries_by_transaction"),
            "dispatch_ticks": dispatch_raw.get("memory_ticks"),
            "dispatch_generated_transactions": dispatch_raw.get(
                "generated_transactions"),
        })
        # Omit this key for archived V1 evidence: the original identity
        # preceded tick-bound recording and did not bind a null value.
        if "dispatcher_bounds" in dispatch_raw:
            identity["dispatch_bounds"] = dispatch_raw["dispatcher_bounds"]
    payload = json.dumps(identity, sort_keys=True,
                         separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()

@dataclass(frozen=True)
class RamulatorPreparation:
    """What prepare() hands to execute() — the resolved memory semantics
    plus the certified profile they were resolved against.

Rationale: docs/decisions/modules/backend.md
    """

    artifact: Any
    geometry: Any
    memory_artifact_hash: str
    access_stream_hash: str
    backend_config_hash: str
    mapping: str = "sequential_bankstriped_v1"
    device_ids: tuple[int, ...] = (0,)

class RamulatorAdapter:
    """Orchestrates workload-graph → memory artifact → trace → evidence.

Rationale: docs/decisions/modules/backend.md
    """

    def __init__(
        self,
        *,
        vendor_dir: str | Path | None = None,
        python_exe: str | None = None,
        geometry_profile: str = DEFAULT_MEMORY_PROFILE,
    ) -> None:
        self._vendor_dir = Path(vendor_dir) \
            if vendor_dir is not None else None
        self._python_exe = python_exe
        self._geometry_profile = memory_geometry_profile(geometry_profile)
        self._limitations = memory_limitations(self._geometry_profile.profile_id)
        self._capabilities: tuple[BackendCapability, ...] = (
            BackendCapability(
                question=EvaluationQuestion.DRAM_TIMING,
                support=SupportLevel.SUPPORTED,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                limitations=self._limitations),
        )

    @property
    def backend_id(self) -> str:
        return BACKEND_ID

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return self._capabilities

    def _discover(self) -> Any:
        """Locate the backend through the canonical discovery authority."""
        from veritx_dse.simulation.ramulator import discover
        return discover(
            python_exe=self._python_exe, vendor_dir=self._vendor_dir)

    def _required_parents(self) -> tuple[str, ...]:
        return ("design", "resolved_fabric", "workload",
                "memory_artifact", "access_stream")

    def assess(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        if question is not EvaluationQuestion.DRAM_TIMING:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason="certified Ramulator answers DRAM_TIMING only",
                required_parents=self._required_parents(),
                limitations=self._limitations)
        try:
            native = self._prepare_native(context, question)
        except _SEMANTIC_REFUSALS as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"{type(exc).__name__}: {exc}",
                required_parents=self._required_parents(),
                limitations=self._limitations)
        from veritx_dse.simulation.ramulator import RamulatorError
        try:
            backend = self._discover()
        except RamulatorError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"Ramulator backend undiscoverable: {exc}",
                required_parents=self._required_parents(),
                limitations=self._limitations)
        if not backend.ready:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason="Ramulator backend not built: no compiled "
                f"extension at {backend.ext_path}; build with "
                f"interpreter {backend.python_exe}: "
                "cd third_party/ramulator2 && ./build.sh",
                required_parents=self._required_parents(),
                limitations=self._limitations)
        try:
            backend.producer()
        except RamulatorError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"Ramulator producer facts unestablished: {exc}",
                required_parents=self._required_parents(),
                limitations=self._limitations)
        multi_pool = len(native.device_ids) > 1
        limitations = self._limitations + ((
            "diagnostic multi-pool execution is a memory-only callback "
            "dispatch model, not a qualified physical HBM package or "
            "release profile",
        ) if multi_pool else ())
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=RAMULATOR_MODEL_FIDELITY,
            qualification_profile=(
                f"{MULTI_HBM_DISPATCH_PROFILE}/{self._geometry_profile.profile_id}"
                if multi_pool else self._geometry_profile.profile_id),
            reason=None,
            required_parents=self._required_parents(),
            limitations=limitations)

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        **kwargs: object,
    ) -> PreparedExecution:
        """Semantic resolution only — no runtime binary required.

        Returns the generic ``PreparedExecution`` seam; the native
        ``RamulatorPreparation`` (real artifact retained) rides in
        ``native_prepared`` so ``execute()`` lowers the real trace
        itself.
        """
        native = self._prepare_native(context, question)
        return PreparedExecution(
            backend_id=self.backend_id,
            projection_identity=native.memory_artifact_hash,
            qualification_identity=native.backend_config_hash,
            backend_config=None, backend_input=None, producer=None,
            native_prepared=native)

    def _prepare_native(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> RamulatorPreparation:
        if question is not EvaluationQuestion.DRAM_TIMING:
            raise RamulatorSemanticRefusal(
                "certified Ramulator answers DRAM_TIMING only")
        from veritx_dse.workload.memory_lowering import (
            backend_config_payload, resolve_memory_graph,
        )
        try:
            design = memory_design_for_request(
                getattr(context, "request", None))
            resolved = resolve_memory_graph(
                context.workload, design,
                policy=certified_mapping_policy())
        except (LoweringError, MemoryArtifactError, InvalidInput) as exc:
            raise RamulatorSemanticRefusal(
                f"no resolvable memory demand: {type(exc).__name__}: "
                f"{exc}") from exc
        from veritx_dse.workload.memory_lowering import ADDR_VEC_ORDERS
        artifact = resolved.artifact
        geometry = certified_geometry(self._geometry_profile.profile_id)
        mapping = (CHANNEL_INTERLEAVED if self._geometry_profile.channels > 1
                   else MAPPING_ALGORITHM)
        assert mapping in ADDR_VEC_ORDERS, mapping
        if len(design.hbm_devices) > 1:
            from veritx_dse.workload.memory_lowering import (
                ramulator_dispatch_config_payload,
            )
            config_payload = ramulator_dispatch_config_payload(
                geometry, design.hbm_devices,
                NATIVE_HBM3_TRANSACTION_BYTES, mapping)
        else:
            config_payload = backend_config_payload(geometry, mapping)
        config_hash = "sha256:" + hashlib.sha256(config_payload).hexdigest()
        return RamulatorPreparation(
            artifact=artifact, geometry=geometry,
            memory_artifact_hash=artifact.artifact_hash,
            access_stream_hash=artifact.access_stream_hash,
            backend_config_hash=config_hash, mapping=mapping,
            device_ids=design.hbm_devices)

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,
    ) -> Any:
        """Lower the real trace and run it through the vendored backend.

Rationale: docs/decisions/modules/backend.md
        """
        from veritx_dse.simulation import ramulator as _sim
        from veritx_dse.workload.memory_lowering import (
            DEFAULT_MAX_TRANSACTIONS,
            bandwidth_model_stream_ns,
            estimate_trace_cost,
            lower_to_ramulator_trace,
        )
        native = prepared.native_prepared
        if not isinstance(native, RamulatorPreparation):
            raise TypeError(
                f"RamulatorAdapter.execute takes a PreparedExecution "
                f"whose native_prepared is a RamulatorPreparation, got "
                f"{type(native).__name__}")
        backend = self._discover()
        if not backend.ready:
            raise RamulatorBackendAbsent(
                f"Ramulator backend not built: no compiled extension at "
                f"{backend.ext_path}; refusing to invent results")
        run_dir = Path(getattr(options, "run_dir"))
        timeout = getattr(options, "timeout_s", 600)
        ram_dir = run_dir / "ramulator"
        ram_dir.mkdir(parents=True, exist_ok=True)
        trace_path = ram_dir / "memory.trace"
        budget = getattr(options, "max_transactions", None)
        budget = DEFAULT_MAX_TRANSACTIONS if budget is None else int(budget)
        if len(native.device_ids) > 1:
            from veritx_dse.workload.memory_lowering import (
                estimate_dispatch_cost, lower_to_ramulator_dispatch,
            )
            dispatch_geometry = replace(
                native.geometry,
                transaction_bytes=NATIVE_HBM3_TRANSACTION_BYTES)
            if budget > 0:
                cost = estimate_dispatch_cost(
                    native.artifact, dispatch_geometry,
                    device_ids=native.device_ids)
                (ram_dir / "trace-cost.json").write_text(
                    json.dumps(cost.to_dict(), sort_keys=True, indent=2)
                    + "\n", encoding="utf-8")
                if cost.transactions > budget:
                    raise RamulatorSemanticRefusal(
                        f"multi-HBM dispatch needs {cost.transactions} "
                        f"native transactions, above configured budget "
                        f"{budget}")
            dispatch_manifest = lower_to_ramulator_dispatch(
                native.artifact, native.geometry,
                device_ids=native.device_ids,
                native_transaction_bytes=NATIVE_HBM3_TRANSACTION_BYTES,
                backend_config_hash=native.backend_config_hash,
                mapping=native.mapping)
            (ram_dir / "memory-artifact.json").write_text(
                json.dumps(native.artifact.serialize(), sort_keys=True,
                           indent=2) + "\n", encoding="utf-8")
            (ram_dir / "dispatch-manifest.json").write_text(
                json.dumps(dispatch_manifest, sort_keys=True, indent=2)
                + "\n", encoding="utf-8")
            requested_outstanding = getattr(options, "max_outstanding", None)
            if requested_outstanding is not None and \
                    int(requested_outstanding) != \
                    dispatch_manifest["dispatcher_max_outstanding"]:
                # The bound is part of the hashed config identity, so an
                # override would silently break replay. Refuse, don't ignore.
                raise RamulatorSemanticRefusal(
                    f"requested dispatcher outstanding limit "
                    f"{requested_outstanding} does not match the prepared "
                    f"config identity "
                    f"{dispatch_manifest['dispatcher_max_outstanding']}")
            evidence = _sim.execute_dispatch(
                native.artifact, dispatch_manifest, backend=backend,
                run_dir=ram_dir / "run",
                max_ticks=int(getattr(options, "max_native_ticks", 1_000_000)))
            (ram_dir / "memory-evidence.json").write_text(
                json.dumps(evidence.to_dict(), sort_keys=True, indent=2)
                + "\n", encoding="utf-8")
            return evidence
        if budget > 0:
            cost = estimate_trace_cost(native.artifact, native.geometry)
            (ram_dir / "trace-cost.json").write_text(
                json.dumps(cost.to_dict(), sort_keys=True, indent=2) + "\n",
                encoding="utf-8")
            if cost.transactions > budget:
                detail = (
                    f"traffic needs {cost.transactions:,} transactions "
                    f"({cost.generated_bytes / 1e9:.2f} GB) but the "
                    f"cycle-accurate budget is {budget:,} — Ramulator "
                    "replays serially, so this would not finish in the "
                    "configured timeout")
                try:
                    est_ns = bandwidth_model_stream_ns(cost, native.geometry)
                    detail += (
                        f"; bandwidth-model bound (NOT cycle-accurate): "
                        f"{est_ns / 1e6:.3f} ms at peak, assuming the trace "
                        "streams with no queueing or row-conflict loss")
                except Exception:
                    detail += "; bandwidth-model bound unavailable (no "
                    "audited peak rate for this timing preset)"
                raise RamulatorSemanticRefusal(
                    f"memory artifact exceeds the cycle-accurate budget: "
                    f"{detail}")
        manifest = lower_to_ramulator_trace(
            native.artifact, native.geometry, out_path=trace_path,
            mapping=native.mapping)
        if manifest.to_dict()["backend_config_hash"] != \
                native.backend_config_hash:
            raise _sim.RamulatorError(
                "lowered trace backend_config_hash does not match the "
                "prepared config identity — refusing to execute")
        (ram_dir / "memory-artifact.json").write_text(
            json.dumps(native.artifact.serialize(), sort_keys=True,
                       indent=2) + "\n",
            encoding="utf-8")
        (ram_dir / "lowering-manifest.json").write_text(
            json.dumps(manifest.to_dict(), sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8")
        evidence = _sim.execute(
            native.artifact, manifest, trace_path, backend=backend,
            run_dir=ram_dir / "run", timeout=timeout)
        (ram_dir / "memory-evidence.json").write_text(
            json.dumps(evidence.to_dict(), sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8")
        return evidence

    def normalize(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        prepared: PreparedExecution,
        native_result: object,
    ) -> NormalizedBackendEvidence:
        """Project authenticated native memory evidence into the common
        envelope. Only PASS evidence normalizes: INCONCLUSIVE stays
        INCONCLUSIVE (a refusal here, never a PASS), crashes and
        unsupported geometries never normalize. Only native metrics
        present are projected — absent stays absent, never zero-filled —
        and wall_time_s is never a scientific design objective."""
        from veritx_dse.backend.normalized_evidence import (
            MetricValue, NormalizedBackendEvidence,
        )
        from veritx_dse.simulation.ramulator import (
            MemoryEvidence, RamulatorError,
        )
        if question is not EvaluationQuestion.DRAM_TIMING:
            raise RamulatorSemanticRefusal(
                "certified Ramulator answers DRAM_TIMING only")
        native = prepared.native_prepared
        if not isinstance(native, RamulatorPreparation):
            raise TypeError(
                f"RamulatorAdapter.normalize takes a PreparedExecution "
                f"whose native_prepared is a RamulatorPreparation, got "
                f"{type(native).__name__}")
        if not isinstance(native_result, MemoryEvidence):
            raise TypeError(
                f"RamulatorAdapter.normalize takes a MemoryEvidence, got "
                f"{type(native_result).__name__}")
        evidence = native_result
        if evidence.memory_artifact_hash != native.memory_artifact_hash:
            raise RamulatorError(
                "native evidence memory_artifact_hash does not match the "
                "prepared artifact — refusing a transplanted normalization")
        if evidence.backend_config_hash != native.backend_config_hash:
            raise RamulatorError(
                "native evidence backend_config_hash does not match the "
                "prepared config identity — refusing a transplanted "
                "normalization")
        if evidence.status != "PASS":
            raise RamulatorError(
                f"native memory evidence status {evidence.status!r} is "
                f"not PASS (reason: {evidence.failure_reason}): "
                f"INCONCLUSIVE stays INCONCLUSIVE, never PASS; only "
                f"drained executions normalize")
        metrics: list[MetricValue] = []
        for native_key in _NORMALIZED_METRICS:
            entry = (evidence.metrics or {}).get(native_key)
            if not isinstance(entry, dict):
                continue
            value, unit = entry.get("value"), entry.get("unit")
            if isinstance(value, bool) or \
                    not isinstance(value, (int, float)):
                continue
            metrics.append(MetricValue(
                key=native_key, value=float(value), unit=unit,
                source_metric_key=native_key))
        _resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        resolved_hash = _resolved() if callable(_resolved) else _resolved
        try:
            producer_identity = evidence.producer["binary_sha256"]
        except (TypeError, KeyError) as exc:
            raise RamulatorError(
                f"native evidence carries no producer binary identity: "
                f"{exc}") from exc
        if not isinstance(producer_identity, str) or not producer_identity:
            raise RamulatorError(
                "native evidence carries no producer binary identity")
        limitations = self._limitations + ((
            "diagnostic multi-pool callback dispatch is not a qualified "
            "physical HBM package model or release profile",
        ) if len(native.device_ids) > 1 else ())
        return NormalizedBackendEvidence(
            backend_id=self.backend_id, question=question,
            model_fidelity=RAMULATOR_MODEL_FIDELITY,
            canonical_parent_ids=(
                context.design_hash, resolved_hash,
                context.workload_id,
                native.memory_artifact_hash,
                evidence.lowering_manifest_hash),
            native_evidence_id=ramulator_evidence_id(evidence),
            qualification=evidence.status,
            producer_identity=producer_identity,
            backend_config_hash=native.backend_config_hash,
            backend_input_hash=evidence.backend_input_hash,
            metrics=tuple(metrics),
            limitations=limitations)

_NORMALIZED_METRICS: tuple[str, ...] = (
    "completion_cycles",
    "average_read_latency_cycles",
    "average_write_latency_cycles",
    "row_hits",
    "row_misses",
    "row_conflicts",
    "read_queue_len_avg",
    "write_queue_len_avg",
    "coalesced_write_requests",
    "completed_read_bytes",
    "completed_write_bytes",
    "generated_requests",
    "accepted_requests",
    "completed_requests",
    "outstanding_requests",
)
RAMULATOR_NORMALIZED_METRICS: tuple[str, ...] = _NORMALIZED_METRICS

from veritx_dse.core.errors import InvalidInput  # noqa: E402
from veritx_dse.core.memory import MemoryArtifactError  # noqa: E402
from veritx_dse.workload.lowering import LoweringError  # noqa: E402
from veritx_dse.workload.memory_lowering import (  # noqa: E402
    CHANNEL_INTERLEAVED,
    MAPPING_ALGORITHM,
)
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    NormalizedBackendEvidence,
)

_SEMANTIC_REFUSALS = (
    RamulatorSemanticRefusal, LoweringError,
    MemoryArtifactError, InvalidInput,
)

__all__ = [
    "BACKEND_ID", "DEFAULT_MEMORY_PROFILE", "MEMORY_GEOMETRY_PROFILES",
    "MODEL_ASSUMPTION", "MULTI_HBM_DISPATCH_PROFILE",
    "MemoryGeometryProfile", "QUALIFICATION_PROFILE",
    "RAMULATOR_LIMITATIONS", "RAMULATOR_MODEL_FIDELITY",
    "certified_memory_design", "certified_mapping_policy",
    "memory_assumption", "memory_geometry_profile", "memory_limitations",
    "RamulatorAdapter", "RamulatorBackendAbsent", "RamulatorPreparation",
    "RamulatorSemanticRefusal", "certified_geometry",
    "certified_mapping_policy", "certified_memory_design",
    "ramulator_evidence_id",
]
