"""veritx_dse.gateway — the live Studio gateway.

Rationale: docs/decisions/modules/gateway.md
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.core.errors import InvalidInput, Refusal
from veritx_dse.core.paths import REPO
from veritx_dse.core.run_bundle import (
    CHECKSUMS_NAME, RunBundleError, verify_run_bundle,
)
from veritx_dse.gateway.staleness import staleness, warn_if_stale
from veritx_dse.gateway.ablations import ablation_catalog, run_ablation
from veritx_dse.gateway.design_sim import DesignSimBody, run_design_simulation
from veritx_dse.gateway.errors import (
    BackendUnavailable, Conflict, EngineUnavailable, NotFound, error_code_for,
    http_status_for,
)
from veritx_dse.gateway.revisions import (
    Revision, RevisionStore, revision_id_for,
)
from veritx_dse.application.capabilities import capability_registry
from veritx_dse.application.loom_capability import loom_capabilities
from veritx_dse.application.value_provenance import provenance_registry
from veritx_dse.product.qualification import qualification_view
from veritx_dse.product.service import ProductConfig, ProductService
from veritx_dse.product.validation import validation_campaigns

logger = logging.getLogger("veritx.gateway")


def run_freshness(product: ProductService, run_id: str,
                  run: dict[str, Any]) -> dict[str, Any] | None:
    """Server-computed freshness for one run against the design in view.

    Returns None only when the owning project cannot be resolved, which is a
    data-integrity problem the run view already refuses — not a reason to
    invent a verdict.
    """
    from veritx_dse.application.value_provenance import (
        STALENESS_MEANING, staleness_for,
    )
    try:
        project = product.project_view(run["project_id"])
    except Exception:  # noqa: BLE001 — the run view already refused it
        return None
    active = project.get("active_revision_id")
    dirty = bool((project.get("draft") or {}).get("dirty"))
    state = staleness_for(run.get("revision_id"), active, draft_dirty=dirty)
    return {
        "state": state,
        "meaning": STALENESS_MEANING[state],
        "run_revision_id": run.get("revision_id"),
        "active_revision_id": active,
        "draft_dirty": dirty,
        "draft_design_hash": (project.get("draft") or {}).get("design_hash"),
        "run_design_hash": run.get("design_hash"),
    }

@dataclass(frozen=True)
class GatewayConfig:
    store_root: Path
    runs_root: Path
    booksim_bin: Path | None = None
    astra_bin: Path | None = None
    network_clock_hz: int = 1_000_000_000
    timeout_s: int = 600
    experiments_dir: Path | None = None
    revisions_root: Path | None = None
    projects_root: Path | None = None
    prewarm_capability_probe: bool = True
    # Sampled-series opt-in (all None = off). Widths are the operator's
    # fabric assertion for this deployment, recorded in evidence.
    sample_period_cycles: int | None = None
    series_link_width_bits: int | None = None
    series_flit_width_bits: int | None = None
    series_store_dir: Path | None = None

    @property
    def revisions_dir(self) -> Path:
        return self.revisions_root or (
            self.store_root.parent / "studio-revisions")

def _env_pos_int(name: str) -> int | None:
    """Optional positive-int env knob (absent = off). Refuses garbage at
    startup rather than sampling with a misread period."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a positive int, got {raw!r}")
    if value <= 0:
        raise ValueError(f"{name} must be a positive int, got {raw!r}")
    return value


def config_from_env() -> GatewayConfig:
    # One authority for "where is the repo": core.paths.REPO. This used to be
    # Path(__file__).resolve().parents[3], which resolves to the t3-topology
    # track dir, not the repo root — so store/runs landed under
    # tracks/t3-topology/runs/ and experiments_dir pointed at
    # tracks/t3-topology/validation/experiments, which does not exist.
    repo = REPO
    store = os.environ.get("VERITX_STORE_ROOT")
    runs = os.environ.get("VERITX_RUNS_ROOT")
    revisions = os.environ.get("VERITX_REVISIONS_ROOT")
    projects = os.environ.get("VERITX_PROJECTS_ROOT")
    binary = os.environ.get("VERITX_BOOKSIM_BIN")
    store_root = Path(store) if store else repo / "runs" / "studio-store"
    runs_root = Path(runs) if runs else repo / "runs" / "veritx-runs"
    # The series opt-in is all-or-nothing. A store dir (or a width) without a
    # period is a dangling parameter that execution refuses, so the runs-root
    # default applies only when sampling is actually on; otherwise the gateway
    # sends nothing. Defaulting the store unconditionally refused every
    # BookSim run on a default deployment.
    period_cycles = _env_pos_int("VERITX_SERIES_SAMPLE_PERIOD")
    store_env = os.environ.get("VERITX_SERIES_STORE_DIR")
    if store_env:
        series_store_dir: Path | None = Path(store_env)
    elif period_cycles is not None:
        series_store_dir = runs_root
    else:
        series_store_dir = None
    return GatewayConfig(
        store_root=store_root,
        runs_root=runs_root,
        booksim_bin=resolve_booksim_bin(binary),
        astra_bin=resolve_astra_bin(os.environ.get("VERITX_ASTRA_BIN")),
        experiments_dir=repo / "validation" / "experiments",
        revisions_root=(Path(revisions) if revisions
                        else store_root.parent / "studio-revisions"),
        projects_root=Path(projects) if projects else store_root / "projects",
        sample_period_cycles=period_cycles,
        series_link_width_bits=_env_pos_int(
            "VERITX_SERIES_LINK_WIDTH_BITS"),
        series_flit_width_bits=_env_pos_int(
            "VERITX_SERIES_FLIT_WIDTH_BITS"),
        series_store_dir=series_store_dir,
    )

def resolve_astra_bin(env_value: str | None = None) -> Path | None:
    """The gateway's ASTRA binary: env override, then the canonical
    resolver. Returns None only when the binary genuinely does not
    exist, so MISSING means missing rather than unset."""
    if env_value:
        return Path(env_value)
    try:
        from veritx_dse.backend.astra import resolve_runtime_binary
        return resolve_runtime_binary()
    except Exception:
        return None

def _backend_presence(config: GatewayConfig) -> dict[str, Any]:
    """Cheap, non-secret backend presence. No simulation ever runs here.

    States are install facts (PRESENT/ABSENT), never readiness: READY
    requires adjudicating a real canonical context, which health must
    not do. A manifest flag names whether build-time provenance exists
    for the binary (no digests, no paths leak).
    """
    from veritx_dse.core.build_manifest import manifest_path_for

    def probe(binary: Path | None) -> dict[str, Any]:
        if binary is None or not Path(binary).is_file():
            return {"state": "ABSENT", "binary_present": False,
                    "manifest_present": False}
        try:
            manifest = manifest_path_for(Path(binary)).is_file()
        except Exception:
            manifest = False
        return {"state": "PRESENT", "binary_present": True,
                "manifest_present": bool(manifest)}

    return {
        "BOOKSIM_STANDALONE": probe(config.booksim_bin),
        "ASTRA2_EMBEDDED_BOOKSIM": probe(config.astra_bin),
        "RAMULATOR2_HBM3_V1": _ramulator_presence(),
    }

def _ramulator_presence() -> dict[str, Any]:
    """Ramulator install fact: is the compiled extension importable by
    this interpreter? No build, no simulation, no readiness claim."""
    try:
        from veritx_dse.core.build_manifest import manifest_path_for
        from veritx_dse.simulation.ramulator import discover
        backend = discover()
    except Exception:
        return {"state": "ABSENT", "binary_present": False,
                "manifest_present": False}
    if not backend.ready:
        return {"state": "ABSENT", "binary_present": False,
                "manifest_present": False}
    try:
        manifest = manifest_path_for(backend.ext_path).is_file()
    except Exception:
        manifest = False
    return {"state": "PRESENT", "binary_present": True,
            "manifest_present": bool(manifest)}

def resolve_booksim_bin(env_value: str | None = None) -> Path | None:
    """The gateway's BookSim binary: env override, then the standard search.

Rationale: docs/decisions/modules/gateway.md
    """
    if env_value:
        return Path(env_value)
    try:
        from veritx_dse.core.paths import REPO
        from veritx_dse.simulation.booksim import find_booksim_bin
        return find_booksim_bin(REPO)
    except Exception:
        return None

class CreateProjectBody(BaseModel):
    name: str
    workload_id: str | None = None

class CreateProjectFromPresetBody(BaseModel):
    preset_id: str
    name: str | None = None

class DraftBody(BaseModel):
    request: dict[str, Any]
    expected_draft_design_hash: str | None = None

class FloorplanBody(BaseModel):
    model_config = {"extra": "forbid"}
    mode: str
    grid: dict[str, Any] | None = None
    floorplan: dict[str, Any] | None = None

class AgentChatBody(BaseModel):
    model_config = {"extra": "forbid"}
    message: str = Field(min_length=1, max_length=16000)
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    allow_model: bool = False
    include_draft: bool = False
    expected_draft_design_hash: str | None = None
    context: dict[str, Any] | None = None

class AgentConfigBody(BaseModel):
    model_config = {"extra": "forbid"}
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)

class WorkloadTranslationBody(BaseModel):
    model_config = {"extra": "forbid"}
    message: str = Field(min_length=1, max_length=16000)
    allow_model: bool = False
    expected_draft_design_hash: str

class StampIpTemplateBody(BaseModel):
    model_config = {"extra": "forbid"}
    expected_draft_design_hash: str
    template_id: str
    instance_id: str
    address_base: int | None = None
    address_size: int | None = None
    clock_domain: str
    power_domain: str
    initiator_group_index: int | None = None
    access_permission: str | None = None

class DesignPreviewBody(BaseModel):
    model_config = {"extra": "forbid"}
    request: dict[str, Any]

class TopologyPreviewBody(BaseModel):
    model_config = {"extra": "forbid"}
    request: dict[str, Any]
    topology: dict[str, Any]

class SelectWorkloadBody(BaseModel):
    workload_id: str

class RenameProjectBody(BaseModel):
    name: str

class EvaluateBodyV1(BaseModel):
    backend: str | None = None
    questions: list[str] | None = None

class AblationBody(BaseModel):
    workloads: list[str] | None = None
    topologies: list[str] | None = None
    packet_size: int = 5
    vc_buf_size: int = 8
    use_noc_latency: int = 0
    jobs: int = 6
    seed: int = 1
    overrides: dict[str, str] = Field(default_factory=dict)

class ServingBody(BaseModel):
    workload_id: str | None = None
    num_reqs: int | None = None
    cluster_config: str | None = None
    dataset: str | None = None
    timeout_s: int | None = None
    profile_overrides: dict[str, Any] | None = None

class DeploymentPreviewBody(BaseModel):
    """Deployment builder preview: model -> hardware -> serving policy."""

    model_config = {"extra": "forbid"}
    name: str | None = None
    model_name: str = Field(min_length=1)
    hardware: str = Field(min_length=1)
    tp_size: int = Field(ge=1)
    pp_size: int = Field(default=1, ge=1)
    ep_size: int | None = Field(default=None, ge=1)
    dp_instances: int = Field(default=1, ge=1)
    max_num_seqs: int | None = None
    max_num_batched_tokens: int | None = None
    trace: str = Field(min_length=1)
    num_reqs: int | None = None
    topology: dict[str, Any]
    link_width_bits: int = Field(default=128, ge=1)
    hbm_controllers_per_rank: int = Field(default=0, ge=0)


class ServingBindingBody(BaseModel):
    """Bind one cluster×trace serving experiment to a project."""
    cluster_config: str | None = None
    dataset: str | None = None
    num_reqs: int | None = None
    timeout_s: int | None = None
    profile_overrides: dict[str, Any] | None = None

class OptimizeBodyV1(BaseModel):
    domain: list[dict[str, Any]]
    objectives: list[dict[str, Any]] = [
        {"metric": "completion_cycles", "direction": "MIN"}]
    constraints: list[dict[str, Any]] = []
    method: str = "grid"
    selection: str | None = None
    seed: int | None = None
    budget: dict[str, Any] | None = None

class CompileBody(BaseModel):
    preset: str | None = None
    policy: str = "baseline_deterministic_v2"
    overrides: list[str] = []
    name: str | None = None
    request: dict[str, Any] | None = None

class CompileDraftBody(BaseModel):
    """Compile request body (Gate 7 §4).

Rationale: docs/decisions/modules/gateway.md
    """

    expected_draft_design_hash: str | None = None

class PinnedDraftBody(BaseModel):
    model_config = {"extra": "forbid"}
    expected_draft_design_hash: str

class CatalogEvaluationBody(PinnedDraftBody):
    topology_ids: list[str] | None = None

class CatalogSelectionBody(PinnedDraftBody):
    acknowledge_incomplete_backends: bool = False

class RtlPreviewBody(PinnedDraftBody):
    acknowledge_preview: bool = False

class EvaluateBody(BaseModel):
    revision_id: str | None = None
    request: dict[str, Any] = {}
    patch: dict[str, Any] = {}

def _compile_design(config: GatewayConfig, body: CompileBody):
    """Compile one design to (canonical request, Compilation, design_hash,
    resolved_fabric_hash). Two engine-authored paths, one product boundary.

Rationale: docs/decisions/modules/gateway.md
    """
    from veritx_dse.application.fabric_compiler import FabricCompiler

    if body.request is not None:
        from veritx_dse.model.compile_model import CompileRequestV3
        try:
            request = CompileRequestV3.from_dict(body.request)
        except (ValueError, KeyError, InvalidInput) as exc:
            raise InvalidInput(str(exc)) from exc
        compilation = FabricCompiler().compile(request)
        resolved = ""
        if compilation.status == "COMPILED":
            resolved = compilation.bundle.root_hashes()["resolved_fabric_hash"]
        return request, compilation, request.design_hash(), resolved

    if body.preset is None:
        raise InvalidInput(
            "a compile needs either a preset or a v3 design request")

    from veritx_dse.application.compile_intent import CompileIntent
    from veritx_dse.application.service import SrotaControlPlane
    from veritx_dse.application.store import ResourceStore
    from veritx_dse.cli.commands_compile import _parse_override
    from veritx_dse.compiler.candidate_policy import CandidatePolicy

    try:
        overrides = tuple(_parse_override(t) for t in body.overrides)
        policy = CandidatePolicy(body.policy)
        intent = CompileIntent(
            name=body.name or f"studio:{body.preset}",
            fabric_preset=body.preset, fabric_overrides=overrides,
            candidate_policy=policy)
    except (ValueError, KeyError, InvalidInput) as exc:
        raise InvalidInput(str(exc)) from exc
    outcome = SrotaControlPlane(store=ResourceStore(config.store_root))\
        .compile(intent)
    request = outcome.compiled.design
    compilation = FabricCompiler().compile(request)
    if compilation.status == "COMPILED":
        resolved = compilation.bundle.root_hashes()["resolved_fabric_hash"]
        if resolved != outcome.resolved_fabric_hash:
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                "guided and v3 compile paths disagree on resolved_fabric_hash",
                operation="compile")
    else:
        resolved = ""
    return request, compilation, outcome.design_hash, resolved

def _views(request: Any,
           compilation: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    from veritx_dse.application.views import compilation_view, design_view

    return design_view(request, compilation), compilation_view(compilation)

def _revision_of(config: GatewayConfig, body: CompileBody, *,
                 design_hash: str,
                 resolved_fabric_hash: str) -> Revision | None:
    """Record an immutable revision for a COMPILED design."""
    if not resolved_fabric_hash:
        return None
    intent = body.model_dump()
    revision = Revision(
        revision_id=revision_id_for(
            intent=intent, design_hash=design_hash,
            resolved_fabric_hash=resolved_fabric_hash),
        intent=intent, design_hash=design_hash,
        resolved_fabric_hash=resolved_fabric_hash)
    RevisionStore(config.revisions_dir).put(revision)
    return revision

def _load_revision(config: GatewayConfig, revision_id: str):
    """Re-derive a revision's canonical request; refuse on compiler drift."""
    revision = RevisionStore(config.revisions_dir).get(revision_id)
    request, compilation, design_hash, resolved = _compile_design(
        config, CompileBody(**revision.intent))
    if (design_hash != revision.design_hash
            or resolved != revision.resolved_fabric_hash):
        raise Conflict(
            f"revision {revision_id} no longer compiles to its stored "
            "identity; refusing to reinterpret it")
    if compilation.status != "COMPILED":
        raise Conflict(
            f"revision {revision_id} is {compilation.status}, not a "
            "compiled fabric")
    return revision, request, compilation

def _canonical_request(config: GatewayConfig, body: Any):
    """The canonical request from a revision id, or a raw compatibility body."""
    if getattr(body, "revision_id", None):
        _revision, request, _compilation = _load_revision(
            config, body.revision_id)
        return request
    from veritx_dse.model.compile_model import CompileRequestV3

    try:
        return CompileRequestV3.from_dict(body.request)
    except (ValueError, KeyError, InvalidInput) as exc:
        raise InvalidInput(str(exc)) from exc

def _compile(config: GatewayConfig, body: CompileBody) -> dict[str, Any]:
    request, compilation, design_hash, resolved = _compile_design(config, body)
    design, compilation_projection = _views(request, compilation)
    revision = _revision_of(config, body, design_hash=design_hash,
                            resolved_fabric_hash=resolved)
    out: dict[str, Any] = {
        "revision_id": revision.revision_id if revision else None,
        "design_hash": design_hash,
        "resolved_fabric_hash": resolved or None,
        "design_view": design,
        "compilation_view": compilation_projection,
    }
    if compilation.status == "COMPILED":
        hashes = {str(k): str(v)
                  for k, v in compilation.bundle.root_hashes().items()}
        out.update({
            "topology_hash": hashes["topology_hash"],
            "attachment_hash": hashes["attachment_hash"],
            "mapping_hash": hashes["mapping_hash"],
            "route_hash": hashes["router_route_hash"],
            "resolved_route_hash": hashes["resolved_route_hash"],
            "vc_assignment_hash": hashes["vc_assignment_hash"],
            "fabric_hash": hashes["fabric_hash"],
            "vc_count": compilation.bundle.vc_assignment.vc_count,
        })
    return out

def _list_runs(config: GatewayConfig) -> list[dict[str, Any]]:
    root = config.runs_root
    if not root.is_dir():
        return []
    runs = []
    for child in sorted(root.iterdir()):
        if not (child / CHECKSUMS_NAME).is_file():
            continue
        entry: dict[str, Any] = {"run_id": child.name, "status": "UNVERIFIED"}
        try:
            summary = verify_run_bundle(child)
            entry["status"] = "VERIFIED"
            entry["bundle_id"] = summary["bundle_id"]
            entry["file_count"] = summary["file_count"]
        except RunBundleError as exc:
            entry["status"] = "INVALID"
            entry["reason"] = str(exc)
        runs.append(entry)
    return runs

def _run_dir(config: GatewayConfig, run_id: str) -> Path:
    if "/" in run_id or "\\" in run_id or run_id in (".", ".."):
        raise InvalidInput("invalid run id")
    path = config.runs_root / run_id
    if not path.is_dir():
        raise NotFound(f"no such run: {run_id}")
    return path

def _workloads(config: GatewayConfig) -> dict[str, Any]:
    from veritx_dse.application.compile_intent import preset_names
    workloads: list[dict[str, Any]] = [
        {"id": f"preset:{name}", "kind": "preset", "name": name}
        for name in preset_names()
    ]
    exp_dir = config.experiments_dir
    if exp_dir is not None and exp_dir.is_dir():
        for path in sorted(exp_dir.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            workloads.append({
                "id": f"experiment:{doc.get('id', path.stem)}",
                "kind": "validation_experiment",
                "title": doc.get("title", ""),
            })
    return {"workloads": workloads}

_LOOM_CAPABILITY_CACHE: dict[str, tuple[float | None, dict[str, Any]]] = {}
_LOOM_CAPABILITY_LOCK = threading.Lock()

def _cached_topology_probe(refresh: bool = False) -> dict[str, Any]:
    """The probed capability table, memoized against the loaded code.

    The probe compiles every registered family (~4 s). It is a PURE function
    of the code this process loaded, so recomputing it per page navigation
    buys no truth: ``newest_source_mtime`` is the same signal ``health``
    already reports, and a changed tree invalidates the entry (and is already
    flagged STALE by health, which requires a restart). ``refresh`` re-probes
    on demand. The lock makes it single-flight, so a startup prewarm and a
    first request cannot both pay the cost.
    """
    from veritx_dse.gateway.staleness import newest_source_mtime
    with _LOOM_CAPABILITY_LOCK:
        key = newest_source_mtime()
        cached = _LOOM_CAPABILITY_CACHE.get("topology")
        if not refresh and cached is not None and cached[0] == key:
            return cached[1]
        table = loom_capabilities(include_topology_probe=True)
        _LOOM_CAPABILITY_CACHE["topology"] = (key, table)
        return table

def _prewarm_topology_probe() -> None:
    """Pay the one-time probe cost at startup, never on a page load."""
    try:
        _cached_topology_probe()
    except Exception:  # pragma: no cover - startup must never fail here
        logger.warning(
            "capability probe prewarm failed; it will run on demand",
            exc_info=True)


def _prewarm_read_paths(product: ProductService) -> None:
    """Warm the two read paths a first page load would otherwise pay cold.

    The topology probe compiles every registered family (~4 s) and the
    workload catalog materializes every registry workload once (module import
    plus a cold page cache: ~6 s on the first call, ~8 ms after). Both are
    read-only derivations of the tree on disk, so they are paid here, off the
    request path, rather than inside the first page load.
    """
    _prewarm_topology_probe()
    try:
        product.workload_catalog()
    except Exception:  # pragma: no cover - startup must never fail here
        logger.warning(
            "workload catalog prewarm failed; it will run on demand",
            exc_info=True)

# Read-only inventory of the artifacts the t3 report tools write. Three roots only: the generated
# dashboard/report tree, the tracks results tree (plots), and the analysis output tree (Pareto,
# area, energy, robustness figures). The endpoint never accepts a path from the client; report_id
# is a digest of a path the server itself enumerated.
_REPORT_ROOTS = (
    REPO / "report",
    REPO / "tracks" / "t3-topology" / "results",
    REPO / "tracks" / "t3-topology" / "output",
)
_REPORT_MEDIA = {
    ".html": "text/html",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}
_REPORT_MAX_BYTES = 25 * 1024 * 1024
_REPORT_LIMIT = 200


def _report_title(path: Path) -> str:
    if path.name == "index.html" and path.parent.name == "t3":
        return "T3 dashboard"
    known = {
        "latency_curves": "Latency–throughput curves",
        "pareto_by_size": "Pareto frontier by size",
        "pareto_latency_energy": "Pareto frontier · latency vs energy",
        "pareto_2d": "Pareto frontier · latency vs energy (PA-16)",
        "pareto_3d": "Pareto frontier · latency, energy, area (PA-18)",
    }
    if path.stem in known:
        return known[path.stem]
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else path.name


def _report_index() -> list[dict[str, Any]]:
    from datetime import datetime, timezone
    entries: list[dict[str, Any]] = []
    for root in _REPORT_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if len(entries) >= _REPORT_LIMIT:
                break
            if not path.is_file():
                continue
            media = _REPORT_MEDIA.get(path.suffix.lower())
            if media is None:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size <= 0 or stat.st_size > _REPORT_MAX_BYTES:
                continue
            relative = path.relative_to(REPO).as_posix()
            dashboard = path.name == "index.html" and path.parent.name == "t3"
            entries.append({
                "report_id": hashlib.sha256(relative.encode()).hexdigest()[:16],
                "title": _report_title(path),
                "kind": ("dashboard" if dashboard
                         else "image" if media.startswith("image/")
                         else "report"),
                "media_type": media,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc).isoformat(),
                "source_path": relative,
            })
    entries.sort(key=lambda entry: (
        0 if entry["kind"] == "dashboard" else 1, entry["source_path"]))
    return entries


def _report_file(report_id: str) -> tuple[Path, dict[str, Any]]:
    for entry in _report_index():
        if entry["report_id"] != report_id:
            continue
        path = (REPO / entry["source_path"]).resolve()
        if any(path.is_relative_to(root.resolve()) for root in _REPORT_ROOTS):
            return path, entry
        break
    raise NotFound(f"report {report_id!r} is not in an allowed report root")

def create_app(config: GatewayConfig | None = None) -> FastAPI:
    from contextlib import asynccontextmanager
    cfg = config or config_from_env()
    projects_root = cfg.projects_root or (cfg.store_root / "projects")
    product = ProductService(ProductConfig(
        projects_root=projects_root, booksim_bin=cfg.booksim_bin,
        astra_bin=cfg.astra_bin,
        network_clock_hz=cfg.network_clock_hz, timeout_s=cfg.timeout_s,
        sample_period_cycles=cfg.sample_period_cycles,
        series_link_width_bits=cfg.series_link_width_bits,
        series_flit_width_bits=cfg.series_flit_width_bits,
        series_store_dir=cfg.series_store_dir))
    @asynccontextmanager
    async def lifespan(_app):
        try:
            if cfg.prewarm_capability_probe:
                threading.Thread(target=_prewarm_read_paths,
                                 args=(product,),
                                 name="loom-capability-prewarm",
                                 daemon=True).start()
            yield
        finally:
            product.jobs.shutdown()

    app = FastAPI(title="VERITX Studio Gateway", version="1.0.0", lifespan=lifespan)
    app.state.product = product

    @app.get("/api/v1/health", tags=["product"])
    def v1_health() -> dict[str, Any]:
        """Liveness PLUS code staleness.

Rationale: docs/decisions/modules/gateway.md
        """
        info = staleness()
        status = "stale" if info.get("stale") else "ok"
        return {"status": status, "api": "v1", "code": info,
                "features": {"draft_preconditions": True,
                             "optimization_adoption_preconditions": True,
                             "artifact_bytes": True, "job_events": True,
                             "job_logs": True, "agent_runtime": True},
                "backends": _backend_presence(cfg)}

    @app.get("/api/v1/qualification", tags=["product"])
    def v1_qualification() -> dict[str, Any]:
        return qualification_view()

    @app.get("/api/v1/capabilities", tags=["product"])
    def v1_capabilities() -> dict[str, Any]:
        return capability_registry()

    @app.get("/api/v1/loom/capabilities", tags=["product"])
    def v1_loom_capabilities(
            include_topology_probe: bool = True,
            refresh: bool = False) -> dict[str, Any]:
        """The ONE capability table a Loom client may read.

        Every status here is decided server-side. The topology rows are
        PROBED — the compiler, the profile selector and the execution handlers
        are actually run for each registered family — so the table cannot claim
        a capability the compiler does not have. ``check_capability_truth.py``
        enforces the same invariant at build time.

        The probe is expensive, so ``include_topology_probe=false`` returns the
        static rows alone for callers that will not render a topology
        selector. A client that offers a topology choice MUST read the probed
        table and must not fall back to a name list. A probed table is
        memoized for this process (see ``_cached_topology_probe``);
        ``refresh=true`` re-probes explicitly.
        """
        if not include_topology_probe:
            return loom_capabilities(include_topology_probe=False)
        if refresh:
            _LOOM_CAPABILITY_CACHE.pop("topology", None)
        return _cached_topology_probe(refresh=refresh)

    @app.get("/api/v1/loom/provenance", tags=["product"])
    def v1_loom_provenance() -> dict[str, Any]:
        """The value-provenance vocabulary, served so a client renders
        origin and freshness labels from one source rather than its own."""
        return provenance_registry()

    @app.get("/api/v1/loom/origin", tags=["product"])
    def v1_loom_origin() -> dict[str, Any]:
        """The value origin and freshness vocabulary under the current name.

        The older /loom/provenance path remains for existing clients; the
        payload is identical.
        """
        return provenance_registry()

    @app.get("/api/v1/analysis/topology-sweep", tags=["product"])
    def v1_topology_sweep() -> Response:
        from veritx_dse.gateway.sweeps import latest_topology_sweep

        return JSONResponse(latest_topology_sweep(REPO),
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/reports", tags=["product"])
    def v1_reports() -> dict[str, Any]:
        """Generated dashboard, report and plot inventory.

        Only the two enumerated roots are scanned; the response carries a
        digest id and a read-only content URL. A client never supplies a
        filesystem path.
        """
        return {"contract_version": 1, "reports": _report_index()}

    @app.get("/api/v1/reports/{report_id}", tags=["product"])
    def v1_report(report_id: str) -> Response:
        """Serve one enumerated report or plot.

        HTML reports carry a script-only CSP sandbox so an opened report
        cannot reach the Studio origin. The files are the tools' own output;
        the gateway does not rewrite their content.
        """
        path, entry = _report_file(report_id)
        headers = {"Cache-Control": "no-store"}
        if entry["media_type"] == "text/html":
            # The generated dashboard stores its theme in localStorage, which a
            # sandboxed document refuses without allow-same-origin. The report is
            # a trusted local tool output served from the gateway origin and is
            # opened as a top-level tab, so this remains a script-only sandbox
            # without granting access to the Studio origin (a different origin).
            headers["Content-Security-Policy"] = (
                "sandbox allow-scripts allow-popups allow-same-origin")
        return FileResponse(path, media_type=entry["media_type"],
                            headers=headers)

    @app.get("/api/v1/loom/simulation/load", tags=["product"])
    def v1_loom_sim_load(run: str,
                          source: str = "measured") -> dict[str, Any]:
        """Per-channel utilization table for one run, most-loaded first.

        ``source=measured`` is served from the sampled-counters artifact.
        ``source=derived`` has no server-side producer and is refused —
        derived load remains the Studio client's own derivation."""
        from veritx_dse.gateway.simulation_series import (
            load_table,
            resolve_series_run,
        )
        return load_table(
            cfg.runs_root, run, source,
            resolve_run=lambda rid: resolve_series_run(product, rid))

    @app.get("/api/v1/loom/simulation/series", tags=["product"])
    def v1_loom_sim_series(run: str,
                            source: str | None = None) -> dict[str, Any]:
        """The full sampled window series for scrubbing (measured only).

        Derived data has no time axis: ``source=derived`` answers
        NO_TIME_AXIS, never a flat line."""
        from veritx_dse.gateway.simulation_series import (
            resolve_series_run,
            series_payload,
        )
        return series_payload(
            cfg.runs_root, run, source,
            resolve_run=lambda rid: resolve_series_run(product, rid))

    @app.get("/api/v1/loom/simulation/link", tags=["product"])
    def v1_loom_sim_link(run: str, channel: str) -> dict[str, Any]:
        """Selected-link detail. Absent segments (e.g. the wait/Tx
        breakdown) are named nulls, never interpolated values."""
        from veritx_dse.gateway.simulation_series import (
            link_detail,
            resolve_series_run,
        )
        return link_detail(
            cfg.runs_root, run, channel,
            resolve_run=lambda rid: resolve_series_run(product, rid))

    @app.post("/api/v1/loom/design/simulate", tags=["product"])
    def v1_design_simulate(body: DesignSimBody) -> dict[str, Any]:
        """Run trace-sized candidate fabrics through BookSim.

        The trace is resolved through a stored product run's bundle; the
        candidates are bounded family/side/VC declarations.  Results are
        cycle-level trace replay, never a silicon measurement.
        """
        return run_design_simulation(
            body, roots=(cfg.store_root, cfg.runs_root), product=product,
            booksim_bin=cfg.booksim_bin)

    @app.get("/api/v1/federation/backends", tags=["product"])
    def v1_federation_backends() -> dict[str, Any]:
        """Per-backend federation truth: registration (declared
        capabilities) plus install-presence facts only. No runtime-readiness
        fact is served here; readiness belongs to the evaluation plan for a
        real canonical context."""
        return product.federation_backends()

    @app.get("/api/v1/validation", tags=["product"])
    def v1_validation() -> dict[str, Any]:
        return validation_campaigns()

    @app.get("/api/v1/catalog/workloads", tags=["product"])
    def v1_workloads() -> dict[str, Any]:
        return product.workload_catalog()

    @app.get("/api/v1/workloads/{workload_id}/lowering", tags=["product"])
    def v1_workload_lowering(workload_id: str) -> dict[str, Any]:
        return product.workload_lowering(workload_id)

    @app.get("/api/v1/catalog/capability-gaps", tags=["product"])
    def v1_capability_gaps() -> dict[str, Any]:
        """Missing capabilities, derived from the refusal sites."""
        return product.capability_gaps()

    @app.get("/api/v1/catalog/execution-evidence", tags=["product"])
    def v1_execution_evidence() -> dict[str, Any]:
        """Executed configurations with their authored knobs and metrics."""
        return product.execution_evidence()

    @app.get("/api/v1/catalog/knob-inventory", tags=["product"])
    def v1_knob_inventory() -> dict[str, Any]:
        """The authorable knob surface, derived from the engine model."""
        return product.knob_inventory()

    @app.get("/api/v1/catalog/rtl-sources", tags=["product"])
    def v1_rtl_sources() -> dict[str, Any]:
        from veritx_dse.product.chipyard_sources import source_inventory
        return source_inventory()

    @app.get("/api/v1/catalog/rtl-sources/archive", tags=["product"])
    def v1_rtl_sources_archive():
        from veritx_dse.product.chipyard_sources import ChipyardSourceError, source_archive
        try:
            data = source_archive()
        except (ChipyardSourceError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="chipyard-all-14-sources.zip"',
            "Cache-Control": "no-store",
        })

    @app.get("/api/v1/catalog/rtl-prototypes", tags=["product"])
    def v1_rtl_prototypes() -> dict[str, Any]:
        """Current research RTL filesystem evidence; not product RTL."""
        return product.catalog_rtl_prototypes()

    @app.get("/api/v1/catalog/final-implementation", tags=["product"])
    def v1_final_implementation() -> dict[str, Any]:
        """Recorded composed-family (A1-A10) evidence; not a selected-project claim."""
        from veritx_dse.product.final_evidence import composed_family_evidence
        return composed_family_evidence()

    @app.get("/api/v1/catalog/rtl-prototypes/{topology_id}/artifacts/{name}", tags=["product"])
    def v1_rtl_prototype_artifact(topology_id: str, name: str, version: str = "") -> StreamingResponse:
        """Stream one server-allowlisted research artifact by opaque catalog ID."""
        from veritx_dse.product.rtl_prototypes import stream_artifact
        try:
            chunks, size = stream_artifact(topology_id, name, version)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown research artifact") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Research artifact unavailable or stale") from exc
        return StreamingResponse(chunks, media_type="application/octet-stream", headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Length": str(size), "X-Content-Type-Options": "nosniff",
        })

    @app.get("/api/v1/ablations/catalog", tags=["product"])
    def v1_ablation_catalog() -> dict[str, Any]:
        return ablation_catalog()

    @app.post("/api/v1/ablations", tags=["product"])
    def v1_run_ablation(body: AblationBody | None = None) -> Any:
        """Run a bounded workload × topology trace ablation.

        The request names workloads and topologies from the bundled catalog;
        the gateway invokes the same CLI runner and returns its measured
        document. It never accepts a free-form command or output path.
        """
        return run_ablation(body.model_dump() if body else None)

    @app.get("/api/v1/catalog/fabric-presets", tags=["product"])
    def v1_presets() -> dict[str, Any]:
        return product.fabric_presets()

    @app.get("/api/v1/catalog/fabric-presets/{preset_id}/graph",
             tags=["product"])
    def v1_preset_graph(preset_id: str) -> dict[str, Any]:
        """A shipped preset's materialized graph for graph seeding.

        Compiled in memory from the preset's canonical request; a
        preset that does not compile refuses with its stage and
        reason instead of a partial graph."""
        return product.preset_graph(preset_id)

    @app.get("/api/v1/catalog/serving-configs", tags=["product"])
    def v1_serving_configs() -> dict[str, Any]:
        """Cluster service-semantics configs and request traces the
        canonical serve path can be pointed at, with the tracked defaults."""
        return product.serving_config_catalog()

    @app.get("/api/v1/catalog/hardware-profiles", tags=["product"])
    def v1_hardware_profiles() -> dict[str, Any]:
        """Hardware profiles derived from tracked measured sources (serving
        cluster configs + profiler meta). Every field states whether an
        authority consumes it; the profile is descriptive at design time."""
        from veritx_dse.application.hardware_profiles import (
            hardware_profile_catalog,
        )
        return hardware_profile_catalog()

    @app.get("/api/v1/catalog/serving-experiments", tags=["product"])
    def v1_serving_experiments() -> dict[str, Any]:
        """Runnable serving experiments: on-disk cluster configs
        crossed with on-disk request traces, facet labels derived from
        geometry and asset names, install-fact readiness per entry, and
        explicit gaps for model configs no cluster file references."""
        return product.serving_experiment_catalog()

    @app.get("/api/v1/catalog/deployment-models", tags=["product"])
    def v1_deployment_models() -> dict[str, Any]:
        """Selectable LLMServingSim model configs with derived geometry."""
        from veritx_dse.application.deployment_builder import (
            deployment_model_catalog,
        )
        return deployment_model_catalog(product.config.repo_root)

    @app.get("/api/v1/catalog/deployment-hardware", tags=["product"])
    def v1_deployment_hardware() -> dict[str, Any]:
        """Serving hardware profiles merged with declared datasheet facts."""
        from veritx_dse.application.deployment_builder import (
            deployment_hardware_catalog,
        )
        return deployment_hardware_catalog(product.config.repo_root)

    @app.post("/api/v1/deployment-intent/preview", tags=["product"])
    def v1_deployment_preview(
            body: DeploymentPreviewBody) -> dict[str, Any]:
        """Preview a deployment as a schema-4 intent and compile verdict.

        Refusals are reported in the body (status REFUSED), not as HTTP
        errors: the client renders the typed issues and disables creation.
        """
        from veritx_dse.application.deployment_builder import (
            preview_deployment_intent,
        )
        serving = product.serving_config_catalog()
        experiments = product.serving_experiment_catalog()
        trace_entries = list(serving["traces"]) + [
            {"source": entry["trace_source"],
             "trace_digest": entry["trace_digest"],
             "trace_id": entry["trace_id"]}
            for entry in experiments["experiments"]]
        return preview_deployment_intent(
            body=body.model_dump(),
            repo_root=product.config.repo_root,
            trace_entries=trace_entries)

    @app.post("/api/v1/projects", tags=["product"])
    def v1_create_project(body: CreateProjectBody) -> dict[str, Any]:
        return product.create_project(name=body.name,
                                      workload_id=body.workload_id)

    @app.post("/api/v1/projects/from-preset", tags=["product"])
    def v1_create_project_from_preset(
            body: CreateProjectFromPresetBody) -> dict[str, Any]:
        """Materialize a shipped preset as an editable, runnable project."""
        return product.create_project_from_preset(body.preset_id, body.name)

    @app.get("/api/v1/projects", tags=["product"])
    def v1_list_projects() -> dict[str, Any]:
        return product.list_projects()

    @app.get("/api/v1/projects/{project_id}", tags=["product"])
    def v1_project(project_id: str) -> dict[str, Any]:
        return product.project_view(project_id)

    @app.get("/api/v1/projects/{project_id}/obligations", tags=["product"])
    def v1_project_obligations(project_id: str) -> dict[str, Any]:
        """Open design obligations, distinct from capability gaps."""
        return product.project_obligations(project_id)

    @app.patch("/api/v1/projects/{project_id}", tags=["product"])
    def v1_rename_project(project_id: str,
                          body: RenameProjectBody) -> dict[str, Any]:
        return product.rename_project(project_id, body.name)

    @app.delete("/api/v1/projects/{project_id}", tags=["product"])
    def v1_delete_project(project_id: str) -> dict[str, Any]:
        return product.delete_project(project_id)

    @app.get("/api/v1/projects/{project_id}/draft", tags=["product"])
    def v1_draft(project_id: str) -> dict[str, Any]:
        return product.draft_view(project_id)

    @app.get("/api/v1/projects/{project_id}/design", tags=["product"])
    def v1_design(project_id: str,
                  presentation: str = "edit",
                  review_snapshot_hash: str | None = None) -> dict[str, Any]:
        """DesignViewV2 — authoring (edit) or the pre-compile boundary
        (review). One projection, not two models (Gate 7 §2/§51.1)."""
        return product.design_view_v2(
            project_id, presentation=presentation,
            review_snapshot_hash=review_snapshot_hash)

    @app.put("/api/v1/projects/{project_id}/draft", tags=["product"])
    def v1_put_draft(project_id: str, body: DraftBody) -> dict[str, Any]:
        return product.put_draft(project_id, body.request,
                                 body.expected_draft_design_hash)

    @app.get("/api/v1/projects/{project_id}/floorplan", tags=["product"])
    def v1_floorplan(project_id: str) -> dict[str, Any]:
        """Authored floorplan for the active topology, with derived area."""
        return product.get_floorplan(project_id)

    @app.put("/api/v1/projects/{project_id}/floorplan", tags=["product"])
    def v1_put_floorplan(project_id: str,
                         body: FloorplanBody) -> dict[str, Any]:
        return product.put_floorplan(
            project_id, body.model_dump(exclude_none=True))

    @app.delete("/api/v1/projects/{project_id}/floorplan", tags=["product"])
    def v1_delete_floorplan(project_id: str) -> dict[str, Any]:
        return product.delete_floorplan(project_id)

    @app.get("/api/v1/projects/{project_id}/draft-history", tags=["product"])
    def v1_draft_history(project_id: str) -> dict[str, Any]:
        return product.draft_history(project_id)

    @app.post("/api/v1/projects/{project_id}/draft-history/{snapshot_id}/restore", tags=["product"])
    def v1_restore_draft(project_id: str, snapshot_id: str, body: PinnedDraftBody) -> dict[str, Any]:
        return product.restore_draft(project_id, snapshot_id, body.expected_draft_design_hash)

    @app.post("/api/v1/projects/{project_id}/draft/ip-templates/stamp",
              tags=["product"])
    def v1_stamp_ip_template(project_id: str,
                             body: StampIpTemplateBody) -> dict[str, Any]:
        return product.stamp_ip_template_in_draft(
            project_id,
            expected_draft_design_hash=body.expected_draft_design_hash,
            template_id=body.template_id, instance_id=body.instance_id,
            address_base=body.address_base, address_size=body.address_size,
            clock_domain=body.clock_domain, power_domain=body.power_domain,
            initiator_group_index=body.initiator_group_index,
            access_permission=body.access_permission)

    @app.post("/api/v1/projects/{project_id}/design-preview", tags=["product"])
    def v1_design_preview(project_id: str, body: DesignPreviewBody) -> dict[str, Any]:
        return product.preview_design(project_id, body.request)

    @app.post("/api/v1/projects/{project_id}/topology-preview", tags=["product"])
    def v1_topology_preview(project_id: str,
                            body: TopologyPreviewBody) -> dict[str, Any]:
        return product.preview_topology(project_id, body.request, body.topology)

    @app.post("/api/v1/projects/{project_id}/workload", tags=["product"])
    def v1_select_workload(project_id: str,
                           body: SelectWorkloadBody) -> dict[str, Any]:
        return product.select_workload(project_id, body.workload_id)

    @app.post("/api/v1/projects/{project_id}/compile", tags=["product"])
    def v1_compile(project_id: str,
                   body: CompileDraftBody | None = None) -> dict[str, Any]:
        """Compile the draft into an immutable revision.

        ``expected_draft_design_hash`` binds the compile to the reviewed
        snapshot (Gate 7 §4, REV-D2). Omitting it compiles the current draft
        — the compatibility path — but the product flow always sends it.
        """
        return product.compile_draft(
            project_id,
            expected_draft_design_hash=(
                body.expected_draft_design_hash if body else None))

    @app.post("/api/v1/projects/{project_id}/revisions/{revision_id}/abstract-experiments", tags=["product"])
    async def v1_abstract_experiment(project_id: str, revision_id: str,
                                     request: Request) -> dict[str, Any]:
        from veritx_dse.application.abstract_experiment import MAX_BODY_BYTES
        from veritx_dse.application.errors import intent_error
        from starlette.concurrency import run_in_threadpool
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BODY_BYTES:
                raise intent_error("explicit experiment body exceeds 256 KiB")
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate experiment JSON key: " + key)
                result[key] = value
            return result
        try:
            document = json.loads(data, object_pairs_hook=unique_object,
                                  parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        except (ValueError, UnicodeError) as exc:
            raise intent_error("invalid explicit experiment JSON: " + str(exc)) from exc
        return await run_in_threadpool(product.abstract_experiment, project_id, revision_id, document)

    @app.get("/api/v1/revisions/{revision_id}", tags=["product"])
    def v1_revision(revision_id: str) -> dict[str, Any]:
        return product.get_revision(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/compilation", tags=["product"])
    def v1_revision_compilation(revision_id: str) -> dict[str, Any]:
        """Compatibility alias: returns the revision envelope (the same
        shape as GET .../revisions/{id}), NOT the CompileResult inspector
        shape — that lives at GET .../revisions/{id}/compile-result.
        The alias stays so existing readers keep working; new clients
        must use /compile-result.
        """
        return product.get_revision(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/topology", tags=["product"])
    def v1_revision_topology(revision_id: str) -> dict[str, Any]:
        return product.get_revision_topology(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/artifacts", tags=["product"])
    def v1_revision_artifacts(revision_id: str) -> dict[str, Any]:
        return product.get_revision_artifact_chain(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/compile-result", tags=["product"])
    def v1_revision_compile_result(revision_id: str) -> dict[str, Any]:
        """CompileResultView — the eight inspector groups under one Compile
        Result (Gate 8 §50), frozen at certification time."""
        return product.get_revision_compile_result(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/route", tags=["product"])
    def v1_revision_route(revision_id: str, routing_class: str | None = None,
                          src: int | None = None,
                          dst: int | None = None) -> dict[str, Any]:
        """The canonical DERIVED EXPECTED route for one (class, src, dst).

        A query over the route table frozen at certification time, never a
        re-derivation. Gate 8 §58: this is the expected state; a runtime
        observation is a different fact with its own scope.
        """
        return product.canonical_route(revision_id,
                                       routing_class=routing_class,
                                       src=src, dst=dst)

    @app.post("/api/v1/revisions/{revision_id}/uvm", tags=["product"])
    def v1_revision_uvm(revision_id: str) -> dict[str, Any]:
        """UvmGenerationView — UVM collateral derived from the compiled
        bundle (node count, K, VC structure and routing are evidence,
        never parameters), stamped with the revision's frozen identity.
        Non-grid fabrics refuse explicitly instead of guessing K."""
        return product.generate_revision_uvm(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/preflight", tags=["product"])
    def v1_revision_preflight(revision_id: str) -> dict[str, Any]:
        return product.revision_preflight(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/diff", tags=["product"])
    def v1_revision_diff(revision_id: str,
                         against: str | None = None) -> dict[str, Any]:
        """RevisionDiffView — DESIGN / DERIVED / CAPABILITY changes between
        two frozen compile results. The default basis is the predecessor
        in the project's revision order."""
        return product.revision_diff(revision_id, against)

    @app.get("/api/v1/projects/{project_id}/serving", tags=["product"])
    def v1_serving_list(project_id: str) -> dict[str, Any]:
        return {"contract_version": 1,
                "experiments": product.list_serving(project_id)}

    @app.post("/api/v1/projects/{project_id}/serving", tags=["product"])
    def v1_serving_submit(project_id: str,
                          body: ServingBody | None = None) -> dict[str, Any]:
        return product.submit_serving(project_id,
                                      body.model_dump() if body else None)

    @app.get("/api/v1/serving/{serving_id}", tags=["product"])
    def v1_serving_get(serving_id: str) -> dict[str, Any]:
        return product.get_serving(serving_id)

    @app.get("/api/v1/projects/{project_id}/serving-binding", tags=["product"])
    def v1_serving_binding_get(project_id: str) -> dict[str, Any]:
        return product.serving_binding(project_id)

    @app.post("/api/v1/projects/{project_id}/serving-binding",
              tags=["product"])
    def v1_serving_binding_set(
            project_id: str,
            body: ServingBindingBody | None = None) -> dict[str, Any]:
        return product.bind_serving(
            project_id, body.model_dump() if body else None)

    @app.delete("/api/v1/projects/{project_id}/serving-binding",
                tags=["product"])
    def v1_serving_binding_clear(project_id: str) -> dict[str, Any]:
        return product.clear_serving_binding(project_id)

    @app.get("/api/v1/revisions/{revision_id}/evaluation-plan",
            tags=["product"])
    def v1_evaluation_plan(revision_id: str,
                           questions: str | None = None,
                           backend: str | None = None) -> dict[str, Any]:
        """EvaluationPlanView — what this revision can run, per question.

        ``questions`` is a comma-separated question selection
        (default: all known questions); ``backend`` pins one explicit
        backend. Pure adjudication: never executes.
        """
        parsed = ([q.strip() for q in questions.split(",") if q.strip()]
                  if questions else None)
        return product.evaluation_plan(
            revision_id, questions=parsed, requested_backend=backend)

    @app.post("/api/v1/revisions/{revision_id}/evaluate", tags=["product"])
    def v1_evaluate(revision_id: str,
                    body: EvaluateBodyV1 | None = None) -> dict[str, Any]:
        payload = body or EvaluateBodyV1()
        return product.submit_evaluation(
            revision_id, questions=payload.questions,
            requested_backend=payload.backend)

    @app.post("/api/v1/revisions/{revision_id}/optimize", tags=["product"])
    def v1_optimize(revision_id: str,
                    body: OptimizeBodyV1) -> dict[str, Any]:
        return product.submit_optimization(revision_id, body.model_dump())

    @app.get("/api/v1/revisions/{revision_id}/chipyard-source/archive", tags=["product"])
    def v1_revision_chipyard_source_archive(revision_id: str):
        return Response(product.revision_chipyard_source_archive(revision_id),
                        media_type="application/zip", headers={
                            "Content-Disposition": 'attachment; filename="compiled-fabric-chipyard-source.zip"',
                            "Cache-Control": "no-store",
                        })

    @app.get("/api/v1/projects/{project_id}/rtl-readiness", tags=["product"])
    def v1_rtl_readiness(project_id: str) -> dict[str, Any]:
        return product.rtl_readiness(project_id)

    @app.post("/api/v1/projects/{project_id}/rtl-previews", tags=["product"], status_code=202)
    def v1_rtl_preview(project_id: str, body: RtlPreviewBody) -> dict[str, Any]:
        return product.submit_rtl_preview(project_id, body.expected_draft_design_hash, body.acknowledge_preview)

    @app.get("/api/v1/projects/{project_id}/rtl-previews/{job_id}", tags=["product"])
    def v1_rtl_preview_view(project_id: str, job_id: str) -> dict[str, Any]:
        return product.rtl_preview_view(project_id, job_id)

    @app.get("/api/v1/projects/{project_id}/rtl-previews/{job_id}/archive", tags=["product"])
    def v1_rtl_preview_archive(project_id: str, job_id: str):
        return FileResponse(product.rtl_preview_archive(project_id, job_id), media_type="application/zip", filename="topology-rtl-preview.zip")

    @app.get("/api/v1/projects/{project_id}/catalog-evaluation-plan", tags=["product"])
    def v1_catalog_plan(project_id: str) -> dict[str, Any]:
        return product.catalog_plan(project_id)

    @app.post("/api/v1/projects/{project_id}/catalog-evaluations", tags=["product"], status_code=202)
    def v1_catalog_submit(project_id: str, body: CatalogEvaluationBody) -> dict[str, Any]:
        return product.submit_catalog_evaluation(project_id, body.expected_draft_design_hash, body.topology_ids)

    @app.get("/api/v1/projects/{project_id}/catalog-evaluations/{job_id}", tags=["product"])
    def v1_catalog_view(project_id: str, job_id: str) -> dict[str, Any]:
        return product.catalog_evaluation_view(project_id, job_id)

    @app.post("/api/v1/projects/{project_id}/catalog-evaluations/{job_id}/candidates/{candidate_id}/select", tags=["product"])
    def v1_catalog_select(project_id: str, job_id: str, candidate_id: str, body: CatalogSelectionBody) -> dict[str, Any]:
        return product.select_catalog_fabric(project_id, job_id, candidate_id, body.expected_draft_design_hash, body.acknowledge_incomplete_backends)

    @app.get("/api/v1/projects/{project_id}/catalog-evaluations/{job_id}/artifact", tags=["product"])
    def v1_catalog_artifact(project_id: str, job_id: str, path: str):
        file = product.catalog_artifact(project_id, job_id, path)
        return FileResponse(file, media_type="application/octet-stream", filename=file.name)

    @app.get("/api/v1/agents/capabilities", tags=["product"])
    def v1_agent_capabilities() -> dict[str, Any]:
        from veritx_dse.product.agent_runtime import capabilities
        return capabilities()

    @app.post("/api/v1/agents/config", tags=["product"])
    def v1_agent_config(body: AgentConfigBody) -> dict[str, Any]:
        """Persist local model settings; environment variables still win."""
        from veritx_dse.optimization.ai_search import ProviderError, save_provider_config
        from veritx_dse.product.agent_runtime import capabilities
        try:
            path = save_provider_config(body.base_url, body.model, body.api_key)
        except ProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {"contract_version": 1, "saved": True,
                "config_path": str(path), **capabilities()}

    @app.post("/api/v1/projects/{project_id}/agent/chat", tags=["product"])
    def v1_agent_chat(project_id: str, body: AgentChatBody) -> dict[str, Any]:
        return product.agent_chat(project_id, **body.model_dump())

    @app.post("/api/v1/projects/{project_id}/agent/workload-proposals", tags=["product"])
    def v1_translate_workload(project_id: str, body: WorkloadTranslationBody) -> dict[str, Any]:
        return product.translate_workload(project_id, **body.model_dump())

    @app.post("/api/v1/projects/{project_id}/agent/workload-proposals/{proposal_id}/adopt", tags=["product"])
    def v1_adopt_workload(project_id: str, proposal_id: str, body: PinnedDraftBody) -> dict[str, Any]:
        return product.adopt_workload_proposal(project_id, proposal_id, body.expected_draft_design_hash)

    @app.get("/api/v1/ai-topology-search/capabilities", tags=["product"])
    def v1_ai_capabilities() -> dict[str, Any]:
        from veritx_dse.optimization.ai_search import capabilities
        return {**capabilities(), "backend_present": bool(cfg.booksim_bin and Path(cfg.booksim_bin).is_file())}

    @app.post("/api/v1/projects/{project_id}/compile-jobs", tags=["product"], status_code=202)
    def v1_compile_job(project_id: str, body: PinnedDraftBody) -> dict[str, Any]:
        return product.submit_compile(project_id, body.expected_draft_design_hash)

    @app.get("/api/v1/projects/{project_id}/jobs", tags=["product"])
    def v1_project_jobs(project_id: str, kind: str | None = None) -> dict[str, Any]:
        return product.list_project_jobs(project_id, kind)

    @app.post("/api/v1/projects/{project_id}/ai-topology-search", tags=["product"], status_code=202)
    def v1_ai_search(project_id: str, body: PinnedDraftBody) -> dict[str, Any]:
        return product.submit_ai_search(project_id, body.expected_draft_design_hash)

    @app.post("/api/v1/projects/{project_id}/ai-parameter-search", tags=["product"], status_code=202)
    def v1_parameter_search(project_id: str, body: PinnedDraftBody) -> dict[str, Any]:
        return product.submit_ai_search(project_id, body.expected_draft_design_hash, parameters_only=True)

    @app.get("/api/v1/projects/{project_id}/ai-topology-search/{job_id}", tags=["product"])
    def v1_ai_search_view(project_id: str, job_id: str) -> dict[str, Any]:
        return product.ai_search_view(project_id, job_id)

    @app.post("/api/v1/projects/{project_id}/ai-topology-search/{job_id}/candidates/{candidate_id}/adopt", tags=["product"])
    def v1_ai_adopt(project_id: str, job_id: str, candidate_id: str, body: PinnedDraftBody) -> dict[str, Any]:
        return product.adopt_ai_candidate(project_id, job_id, candidate_id, body.expected_draft_design_hash)

    @app.post("/api/v1/jobs/{job_id}/cancel", tags=["product"])
    def v1_cancel_job(job_id: str) -> dict[str, Any]:
        return product.cancel_job(job_id)

    @app.get("/api/v1/jobs/{job_id}", tags=["product"])
    def v1_job(job_id: str) -> dict[str, Any]:
        return product.get_job(job_id)

    @app.get("/api/v1/jobs/{job_id}/events", tags=["product"])
    async def v1_job_events(job_id: str, request: Request):
        import asyncio
        from starlette.concurrency import run_in_threadpool
        # Validate before starting the response so missing jobs remain HTTP errors,
        # then reuse that snapshot for the initial event instead of reading twice.
        initial = await run_in_threadpool(product.get_job, job_id)
        async def events():
            previous = None
            record = initial
            first = True
            while not await request.is_disconnected():
                if not first:
                    record = await run_in_threadpool(product.get_job, job_id)
                first = False
                encoded = json.dumps(record, sort_keys=True)
                if encoded != previous:
                    yield "event: job\ndata: " + encoded + "\n\n"
                    previous = encoded
                if record.get("state") in ("COMPLETED", "FAILED", "REFUSED", "CANCELLED"):
                    break
                await asyncio.sleep(1)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/v1/jobs/{job_id}/log", tags=["product"])
    def v1_job_log(job_id: str, offset: int = 0,
                   max_bytes: int = 65536) -> dict[str, Any]:
        return product.job_log(job_id, offset=offset, max_bytes=max_bytes)

    @app.get("/api/v1/jobs/{job_id}/log/events", tags=["product"])
    async def v1_job_log_events(job_id: str, request: Request):
        import asyncio
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(product.get_job, job_id)
        async def events():
            offset = 0
            previous_state = None
            while not await request.is_disconnected():
                record = await run_in_threadpool(
                    product.job_log, job_id, offset=offset, max_bytes=65536)
                if record.get("text"):
                    yield "event: log\ndata: " + json.dumps(
                        record, sort_keys=True) + "\n\n"
                if record.get("state") != previous_state:
                    previous_state = record.get("state")
                    yield "event: state\ndata: " + json.dumps({
                        "job_id": job_id, "state": previous_state,
                        "terminal": record.get("terminal"),
                        "available": record.get("available"),
                    }, sort_keys=True) + "\n\n"
                if record.get("eof"):
                    yield "event: end\ndata: " + json.dumps({
                        "job_id": job_id, "state": record.get("state"),
                        "size": record.get("size"),
                    }, sort_keys=True) + "\n\n"
                    break
                offset = int(record.get("next_offset") or 0)
                await asyncio.sleep(0.5)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/v1/runs", tags=["product"])
    def v1_runs(project_id: str | None = None,
                revision_id: str | None = None) -> dict[str, Any]:
        return product.list_runs(project_id=project_id,
                                 revision_id=revision_id)

    @app.get("/api/v1/runs/{run_id}", tags=["product"])
    def v1_run(run_id: str) -> dict[str, Any]:
        """The run view, plus a server-computed freshness verdict.

        The verdict is computed HERE rather than in a client because it is a
        relation between three server-owned facts: the revision the run
        executed, the revision currently active on the project, and whether the
        draft has uncompiled changes. A client that derives it locally can
        disagree with the server about whether a result is stale, which is the
        one thing a stale-result warning must never do.
        """
        run = product.get_run(run_id)
        freshness = run_freshness(product, run_id, run)
        if freshness is not None:
            run["freshness"] = freshness
        return run

    @app.get("/api/v1/runs/{run_id}/evidence", tags=["product"])
    def v1_run_evidence(run_id: str) -> dict[str, Any]:
        return product.run_evidence(run_id)

    @app.get("/api/v1/runs/{run_id}/artifacts", tags=["product"])
    def v1_run_artifacts(run_id: str) -> dict[str, Any]:
        return product.run_artifacts(run_id)

    @app.get("/api/v1/runs/{run_id}/artifact", tags=["product"])
    def v1_run_artifact(run_id: str, path: str) -> Response:
        from urllib.parse import quote
        data, digest = product.run_artifact_bytes(run_id, path)
        return Response(data, media_type="application/octet-stream", headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(path.rsplit("/", 1)[-1], safe=""),
            "X-Content-SHA256": digest, "ETag": f'"{digest}"',
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @app.get("/api/v1/runs/{run_id}/traffic-matrix", tags=["product"])
    def v1_run_traffic_matrix(run_id: str) -> dict[str, Any]:
        return product.run_traffic_matrix(run_id)

    @app.get("/api/v1/runs/{run_id}/integrity", tags=["product"])
    def v1_run_integrity(run_id: str) -> dict[str, Any]:
        return product.run_integrity(run_id)

    @app.post("/api/v1/runs/{run_id}/verify", tags=["product"])
    def v1_run_verify(run_id: str) -> dict[str, Any]:
        return product.verify_run(run_id)

    @app.post("/api/v1/runs/{run_id}/reproduce", tags=["product"])
    def v1_run_reproduce(run_id: str) -> dict[str, Any]:
        return product.submit_reproduction(run_id)
    @app.get("/api/v1/optimization/capabilities", tags=["product"])
    def v1_optimization_capabilities() -> dict[str, Any]:
        """What VERITX can actually optimize, derived from backend authority.

Rationale: docs/decisions/modules/gateway.md
        """
        from veritx_dse.optimization.capabilities import (
            optimization_capabilities,
        )
        return optimization_capabilities()

    @app.post(
        "/api/v1/optimizations/{optimization_id}/candidates/{candidate_id}/use",
        tags=["product"])
    def v1_use_candidate(optimization_id: str, candidate_id: str,
                         body: PinnedDraftBody | None = None) -> dict[str, Any]:
        """Adopt a studied candidate as the DRAFT.

        The base revision is NOT mutated: it stays immutable, and the user
        must explicitly compile before a new revision exists.
        """
        return product.use_candidate(optimization_id, candidate_id,
                                     body.expected_draft_design_hash if body else None)

    @app.get("/api/v1/optimizations/{optimization_id}", tags=["product"])
    def v1_optimization(optimization_id: str) -> dict[str, Any]:
        return product.get_optimization(optimization_id)

    @app.get("/api/v1/compare", tags=["product"])
    def v1_compare(a: str, b: str) -> dict[str, Any]:
        return product.compare(a, b)

    from veritx_dse.gateway.vnext import register_vnext_routes
    register_vnext_routes(app)

    @app.get("/health", deprecated=True)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/qualification", deprecated=True)
    def qualification() -> dict[str, Any]:
        return qualification_view()

    @app.get("/workloads", deprecated=True)
    def workloads() -> dict[str, Any]:
        return _workloads(cfg)

    @app.post("/compile", deprecated=True)
    def compile_(body: CompileBody) -> dict[str, Any]:
        return _compile(cfg, body)

    @app.get("/revisions", deprecated=True)
    def revisions() -> dict[str, Any]:
        store = RevisionStore(cfg.revisions_dir)
        return {"revisions": [
            {"revision_id": rid}
            for rid in store.list_ids()]}

    @app.get("/revisions/{revision_id}", deprecated=True)
    def revision(revision_id: str) -> dict[str, Any]:
        rev, request, compilation = _load_revision(cfg, revision_id)
        design, compilation_projection = _views(request, compilation)
        return {
            "revision_id": rev.revision_id,
            "design_hash": rev.design_hash,
            "resolved_fabric_hash": rev.resolved_fabric_hash,
            "intent": rev.intent,
            "design_view": design,
            "compilation_view": compilation_projection,
        }

    @app.get("/runs", deprecated=True)
    def runs() -> dict[str, Any]:
        return {"runs": _list_runs(cfg)}

    @app.get("/runs/{run_id}", deprecated=True)
    def run(run_id: str) -> dict[str, Any]:
        path = _run_dir(cfg, run_id)
        try:
            summary = verify_run_bundle(path)
        except RunBundleError as exc:
            raise Conflict(str(exc)) from exc
        manifest = path / "manifest.json"
        doc = json.loads(manifest.read_text()) if manifest.is_file() else None
        return {"run_id": run_id, **summary, "manifest": doc}

    @app.get("/runs/{run_id}/evidence", deprecated=True)
    def evidence(run_id: str) -> dict[str, Any]:
        path = _run_dir(cfg, run_id)
        try:
            verify_run_bundle(path)
        except RunBundleError as exc:
            raise Conflict(str(exc)) from exc
        ev = path / "backend-evidence.json"
        if not ev.is_file():
            raise NotFound("no evidence in run")
        return json.loads(ev.read_text())

    def _require_binary() -> Path:
        if cfg.booksim_bin is None or not Path(cfg.booksim_bin).is_file():
            raise BackendUnavailable(
                "no qualified backend configured (set VERITX_BOOKSIM_BIN)")
        return Path(cfg.booksim_bin)

    @app.post("/evaluate", deprecated=True)
    def evaluate(body: EvaluateBody) -> dict[str, Any]:
        binary = _require_binary()
        from veritx_dse.optimization.candidate import make_candidate
        from veritx_dse.optimization.real_evaluator import (
            RealCandidateEvaluator,
        )
        request = _canonical_request(cfg, body)
        from veritx_dse.core.errors import UnsupportedSemantics
        from veritx_dse.model.compile_model import CompileRequestV3
        if not isinstance(request, CompileRequestV3):
            raise UnsupportedSemantics(
                "evaluation requires a v3 design; this revision was "
                "compiled from a guided preset")
        port = RealCandidateEvaluator(
            binary=str(binary), run_root=str(cfg.runs_root / "_evaluate"),
            network_clock_hz=cfg.network_clock_hz, timeout_s=cfg.timeout_s)
        out = port.evaluate(make_candidate(request, body.patch))
        return {"status": out.status,
                "performance_result_id": out.performance_result_id,
                "objective_values": getattr(out, "objective_values", None),
                "error": out.error}

    async def _typed_error_response(exc: Exception) -> JSONResponse:
        status = http_status_for(exc)
        code = error_code_for(exc)
        if status is None:
            logger.exception("unhandled gateway error", exc_info=exc)
            return JSONResponse(
                status_code=500,
                content={"detail": "internal server error",
                         "code": "INTERNAL_ERROR"})
        if status >= 500:
            if isinstance(exc, OSError):
                # Storage faults keep their traceback: the detail names the
                # path, but only the stack says which writer reached it.
                logger.error("gateway storage failure %s: %s", code, exc,
                             exc_info=exc)
            else:
                logger.error("gateway typed failure %s: %s", code, exc)
        return JSONResponse(status_code=status,
                            content={"detail": str(exc), "code": code})

    from veritx_dse.gateway.simulation_series import SeriesRefusal
    for _typed in (Refusal, ControlPlaneError, BackendUnavailable,
                   EngineUnavailable, Conflict, NotFound, SeriesRefusal):
        async def _handler(request: Request, exc: Exception,
                           _t=_typed) -> JSONResponse:
            return await _typed_error_response(exc)

        app.add_exception_handler(_typed, _handler)

    @app.exception_handler(Exception)
    async def _internal_error_handler(request: Request,
                                      exc: Exception) -> JSONResponse:
        return await _typed_error_response(exc)

    return app

app = create_app()

warn_if_stale()
