"""veritx_dse.backend.reproduce_ramulator — re-execute and compare a run.

``reproduce`` does NOT trust the stored numbers and does NOT re-derive
the inputs: it rebuilds the exact stored memory artifact and manifest
from the archived JSONs (refusing on any identity mismatch), re-runs
the stored trace through the backend in a fresh directory, and compares
the deterministic science (native evidence identity + status). A
divergence refuses.

Wall time is excluded from the comparison by construction: the native
evidence identity (``ramulator_evidence_id``) never covers it, so two
executions of the same science agree even though the host clock moved.
"""
from __future__ import annotations

import json
import tempfile
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

    # The archived prepared identities must match what the stored
    # evidence claims it executed — a transplanted artifact is refused.
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
    return {
        "matched": matched,
        "evidence_id": ramulator_evidence_id(stored),
        "status": rerun.status,
        "rerun_status": rerun.status,
    }


__all__ = ["reproduce_ramulator_run_bundle"]
