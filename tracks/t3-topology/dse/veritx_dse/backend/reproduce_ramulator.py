"""veritx_dse.backend.reproduce_ramulator — re-execute and compare a run.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from veritx_dse.core.run_bundle import RunBundleError

_EVIDENCE_NAME = "memory-evidence.json"
_ARTIFACT_NAME = "memory-artifact.json"
_MANIFEST_NAME = "lowering-manifest.json"
_TRACE_NAME = "memory.trace"

def _load_json(path: Path, where: str) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunBundleError(f"{where} {path} is unreadable: {exc}") from exc
    if not isinstance(doc, dict):
        raise RunBundleError(f"{where} {path} must contain a JSON object")
    return doc

def reproduce_ramulator_run_bundle(
        analysis_dir: str | Path, *,
        vendor_dir: str | Path | None = None,
        python_exe: str | None = None,
        timeout: int = 600) -> dict[str, Any]:
    """Verify, re-execute and compare; refuse any scientific divergence.

    ``analysis_dir`` is the federated ``analyses/dram_timing/``
    directory holding ``ramulator/`` (trace, manifest, artifact, native
    evidence) and ``ramulator-inputs/`` (archived artifact + prepared
    identities).
    """
    from veritx_dse.backend.ramulator_adapter import ramulator_evidence_id
    from veritx_dse.core.memory import MemoryArtifact
    from veritx_dse.simulation import ramulator as _sim
    from veritx_dse.workload.memory_lowering import MemoryLoweringManifest

    root = Path(analysis_dir)
    ram_dir = root / "ramulator"
    inputs_dir = root / "ramulator-inputs"
    evidence_path = ram_dir / _EVIDENCE_NAME
    if not evidence_path.is_file():
        raise RunBundleError(
            f"{ram_dir} holds no {_EVIDENCE_NAME}; this run predates "
            "reproducible Ramulator archival — reproduction is "
            "NOT_AVAILABLE for it")
    if (ram_dir / "dispatch-manifest.json").is_file():
        return _reproduce_dispatch_bundle(
            ram_dir, inputs_dir, evidence_path, vendor_dir=vendor_dir,
            python_exe=python_exe, timeout=timeout)
    for name in (_ARTIFACT_NAME, _MANIFEST_NAME, _TRACE_NAME):
        if not (ram_dir / name).is_file():
            raise RunBundleError(
                f"{ram_dir} holds no {name}; cannot re-execute the exact "
                "stored inputs — reproduction is NOT_AVAILABLE")
    try:
        stored_artifact = MemoryArtifact.from_dict(
            _load_json(ram_dir / _ARTIFACT_NAME, "stored memory artifact"))
        stored_manifest = MemoryLoweringManifest(**_load_json(
            ram_dir / _MANIFEST_NAME, "stored lowering manifest"))
        stored_doc = _load_json(evidence_path, "stored evidence")
        stored = _sim.MemoryEvidence(
            status=stored_doc["status"],
            producer=stored_doc["producer"],
            fidelity=stored_doc["fidelity"],
            memory_artifact_hash=stored_doc["memory_artifact_hash"],
            lowering_manifest_hash=stored_doc["lowering_manifest_hash"],
            backend_input_hash=stored_doc["backend_input_hash"],
            backend_config_hash=stored_doc["backend_config_hash"],
            metrics=stored_doc.get("metrics", {}),
            assumptions=tuple(stored_doc.get("assumptions", ())),
            semantic_losses=tuple(stored_doc.get("semantic_losses", ())),
            failure_reason=stored_doc.get("failure_reason", ""),
            raw={})
    except (KeyError, TypeError, ValueError) as exc:
        raise RunBundleError(
            f"stored Ramulator inputs do not rebuild: {exc}") from exc

    if inputs_dir.is_dir() and (inputs_dir / "prepared.json").is_file():
        prepared = _load_json(inputs_dir / "prepared.json",
                              "archived preparation")
        for key in ("memory_artifact_hash", "backend_config_hash"):
            if prepared.get(key) != getattr(stored, key):
                raise RunBundleError(
                    f"archived preparation {key} does not match the "
                    f"stored evidence; refusing a transplanted "
                    f"reproduction")

    backend = _sim.discover(python_exe=python_exe, vendor_dir=(
        Path(vendor_dir) if vendor_dir is not None else None))
    if not backend.ready:
        raise RunBundleError(
            f"reproduce needs the built Ramulator extension at "
            f"{backend.ext_path}; none here — reproduction is "
            f"NOT_AVAILABLE on this tree")

    with tempfile.TemporaryDirectory(
            prefix="veritx-reproduce-ramulator-") as tmp:
        rerun = _sim.execute(
            stored_artifact, stored_manifest, ram_dir / _TRACE_NAME,
            backend=backend, run_dir=Path(tmp), timeout=timeout)
    matched = (
        rerun.status == stored.status
        and ramulator_evidence_id(rerun) == ramulator_evidence_id(stored))
    if not matched:
        raise RunBundleError(
            "Ramulator reproduction diverges from the stored science: "
            f"evidence {ramulator_evidence_id(rerun)[:16]} != "
            f"{ramulator_evidence_id(stored)[:16]}")
    return {
        "matched": True,
        "evidence_id": ramulator_evidence_id(stored),
        "status": rerun.status,
        "rerun_status": rerun.status,
    }

def _reproduce_dispatch_bundle(
        ram_dir: Path, inputs_dir: Path, evidence_path: Path, *,
        vendor_dir: str | Path | None, python_exe: str | None,
        timeout: int) -> dict[str, Any]:
    """Rebuild the canonical dispatcher ledger and replay one shared engine."""
    from veritx_dse.backend.ramulator_adapter import ramulator_evidence_id
    from veritx_dse.core.memory import MemoryArtifact
    from veritx_dse.simulation import ramulator as _sim
    from veritx_dse.workload.memory_lowering import (
        RAMULATOR_DISPATCHER_V1, RAMULATOR_DISPATCHER_VERSION,
        RamulatorGeometry, lower_to_ramulator_dispatch,
    )
    try:
        artifact = MemoryArtifact.from_dict(
            _load_json(ram_dir / _ARTIFACT_NAME, "stored memory artifact"))
        manifest = _load_json(ram_dir / "dispatch-manifest.json",
                              "stored dispatch manifest")
        stored_doc = _load_json(evidence_path, "stored evidence")
        stored = _sim.MemoryEvidence(
            status=stored_doc["status"], producer=stored_doc["producer"],
            fidelity=stored_doc["fidelity"],
            memory_artifact_hash=stored_doc["memory_artifact_hash"],
            lowering_manifest_hash=stored_doc["lowering_manifest_hash"],
            backend_input_hash=stored_doc["backend_input_hash"],
            backend_config_hash=stored_doc["backend_config_hash"],
            metrics=stored_doc.get("metrics", {}),
            assumptions=tuple(stored_doc.get("assumptions", ())),
            semantic_losses=tuple(stored_doc.get("semantic_losses", ())),
            failure_reason=stored_doc.get("failure_reason", ""),
            raw=stored_doc.get("raw", {}))
        dispatcher_version = manifest.get("dispatcher")
        if dispatcher_version not in (RAMULATOR_DISPATCHER_V1,
                                      RAMULATOR_DISPATCHER_VERSION):
            raise RunBundleError(
                f"stored dispatch engine {dispatcher_version!r} is "
                f"not supported by this build ({RAMULATOR_DISPATCHER_VERSION})")
        retry_policy = manifest.get("backpressure_retry_policy")
        if dispatcher_version == RAMULATOR_DISPATCHER_V1 and \
                retry_policy is not None:
            raise RunBundleError("stored V1 dispatcher has an unknown retry policy")
        geometry = RamulatorGeometry.from_dict(manifest["geometry_per_pool"])
        devices = tuple(int(d) for d in manifest["device_channel_groups"])
        expected = lower_to_ramulator_dispatch(
            artifact, geometry, device_ids=devices,
            native_transaction_bytes=geometry.transaction_bytes,
            backend_config_hash=manifest["backend_config_hash"],
            mapping=manifest["mapping_algorithm"],
            dispatcher_version=dispatcher_version,
            backpressure_retry_policy=retry_policy)
        if expected != manifest:
            raise RunBundleError(
                "stored multi-HBM dispatch manifest differs from the "
                "independently rebuilt artifact ledger")
        if inputs_dir.is_dir() and (inputs_dir / "prepared.json").is_file():
            prepared = _load_json(inputs_dir / "prepared.json",
                                  "archived preparation")
            if prepared.get("backend_config_hash") != stored.backend_config_hash:
                raise RunBundleError(
                    "archived backend config does not match dispatch evidence")
            if prepared.get("device_ids") != list(devices) or \
                    prepared.get("dispatch_engine") != manifest["dispatcher"]:
                raise RunBundleError(
                    "archived device routing/dispatcher does not match "
                    "stored dispatch manifest")
        bounds = (stored_doc.get("raw") or {}).get("dispatcher_bounds")
        legacy_identity = dispatcher_version == RAMULATOR_DISPATCHER_V1
        if not isinstance(bounds, dict) or "max_ticks" not in bounds:
            if not legacy_identity or stored.status != "PASS":
                raise RunBundleError(
                    "stored dispatch evidence records no engine tick bound; "
                    "exact replay is NOT_AVAILABLE for it")
            # V1 federated runs used RamulatorRunOptions, which had no native
            # tick override; the adapter's fixed default was 1,000,000. A
            # PASS proves that bound did not truncate the observed run.
            max_ticks = 1_000_000
        else:
            max_ticks = bounds["max_ticks"]
        if not isinstance(max_ticks, int) or isinstance(max_ticks, bool) or \
                max_ticks < 1:
            raise RunBundleError(
                f"stored dispatch tick bound {max_ticks!r} is malformed")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, RunBundleError):
            raise
        raise RunBundleError(
            f"stored multi-HBM dispatch inputs do not rebuild: {exc}") from exc
    backend = _sim.discover(
        python_exe=python_exe,
        vendor_dir=Path(vendor_dir) if vendor_dir is not None else None)
    if not backend.ready:
        raise RunBundleError(
            f"reproduce needs the built Ramulator extension at "
            f"{backend.ext_path}; none here")
    with tempfile.TemporaryDirectory(
            prefix="veritx-reproduce-ramulator-dispatch-") as tmp:
        rerun = _sim.execute_dispatch(
            artifact, manifest, backend=backend, run_dir=Path(tmp),
            max_ticks=max_ticks)
    if legacy_identity:
        # V1 evidence identity did not include dispatcher_bounds.
        rerun = replace(rerun, raw={
            k: v for k, v in rerun.raw.items()
            if k != "dispatcher_bounds"})
    matched = (rerun.status == stored.status and
               ramulator_evidence_id(rerun) == ramulator_evidence_id(stored))
    if not matched:
        raise RunBundleError(
            "multi-HBM Ramulator replay diverges: "
            f"{ramulator_evidence_id(rerun)[:16]} != "
            f"{ramulator_evidence_id(stored)[:16]}")
    return {"matched": True, "evidence_id": ramulator_evidence_id(stored),
            "status": rerun.status, "rerun_status": rerun.status}


__all__ = ["reproduce_ramulator_run_bundle"]
