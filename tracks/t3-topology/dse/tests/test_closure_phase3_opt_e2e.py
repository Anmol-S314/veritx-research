"""Phase-3 opt-e2e: non-network optimization completes end to end.

RC-12 completion: ``RealCandidateEvaluator`` accepts ``binary=None``
and an ASTRA-only / Ramulator-only study runs through ProductService
to a terminal COMPLETED state with measurements + provenance — never
FAILED, never touching BookSim. The legacy default (no questions /
objectives) still resolves to NETWORK_COMPLETION and still requires
a BookSim binary.

The scripted doubles below are self-contained (not shared with other
suites) and carry archivable native inputs: under the fail-closed
archival law an EVALUATED analysis must persist its mandatory
reproduction inputs, so a double that executes must also archive.
Every archived byte is openly labeled scripted; no test presents
these numbers as backend measurements.

Live legs run only when the real producers are installed and
qualified; otherwise they skip with an explicit reason (never a
silent pass, never a failure-as-success).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendAssessment, BackendCapability, BackendReadiness,
    ModelFidelity, PreparedExecution, SupportLevel,
)
from veritx_dse.backend.booksim_adapter import (  # noqa: E402
    BookSimAdapter,
)
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    MetricValue, NormalizedBackendEvidence,
)
from veritx_dse.backend.registry import BackendRegistry  # noqa: E402
from veritx_dse.optimization.evaluators import (  # noqa: E402
    AUTHORITY_CERTIFIED_BACKEND,
)
from veritx_dse.optimization.real_evaluator import (  # noqa: E402
    EvaluationError, RealCandidateEvaluator,
)

from test_federated_optimizer import _base  # noqa: E402
from test_gateway_federation import _wait_run  # noqa: E402
from test_product_workflow import (  # noqa: E402
    _client, _make_project,
)

NETWORK = EvaluationQuestion.NETWORK_COMPLETION
SYSTEM = EvaluationQuestion.SYSTEM_MAKESPAN
DRAM = EvaluationQuestion.DRAM_TIMING


# ── port-level: binary is backend-optional ────────────────────────────

def test_binary_none_accepted_for_non_network_questions(tmp_path):
    """RC-12: explicit non-network questions construct with binary=None;
    the legacy network default still refuses without a binary."""
    from veritx_dse.optimization.definition import Objective
    objectives = (Objective("system_makespan_cycles", "MIN",
                            question=SYSTEM),)
    port = RealCandidateEvaluator(
        binary=None, run_root=str(tmp_path / "runs"),
        network_clock_hz=10 ** 9, objectives=objectives)
    assert port.binary is None
    assert port._resolve_questions() == (SYSTEM,)
    dram_port = RealCandidateEvaluator(
        binary=None, run_root=str(tmp_path / "dram"),
        network_clock_hz=10 ** 9,
        questions=(DRAM,))
    assert dram_port._resolve_questions() == (DRAM,)


def test_binary_none_refused_for_network_question_at_init(tmp_path):
    """The legacy default (no questions/objectives) resolves to
    NETWORK_COMPLETION and still requires BookSim; so does an
    explicit network question."""
    with pytest.raises(EvaluationError, match="backend binary"):
        RealCandidateEvaluator(
            binary=None, run_root=str(tmp_path / "runs"))
    with pytest.raises(EvaluationError, match="backend binary"):
        RealCandidateEvaluator(
            binary=None, run_root=str(tmp_path / "runs"),
            questions=(NETWORK,))
    # An explicit binary keeps working for network studies.
    port = RealCandidateEvaluator(
        binary="/no-such-booksim", run_root=str(tmp_path / "runs"),
        questions=(NETWORK,))
    assert port.binary == "/no-such-booksim"


def test_evaluate_reasserts_binary_before_network_leg(
        tmp_path, monkeypatch):
    """Defense in depth: even if construction allowed it, evaluate()
    refuses a network leg with binary=None before any BookSim-bound
    options are built (post-construction mutation cannot smuggle a
    network evaluation past the constructor gate)."""
    from veritx_dse.optimization.candidate import make_candidate
    port = RealCandidateEvaluator(
        binary=None, run_root=str(tmp_path / "runs"),
        network_clock_hz=10 ** 9, questions=(SYSTEM,))
    monkeypatch.setattr(
        port, "_resolve_questions", lambda: (NETWORK,))
    with pytest.raises(EvaluationError, match="backend binary"):
        port.evaluate(make_candidate(_base(), {"link_width": 64}))


def test_booksim_assess_without_resolvable_binary_is_unavailable(
        tmp_path):
    """A BookSim adapter with no configured binary and no discoverable
    one assesses UNAVAILABLE (never READY, never a crash)."""
    from veritx_dse.application.evaluation_context import (
        build_evaluation_context,
    )
    from veritx_dse.application.fabric_compiler import FabricCompiler
    compilation = FabricCompiler().compile(_base())
    assert compilation.status == "COMPILED"
    context = build_evaluation_context(compilation)
    adapter = BookSimAdapter(binary=None, repo_root=tmp_path / "empty")
    assessment = adapter.assess(context, NETWORK)
    assert assessment.readiness is BackendReadiness.UNAVAILABLE
    assert assessment.reason, "an UNAVAILABLE verdict names its reason"


# ── self-contained scripted doubles (archivable) ──────────────────────

#: per-question scripted scalar readings: (metric key, value, unit).
SCRIPTED_METRICS = {
    SYSTEM: (("system_makespan_cycles", 6070.0, "cycles"),),
    DRAM: (("average_read_latency_cycles", 42.0, "cycles"),
           ("row_hits", 900.0, None)),
}

SCRIPTED_FIDELITY = {
    SYSTEM: ModelFidelity.SYSTEM_SIMULATION,
    DRAM: ModelFidelity.MEMORY_CYCLE_SIMULATION,
}

SCRIPTED_BACKEND = {
    SYSTEM: "ASTRA2_EMBEDDED_BOOKSIM",
    DRAM: "RAMULATOR2_HBM3_V1",
}


@dataclass(frozen=True)
class _ScriptedMachine:
    """Openly scripted ASTRA machine input (archival payload only)."""

    machine_id: str = "machine-scripted"
    question: str = ""
    scripted_double: bool = True


@dataclass(frozen=True)
class _ScriptedProjection:
    """Openly scripted ASTRA workload-projection input."""

    workload_projection_id: str = "wp-scripted"
    question: str = ""
    scripted_double: bool = True


@dataclass(frozen=True)
class _ScriptedNamespace:
    """Openly scripted ASTRA namespace input."""

    namespace_id: str = "ns-scripted"
    question: str = ""
    scripted_double: bool = True


class _ScriptedArtifact:
    """Openly scripted Ramulator memory artifact (archival payload)."""

    def serialize(self) -> dict:
        return {"scripted_double": True,
                "artifact": "ramulator-scripted"}


class _ScriptedGeometry:
    """Openly scripted Ramulator geometry (archival payload)."""

    def to_dict(self) -> dict:
        return {"scripted_double": True,
                "geometry": "hbm3-single-scripted"}


class _ArchivableScriptedAdapter:
    """Deterministic orchestration double under a certified backend id.

    Answers its questions READY with fixed scalar envelopes so the
    non-network completion law can be proven without live simulators.
    The envelope is openly scripted (qualification "SCRIPTED",
    scripted native ids); no test presents these numbers as
    measurements. Unlike older doubles, prepare() carries archivable
    native inputs: fail-closed archival flips an EVALUATED analysis
    whose inputs cannot persist, so an executing double must archive.
    """

    def __init__(self, backend_id, questions):
        self._id = backend_id
        self._questions = tuple(questions)
        self.executed: list[EvaluationQuestion] = []

    @property
    def backend_id(self) -> str:
        return self._id

    def capabilities(self):
        return tuple(
            BackendCapability(
                question=q, support=SupportLevel.SUPPORTED,
                fidelity=SCRIPTED_FIDELITY[q])
            for q in self._questions)

    def assess(self, context, question):
        if question not in self._questions:
            return BackendAssessment(
                backend_id=self._id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=ModelFidelity.SYSTEM_SIMULATION,
                qualification_profile=None,
                reason=f"{self._id} answers "
                f"{[q.value for q in self._questions]} only",
                required_parents=("design",),
                limitations=())
        return BackendAssessment(
            backend_id=self._id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=SCRIPTED_FIDELITY[question],
            qualification_profile="SCRIPTED",
            reason=None,
            required_parents=("design",),
            limitations=())

    def prepare(self, context, question, **kwargs):
        if self._id == "ASTRA2_EMBEDDED_BOOKSIM":
            native: object = SimpleNamespace(
                marker=question,
                machine=_ScriptedMachine(question=question.value),
                workload_projection=_ScriptedProjection(
                    question=question.value),
                namespace=_ScriptedNamespace(
                    question=question.value))
        else:
            native = SimpleNamespace(
                marker=question,
                artifact=_ScriptedArtifact(),
                memory_artifact_hash="m" * 64,
                access_stream_hash="a" * 64,
                backend_config_hash="c" * 64,
                geometry=_ScriptedGeometry())
        return PreparedExecution(
            backend_id=self._id, projection_identity="wp-scripted",
            qualification_identity="m-scripted",
            backend_config=None, backend_input=None, producer=None,
            native_prepared=native)

    def execute(self, prepared, options):
        question = prepared.native_prepared.marker
        self.executed.append(question)
        return SimpleNamespace(
            question=question, status="PASS",
            metrics={}, failure_reason=None,
            evidence_tier="SCRIPTED_TIER",
            expansion_authority="scripted",
            autonomous_injection_packets=0,
            participant_statistics_present=True,
            namespace_binding="SCRIPTED", namespace_id="ns-scripted",
            rank_to_endpoint=((0, 0), (1, 1)),
            aggregate_cycles=1000, aggregate_exposed_comm=100)

    def normalize(self, context, question, prepared, native_result):
        resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        resolved_hash = resolved() if callable(resolved) else resolved
        fidelity = SCRIPTED_FIDELITY[question]
        return NormalizedBackendEvidence(
            backend_id=self._id, question=question,
            model_fidelity=fidelity,
            canonical_parent_ids=(
                context.design_hash, resolved_hash,
                context.workload_id, "wp-scripted"),
            native_evidence_id=f"native-{self._id}-{question.value}",
            qualification="SCRIPTED",
            producer_identity="s" * 64,
            metrics=tuple(
                MetricValue(key=key, value=value, unit=unit,
                            source_metric_key=key)
                for key, value, unit in SCRIPTED_METRICS[question]),
            limitations=())


def _scripted_registry():
    astra = _ArchivableScriptedAdapter(
        "ASTRA2_EMBEDDED_BOOKSIM", (SYSTEM,))
    dram = _ArchivableScriptedAdapter("RAMULATOR2_HBM3_V1", (DRAM,))
    return BackendRegistry((astra, dram)), astra, dram


# ── service-level: scripted non-network studies COMPLETE ──────────────

def _boom(*args, **kwargs):
    raise AssertionError(
        "BookSim must never be invoked for a non-network study")


def _scripted_client(tmp_path, monkeypatch):
    """Gateway client whose federation is the scripted ASTRA + DRAM
    registry, with tripwires proving the BookSim leg is never touched:
    the adapter seam and the legacy FabricEvaluator both detonate on
    any call."""
    import veritx_dse.application.federated_evaluator as _fed
    registry, astra, dram = _scripted_registry()
    monkeypatch.setattr(
        "veritx_dse.backend.registry.default_backend_registry",
        lambda **kw: registry)
    monkeypatch.setattr(BookSimAdapter, "assess", _boom)
    monkeypatch.setattr(BookSimAdapter, "prepare", _boom)
    monkeypatch.setattr(BookSimAdapter, "execute", _boom)
    monkeypatch.setattr(_fed, "FabricEvaluator", _boom)
    client = _client(tmp_path, with_backend=False)
    return client, astra, dram


def _study(metric: str, direction: str, question: str) -> dict:
    return {
        "domain": [{"name": "link_width", "values": [64, 128]}],
        "objectives": [{"metric": metric, "direction": direction,
                        "question": question}],
    }


def _submit_and_wait_completed(client, revision_id: str,
                               study: dict) -> dict:
    """Submit a study and wait for the terminal state. COMPLETED is
    required: FAILED/REFUSED/CANCELLED are failures, never success."""
    resp = client.post(f"/api/v1/revisions/{revision_id}/optimize",
                       json=study)
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] in ("QUEUED", "PREPARING", "RUNNING"), (
        resp.json())
    job = _wait_run(client, resp.json()["job_id"])
    assert job["state"] == "COMPLETED", job
    optimization_id = job["result"]["optimization_id"]
    return client.get(
        f"/api/v1/optimizations/{optimization_id}").json()


def _revision(client) -> str:
    pid = _make_project(client)["project"]["project_id"]
    assert client.post(f"/api/v1/projects/{pid}/compile").status_code \
        == 200
    return client.get(f"/api/v1/projects/{pid}").json()[
        "active_revision_id"]


def _assert_measured(candidate: dict, metric: str, question: str,
                     backend: str, fidelity: str, value: float) -> None:
    assert candidate["evaluation_status"] == "EVALUATED", candidate
    assert candidate["evaluation_authority"] == \
        AUTHORITY_CERTIFIED_BACKEND, candidate
    assert candidate["objective_values"].get(metric) == value, candidate
    assert candidate["objective_availability"].get(metric) == \
        "MEASURED", candidate
    matches = [p for p in candidate["objective_provenance"]
               if p["metric_key"] == metric]
    assert len(matches) == 1, candidate["objective_provenance"]
    prov = matches[0]
    assert prov["question"] == question, prov
    assert prov["backend_id"] == backend, prov
    assert prov["model_fidelity"] == fidelity, prov
    assert prov["qualification"], prov
    assert prov["native_evidence_id"], prov
    assert prov["value"] == value, prov


def test_astra_only_study_completes_with_measurements_and_provenance(
        tmp_path, monkeypatch):
    """RC-12 end to end: an ASTRA-only study submits with no BookSim
    binary, the job COMPLETES (not FAILED), both candidates carry
    measured makespan values with backend/question/native-evidence
    provenance, ASTRA executed exactly once per candidate, and the
    BookSim tripwires never fired."""
    client, astra, dram = _scripted_client(tmp_path, monkeypatch)
    rid = _revision(client)
    astra.executed.clear()
    dram.executed.clear()
    study = _submit_and_wait_completed(
        client, rid,
        _study("system_makespan_cycles", "MIN", "SYSTEM_MAKESPAN"))
    candidates = study["study"]["candidates"]
    assert len(candidates) == 2, study
    for candidate in candidates:
        _assert_measured(
            candidate, "system_makespan_cycles", "SYSTEM_MAKESPAN",
            "ASTRA2_EMBEDDED_BOOKSIM", "SYSTEM_SIMULATION", 6070.0)
    assert [q for q in astra.executed] == [SYSTEM, SYSTEM]
    assert dram.executed == []


def test_ramulator_only_study_completes_with_measurements_and_provenance(
        tmp_path, monkeypatch):
    """RC-12 end to end, memory leg: a Ramulator-only study submits
    with no BookSim binary, the job COMPLETES, both candidates carry
    measured DRAM values with provenance, Ramulator executed exactly
    once per candidate, and the BookSim tripwires never fired."""
    client, astra, dram = _scripted_client(tmp_path, monkeypatch)
    rid = _revision(client)
    astra.executed.clear()
    dram.executed.clear()
    study = _submit_and_wait_completed(
        client, rid,
        _study("average_read_latency_cycles", "MIN", "DRAM_TIMING"))
    candidates = study["study"]["candidates"]
    assert len(candidates) == 2, study
    for candidate in candidates:
        _assert_measured(
            candidate, "average_read_latency_cycles", "DRAM_TIMING",
            "RAMULATOR2_HBM3_V1", "MEMORY_CYCLE_SIMULATION", 42.0)
    assert [q for q in dram.executed] == [DRAM, DRAM]
    assert astra.executed == []


# ── live legs: real producers or explicit skip ────────────────────────

def _astra_live_binary():
    """The installed ASTRA producer, iff it is pinned (manifest-verified
    clean build of the required recipe). Anything less is not a
    qualified producer, so the live tests skip instead of pretending."""
    from veritx_dse.backend import astra as _astra_mod
    from veritx_dse.backend.astra_execution import (
        ASTRA_BUILD_RECIPE_VERSION,
    )
    from veritx_dse.backend.producer import (
        ProducerError, assert_pinned_producer,
        resolve_producer_identity,
    )
    binary = _astra_mod.resolve_runtime_binary()
    if binary is None:
        return None
    try:
        identity = resolve_producer_identity(
            binary, require_manifest_recipe=ASTRA_BUILD_RECIPE_VERSION)
        assert_pinned_producer(identity)
    except ProducerError:
        return None
    return binary


needs_live_astra = pytest.mark.skipif(
    _astra_live_binary() is None,
    reason="no pinned ASTRA producer installed — live ASTRA leg "
           "cannot run here")


@needs_live_astra
def test_live_astra_only_optimization_completes_with_binary_none(
        tmp_path):
    """Live RC-12: with a qualified ASTRA producer but NO BookSim
    binary configured, an ASTRA-only study COMPLETES and both
    candidates carry measured makespan values with authentic ASTRA
    provenance (native evidence ids are content identities, and the
    makespan values are backend measurements, not scripted)."""
    from veritx_dse.gateway.app import (
        GatewayConfig, create_app,
    )
    from fastapi.testclient import TestClient
    binary = _astra_live_binary()
    assert binary is not None
    cfg = GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects",
        booksim_bin=None, astra_bin=Path(binary), timeout_s=600)
    client = TestClient(create_app(cfg), raise_server_exceptions=False)
    rid = _revision(client)
    study = _submit_and_wait_completed(
        client, rid,
        _study("system_makespan_cycles", "MIN", "SYSTEM_MAKESPAN"))
    candidates = study["study"]["candidates"]
    assert len(candidates) == 2, study
    for candidate in candidates:
        assert candidate["evaluation_status"] == "EVALUATED", candidate
        value = candidate["objective_values"].get(
            "system_makespan_cycles")
        assert isinstance(value, float) and value > 0, candidate
        matches = [p for p in candidate["objective_provenance"]
                   if p["metric_key"] == "system_makespan_cycles"]
        assert len(matches) == 1, candidate["objective_provenance"]
        prov = matches[0]
        assert prov["backend_id"] == "ASTRA2_EMBEDDED_BOOKSIM", prov
        assert prov["question"] == "SYSTEM_MAKESPAN", prov
        assert prov["native_evidence_id"].startswith("sha256:"), prov
        assert prov["value"] == value, prov


def _ramulator_live() -> tuple[str, Path] | None:
    """A Ramulator backend this interpreter can execute, iff its
    extension is built AND its discovery reports ready (manifest-bound
    bytes, valid producer). Anything less skips instead of pretending."""
    from veritx_dse.simulation import ramulator as _sim
    vendor = Path(_sim.__file__).resolve().parent.parent.parent / \
        "ramulator2"
    if not vendor.is_dir():
        vendor = Path(
            __file__).resolve().parent.parent.parent.parent / \
            "third_party" / "ramulator2"
    if not list(vendor.glob("python/ramulator/_ramulator*.so")):
        return None
    try:
        backend = _sim.discover()
    except Exception:  # noqa: BLE001 - discovery failure means skip
        return None
    if not backend.ready:
        return None
    return sys.executable, vendor


needs_live_ramulator = pytest.mark.skipif(
    _ramulator_live() is None,
    reason="no ready Ramulator backend for this interpreter — live "
           "Ramulator leg cannot run here")


@needs_live_ramulator
def test_live_ramulator_only_optimization_reports_honest_unsupported(
        tmp_path):
    """Live RC-12 + no-fake law: with a ready Ramulator backend but no
    BookSim binary, a Ramulator-only study over the dense workload
    (which carries no resolvable COMPUTE memory demand) COMPLETES with
    records UNSUPPORTED — never EVALUATED, never FAILED, values absent
    (never zero), with the memory-demand reason recorded."""
    from veritx_dse.gateway.app import (
        GatewayConfig, create_app,
    )
    from fastapi.testclient import TestClient
    cfg = GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects",
        booksim_bin=None, timeout_s=600)
    client = TestClient(create_app(cfg), raise_server_exceptions=False)
    rid = _revision(client)
    study = _submit_and_wait_completed(
        client, rid,
        _study("average_read_latency_cycles", "MIN", "DRAM_TIMING"))
    candidates = study["study"]["candidates"]
    assert len(candidates) == 2, study
    for candidate in candidates:
        assert candidate["evaluation_status"] == "UNSUPPORTED", \
            candidate
        assert candidate["objective_values"] == {}, candidate
        assert candidate["objective_availability"].get(
            "average_read_latency_cycles") == "UNMEASURABLE", candidate
