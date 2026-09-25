"""veritx_dse.gateway — the live Studio gateway.

A thin FastAPI surface over canonical services and the product resource
layer (`veritx_dse.product`). HTTP handlers parse, validate API shape,
load resources, invoke application services, project canonical product
views and map typed failures to HTTP. NO scientific semantics live here.

The product API is versioned under ``/api/v1``. The older ad-hoc routes
(``/compile``, ``/evaluate``, ``/optimize``, ``/runs``, ``/workloads``,
``/qualification``) are retained as DEPRECATED aliases for one release;
they are not the long-term product API.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.core.run_bundle import (
    CHECKSUMS_NAME, RunBundleError, verify_run_bundle,
)
from veritx_dse.product.qualification import qualification_view
from veritx_dse.product.service import ProductConfig, ProductService

log = logging.getLogger("veritx.gateway")

#: Explicit HTTP boundary mapping. An unexpected exception is never in
#: this table: it escapes to the internal-error handler as 500.
_HTTP_BY_CODE = {
    ErrorCode.INVALID_INTENT: 400,
    ErrorCode.UNSUPPORTED_SEMANTICS: 422,
    ErrorCode.LOWERING_UNSUPPORTED: 422,
    ErrorCode.POLICY_REJECTED: 422,
    ErrorCode.COMPARISON_INCOMPATIBLE: 422,
    ErrorCode.EVIDENCE_INVALID: 422,
    ErrorCode.NO_FEASIBLE_DESIGN: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.EXECUTION_FAILED: 503,
    ErrorCode.EXECUTION_TIMEOUT: 504,
    ErrorCode.INTERNAL_ERROR: 500,
}


@dataclass(frozen=True)
class GatewayConfig:
    store_root: Path
    runs_root: Path
    booksim_bin: Path | None = None
    network_clock_hz: int = 1_000_000_000
    timeout_s: int = 600
    experiments_dir: Path | None = None
    projects_root: Path | None = None


def config_from_env() -> GatewayConfig:
    repo = Path(__file__).resolve().parents[3]
    store = os.environ.get("VERITX_STORE_ROOT")
    runs = os.environ.get("VERITX_RUNS_ROOT")
    projects = os.environ.get("VERITX_PROJECTS_ROOT")
    binary = os.environ.get("VERITX_BOOKSIM_BIN")
    store_root = Path(store) if store else repo / "runs" / "studio-store"
    return GatewayConfig(
        store_root=store_root,
        runs_root=Path(runs) if runs else repo / "runs" / "veritx-runs",
        booksim_bin=Path(binary) if binary else None,
        experiments_dir=repo / "validation" / "experiments",
        projects_root=Path(projects) if projects else store_root / "projects",
    )


# ── API bodies ────────────────────────────────────────────────────────────

class CreateProjectBody(BaseModel):
    name: str
    workload_id: str | None = None


class DraftBody(BaseModel):
    request: dict[str, Any]


class SelectWorkloadBody(BaseModel):
    workload_id: str


class RenameProjectBody(BaseModel):
    name: str


class EvaluateBodyV1(BaseModel):
    backend: str | None = None


class OptimizeBodyV1(BaseModel):
    domain: list[dict[str, Any]]
    objectives: list[dict[str, Any]] = [
        {"metric": "completion_cycles", "direction": "MIN"}]
    constraints: list[dict[str, Any]] = []
    method: str = "grid"
    selection: str | None = None
    seed: int | None = None


# legacy bodies (deprecated) ───────────────────────────────────────────────

class CompileBody(BaseModel):
    preset: str
    policy: str = "baseline_deterministic_v2"
    overrides: list[str] = []
    name: str | None = None


class EvaluateBody(BaseModel):
    request: dict[str, Any]
    patch: dict[str, Any] = {}


class OptimizeBody(BaseModel):
    request: dict[str, Any]
    domain: list[dict[str, Any]] = []
    objectives: list[dict[str, Any]] = [
        {"metric": "completion_cycles", "direction": "MIN"}]
    constraints: list[dict[str, Any]] = []


# ── legacy handlers (deprecated) ─────────────────────────────────────────

def _compile(config: GatewayConfig, body: CompileBody) -> dict[str, Any]:
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
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        service = SrotaControlPlane(store=ResourceStore(config.store_root))
        outcome = service.compile(intent)
    except ControlPlaneError as exc:
        raise HTTPException(status_code=422,
                            detail=f"{type(exc).__name__}: {exc}") from exc
    compiled = outcome.compiled
    return {
        "intent_id": outcome.intent_id,
        "design_hash": outcome.design_hash,
        "resolved_fabric_hash": outcome.resolved_fabric_hash,
        "topology_hash": compiled.topology.topology_hash(),
        "attachment_hash": compiled.attachment.attachment_hash(),
        "mapping_hash": compiled.mapping.mapping_hash(),
        "route_hash": compiled.routing.route.artifact_hash,
        "resolved_route_hash": compiled.routing.resolved_route.resolved_route_hash(),
        "vc_assignment_hash": compiled.routing.vc_assignment.vc_assignment_hash(),
        "fabric_hash": compiled.fabric.fabric_hash,
        "vc_count": compiled.vc_resource.vc_count,
    }


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
        raise HTTPException(status_code=400, detail="invalid run id")
    path = config.runs_root / run_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"no such run: {run_id}")
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


def create_app(config: GatewayConfig | None = None) -> FastAPI:
    cfg = config or config_from_env()
    projects_root = cfg.projects_root or (cfg.store_root / "projects")
    product = ProductService(ProductConfig(
        projects_root=projects_root, booksim_bin=cfg.booksim_bin,
        network_clock_hz=cfg.network_clock_hz, timeout_s=cfg.timeout_s))
    app = FastAPI(title="VERITX Studio Gateway", version="1.0.0")
    app.state.product = product

    # ── error boundary: typed control-plane failures only ─────────────
    @app.exception_handler(ControlPlaneError)
    async def _typed_error(request: Request, exc: ControlPlaneError):
        status = _HTTP_BY_CODE.get(exc.code, 500)
        return JSONResponse(status_code=status, content={
            "error": True, "code": exc.code.value, "message": exc.message,
            "operation": exc.operation, "resource_id": exc.resource_id})

    @app.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None) or str(
            uuid.uuid4())
        log.exception("internal error request_id=%s", request_id)
        return JSONResponse(status_code=500, content={
            "error": True, "code": ErrorCode.INTERNAL_ERROR.value,
            "message": "Internal VERITX error", "request_id": request_id})

    # ── product API v1 ────────────────────────────────────────────────
    @app.get("/api/v1/health", tags=["product"])
    def v1_health() -> dict[str, str]:
        return {"status": "ok", "api": "v1"}

    @app.get("/api/v1/qualification", tags=["product"])
    def v1_qualification() -> dict[str, Any]:
        return qualification_view()

    @app.get("/api/v1/catalog/workloads", tags=["product"])
    def v1_workloads() -> dict[str, Any]:
        return product.workload_catalog()

    @app.get("/api/v1/catalog/fabric-presets", tags=["product"])
    def v1_presets() -> dict[str, Any]:
        return product.fabric_presets()

    @app.post("/api/v1/projects", tags=["product"])
    def v1_create_project(body: CreateProjectBody) -> dict[str, Any]:
        return product.create_project(name=body.name,
                                      workload_id=body.workload_id)

    @app.get("/api/v1/projects", tags=["product"])
    def v1_list_projects() -> dict[str, Any]:
        return product.list_projects()

    @app.get("/api/v1/projects/{project_id}", tags=["product"])
    def v1_project(project_id: str) -> dict[str, Any]:
        return product.project_view(project_id)

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

    @app.put("/api/v1/projects/{project_id}/draft", tags=["product"])
    def v1_put_draft(project_id: str, body: DraftBody) -> dict[str, Any]:
        return product.put_draft(project_id, body.request)

    @app.post("/api/v1/projects/{project_id}/workload", tags=["product"])
    def v1_select_workload(project_id: str,
                           body: SelectWorkloadBody) -> dict[str, Any]:
        return product.select_workload(project_id, body.workload_id)

    @app.post("/api/v1/projects/{project_id}/compile", tags=["product"])
    def v1_compile(project_id: str) -> dict[str, Any]:
        return product.compile_draft(project_id)

    @app.get("/api/v1/revisions/{revision_id}", tags=["product"])
    def v1_revision(revision_id: str) -> dict[str, Any]:
        return product.get_revision(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/compilation", tags=["product"])
    def v1_revision_compilation(revision_id: str) -> dict[str, Any]:
        return product.get_revision(revision_id)

    @app.post("/api/v1/revisions/{revision_id}/evaluate", tags=["product"])
    def v1_evaluate(revision_id: str,
                    body: EvaluateBodyV1 | None = None) -> dict[str, Any]:
        return product.submit_evaluation(revision_id)

    @app.post("/api/v1/revisions/{revision_id}/optimize", tags=["product"])
    def v1_optimize(revision_id: str,
                    body: OptimizeBodyV1) -> dict[str, Any]:
        return product.submit_optimization(revision_id, body.model_dump())

    @app.get("/api/v1/jobs/{job_id}", tags=["product"])
    def v1_job(job_id: str) -> dict[str, Any]:
        return product.get_job(job_id)

    @app.get("/api/v1/runs", tags=["product"])
    def v1_runs(project_id: str | None = None,
                revision_id: str | None = None) -> dict[str, Any]:
        return product.list_runs(project_id=project_id,
                                 revision_id=revision_id)

    @app.get("/api/v1/runs/{run_id}", tags=["product"])
    def v1_run(run_id: str) -> dict[str, Any]:
        return product.get_run(run_id)

    @app.get("/api/v1/runs/{run_id}/evidence", tags=["product"])
    def v1_run_evidence(run_id: str) -> dict[str, Any]:
        return product.run_evidence(run_id)

    @app.get("/api/v1/runs/{run_id}/artifacts", tags=["product"])
    def v1_run_artifacts(run_id: str) -> dict[str, Any]:
        return product.run_artifacts(run_id)

    @app.get("/api/v1/optimizations/{optimization_id}", tags=["product"])
    def v1_optimization(optimization_id: str) -> dict[str, Any]:
        return product.get_optimization(optimization_id)

    @app.get("/api/v1/compare", tags=["product"])
    def v1_compare(a: str, b: str) -> dict[str, Any]:
        return product.compare(a, b)

    # ── deprecated aliases (one release) ──────────────────────────────
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

    @app.get("/runs", deprecated=True)
    def runs() -> dict[str, Any]:
        return {"runs": _list_runs(cfg)}

    @app.get("/runs/{run_id}", deprecated=True)
    def run(run_id: str) -> dict[str, Any]:
        path = _run_dir(cfg, run_id)
        try:
            summary = verify_run_bundle(path)
        except RunBundleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        manifest = path / "manifest.json"
        doc = json.loads(manifest.read_text()) if manifest.is_file() else None
        return {"run_id": run_id, **summary, "manifest": doc}

    @app.get("/runs/{run_id}/evidence", deprecated=True)
    def evidence(run_id: str) -> dict[str, Any]:
        path = _run_dir(cfg, run_id)
        try:
            verify_run_bundle(path)
        except RunBundleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        ev = path / "backend-evidence.json"
        if not ev.is_file():
            raise HTTPException(status_code=404, detail="no evidence in run")
        return json.loads(ev.read_text())

    def _require_binary() -> Path:
        if cfg.booksim_bin is None or not Path(cfg.booksim_bin).is_file():
            raise HTTPException(
                status_code=503,
                detail="no qualified backend configured "
                       "(set VERITX_BOOKSIM_BIN)")
        return Path(cfg.booksim_bin)

    @app.post("/evaluate", deprecated=True)
    def evaluate(body: EvaluateBody) -> dict[str, Any]:
        binary = _require_binary()
        from veritx_dse.model.compile_model import CompileRequestV3
        from veritx_dse.optimization.candidate import make_candidate
        from veritx_dse.optimization.real_evaluator import (
            RealCandidateEvaluator,
        )
        try:
            request = CompileRequestV3.from_dict(body.request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        port = RealCandidateEvaluator(
            binary=str(binary), run_root=str(cfg.runs_root / "_evaluate"),
            network_clock_hz=cfg.network_clock_hz, timeout_s=cfg.timeout_s)
        out = port.evaluate(make_candidate(request, body.patch))
        return {"status": out.status,
                "performance_result_id": out.performance_result_id,
                "objective_values": getattr(out, "objective_values", None),
                "error": out.error}

    @app.post("/optimize", deprecated=True)
    def optimize(body: OptimizeBody) -> dict[str, Any]:
        binary = _require_binary()
        from veritx_dse.model.compile_model import CompileRequestV3
        from veritx_dse.optimization.definition import (
            Constraint, DomainParam, Objective, OptimizationDefinition,
        )
        from veritx_dse.optimization.result import (
            CertifiedBackendConfig, Optimizer,
        )
        try:
            request = CompileRequestV3.from_dict(body.request)
            definition = OptimizationDefinition(
                domain=tuple(DomainParam(d["name"], tuple(d["values"]))
                             for d in body.domain),
                objectives=tuple(Objective(o["metric"], o["direction"])
                                 for o in body.objectives),
                constraints=tuple(Constraint(c["metric"], c["op"],
                                             c["threshold"])
                                  for c in body.constraints))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = Optimizer().optimize_certified(
            request, definition,
            backend_config=CertifiedBackendConfig(
                binary=str(binary), run_root=str(cfg.runs_root / "_optimize"),
                network_clock_hz=cfg.network_clock_hz,
                timeout_s=cfg.timeout_s))
        return result.to_study_view()

    return app


app = create_app()
