#!/usr/bin/env python3
"""Regenerate Srota Studio fixtures from the INTEGRATED engine.

Every view in apps/studio/fixtures/*.json originates from a live engine
object on this tree via the product gateways
(application/product_evaluator.py, application/views.py) — no
hand-written semantics, no hashes, no verdicts, no Pareto membership.
Envelope copy (title/description) is preserved from the existing files;
only values regenerate.

The optimization fixture is produced by the CERTIFIED entry point
``Optimizer.optimize_certified(request, definition,
backend_config=CertifiedBackendConfig(...))``. That is the only path
that can yield ``result_class == "CERTIFIED_PRODUCT"`` and bind the
product-controlled metric registry identity; ``optimize_with_port`` /
its ``optimize`` alias is analytic-only and is never used here.

The study is deliberately shaped so the REAL engine emits the full
candidate-state taxonomy the Studio must render (all values below are
engine verdicts, never authored): one eligible Pareto member, one
evaluated candidate failing a binding product requirement, one
evaluated candidate violating a hard optimization constraint, and
compile-refused candidates whose objectives/constraints are
UNMEASURABLE. ``main()`` asserts those states were actually produced.

Usage: python3 -m veritx_dse.tools.generate_studio_fixtures
(from tracks/t3-topology/dse; needs a runnable BookSim binary for the
evaluated + study fixtures).
"""
from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
from pathlib import Path

FIXTURE_DIR = "apps/studio/fixtures"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write(path: Path, envelope: dict) -> None:
    path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")


def main() -> dict[str, str]:
    from veritx_dse.core.paths import REPO
    from veritx_dse.model.compile_model import CompileRequestV3
    from veritx_dse.simulation.booksim import find_booksim_bin

    out_dir = REPO / FIXTURE_DIR
    llama_doc = _load_json(
        REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json")
    llama = CompileRequestV3.from_dict(llama_doc)
    binary = find_booksim_bin(REPO)
    summary: dict[str, str] = {}

    # One transport root for this regeneration. The evidence paths are
    # transport, never science; identities remain content-derived. The
    # tree is removed once every view has been projected.
    run_root = Path(tempfile.mkdtemp(prefix="studio-fixture-runs-"))
    try:
        return _generate(out_dir, llama, binary, run_root, summary)
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


def _generate(out_dir: Path, llama, binary, run_root: Path,
              summary: dict[str, str]) -> dict[str, str]:
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.product_evaluator import evaluate_product
    from veritx_dse.application.views import compilation_view, design_view
    from veritx_dse.model.compile_model import TopologyFamily

    assert out_dir.is_dir(), f"fixture directory not found: {out_dir}"

    def envelope(fixture_id: str, old: dict, **views: object) -> dict:
        return {
            "fixture_id": fixture_id,
            "title": old["title"],
            "description": old["description"],
            "design": views.get("design"),
            "compilation": views.get("compilation"),
            "evaluation": views.get("evaluation"),
            "requirements": views.get("requirements"),
            "optimization": views.get("optimization"),
        }

    # 1. compiled-mesh: real compile, no evaluation.
    comp = FabricCompiler().compile(llama)
    assert comp.status == "COMPILED", comp.error
    old = _load_json(out_dir / "compiled-mesh.json")
    _write(out_dir / "compiled-mesh.json", envelope(
        "compiled-mesh", old,
        design=design_view(llama, comp),
        compilation=compilation_view(comp)))
    summary["compiled-mesh"] = "COMPILED"

    # 2. invalid-design: same design over an uncertified family.
    torus_noc = dataclasses.replace(
        llama.noc_config, topology_family=TopologyFamily.TORUS)
    torus = dataclasses.replace(llama, noc_config=torus_noc)
    refused = FabricCompiler().compile(torus)
    assert refused.status in ("INVALID", "UNSUPPORTED"), refused.status
    old = _load_json(out_dir / "invalid-design.json")
    _write(out_dir / "invalid-design.json", envelope(
        "invalid-design", old,
        design=design_view(torus),
        compilation=compilation_view(refused)))
    summary["invalid-design"] = refused.status

    # 3. backend-unavailable: compiled, no runnable backend.
    missing = evaluate_product(
        llama, binary="/nonexistent-booksim-for-fixture")
    assert missing.status == "BACKEND_UNAVAILABLE", missing.status
    assert missing.outcome is not None
    old = _load_json(out_dir / "backend-unavailable.json")
    _write(out_dir / "backend-unavailable.json", envelope(
        "backend-unavailable", old,
        design=design_view(llama, missing.compilation),
        compilation=compilation_view(missing.compilation),
        evaluation=missing.outcome.to_view_dict()))
    summary["backend-unavailable"] = "BACKEND_UNAVAILABLE"

    # 4. evaluated-design: the full integrated chain, live.
    prod = evaluate_product(
        llama, binary=str(binary), network_clock_hz=10 ** 9,
        timeout_s=900, run_dir=run_root / "evaluated-design")
    assert prod.status == "EVALUATED", prod.reason
    assert prod.requirements_pass is True
    old = _load_json(out_dir / "evaluated-design.json")
    _write(out_dir / "evaluated-design.json", envelope(
        "evaluated-design", old,
        design=design_view(llama, prod.compilation),
        compilation=compilation_view(prod.compilation),
        evaluation=prod.outcome.to_view_dict(),
        requirements=prod.requirement_report))
    summary["evaluated-design"] = "EVALUATED+SATISFIED"

    # 5. optimization-study: real certified study, selected candidate
    # replayed through the full chain so every slot is engine-originated.
    from veritx_dse.model.compile_model import (
        Agent,
        AgentKind,
        CollectiveDimension,
        CollectiveIntent,
        CollectiveKind,
        CompileRequestV3,
        DependencyGraph,
        ModelFamily,
        NocConfig,
        QoSClass,
        RequirementV3,
        WorkloadV3,
    )
    from veritx_dse.optimization.candidate import make_candidate
    from veritx_dse.optimization.definition import (
        Constraint,
        DomainParam,
        Objective,
        OptimizationDefinition,
    )
    from veritx_dse.optimization.result import (
        CertifiedBackendConfig,
        Optimizer,
    )
    tiny = CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=4, dp=1,
            collectives=(CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.TP,
                payload_bytes=2048,
                traffic_class="tp_collective"),)),
        # Binding ceiling set inside the measured spread of the real
        # 4-tile mesh so the engine itself separates the candidates:
        # the widest link configuration passes, narrower ones exceed it.
        # Engine verdicts, asserted below.
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=600, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH,
                             concentration=1))
    study = Optimizer().optimize_certified(
        tiny,
        OptimizationDefinition(
            domain=(DomainParam("link_width", (32, 64, 128)),
                    DomainParam("rcu_enabled", (False, True))),
            objectives=(Objective("completion_cycles", "MIN"),),
            constraints=(Constraint("completion_cycles", "<=", 1000.0),),
            method="grid"),
        backend_config=CertifiedBackendConfig(
            binary=str(binary), network_clock_hz=10 ** 9,
            timeout_s=600, run_root=run_root / "optimization-study"))
    # The fixture must actually demonstrate the three-state taxonomy.
    verdicts = {v for r in study.records
                for v in r.constraint_verdicts.values()}
    assert {"SATISFIED", "VIOLATED", "UNMEASURABLE"} <= verdicts, verdicts
    assert any(r.product_requirements_satisfied is False
               for r in study.records), "no requirement-refused candidate"
    assert any(r.objective_availability.get("completion_cycles")
               == "UNMEASURABLE" for r in study.records), \
        "no objective-unavailable candidate"
    assert study.selected_candidate_id in study.pareto_ids
    selected = next(
        r for r in study.records
        if r.candidate_id == study.selected_candidate_id)
    winner_request = make_candidate(
        tiny, dict(selected.guided_patch)).request
    winner = evaluate_product(
        winner_request,
        binary=str(binary), network_clock_hz=10 ** 9, timeout_s=600,
        run_dir=run_root / "optimization-winner")
    assert winner.status == "EVALUATED", winner.reason
    old = _load_json(out_dir / "optimization-study.json")
    _write(out_dir / "optimization-study.json", envelope(
        "optimization-study", old,
        design=design_view(tiny),
        compilation=compilation_view(winner.compilation),
        evaluation=winner.outcome.to_view_dict(),
        requirements=winner.requirement_report,
        optimization=study.to_study_view()))
    summary["optimization-study"] = (
        f"selected {study.selected_candidate_id} "
        f"({len(study.records)} candidates, "
        f"{len(study.pareto_ids)} Pareto)")
    return summary


if __name__ == "__main__":
    for fixture_id, status in main().items():
        print(f"{fixture_id}: {status}")
