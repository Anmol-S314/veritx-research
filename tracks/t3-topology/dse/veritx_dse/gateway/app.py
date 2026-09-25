"""veritx_dse.gateway — the live Studio gateway (C9).

A thin FastAPI surface over canonical services. HTTP handlers parse a
request, call the same service the CLI calls, and return versioned results
plus the evidence ids the UI trust panel needs. NO scientific semantics
live here.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from veritx_dse.application.errors import ControlPlaneError
from veritx_dse.core.errors import InvalidInput, Refusal
from veritx_dse.core.run_bundle import (
    CHECKSUMS_NAME, RunBundleError, verify_run_bundle,
)
from veritx_dse.gateway.errors import (
    BackendUnavailable, Conflict, NotFound, error_code_for, http_status_for,
)
from veritx_dse.gateway.qualification import qualification_view
from veritx_dse.gateway.revisions import (
    Revision, RevisionStore, revision_id_for,
)

logger = logging.getLogger("veritx.gateway")


@dataclass(frozen=True)
class GatewayConfig:
    store_root: Path
    runs_root: Path
    booksim_bin: Path | None = None
    network_clock_hz: float = 1e9
    timeout_s: int = 600
    experiments_dir: Path | None = None
    revisions_root: Path | None = None

    @property
    def revisions_dir(self) -> Path:
        return self.revisions_root or (
            self.store_root.parent / "studio-revisions")


def config_from_env() -> GatewayConfig:
    repo = Path(__file__).resolve().parents[3]
    store = os.environ.get("VERITX_STORE_ROOT")
    runs = os.environ.get("VERITX_RUNS_ROOT")
    revisions = os.environ.get("VERITX_REVISIONS_ROOT")
    binary = os.environ.get("VERITX_BOOKSIM_BIN")
    store_root = Path(store) if store else repo / "runs" / "studio-store"
    return GatewayConfig(
        store_root=store_root,
        runs_root=Path(runs) if runs else repo / "runs" / "veritx-runs",
        booksim_bin=Path(binary) if binary else None,
        experiments_dir=repo / "validation" / "experiments",
        revisions_root=(Path(revisions) if revisions
                        else store_root.parent / "studio-revisions"),
    )


class CompileBody(BaseModel):
    #: guided preset intent (engine derives the canonical request), OR
    #: a v3 Studio design document supplied by an engine-authored template.
    preset: str | None = None
    policy: str = "baseline_deterministic_v2"
    overrides: list[str] = []
    name: str | None = None
    request: dict[str, Any] | None = None


class EvaluateBody(BaseModel):
    #: evaluate an immutable revision (preferred); the gateway re-derives the
    #: canonical request. Raw ``request`` is a compatibility path only.
    revision_id: str | None = None
    request: dict[str, Any] = {}
    patch: dict[str, Any] = {}


class OptimizeBody(BaseModel):
    revision_id: str | None = None
    request: dict[str, Any] = {}
    domain: list[dict[str, Any]] = []
    objectives: list[dict[str, Any]] = [
        {"metric": "completion_cycles", "direction": "MIN"}]
    constraints: list[dict[str, Any]] = []


def _compile_design(config: GatewayConfig, body: CompileBody):
    """Compile one design to (canonical request, Compilation, design_hash,
    resolved_fabric_hash). Two engine-authored paths, one product boundary.

    * a v3 ``request`` document compiles through ``FabricCompiler`` directly;
    * a guided ``preset`` compiles through ``SrotaControlPlane`` (which
      commits a resolution) and is projected through ``FabricCompiler``; the
      two identities are asserted equal so there is no second authority.
    """
    from veritx_dse.application.fabric_compiler import FabricCompiler

    if body.request is not None:
        from veritx_dse.model.compile_model import CompileRequestV3
        try:
            request = CompileRequestV3.from_dict(body.request)
        except (ValueError, KeyError, InvalidInput) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    # never allow path traversal out of the runs root
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


def create_app(config: GatewayConfig | None = None) -> FastAPI:
    cfg = config or config_from_env()
    app = FastAPI(title="VERITX Studio Gateway", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/qualification")
    def qualification() -> dict[str, Any]:
        return qualification_view()

    @app.get("/workloads")
    def workloads() -> dict[str, Any]:
        return _workloads(cfg)

    @app.post("/compile")
    def compile_(body: CompileBody) -> dict[str, Any]:
        return _compile(cfg, body)

    @app.get("/revisions")
    def revisions() -> dict[str, Any]:
        store = RevisionStore(cfg.revisions_dir)
        return {"revisions": [
            {"revision_id": rid}
            for rid in store.list_ids()]}

    @app.get("/revisions/{revision_id}")
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

    @app.get("/runs")
    def runs() -> dict[str, Any]:
        return {"runs": _list_runs(cfg)}

    @app.get("/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        path = _run_dir(cfg, run_id)
        try:
            summary = verify_run_bundle(path)
        except RunBundleError as exc:
            raise Conflict(str(exc)) from exc
        manifest = path / "manifest.json"
        doc = json.loads(manifest.read_text()) if manifest.is_file() else None
        return {"run_id": run_id, **summary, "manifest": doc}

    @app.get("/runs/{run_id}/evidence")
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

    @app.post("/evaluate")
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

    @app.post("/optimize")
    def optimize(body: OptimizeBody) -> dict[str, Any]:
        binary = _require_binary()
        from veritx_dse.optimization.definition import (
            Constraint, DomainParam, Objective, OptimizationDefinition,
        )
        from veritx_dse.optimization.result import (
            CertifiedBackendConfig, Optimizer,
        )
        request = _canonical_request(cfg, body)
        try:
            definition = OptimizationDefinition(
                domain=tuple(DomainParam(d["name"], tuple(d["values"]))
                             for d in body.domain),
                objectives=tuple(Objective(o["metric"], o["direction"])
                                 for o in body.objectives),
                constraints=tuple(Constraint(c["metric"], c["op"],
                                             c["threshold"])
                                  for c in body.constraints))
        except (ValueError, KeyError, TypeError, InvalidInput) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = Optimizer().optimize_certified(
            request, definition,
            backend_config=CertifiedBackendConfig(
                binary=str(binary), run_root=str(cfg.runs_root / "_optimize"),
                network_clock_hz=cfg.network_clock_hz,
                timeout_s=cfg.timeout_s))
        return result.to_study_view()

    async def _typed_error_response(exc: Exception) -> JSONResponse:
        status = http_status_for(exc)
        code = error_code_for(exc)
        if status is None:
            # not a declared failure: a programmer fault is a logged 500
            logger.exception("unhandled gateway error", exc_info=exc)
            return JSONResponse(
                status_code=500,
                content={"detail": "internal server error",
                         "code": "INTERNAL_ERROR"})
        if status >= 500:
            logger.error("gateway typed failure %s: %s", code, exc)
        return JSONResponse(status_code=status,
                            content={"detail": str(exc), "code": code})

    # Typed failures are registered as exception handlers so Starlette's
    # ExceptionMiddleware returns the mapped status (only the bare Exception
    # case falls through to the 500 ServerErrorMiddleware).
    for _typed in (Refusal, ControlPlaneError, BackendUnavailable,
                   Conflict, NotFound):
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
