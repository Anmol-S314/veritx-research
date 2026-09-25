"""veritx_dse.gateway — the live Studio gateway (C9).

A thin FastAPI surface over canonical services. HTTP handlers parse a
request, call the same service the CLI calls, and return versioned results
plus the evidence ids the UI trust panel needs. NO scientific semantics
live here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from veritx_dse.core.run_bundle import (
    CHECKSUMS_NAME, RunBundleError, verify_run_bundle,
)
from veritx_dse.gateway.qualification import qualification_view


@dataclass(frozen=True)
class GatewayConfig:
    store_root: Path
    runs_root: Path
    booksim_bin: Path | None = None
    network_clock_hz: float = 1e9
    timeout_s: int = 600
    experiments_dir: Path | None = None


def config_from_env() -> GatewayConfig:
    repo = Path(__file__).resolve().parents[3]
    store = os.environ.get("VERITX_STORE_ROOT")
    runs = os.environ.get("VERITX_RUNS_ROOT")
    binary = os.environ.get("VERITX_BOOKSIM_BIN")
    return GatewayConfig(
        store_root=Path(store) if store else repo / "runs" / "studio-store",
        runs_root=Path(runs) if runs else repo / "runs" / "veritx-runs",
        booksim_bin=Path(binary) if binary else None,
        experiments_dir=repo / "validation" / "experiments",
    )


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
    except Exception as exc:  # noqa: BLE001 - typed service refusal
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
    # never allow path traversal out of the runs root
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

    @app.get("/runs")
    def runs() -> dict[str, Any]:
        return {"runs": _list_runs(cfg)}

    @app.get("/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        path = _run_dir(cfg, run_id)
        try:
            summary = verify_run_bundle(path)
        except RunBundleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        manifest = path / "manifest.json"
        doc = json.loads(manifest.read_text()) if manifest.is_file() else None
        return {"run_id": run_id, **summary, "manifest": doc}

    @app.get("/runs/{run_id}/evidence")
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

    @app.post("/evaluate")
    def evaluate(body: EvaluateBody) -> dict[str, Any]:
        binary = _require_binary()
        from veritx_dse.model.compile_model import CompileRequestV3
        from veritx_dse.optimization.candidate import make_candidate
        from veritx_dse.optimization.real_evaluator import (
            RealCandidateEvaluator,
        )
        try:
            request = CompileRequestV3.from_dict(body.request)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        except Exception as exc:  # noqa: BLE001
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
