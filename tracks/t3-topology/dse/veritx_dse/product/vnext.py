"""veritx_dse.product.vnext — Studio vNext product surface.

Rationale: docs/decisions/modules/product.md
"""
from __future__ import annotations

from typing import Any

from veritx_dse.application.errors import intent_error

ENGINE_METHODS: tuple[dict[str, Any], ...] = (
    {
        "engine": "milp_tmcf",
        "label": "Exact / MILP",
        "scope": "exact formulation within the declared formulation and solve status",
        "completeness": "UNBOUNDED",
        "optimality": "OPTIMAL only when the solver proves it; TIME_LIMIT incumbents are never OPTIMAL",
    },
    {
        "engine": "bo_gp",
        "label": "Bayesian topology synthesis",
        "scope": "surrogate-guided exploration of the declared 5-D generator space",
        "completeness": "BUDGETED",
        "optimality": "best observed under the candidate budget; surrogate honesty rides on the proposal",
    },
    {
        "engine": "rho_iterative",
        "label": "Rolling Horizon",
        "scope": "local graph mutation with finite-horizon rollout",
        "completeness": "UNBOUNDED",
        "optimality": "best observed among evaluated candidates",
    },
    {
        "engine": "grpo_group",
        "label": "GRPO-style group search",
        "scope": "group-relative candidate exploration (a selection discipline, not a trained policy)",
        "completeness": "UNBOUNDED",
        "optimality": "best observed among evaluated candidates",
    },
)

_ENGINE_NAMES = frozenset(e["engine"] for e in ENGINE_METHODS)

_MAX_STEPS = 200
_MAX_ITERS = 200
_MAX_NODES = 64

def synthesis_engines() -> dict[str, Any]:
    """The synthesis strategies the product may run, with honest scope."""
    from veritx_dse.synthesis.definition import ENGINES

    unknown = [e["engine"] for e in ENGINE_METHODS
               if e["engine"] not in ENGINES]
    if unknown:
        raise intent_error(
            f"synthesis engine(s) {unknown} not in the canonical "
            f"SynthesisDefinition vocabulary {list(ENGINES)} — the product "
            "may not offer an engine the canonical contract cannot drive")
    return {"engines": [dict(e) for e in ENGINE_METHODS],
            "canonical_vocabulary": list(ENGINES)}

def _parse_synthesis_body(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise intent_error(
            f"malformed synthesis body {body!r}: must be an object")
    allowed = {"engine", "definition", "traffic", "seed", "steps",
               "horizon", "branch", "group", "iters", "max_edges"}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise intent_error(
            f"unknown synthesis option(s) {unknown}; supported: "
            f"{sorted(allowed)}")
    engine = body.get("engine", "milp_tmcf")
    if engine not in _ENGINE_NAMES:
        raise intent_error(
            f"unknown synthesis engine {engine!r}; supported: "
            f"{sorted(_ENGINE_NAMES)}")
    definition = body.get("definition")
    traffic = body.get("traffic")
    if not isinstance(definition, dict) or not isinstance(traffic, dict):
        raise intent_error(
            "synthesis requires explicit 'definition' and 'traffic' "
            "objects — no uniform-traffic fallback, no auto-guessed layout")
    seed = body.get("seed", 7)
    if type(seed) is not int:
        raise intent_error(f"synthesis seed must be an int, got {seed!r}")
    for key, cap in (("steps", _MAX_STEPS), ("iters", _MAX_ITERS)):
        value = body.get(key)
        if value is not None and (
                type(value) is not int or value < 1 or value > cap):
            raise intent_error(
                f"synthesis {key} must be an int in [1, {cap}], "
                f"got {value!r}")
    nodes = definition.get("nodes")
    if type(nodes) is not int or nodes < 2 or nodes > _MAX_NODES:
        raise intent_error(
            f"synthesis nodes must be an int in [2, {_MAX_NODES}], "
            f"got {nodes!r}")
    return {"engine": engine, "definition": definition, "traffic": traffic,
            "seed": seed, "steps": body.get("steps", 20),
            "horizon": body.get("horizon", 3),
            "branch": body.get("branch", 4),
            "group": body.get("group", 4),
            "iters": body.get("iters", 10),
            "max_edges": body.get("max_edges", 120)}

def _run_synthesis_problem(parsed: dict[str, Any]) -> dict[str, Any]:
    """Execute one synthesis problem through the canonical adapters."""
    from veritx_dse.synthesis import candidate as cand
    from veritx_dse.synthesis.definition import SynthesisDefinition
    from veritx_dse.synthesis.traffic import SynthesisTrafficMatrix

    engine = parsed["engine"]
    definition_doc = dict(parsed["definition"])
    definition_doc["engine"] = engine
    try:
        definition = SynthesisDefinition.from_dict(definition_doc)
        traffic = SynthesisTrafficMatrix.from_dict(parsed["traffic"])
    except (ValueError, KeyError, TypeError) as exc:
        raise intent_error(
            f"invalid synthesis problem: {exc}") from exc
    if traffic.dimension != definition.nodes:
        raise intent_error(
            f"traffic dimension {traffic.dimension} != definition nodes "
            f"{definition.nodes} — refusing rather than falling back to "
            "uniform traffic")
    demands = [list(row) for row in traffic.values]

    from veritx_dse.application.errors import (  # noqa: PLC0415
        ControlPlaneError, ErrorCode)
    from veritx_dse.synthesis.rho_grpo_adapter import (  # noqa: PLC0415
        AdapterError as _AdapterError)

    try:
        if engine == "milp_tmcf":
            candidate = cand.synthesize(definition, traffic)
        elif engine in ("rho_iterative", "grpo_group"):
            from veritx_dse.synthesis import (  # noqa: PLC0415
                rho_grpo_adapter as heuristic)

            runner = (heuristic.run_rho if engine == "rho_iterative"
                      else heuristic.run_grpo)
            kwargs: dict[str, Any] = {
                "definition_id": definition.definition_id(),
                "traffic_id": traffic.traffic_id(),
                "nodes": definition.nodes,
                "k": definition_doc.get("k") or 0,
                "demands": demands, "seed": parsed["seed"],
                "steps": parsed["steps"],
                "max_edges": parsed["max_edges"],
                "radix": definition.radix}
            if engine == "rho_iterative":
                kwargs.update(horizon=parsed["horizon"],
                              branch=parsed["branch"])
                proposal = runner(**kwargs)
            else:
                kwargs.update(group=parsed["group"])
                proposal = runner(**kwargs)
            candidate = heuristic.to_topology_candidate(proposal)
        elif engine == "bo_gp":
            from veritx_dse.synthesis import bo_adapter as bo  # noqa: PLC0415

            proposal = bo.run_bo(
                definition_id=definition.definition_id(),
                traffic_id=traffic.traffic_id(),
                nodes=definition.nodes, demands=demands,
                seed=parsed["seed"], iters=parsed["iters"])
            candidate = bo.to_topology_candidate(proposal)
        else:  # pragma: no cover - guarded by _parse_synthesis_body
            raise intent_error(
                f"unknown synthesis engine {engine!r}")
    except _AdapterError as exc:
        raise ControlPlaneError(
            ErrorCode.NO_FEASIBLE_DESIGN,
            f"synthesis engine {engine!r} produced no candidate: {exc}",
            operation="submit_synthesis") from exc

    from veritx_dse.optimization.completeness import SearchCompleteness

    completeness_value = next(
        e["completeness"] for e in ENGINE_METHODS if e["engine"] == engine)
    if completeness_value == "BUDGETED":
        completeness = SearchCompleteness(
            method=engine, universe_size=None, universe_known=False,
            budget=parsed["iters"] if engine == "bo_gp" else parsed["steps"],
            evaluated_count=1, not_evaluated_count=None,
            completeness="BUDGETED", not_evaluated_identities=())
    else:
        completeness = SearchCompleteness(
            method=engine, universe_size=None, universe_known=False,
            budget=None, evaluated_count=1, not_evaluated_count=None,
            completeness="UNBOUNDED", not_evaluated_identities=())
    ir = cand.to_topology_ir(candidate, definition)
    return {"definition": definition, "traffic": traffic,
            "candidate": candidate, "ir": ir,
            "completeness": completeness}

def submit_synthesis(svc: Any, revision_id: str,
                     body: dict[str, Any]) -> dict[str, Any]:
    """Submit a topology-synthesis problem as a job (never inline)."""
    pid, _revision = svc.store.load_revision_global(revision_id)
    parsed = _parse_synthesis_body(body)

    def _run(progress):
        from veritx_dse.product.store import _new_id, utcnow

        progress("RUNNING")
        result = _run_synthesis_problem(parsed)
        definition = result["definition"]
        traffic = result["traffic"]
        candidate = result["candidate"]
        ir = result["ir"]
        completeness = result["completeness"]
        synthesis_id = _new_id("syn")
        links = [list(e) for e in candidate.links]
        degree = [0] * candidate.nodes
        for u, v in candidate.links:
            degree[u] += 1
            degree[v] += 1
        record = {
            "schema_version": 1,
            "synthesis_id": synthesis_id,
            "project_id": pid,
            "base_revision_id": revision_id,
            "engine": parsed["engine"],
            "seed": parsed["seed"],
            "definition": definition.to_dict(),
            "traffic": traffic.to_dict(),
            "candidate": candidate.to_dict(),
            "candidate_id": candidate.candidate_id(),
            "topology_ir": ir.to_dict(),
            "generator_objective": {
                "name": candidate.objective_name,
                "value": candidate.objective_value,
                "is_measured_performance": False,
            },
            "solver_status": candidate.solver_status,
            "node_count": candidate.nodes,
            "link_count": len(links),
            "max_degree": max(degree) if degree else 0,
            "completeness": completeness.to_dict(),
            "completeness_claim": completeness.claim(),
            "may_claim_optimality": completeness.may_claim_optimality(),
            "status": "COMPLETED",
            "created_at": utcnow(),
        }
        svc.store.create_synthesis(pid, record)
        lib_record = {
            "schema_version": 1,
            "candidate_id": candidate.candidate_id(),
            "origin": {"kind": "synthesis",
                       "synthesis_id": synthesis_id,
                       "project_id": pid,
                       "base_revision_id": revision_id},
            "method": parsed["engine"],
            "engine": parsed["engine"],
            "nodes": candidate.nodes,
            "links": links,
            "link_count": len(links),
            "max_degree": max(degree) if degree else 0,
            "generator_objective": record["generator_objective"],
            "solver_status": candidate.solver_status,
            "completeness": completeness.to_dict(),
            "completeness_claim": completeness.claim(),
            "provenance": {
                "definition_id": definition.definition_id(),
                "traffic_id": traffic.traffic_id(),
                "producer": candidate.producer_dict()
                if hasattr(candidate, "producer_dict") else {},
                "seed": parsed["seed"],
            },
            "compiled": False,
            "verified": False,
            "evaluated": False,
            "adopted": False,
            "adopted_project_id": None,
            "revision_id": None,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        try:
            svc.store.create_candidate(lib_record)
        except Exception:
            pass
        return ("COMPLETED", {"synthesis_id": synthesis_id,
                              "candidate_id": candidate.candidate_id()})

    job = svc.jobs.submit(pid, kind="SYNTHESIS", revision_id=revision_id,
                          fn=_run)
    return svc.job_view(job)

def get_synthesis(svc: Any, synthesis_id: str) -> dict[str, Any]:
    pid = svc.store.find_synthesis_project(synthesis_id)
    if pid is None:
        raise intent_error(f"no such synthesis: {synthesis_id!r}")
    record = svc.store.load_synthesis(pid, synthesis_id)
    return {"contract_version": 1, **record}

def list_syntheses(svc: Any, project_id: str) -> dict[str, Any]:
    svc.store.load_project(project_id)
    return {"project_id": project_id,
            "syntheses": svc.store.list_syntheses(project_id)}

def synthesis_completeness(svc: Any,
                           synthesis_id: str) -> dict[str, Any]:
    """The search-completeness panel for one synthesis result."""
    record = get_synthesis(svc, synthesis_id)
    completeness = record.get("completeness") or {}
    return {"synthesis_id": synthesis_id,
            "engine": record.get("engine"),
            "completeness": completeness,
            "claim": record.get("completeness_claim"),
            "may_claim_optimality": record.get("may_claim_optimality",
                                               False)}

def list_candidates(svc: Any, filters: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """The global candidate library, with server-side filtering."""
    from veritx_dse.product.store import ProductStoreError  # noqa: F401

    filters = filters or {}
    allowed = {"origin", "engine", "method", "compiled", "verified",
               "evaluated", "adopted"}
    unknown = sorted(set(filters) - allowed)
    if unknown:
        raise intent_error(
            f"unknown candidate filter(s) {unknown}; supported: "
            f"{sorted(allowed)}")
    records = svc.store.list_candidates()

    def _matches(record: dict[str, Any]) -> bool:
        for key, want in filters.items():
            if key == "origin":
                if (record.get("origin") or {}).get("kind") != want:
                    return False
            elif record.get(key) != want:
                return False
        return True

    matched = [r for r in records if _matches(r)]
    return {"candidates": matched, "count": len(matched)}

def get_candidate(svc: Any, candidate_id: str) -> dict[str, Any]:
    """Candidate detail: graph, provenance, pipeline state, diff vs seed."""
    try:
        record = svc.store.load_candidate(candidate_id)
    except Exception as exc:
        raise intent_error(
            f"no such candidate: {candidate_id!r}") from exc
    detail: dict[str, Any] = {"contract_version": 1, **record}
    detail["pipeline"] = {
        "compiled": bool(record.get("compiled")),
        "verified": bool(record.get("verified")),
        "evaluated": bool(record.get("evaluated")),
        "adopted": bool(record.get("adopted")),
        "revision_id": record.get("revision_id"),
        "evaluated_run_id": record.get("evaluated_run_id"),
        "adopted_project_id": record.get("adopted_project_id"),
    }
    origin = record.get("origin") or {}
    if origin.get("kind") == "synthesis" and origin.get("synthesis_id"):
        pid = svc.store.find_synthesis_project(origin["synthesis_id"])
        if pid is not None:
            synthesis = svc.store.load_synthesis(pid,
                                                 origin["synthesis_id"])
            detail["topology_ir"] = synthesis.get("topology_ir")
            detail["definition"] = synthesis.get("definition")
            base_links = _seed_links(synthesis)
            if base_links is not None:
                current = {tuple(e) for e in record.get("links", [])}
                detail["diff_vs_seed"] = {
                    "added": sorted([list(e) for e in current - base_links]),
                    "removed": sorted(
                        [list(e) for e in base_links - current]),
                }
    return detail

def _seed_links(synthesis: dict[str, Any]) -> set[tuple[int, int]] | None:
    """The seed graph a heuristic proposal mutated, if reconstructible."""
    from veritx_dse.synthesis import rho_grpo_adapter as heuristic

    engine = synthesis.get("engine")
    definition = synthesis.get("definition") or {}
    if engine in ("rho_iterative", "grpo_group"):
        k = definition.get("k")
        nodes = definition.get("nodes")
        if type(k) is int and k * k == nodes:
            try:
                return set(heuristic.mesh_links(k))
            except Exception:
                return None
    return None

def mark_candidate_compiled(store: Any, candidate_id: str,
                              revision_id: str, verified: bool) -> dict[str, Any]:
    """Flip a synthesis candidate's compiled/verified flags post-compile.

Rationale: docs/decisions/modules/product.md
    """
    from veritx_dse.product.store import utcnow
    try:
        record = store.load_candidate(candidate_id)
    except Exception as exc:
        raise intent_error(
            f"no such candidate: {candidate_id!r}") from exc
    origin = record.get("origin") or {}
    if origin.get("kind") not in ("synthesis",):
        raise intent_error(
            f"candidate {candidate_id!r} is not a synthesis candidate "
            f"(origin {origin!r}) — status flips apply to the candidate "
            "library only")
    return store.update_candidate(
        candidate_id, compiled=True, verified=bool(verified),
        revision_id=revision_id, compiled_at=utcnow())

def mark_candidate_evaluated(store: Any, candidate_id: str,
                             run_id: str) -> dict[str, Any]:
    """Flip a synthesis candidate's evaluated flag post-measurement.

    Called by run_evaluation when the candidate's revision produces an
    EVALUATED network measurement. The measurement is the run's own;
    this only records that it exists.
    """
    from veritx_dse.product.store import utcnow
    try:
        record = store.load_candidate(candidate_id)
    except Exception as exc:
        raise intent_error(
            f"no such candidate: {candidate_id!r}") from exc
    origin = record.get("origin") or {}
    if origin.get("kind") not in ("synthesis",):
        raise intent_error(
            f"candidate {candidate_id!r} is not a synthesis candidate "
            f"(origin {origin!r}) — status flips apply to the candidate "
            "library only")
    return store.update_candidate(
        candidate_id, evaluated=True, evaluated_run_id=run_id,
        evaluated_at=utcnow())

def promote_candidate(svc: Any, candidate_id: str,
                      project_id: str) -> dict[str, Any]:
    """Promote a synthesis candidate into an ordinary draft.

    Uses the existing canonical promotion primitive only — no second
    promoted-design type. The draft must be explicitly Compiled before a
    new immutable revision exists; promotion claims no certificate,
    measurement or verification.
    """
    from veritx_dse.product.service import (  # noqa: PLC0415 - same package
        canonical_request_doc, parse_request_doc,
    )
    from veritx_dse.synthesis import candidate as cand
    from veritx_dse.synthesis.definition import SynthesisDefinition

    try:
        record = svc.store.load_candidate(candidate_id)
    except Exception as exc:
        raise intent_error(
            f"no such candidate: {candidate_id!r}") from exc
    origin = record.get("origin") or {}
    if origin.get("kind") != "synthesis" or not origin.get("synthesis_id"):
        raise intent_error(
            f"candidate {candidate_id!r} is not a synthesis candidate "
            f"(origin {origin!r}) — optimization candidates use the "
            "existing use_candidate surface")
    pid = svc.store.find_synthesis_project(origin["synthesis_id"])
    if pid is None:
        raise intent_error(
            f"synthesis {origin.get('synthesis_id')!r} for candidate "
            f"{candidate_id!r} no longer exists — refusing a stale promotion")
    synthesis = svc.store.load_synthesis(pid, origin["synthesis_id"])
    candidate = cand.TopologyCandidate.from_dict(synthesis["candidate"])
    definition = SynthesisDefinition.from_dict(synthesis["definition"])
    promotion = cand.promote_to_explicit_topology(
        candidate, definition,
        expected_candidate_id=candidate.candidate_id())
    svc.store.load_project(project_id)
    draft = svc.store.load_draft(project_id)
    new_doc = cand.apply_promotion_to_request_doc(
        dict(draft.get("request") or {}), promotion)
    try:
        parsed = parse_request_doc(new_doc)
        design_hash = parsed.design_hash()
    except Exception as exc:
        raise intent_error(
            f"promoted candidate {candidate_id!r} does not form a valid "
            f"request document: {exc}") from exc
    from veritx_dse.product.service import _view_hash  # noqa: PLC0415

    draft["request"] = canonical_request_doc(parsed)
    draft["design_hash"] = _view_hash(design_hash)
    draft["derived_from_synthesis_id"] = origin["synthesis_id"]
    draft["derived_from_candidate_id"] = candidate_id
    draft["source"] = "synthesis-candidate"
    svc.store.put_draft(project_id, draft)
    svc.store.update_candidate(
        candidate_id, adopted=True, adopted_project_id=project_id)
    view = svc.draft_view(project_id)
    view["derived_from_synthesis_id"] = origin["synthesis_id"]
    view["derived_from_candidate_id"] = candidate_id
    view["adopted_from_synthesis_id"] = origin["synthesis_id"]
    view["compile_required"] = True
    return view

_LADDER: tuple[tuple[str, str], ...] = (
    ("INTENT", "DECLARABLE"),
    ("MATERIALIZED", "DERIVABLE"),
    ("VERIFIED", "VERIFIABLE"),
    ("PROJECTED", "PROJECTABLE"),
    ("EXECUTABLE", "EXECUTABLE"),
    ("QUALIFIED", "QUALIFIED"),
    ("PRODUCT", "PRODUCT_WIRED"),
)

def _capability_status(stages: dict[str, Any],
                       classifications: list[str]) -> str:
    """One maturity word, computed server-side from authorities.

Rationale: docs/decisions/modules/product.md
    """
    wired = stages.get("PRODUCT_WIRED")
    qualified = stages.get("QUALIFIED")
    dynamic = [stages.get(s) for s in ("PROJECTABLE", "EXECUTABLE",
                                       "QUALIFIED", "PRODUCT_WIRED")]
    has_current = any(c.startswith("CURRENT_") for c in classifications)
    has_historical = any(c.startswith("HISTORICAL_") for c in classifications)
    if wired == "YES" and qualified in ("YES", "CONDITIONAL"):
        return "AVAILABLE"
    if wired == "YES":
        return "EXPERIMENTAL"
    if qualified == "CONDITIONAL" and any(
            v in ("YES", "CONDITIONAL") for v in dynamic):
        return "EXPERIMENTAL"
    if has_current:
        return "RESEARCH"
    if has_historical:
        return "HISTORICAL"
    if all(v == "NO" for v in dynamic):
        return "BLOCKED"
    return "NOT APPLICABLE"

def _archaeology_rows() -> list[dict[str, Any]]:
    import yaml

    from veritx_dse.application.product_registry import registry_dir

    path = registry_dir() / "capability-archaeology.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(document.get("capabilities") or [])

def _related_archaeology(name: str,
                         rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Heuristic linkage (server-side, labelled): token overlap on names.

    The archaeology ledger and the capability registry use different id
    vocabularies; this overlap is reported as *related*, never as the
    authority for a maturity claim.
    """
    stop = {"the", "and", "for", "with", "routing", "topology", "of", "a"}
    tokens = {t.lower() for t in "".join(
        c if c.isalnum() else " " for c in name).split()
        if t.lower() not in stop and len(t) > 2}
    related = []
    for row in rows:
        hay = f"{row.get('id', '')} {row.get('name', '')}".lower()
        if any(t in hay for t in tokens):
            related.append({
                "id": row.get("id"), "name": row.get("name"),
                "classifications": list(row.get("classifications") or []),
                "measured_anywhere": row.get("MEASURED_ANYWHERE"),
                "executed_anywhere": row.get("EXECUTED_ANYWHERE"),
                "missing_bridge": row.get("MISSING_BRIDGE"),
            })
    return related

def capability_explorer() -> dict[str, Any]:
    """Every recorded capability with its seven-stage ladder + status."""
    from veritx_dse.application.product_registry import (
        capability_document, capability_semantics_version,
    )

    try:
        arch_rows = _archaeology_rows()
    except Exception:
        arch_rows = []
    arch_by_id = {r.get("id"): r for r in arch_rows}
    capabilities = []
    for row in capability_document().get("capabilities") or []:
        stages = row.get("stages") or {}
        arch = arch_by_id.get(row.get("id")) or {}
        classifications = list(arch.get("classifications") or [])
        ladder = {stage: stages.get(code) for stage, code in _LADDER}
        capabilities.append({
            "id": row.get("id"), "name": row.get("name"),
            "owner": row.get("owner"), "ladder": ladder,
            "evidence_capable": stages.get("EVIDENCE_CAPABLE"),
            "wiring": row.get("wiring"), "reason": row.get("reason"),
            "limiting": row.get("limiting"),
            "claim_scope": row.get("claim_scope"),
            "conditions": list(row.get("conditions") or []),
            "status": _capability_status(stages, classifications),
            "classifications": classifications,
            "missing_bridge": arch.get("MISSING_BRIDGE"),
        })
    archaeology = [{
        "id": r.get("id"), "name": r.get("name"),
        "classifications": list(r.get("classifications") or []),
        "measured_anywhere": r.get("MEASURED_ANYWHERE"),
        "executed_anywhere": r.get("EXECUTED_ANYWHERE"),
        "current_product_exposure": r.get("PRODUCT_WIRED"),
        "missing_bridge": r.get("MISSING_BRIDGE"),
    } for r in arch_rows]
    return {"capability_semantics_version": capability_semantics_version(),
            "ladder": [stage for stage, _ in _LADDER],
            "capabilities": capabilities, "archaeology": archaeology}

def capability_detail(capability_id: str) -> dict[str, Any]:
    """One capability: ladder, status, evidence, missing bridge."""
    from veritx_dse.application.product_registry import (
        capability_by_id, capability_semantics_version,
    )

    row = capability_by_id().get(capability_id)
    if row is None:
        raise intent_error(
            f"unknown capability {capability_id!r}")
    stages = row.get("stages") or {}
    try:
        arch_rows = _archaeology_rows()
    except Exception:
        arch_rows = []
    exact = [r for r in arch_rows if r.get("id") == capability_id]
    related = [] if exact else _related_archaeology(
        str(row.get("name", "")), arch_rows)
    classifications: list[str] = []
    for r in exact:
        classifications.extend(r.get("classifications") or [])
    return {
        "id": row.get("id"), "name": row.get("name"),
        "owner": row.get("owner"),
        "capability_semantics_version": capability_semantics_version(),
        "ladder": {stage: stages.get(code) for stage, code in _LADDER},
        "evidence_capable": stages.get("EVIDENCE_CAPABLE"),
        "wiring": row.get("wiring"), "reason": row.get("reason"),
        "limiting": row.get("limiting"),
        "claim_scope": row.get("claim_scope"),
        "conditions": list(row.get("conditions") or []),
        "status": _capability_status(stages, classifications),
        "classifications": classifications,
        "archaeology": [{
            "id": r.get("id"), "name": r.get("name"),
            "classifications": list(r.get("classifications") or []),
            "implemented_anywhere": r.get("IMPLEMENTED_ANYWHERE"),
            "executed_anywhere": r.get("EXECUTED_ANYWHERE"),
            "measured_anywhere": r.get("MEASURED_ANYWHERE"),
            "missing_bridge": r.get("MISSING_BRIDGE"),
            "evidence": list(r.get("evidence") or []),
        } for r in exact],
        "related_archaeology": related,
        "related_is_heuristic": True,
    }

def wave_e_metrics() -> dict[str, Any]:
    """Wave-E model metrics with explicit MODELLED fidelity.

    Never MEASURED: every scalar carries measured=False,
    UNCALIBRATED fidelity and PREDICTIVE_VALIDATION NOT_ESTABLISHED.
    Non-scalar facts (sensitivity, TTFT, decode) are reported as
    decisions with reasons, never as invented scalars.
    """
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY, WAVE_E_NOT_SCALAR, WAVE_E_SCALAR_METRICS,
        wave_e_honesty_metadata,
    )

    units: dict[str, Any] = {}
    try:
        from veritx_dse.optimization.metric_registry import (
            federated_metric_catalog,
        )
        for descriptor in federated_metric_catalog():
            if descriptor.metric in units or descriptor.unit is None:
                continue
            units[descriptor.metric] = {
                "unit": descriptor.unit, "question": descriptor.question,
                "backends": list(descriptor.backends),
                "fidelity": descriptor.fidelity}
    except Exception:
        pass
    honesty = wave_e_honesty_metadata({})
    metrics = []
    for name, _producer in WAVE_E_SCALAR_METRICS:
        metrics.append({
            "metric": name,
            "producer_id": f"wave-e-model/{name}",
            "epistemic": "MODELLED",
            "measured": CERTIFIED_METRIC_REGISTRY.is_measured(name),
            "fidelity": "UNCALIBRATED",
            "qualification": "PREDICTIVE_VALIDATION_NOT_ESTABLISHED",
            "unit": (units.get(name) or {}).get("unit"),
            "question": (units.get(name) or {}).get("question"),
            "honesty": honesty,
        })
    return {"authority": "wave-e-model",
            "registry_id": CERTIFIED_METRIC_REGISTRY.registry_id(),
            "epistemic": "MODELLED",
            "measured": False,
            "fidelity": "UNCALIBRATED",
            "qualification": "PREDICTIVE_VALIDATION_NOT_ESTABLISHED",
            "metrics": metrics,
            "not_scalar": dict(WAVE_E_NOT_SCALAR)}

def federated_metrics() -> dict[str, Any]:
    """The federated optimization metric catalog, verbatim."""
    from veritx_dse.optimization.metric_registry import (
        federated_metric_catalog,
    )

    return {"metrics": [d.to_dict()
                        for d in federated_metric_catalog()]}

def energy_authorities(family: str | None = None) -> dict[str, Any]:
    """The six energy/power authorities — separate, never one number."""
    from veritx_dse.reports.energy_fidelity import (
        BOOKSIM_NATIVE_POWER_FOR_MECS, BRIDGE_ERT_STATUS,
        BRIDGE_PJ_PER_HOP, ESTIMATORS, booksim_native_verdict,
    )

    payload: dict[str, Any] = {
        "authorities": [dict(e) for e in ESTIMATORS],
        "bridge_pj_per_hop": BRIDGE_PJ_PER_HOP,
        "bridge_ert_status": BRIDGE_ERT_STATUS,
        "mecs_power_law": BOOKSIM_NATIVE_POWER_FOR_MECS,
    }
    if family:
        verdict, reason = booksim_native_verdict(family)
        payload["family"] = family
        payload["booksim_native_verdict"] = verdict
        payload["booksim_native_reason"] = reason
    return payload

def reuse_info(svc: Any, run_id: str) -> dict[str, Any]:
    """Why a run's evidence may (or may not) be reused — explicit data.

    A cache hit is explicit in the UI and references the reused evidence
    id; it never creates a synthetic measurement. When the run carries
    no reuse linkage, reuse is reported as unavailable with the reason,
    never silently substituted.
    """
    from veritx_dse.backend.evidence_cache import KEY_FIELDS

    pid = svc.store.find_run_project(run_id)
    if pid is None:
        raise intent_error(f"no such run: {run_id!r}")
    run = svc.store.load_run(pid, run_id)
    reused_id = run.get("reused_evidence_id")
    if not reused_id:
        return {"run_id": run_id, "reused": False,
                "reused_evidence_id": None,
                "reason": "this run executed directly; no authenticated "
                          "evidence was reused",
                "reuse_key_fields": list(KEY_FIELDS)}
    return {"run_id": run_id, "reused": True,
            "reused_evidence_id": reused_id,
            "reason": "REUSED AUTHENTICATED EVIDENCE — the measurement "
                      "below is the referenced evidence, not a new run",
            "reuse_key_fields": list(KEY_FIELDS),
            "matching": run.get("reuse_matching")}

def optimization_completeness(svc: Any,
                              optimization_id: str) -> dict[str, Any]:
    """The search-completeness panel for one optimization study."""
    from veritx_dse.optimization.completeness import CLAIM_TEXT

    optimization = svc.get_optimization(optimization_id)
    study = optimization.get("study") or {}
    completeness = study.get("completeness")
    if not completeness:
        return {"optimization_id": optimization_id,
                "completeness": None,
                "reason": "this study predates completeness accounting"}
    value = completeness.get("completeness")
    return {"optimization_id": optimization_id,
            "completeness": completeness,
            "claim": CLAIM_TEXT.get(value, value),
            "may_claim_optimality": value == "EXHAUSTIVE"}

__all__ = [
    "ENGINE_METHODS",
    "synthesis_engines",
    "submit_synthesis",
    "get_synthesis",
    "list_syntheses",
    "synthesis_completeness",
    "list_candidates",
    "get_candidate",
    "promote_candidate",
    "capability_explorer",
    "capability_detail",
    "wave_e_metrics",
    "federated_metrics",
    "energy_authorities",
    "reuse_info",
    "optimization_completeness",
]
