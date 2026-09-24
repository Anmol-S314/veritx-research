"""Studio contract-v2 tests (C-6).

These tests are the executable statement of the RT-final Studio
deliverable:

 1. all committed fixtures validate against their declared contract versions;
 2. the fast validator explicitly says backend realizability is not proven;
 3. the provisioned validator proves the backend fixtures through the engine;
 4. fresh provisioned regeneration bytes: byte-identical across two fresh
    roots and against the committed fixtures (evidence-v2: no runtime
    provenance in scientific identity; no volatility allowlist);
 5. generated hashes originate from engine objects (no label hashing);
 6. the optimization fixture originates from ``optimize_certified``;
 7. UNMEASURABLE renders differently from VIOLATED;
 8. no Studio script references the deleted synthetic generator;
 9. no hard-coded 96.4 / 50000 / synthetic candidate table survives.

Provisioned tests skip (with a clear reason) when no qualified BookSim is
present; in a provisioned environment they run the real engine.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

STUDIO = Path(__file__).resolve().parent.parent
REPO = STUDIO.parent.parent
SCRIPTS = STUDIO / "scripts"
FIXTURES = STUDIO / "fixtures"
DSE = REPO / "tracks" / "t3-topology" / "dse"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(DSE) not in sys.path:
    sys.path.insert(0, str(DSE))

import validate_fixtures as vf  # noqa: E402


def _load(stem: str) -> dict:
    return json.loads((FIXTURES / f"{stem}.json").read_text())


def _validators() -> dict[tuple[Path, str], Draft202012Validator]:
    return {
        key: Draft202012Validator(vf.load_schema(*key))
        for key in vf.VIEW_SCHEMAS.values()
    }


def _run_validator(*args: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    env.pop("CI", None)
    env.pop("GITHUB_ACTIONS", None)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "validate_fixtures.py"), *args],
        cwd=STUDIO, capture_output=True, text=True, env=env, timeout=900,
    )


def _provisioned() -> tuple[bool, str]:
    return vf.provisioned_environment()


# ── C-6 (1) schema validation ───────────────────────────────────────────────

def test_all_committed_fixtures_validate_against_declared_contract_versions():
    validators = _validators()
    found = sorted(p.stem for p in FIXTURES.glob("*.json"))
    assert set(found) == vf.EXPECTED_FIXTURES
    for stem in sorted(vf.EXPECTED_FIXTURES):
        errors = vf.validate_one(FIXTURES / f"{stem}.json", validators)
        assert errors == [], f"{stem}: {errors}"

    # Study view: authoritative v2 schema in contracts/srota/v2 (C-1).
    study = _load("optimization-study")["optimization"]
    assert study["contract_version"] == 2
    v2 = Draft202012Validator(json.loads(vf.STUDY_SCHEMA_V2.read_text()))
    assert list(v2.iter_errors(study)) == []
    assert vf.STUDY_SCHEMA_V2.parent.name == "v2"

    # The shadow v1-dir v2-named file no longer exists and is never read.
    assert not (
        REPO / "contracts/srota/v1/optimization.study.view.v2.schema.json"
    ).exists()
    assert vf.VIEW_SCHEMAS["optimization"][0].name == "v2"
    for view in ("design", "compilation", "evaluation", "requirements"):
        assert vf.VIEW_SCHEMAS[view][0].name == "v1", view

    # Other four views stay on the v1 schemas.
    other = _load("evaluated-design")
    for view, name in (
        ("design", "design.view.schema.json"),
        ("compilation", "compilation.view.schema.json"),
        ("evaluation", "evaluation.view.schema.json"),
        ("requirements", "requirement.report.schema.json"),
    ):
        schema = json.loads((vf.SCHEMAS_V1 / name).read_text())
        assert list(Draft202012Validator(schema).iter_errors(other[view])) == []


# ── C-6 (2) fast path statement ─────────────────────────────────────────────

def test_fast_validator_states_backend_realizability_is_not_proven():
    proc = _run_validator("--skip-engine")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    assert vf.FAST_LINE in lines, lines
    # No generic PASS implying backend realizability on the fast path.
    assert vf.PROVEN_LINE not in proc.stdout
    assert "proving backend realizability" not in proc.stdout
    assert "backend realizability PROVEN" not in proc.stdout


# ── C-6 (3) provisioned engine proof ────────────────────────────────────────

def test_provisioned_validator_proves_backend_fixtures_through_engine():
    ok, detail = _provisioned()
    if not ok:
        pytest.skip(f"not provisioned: {detail}")
    proc = _run_validator("--engine")
    out = proc.stdout
    # The EVALUATED fixture + RequirementReport + certified study were
    # proven through engine objects (C-3), and the byte gate passes: the
    # evidence-v2 split keeps runtime provenance out of scientific
    # identity, so no defect class may appear.
    assert ("Engine objects verified: EVALUATED fixture + RequirementReport"
            " + CERTIFIED_PRODUCT OptimizationStudy") in out, out
    assert "SEMANTIC field" not in out, out
    assert "ENGINE DEFECT" not in out, out
    assert proc.returncode == 0, out
    assert vf.PROVEN_LINE in out, out


# ── C-6 (4) byte reproducibility / reported defect ──────────────────────────

@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    ok, detail = _provisioned()
    if not ok:
        pytest.skip(f"not provisioned: {detail}")
    tmp = tmp_path_factory.mktemp("studio-fixture-regen")
    for stem in vf.EXPECTED_FIXTURES:
        shutil.copy2(FIXTURES / f"{stem}.json", tmp / f"{stem}.json")
    from veritx_dse.tools import generate_studio_fixtures as engine
    old = engine.FIXTURE_DIR
    engine.FIXTURE_DIR = str(tmp)
    try:
        engine.main()
    finally:
        engine.FIXTURE_DIR = old
    return tmp


def test_fresh_provisioned_regeneration_bytes(regenerated):
    """C-6 (4): byte-for-byte against the committed fixtures.

    evidence-v2 removed the runtime provenance (wall time, absolute run
    paths, platform text) from the scientific evidence document; the
    attempt record is separate and never hashed. Fresh regeneration must
    therefore be byte-identical on every fixture, with no volatile field.
    """
    for stem in sorted(vf.EXPECTED_FIXTURES):
        identical, prov, semantic = vf.compare_bytes(
            FIXTURES / f"{stem}.json", regenerated / f"{stem}.json")
        assert identical, (stem, prov, semantic)


def test_two_fresh_regeneration_roots_are_byte_identical(tmp_path):
    """The required proof: generator twice from fresh roots, exact bytes."""
    ok, detail = _provisioned()
    if not ok:
        pytest.skip(f"not provisioned: {detail}")
    from veritx_dse.tools import generate_studio_fixtures as engine
    roots = [tmp_path / "fixtures-A", tmp_path / "fixtures-B"]
    for root in roots:
        root.mkdir()
        for stem in vf.EXPECTED_FIXTURES:
            shutil.copy2(FIXTURES / f"{stem}.json", root / f"{stem}.json")
    old = engine.FIXTURE_DIR
    try:
        for root in roots:
            engine.FIXTURE_DIR = str(root)
            engine.main()
    finally:
        engine.FIXTURE_DIR = old
    names_a = sorted(p.name for p in roots[0].glob("*.json"))
    names_b = sorted(p.name for p in roots[1].glob("*.json"))
    assert names_a == names_b and names_a, (names_a, names_b)
    for name in names_a:
        assert (roots[0] / name).read_bytes() == \
            (roots[1] / name).read_bytes(), name


# ── C-6 (5) hashes originate from engine objects ────────────────────────────

def test_generated_hashes_originate_from_engine_objects():
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.model.compile_model import CompileRequestV3
    from veritx_dse.optimization.definition import (
        Constraint,
        DomainParam,
        Objective,
        OptimizationDefinition,
    )
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY,
    )

    llama_doc = json.loads(
        (REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json")
        .read_text())
    request = CompileRequestV3.from_dict(llama_doc)
    compiled = _load("compiled-mesh")
    assert compiled["design"]["design_hash"] == \
        f"sha256:{request.design_hash()}"
    compilation = FabricCompiler().compile(request)
    assert compiled["compilation"]["resolved_fabric_hash"] == \
        f"sha256:{compilation.bundle.resolved_fabric.resolved_fabric_hash()}"

    study = _load("optimization-study")["optimization"]
    assert study["metric_registry_id"] == \
        CERTIFIED_METRIC_REGISTRY.registry_id()
    assert study["metric_registry_version"] == CERTIFIED_METRIC_REGISTRY.version
    definition = study["definition"]
    rebuilt = OptimizationDefinition(
        domain=tuple(DomainParam(name, tuple(values))
                     for name, values in definition["domain"].items()),
        objectives=tuple(Objective(o["metric"], o["direction"])
                         for o in definition["objectives"]),
        constraints=tuple(Constraint(c["metric"], c["op"], c["threshold"])
                          for c in definition["constraints"]),
        method=definition["method"],
        budget=definition["budget"],
        seed=definition.get("seed"),
        selection=definition["selection"],
    )
    assert rebuilt.definition_id() == definition["definition_id"]


# ── C-6 (6) certified entry point ───────────────────────────────────────────

def test_optimization_fixture_originates_from_optimize_certified():
    from veritx_dse.optimization.evaluators import FakeDeterministicEvaluator
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY,
    )
    from veritx_dse.optimization.result import Optimizer

    study = _load("optimization-study")["optimization"]
    assert study["result_class"] == "CERTIFIED_PRODUCT"
    assert study["metric_registry_id"] == \
        CERTIFIED_METRIC_REGISTRY.registry_id()
    assert study["metric_registry_version"] == CERTIFIED_METRIC_REGISTRY.version
    assert study["pareto_ids"]
    assert study["selected_candidate_id"] in study["pareto_ids"]

    # Negative control: the analytic alias is structurally unable to
    # produce a certified result or bind registry identity.
    definition = study["definition"]
    analytic = Optimizer().optimize_with_port(
        _tiny_request(),
        _definition_from_view(definition),
        FakeDeterministicEvaluator(seed=0),
    )
    analytic_view = analytic.to_study_view()
    assert analytic_view["result_class"] == "ANALYTIC_RESEARCH"
    assert analytic_view["metric_registry_id"] is None
    assert analytic_view["metric_registry_version"] is None
    assert analytic_view["pareto_ids"] == []

    # CERTIFIED_PRODUCT has exactly one assignment site: optimize_certified.
    source = (DSE / "veritx_dse/optimization/result.py").read_text()
    assert source.count("result_class=RESULT_CLASS_CERTIFIED") == 1


def _tiny_request():
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
        TopologyFamily,
        WorkloadV3,
    )
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=4, dp=1,
            collectives=(CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.TP,
                payload_bytes=2048,
                traffic_class="tp_collective"),)),
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=600, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH,
                             concentration=1))


def _definition_from_view(definition: dict):
    from veritx_dse.optimization.definition import (
        Constraint,
        DomainParam,
        Objective,
        OptimizationDefinition,
    )
    return OptimizationDefinition(
        domain=tuple(DomainParam(name, tuple(values))
                     for name, values in definition["domain"].items()),
        objectives=tuple(Objective(o["metric"], o["direction"])
                         for o in definition["objectives"]),
        constraints=tuple(Constraint(c["metric"], c["op"], c["threshold"])
                          for c in definition["constraints"]),
        method=definition["method"],
        budget=definition["budget"],
        seed=definition.get("seed"),
        selection=definition["selection"],
    )


# ── C-6 (7) rendering distinguishes the states ──────────────────────────────

def test_unmeasurable_renders_differently_from_violated():
    presentation = json.loads(
        (STUDIO / "src/presentation.json").read_text())
    verdicts = presentation["constraintVerdict"]
    states = ("SATISFIED", "VIOLATED", "UNMEASURABLE")
    for state in states:
        assert state in verdicts, state
    classes = [verdicts[s]["class"] for s in states]
    labels = [verdicts[s]["label"] for s in states]
    assert len(set(classes)) == 3, classes
    assert len(set(labels)) == 3, labels
    assert classes[1] != classes[2] and labels[1] != labels[2]

    # Every engine enum value has a presentation; none collapses to another.
    coverage = {
        "constraintVerdict": vf.CONSTRAINT_VERDICTS,
        "objectiveState": vf.OBJECTIVE_STATES,
        "compilationStatus": vf.COMPILATION_STATUSES,
        "evaluationStatus": vf.CANDIDATE_EVALUATION_STATUSES,
        "productRequirements": {"PASS", "FAIL", "UNBOUND"},
        "eligibility": {"ELIGIBLE", "INELIGIBLE"},
        "pareto": {"MEMBER", "ELIGIBLE", "INELIGIBLE"},
    }
    for map_name, expected in coverage.items():
        assert expected <= set(presentation[map_name]), map_name
    for map_name in ("compilationStatus", "evaluationStatus", "pareto"):
        entries = presentation[map_name]
        assert len({entries[k]["label"] for k in entries}) == len(entries), \
            map_name

    # The component binds the maps (no dead policy) and never coerces an
    # absent objective to 0.
    source = (STUDIO / "src/components/OptimizeView.tsx").read_text()
    for map_name in coverage:
        assert f"presentation.{map_name}" in source, map_name
    assert "objective_availability" in source
    assert "?? 0" not in source


# ── C-6 (8) deleted synthetic generator ─────────────────────────────────────

def test_no_studio_script_references_deleted_synthetic_generator():
    assert not (FIXTURES / "generate_fixtures.py").exists()
    patterns = (
        re.compile(r"(?<!studio_)generate_fixtures"),
    )
    scanned = [
        *list((STUDIO / "scripts").rglob("*.py")),
        *list((STUDIO / "src").rglob("*.ts")),
        *list((STUDIO / "src").rglob("*.tsx")),
        *list(FIXTURES.rglob("*.json")),
        STUDIO / "README.md",
        STUDIO / "package.json",
        REPO / "tracks/t3-topology/dse/veritx_dse/tools"
        / "generate_studio_fixtures.py",
    ]
    for path in scanned:
        text = path.read_text()
        for pattern in patterns:
            assert not pattern.search(text), f"{path} references {pattern}"


# ── C-6 (9) no hard-coded synthetic authority ───────────────────────────────

def test_no_hardcoded_synthetic_authority_survives():
    scanned: list[Path] = []
    for sub in ("scripts", "src", "fixtures"):
        base = STUDIO / sub
        if not base.exists():
            continue
        scanned.extend(p for p in base.rglob("*") if p.is_file())
    for literal in ("96.4", "50000"):
        for path in scanned:
            assert literal not in path.read_text(errors="ignore"), \
                f"{literal!r} survives in {path}"
    # The old synthetic candidate table's metric names are absent.
    for marker in ("avg_packet_latency_cycles", "links_mm2"):
        for path in scanned:
            assert marker not in path.read_text(errors="ignore"), \
                f"synthetic metric {marker!r} survives in {path}"
