"""veritx_dse.backend.reproduce_astra — re-execute and compare an ASTRA run.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from veritx_dse.backend.astra import AstraWorkloadProjection
from veritx_dse.backend.astra_execution import (
    AstraExecutionError, AstraRuntimeEvidence, execute_astra_machine,
)
from veritx_dse.backend.astra_machine import AstraMachineProjection
from veritx_dse.backend.astra_namespace import AstraExecutionNamespace
from veritx_dse.core.run_bundle import RunBundleError

_INPUT_NAMES = ("machine.json", "workload-projection.json", "namespace.json")
_EVIDENCE_NAME = "astra_evidence.json"


def _load_json(path: Path, where: str) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunBundleError(f"{where} {path} is unreadable: {exc}") from exc
    if not isinstance(doc, dict):
        raise RunBundleError(f"{where} {path} must contain a JSON object")
    return doc


def reproduce_astra_run_bundle(
        analysis_dir: str | Path, *, binary: str | Path | None = None,
        timeout: int = 600) -> dict[str, Any]:
    """Verify, re-execute and compare; refuse any scientific divergence.

    ``analysis_dir`` is the federated ``analyses/<question>/`` directory
    holding ``astra/`` (machine files, staged workload, native evidence)
    and ``astra-inputs/`` (archived machine/projection/namespace JSONs).
    """
    root = Path(analysis_dir)
    astra_dir = root / "astra"
    inputs_dir = root / "astra-inputs"
    for name in _INPUT_NAMES:
        if not (inputs_dir / name).is_file():
            raise RunBundleError(
                f"{root} holds no archived ASTRA inputs "
                f"(missing {name}); this run predates reproducible ASTRA "
                "archival — reproduction is NOT_AVAILABLE for it")
    evidence_path = astra_dir / _EVIDENCE_NAME
    if not evidence_path.is_file():
        raise RunBundleError(
            f"{astra_dir} holds no {_EVIDENCE_NAME}; not an ASTRA run")
    if binary is None or not Path(binary).is_file():
        raise RunBundleError(
            f"reproduce needs the ASTRA runtime binary; none at "
            f"{binary!r} (pass --binary)")

    try:
        machine = AstraMachineProjection.from_dict(
            _load_json(inputs_dir / "machine.json", "machine"))
        workload = AstraWorkloadProjection.from_dict(
            _load_json(inputs_dir / "workload-projection.json",
                       "workload projection"))
        namespace = AstraExecutionNamespace.from_dict(
            _load_json(inputs_dir / "namespace.json", "namespace"))
        stored = AstraRuntimeEvidence.from_dict(
            _load_json(evidence_path, "stored evidence"))
    except (AstraExecutionError, ValueError) as exc:
        raise RunBundleError(
            f"stored ASTRA inputs do not rebuild: {exc}") from exc

    # The archived inputs must identify exactly what the stored evidence
    # claims it executed — a transplanted machine is refused here.
    if machine.machine_id() != stored.machine_id:
        raise RunBundleError(
            "archived machine does not match the stored evidence's "
            "machine_id; refusing a transplanted reproduction")
    if workload.projection_id() != stored.workload_projection_id:
        raise RunBundleError(
            "archived workload does not match the stored evidence's "
            "workload_projection_id")
    if namespace.namespace_id() != stored.namespace_id:
        raise RunBundleError(
            "archived namespace does not match the stored evidence's "
            "namespace_id")
    if tuple(tuple(pair) for pair in namespace.rank_to_endpoint) != \
            tuple(tuple(pair) for pair in stored.rank_to_endpoint):
        raise RunBundleError(
            "archived namespace rank map does not match the stored "
            "evidence's executed rank_to_endpoint; refusing a "
            "reproduction against a different placement")
    from veritx_dse.backend.astra_execution import (
        ASTRA_BUILD_RECIPE_VERSION,
    )
    from veritx_dse.backend.producer import (
        ProducerError, resolve_producer_identity,
    )
    if stored.astra_build_manifest_sha256 is None \
            or stored.astra_build_recipe_version is None:
        raise RunBundleError(
            "stored evidence predates producer binding (no manifest "
            "facts); reproduction is NOT_AVAILABLE for it")
    try:
        rerun_identity = resolve_producer_identity(
            Path(binary),
            require_manifest_recipe=ASTRA_BUILD_RECIPE_VERSION)
    except ProducerError as exc:
        raise RunBundleError(
            "reproduction binary is not a qualified producer: "
            f"{exc}") from exc
    if rerun_identity.binary_sha256 != stored.astra_binary_sha256:
        raise RunBundleError(
            "reproduction binary SHA does not match the stored "
            "evidence's producer SHA; refusing reproduction against "
            "a different producer")
    workload_base = astra_dir / "workload" / "workload.et"
    if not workload_base.is_file():
        raise RunBundleError(
            f"stored staged workload {workload_base} is absent; cannot "
            "re-execute the exact staged inputs")

    with tempfile.TemporaryDirectory(prefix="veritx-reproduce-astra-") as tmp:
        try:
            rerun = execute_astra_machine(
                machine=machine, binary=str(binary),
                run_dir=Path(tmp),
                workload_configuration=workload_base,
                timeout_s=timeout, write=False, namespace=namespace,
                class_binding_id=workload.class_binding_id())
        except AstraExecutionError as exc:
            raise RunBundleError(
                f"ASTRA reproduction execution failed: {exc}") from exc

    matched = (
        rerun.evidence_id() == stored.evidence_id()
        and rerun.per_rank_cycles == stored.per_rank_cycles
        and rerun.aggregate_cycles == stored.aggregate_cycles)
    if not matched:
        raise RunBundleError(
            "ASTRA reproduction diverges from the stored science: "
            f"evidence {rerun.evidence_id()[:16]} != "
            f"{stored.evidence_id()[:16]}")
    return {"matched": True, "evidence_id": stored.evidence_id(),
            "aggregate_cycles": stored.aggregate_cycles,
            "per_rank_cycles": [list(pair)
                                for pair in stored.per_rank_cycles]}


__all__ = ["reproduce_astra_run_bundle"]
