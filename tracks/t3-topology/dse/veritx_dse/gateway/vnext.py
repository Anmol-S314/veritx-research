"""veritx_dse.gateway.vnext — Studio vNext product routes.

Rationale: docs/decisions/modules/gateway.md
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel


class SynthesisBody(BaseModel):
    engine: str = "milp_tmcf"
    definition: dict[str, Any]
    traffic: dict[str, Any]
    seed: int = 7
    steps: int = 20
    horizon: int = 3
    branch: int = 4
    group: int = 4
    iters: int = 10
    max_edges: int = 120


class PromoteCandidateBody(BaseModel):
    project_id: str


def register_vnext_routes(app: FastAPI) -> FastAPI:
    """Attach the vNext product routes. Returns the app."""
    from veritx_dse.product import vnext as service

    def _product() -> Any:
        return app.state.product

    # ── synthesis ─────────────────────────────────────────────────
    @app.get("/api/v1/synthesis/engines", tags=["product"])
    def v1_synthesis_engines() -> dict[str, Any]:
        """Synthesis strategies with honest method scope + completeness."""
        return service.synthesis_engines()

    @app.post("/api/v1/revisions/{revision_id}/synthesize",
              tags=["product"])
    def v1_synthesize(revision_id: str,
                      body: SynthesisBody) -> dict[str, Any]:
        """Submit a topology-synthesis problem (job; candidate producer).

        Engines emit typed TopologyCandidates under the canonical
        synthesis definition. Screening uses the analytical generator
        objective; product evaluation happens after promotion through
        the ordinary compile path.
        """
        return service.submit_synthesis(
            _product(), revision_id, body.model_dump())

    @app.get("/api/v1/projects/{project_id}/syntheses", tags=["product"])
    def v1_syntheses(project_id: str) -> dict[str, Any]:
        return service.list_syntheses(_product(), project_id)

    @app.get("/api/v1/syntheses/{synthesis_id}", tags=["product"])
    def v1_synthesis(synthesis_id: str) -> dict[str, Any]:
        return service.get_synthesis(_product(), synthesis_id)

    @app.get("/api/v1/syntheses/{synthesis_id}/completeness",
             tags=["product"])
    def v1_synthesis_completeness(synthesis_id: str) -> dict[str, Any]:
        """EXHAUSTIVE vs BUDGETED vs UNBOUNDED wording, server-derived."""
        return service.synthesis_completeness(_product(), synthesis_id)

    # ── candidates ────────────────────────────────────────────────
    @app.get("/api/v1/candidates", tags=["product"])
    def v1_candidates(request: Request, origin: str | None = None,
                      engine: str | None = None,
                      method: str | None = None,
                      compiled: bool | None = None,
                      verified: bool | None = None,
                      evaluated: bool | None = None,
                      adopted: bool | None = None) -> dict[str, Any]:
        """Global candidate library with server-side filtering."""
        from veritx_dse.application.errors import intent_error

        known = {"origin", "engine", "method", "compiled",
                 "verified", "evaluated", "adopted"}
        unknown = sorted(set(request.query_params) - known)
        if unknown:
            raise intent_error(
                f"unknown candidate filter(s) {unknown}; supported: "
                f"{sorted(known)}")
        filters = {k: v for k, v in {
            "origin": origin, "engine": engine, "method": method,
            "compiled": compiled, "verified": verified,
            "evaluated": evaluated, "adopted": adopted,
        }.items() if v is not None}
        return service.list_candidates(_product(), filters)

    @app.get("/api/v1/candidates/{candidate_id}", tags=["product"])
    def v1_candidate(candidate_id: str) -> dict[str, Any]:
        """Candidate detail: graph, provenance, pipeline state, seed diff."""
        return service.get_candidate(_product(), candidate_id)

    @app.post("/api/v1/candidates/{candidate_id}/promote",
              tags=["product"])
    def v1_promote_candidate(candidate_id: str,
                             body: PromoteCandidateBody) -> dict[str, Any]:
        """Promote into an ordinary draft via the canonical primitive.

        Writes the draft only — an explicit Compile is required before
        a new immutable revision exists. Claims no certificate.
        """
        return service.promote_candidate(
            _product(), candidate_id, body.project_id)

    # ── capabilities ──────────────────────────────────────────────
    @app.get("/api/v1/capabilities/explorer", tags=["product"])
    def v1_capability_explorer() -> dict[str, Any]:
        """Every recorded capability: seven-stage ladder + maturity."""
        return service.capability_explorer()

    @app.get("/api/v1/capabilities/{capability_id}", tags=["product"])
    def v1_capability_detail(capability_id: str) -> dict[str, Any]:
        return service.capability_detail(capability_id)

    # ── metric authorities ────────────────────────────────────────
    @app.get("/api/v1/metrics/wave-e", tags=["product"])
    def v1_wave_e_metrics() -> dict[str, Any]:
        """Wave-E model metrics: MODELLED, UNCALIBRATED, never measured."""
        return service.wave_e_metrics()

    @app.get("/api/v1/metrics/federated", tags=["product"])
    def v1_federated_metrics() -> dict[str, Any]:
        return service.federated_metrics()

    @app.get("/api/v1/energy/authorities", tags=["product"])
    def v1_energy_authorities(
            family: str | None = None) -> dict[str, Any]:
        """Six energy/power authorities — separate, never one number."""
        return service.energy_authorities(family)

    # ── reuse + completeness ──────────────────────────────────────
    @app.get("/api/v1/runs/{run_id}/reuse", tags=["product"])
    def v1_run_reuse(run_id: str) -> dict[str, Any]:
        """Explicit cache-hit data: reused id or unavailable-with-reason."""
        return service.reuse_info(_product(), run_id)

    @app.get("/api/v1/optimizations/{optimization_id}/completeness",
             tags=["product"])
    def v1_optimization_completeness(
            optimization_id: str) -> dict[str, Any]:
        return service.optimization_completeness(
            _product(), optimization_id)

    return app


__all__ = ["register_vnext_routes", "SynthesisBody", "PromoteCandidateBody"]
