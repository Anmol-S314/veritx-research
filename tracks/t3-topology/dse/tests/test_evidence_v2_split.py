"""evidence-v2: scientific evidence separated from execution-attempt metadata.

Mandatory adversarial suite (task evidence-v2). The binding defect this
suite exists for: ``CertifiedBookSimEvidence.to_dict()`` used to include
run-varying fields (``wall_time_s``, ``backend_dir``, ``command``,
``producer_tool_identity`` = platform text), so ``EvidenceRef.sha256`` and
everything downstream (``EvidenceArtifact`` -> ``NetworkWindowBinding`` ->
``wave_d_chain`` -> ``PerformanceEventGraph.event_graph_id()`` ->
``PerformanceResult.resource_id`` -> requirement/optimization provenance)
moved between identical deterministic runs.

The repair splits the persisted document:

    ScientificBackendEvidence   veritx/backend-scientific-evidence/v2
        -> EvidenceRef.sha256 -> ... -> PerformanceResult identity

    ExecutionAttempt            veritx/execution-attempt/v1
        wall time, command/executable path, backend/run directory,
        host platform text — never hashed into the scientific chain

Cases (1-12) map one-to-one to the mandated list. Cases needing a real
BookSim run use the qualified producer discovered from the repository.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veritx_dse.application.authenticated_evaluation import (  # noqa: E402
    authenticate_backend_evaluation,
)
from veritx_dse.application.product_evaluator import (  # noqa: E402
    evaluate_product,
)
from veritx_dse.application.requirements import report_identity  # noqa: E402
from veritx_dse.backend.booksim import CertifiedBookSimEvidence  # noqa: E402
from veritx_dse.backend.evidence import (  # noqa: E402
    ATTEMPT_FILE,
    EXECUTION_ATTEMPT_SCHEMA_VERSION,
    SCIENTIFIC_EVIDENCE_SCHEMA_VERSION,
    BackendEvidenceError,
    EvidenceArtifact,
    EvidenceRef,
    ScientificBackendEvidence,
    evidence_sha256_of,
    read_evidence,
    read_verified_evidence,
    validate_evidence_document,
    write_evidence,
)
from veritx_dse.core.errors import EvidenceInvalid  # noqa: E402
from veritx_dse.backend.producer import (  # noqa: E402
    ProducerError,
    ProducerIdentity,
    verify_reusable_evidence,
)
from veritx_dse.core.paths import REPO as ENGINE_REPO  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
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
from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402


def _binary() -> Path:
    return Path(find_booksim_bin(ENGINE_REPO))


@pytest.fixture(scope="module")
def binary() -> Path:
    return _binary()


def _tiny_request() -> CompileRequestV3:
    """A 4-tile mesh intent: small enough for fast real BookSim runs."""
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


def _evaluate(run_dir: Path, binary: Path):
    product = evaluate_product(
        _tiny_request(), binary=str(binary), network_clock_hz=10 ** 9,
        timeout_s=600, run_dir=str(run_dir))
    assert product.status == "EVALUATED", product.reason
    assert product.requirement_report is not None
    return product


@pytest.fixture(scope="module")
def two_runs(binary, tmp_path_factory):
    """Two identical deterministic evaluations in different run dirs."""
    root = tmp_path_factory.mktemp("evidence-v2-determinism")
    return _evaluate(root / "run-a", binary), _evaluate(root / "run-b",
                                                        binary)


# ── unit-level evidence fixture ─────────────────────────────────────────────

def _evidence(**over) -> CertifiedBookSimEvidence:
    """One valid scientific evidence carrier; overrides are surgical."""
    kw = dict(
        backend_config_hash="1" * 64,
        backend_input_hash="2" * 64,
        resolved_fabric_hash="3" * 64,
        fabric_hash="4" * 64,
        route_equivalence="EXACT",
        route_expected_sha256="5" * 64,
        route_executed_sha256="6" * 64,
        route_pairs_compared=4,
        exact_fabric_eligible=True,
        qualification="EXECUTED_EXACT",
        semantic_loss=(),
        stats={"completion_time": 128, "delivered": 4,
               "latency": 12.5},
        exit_status=0,
        wall_time_s=1.25,
        command=("/opt/booksim", "config.cfg"),
        backend_dir="/tmp/run-a/backend",
        run_dir="/tmp/run-a",
        workload_hash="7" * 64,
        seed=11,
        seed_policy="EXPLICIT",
        rendered_inputs=(),
        invocation_args=(),
        booksim_binary_sha256="8" * 64,
        producer_source_revision="a" * 40,
        producer_source_dirty=False,
        producer_source_dirty_digest="9" * 64,
        producer_tool_identity="Linux-test-x86_64",
        execution_transport="SUPERVISED_PROCESS",
    )
    kw.update(over)
    return CertifiedBookSimEvidence(**kw)


def _science_digest(evidence: CertifiedBookSimEvidence) -> str:
    return evidence.scientific_evidence().digest()


# ── required proof: same science, different attempts ────────────────────────

class TestRequiredProof:
    def test_same_scientific_identity_across_different_run_dirs(
            self, two_runs):
        a, b = two_runs
        assert a.outcome.raw_evidence_digest == \
            b.outcome.raw_evidence_digest
        assert a.outcome.backend_config_hash == \
            b.outcome.backend_config_hash
        assert a.outcome.backend_input_hash == b.outcome.backend_input_hash
        assert a.outcome.stats_digest == b.outcome.stats_digest
        assert a.outcome.evidence_id == b.outcome.evidence_id
        assert a.outcome.performance_result["event_graph_id"] == \
            b.outcome.performance_result["event_graph_id"]
        assert a.outcome.performance_result_id == \
            b.outcome.performance_result_id
        assert report_identity(a.requirement_report) == \
            report_identity(b.requirement_report)
        assert a.outcome.metrics == b.outcome.metrics
        # The persisted document really is the v2 scientific contract.
        doc_a = read_evidence(Path(a.outcome.evidence_path))
        assert doc_a["schema_version"] == \
            SCIENTIFIC_EVIDENCE_SCHEMA_VERSION
        assert ScientificBackendEvidence.from_dict(doc_a).digest() == \
            a.outcome.raw_evidence_digest
        assert doc_a == read_evidence(Path(b.outcome.evidence_path))
        # EvidenceArtifact identity is content-derived and stable. The
        # evaluation-time artifact names the standalone backend; the
        # read-time artifact derives its backend label from the transport
        # (v2 has no platform text). Both identities are stable across
        # runs — compare like with like.
        artifacts = []
        for product in (a, b):
            ref = EvidenceRef(path=product.outcome.evidence_path,
                              sha256=product.outcome.raw_evidence_digest)
            artifact = EvidenceArtifact.from_verified_evidence(
                read_verified_evidence(ref), ref)
            artifacts.append(artifact)
            assert artifact.raw_evidence_sha256 == \
                product.outcome.raw_evidence_digest
            assert artifact.stats_sha256 == product.outcome.stats_digest
        assert artifacts[0].evidence_id() == artifacts[1].evidence_id()
        assert artifacts[0].backend == artifacts[1].backend

    def test_different_attempt_metadata_across_different_run_dirs(
            self, two_runs):
        a, b = two_runs
        assert a.outcome.attempt_path != b.outcome.attempt_path
        assert a.outcome.attempt_digest != b.outcome.attempt_digest
        doc_a = json.loads(Path(a.outcome.attempt_path).read_text())
        doc_b = json.loads(Path(b.outcome.attempt_path).read_text())
        assert doc_a["schema_version"] == EXECUTION_ATTEMPT_SCHEMA_VERSION
        assert doc_a["backend_dir"] != doc_b["backend_dir"]
        assert doc_a["run_dir"] != doc_b["run_dir"]
        assert doc_a["command"] == doc_b["command"]
        # Wall time is measured per attempt; each record carries its own
        # non-negative measurement. Independence from science is proven
        # deterministically by the wall-time adversarial case below
        # (booksim is fast enough that two real runs can land on the same
        # millisecond).
        assert doc_a["wall_time_s"] >= 0 and doc_b["wall_time_s"] >= 0
        assert doc_a["producer_tool_identity"] == \
            doc_b["producer_tool_identity"]
        # Attempt identity is external content identity, never hashed.
        assert a.outcome.attempt_digest == evidence_sha256_of(doc_a)
        assert b.outcome.attempt_digest == evidence_sha256_of(doc_b)

    def test_two_deterministic_executions_same_performance_result_id(
            self, two_runs):
        a, b = two_runs
        assert a.outcome.performance_result_id == \
            b.outcome.performance_result_id
        assert a.outcome.performance_result == b.outcome.performance_result
        assert a.outcome.performance_result_id == \
            a.outcome.performance_result["resource_id"]


# ── mandatory adversarial cases 1-12 ────────────────────────────────────────

class TestAdversarial:
    def test_1_different_run_dir_same_scientific_digest(self):
        a = _evidence()
        b = _evidence(run_dir="/tmp/run-b", backend_dir="/tmp/run-b/backend")
        assert _science_digest(a) == _science_digest(b)
        assert a.to_attempt_dict() != b.to_attempt_dict()

    def test_2_different_backend_dir_same_scientific_digest(self):
        a = _evidence()
        b = _evidence(backend_dir="/var/other/backend")
        assert _science_digest(a) == _science_digest(b)

    def test_3_different_wall_time_same_scientific_digest(self):
        a = _evidence(wall_time_s=0.008)
        b = _evidence(wall_time_s=987.654)
        assert _science_digest(a) == _science_digest(b)
        assert a.to_dict() == b.to_dict()
        assert a.to_attempt_dict() != b.to_attempt_dict()

    def test_4_altered_stats_move_scientific_digest(self):
        a = _evidence()
        b = _evidence(stats={**a.stats, "delivered": 5})
        assert _science_digest(a) != _science_digest(b)

    def test_5_altered_backend_input_moves_scientific_digest(self):
        a = _evidence()
        b = _evidence(backend_input_hash="e" * 64)
        assert _science_digest(a) != _science_digest(b)

    def test_6_altered_producer_binary_identity_moves_digest(self):
        a = _evidence()
        b = _evidence(booksim_binary_sha256="f" * 64)
        assert _science_digest(a) != _science_digest(b)

    def test_7_altered_route_realization_moves_digest(self):
        a = _evidence()
        b = _evidence(route_executed_sha256="d" * 64)
        assert _science_digest(a) != _science_digest(b)
        c = _evidence(route_equivalence="DIVERGENT")
        assert _science_digest(a) != _science_digest(c)

    def test_8_tampered_scientific_evidence_bytes_refuse(
            self, tmp_path, two_runs):
        product, _ = two_runs
        ref = EvidenceRef(path=product.outcome.evidence_path,
                          sha256=product.outcome.raw_evidence_digest)
        # In-place tamper: the external identity no longer matches.
        raw = Path(ref.path).read_bytes()
        doc = json.loads(raw)
        doc["stats"]["completion_time"] += 1
        Path(ref.path).write_text(json.dumps(doc))
        try:
            with pytest.raises(BackendEvidenceError, match="digest"):
                read_verified_evidence(ref)
        finally:
            Path(ref.path).write_bytes(raw)
        # A tampered copy named by the genuine binding refuses too.
        copy_path = tmp_path / "tampered-evidence.json"
        copy_path.write_text(json.dumps(doc))
        with pytest.raises(EvidenceInvalid):
            authenticate_backend_evaluation(
                compilation=product.compilation,
                workload=product.lowered.graph,
                verified_result=product.outcome.performance_result,
                evidence_path=str(copy_path),
                producer_identity=product.outcome.producer_identity,
            )

    def test_9_tampered_attempt_metadata_never_resigns_the_result(
            self, two_runs):
        product, _ = two_runs
        attempt_path = Path(product.outcome.attempt_path)
        before = json.loads(attempt_path.read_text())
        before_perf = product.outcome.performance_result_id
        before_report = report_identity(product.requirement_report)
        tampered = copy.deepcopy(before)
        tampered["wall_time_s"] = 999.999
        tampered["command"] = ["/forged/booksim", "forged.cfg"]
        tampered["backend_dir"] = "/forged/backend"
        attempt_path.write_text(json.dumps(tampered))
        try:
            # Scientific evidence is untouched and still verifies.
            ref = EvidenceRef(path=product.outcome.evidence_path,
                              sha256=product.outcome.raw_evidence_digest)
            assert read_verified_evidence(ref)["stats"] == \
                json.loads(Path(ref.path).read_text())["stats"]
            # The authenticated chain does not read attempt metadata; the
            # result identity is exactly what it was before the tamper.
            proof = authenticate_backend_evaluation(
                compilation=product.compilation,
                workload=product.lowered.graph,
                verified_result=product.outcome.performance_result,
                evidence_path=product.outcome.evidence_path,
                producer_identity=product.outcome.producer_identity)
            assert proof.verified_result["resource_id"] == before_perf
            assert report_identity(proof.requirement_report) == before_report
        finally:
            attempt_path.write_text(json.dumps(before))

    def test_10_real_executions_share_performance_result_id(self, two_runs):
        a, b = two_runs
        assert a.outcome.performance_result_id == \
            b.outcome.performance_result_id

    def test_11_two_certified_optimizations_same_result_id(
            self, binary, tmp_path):
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

        definition = OptimizationDefinition(
            domain=(DomainParam("link_width", (32, 64, 128)),
                    DomainParam("rcu_enabled", (False, True))),
            objectives=(Objective("completion_cycles", "MIN"),),
            constraints=(Constraint("completion_cycles", "<=", 1000.0),),
            method="grid")
        studies = []
        for name in ("opt-a", "opt-b"):
            study = Optimizer().optimize_certified(
                _tiny_request(), definition,
                backend_config=CertifiedBackendConfig(
                    binary=str(binary), network_clock_hz=10 ** 9,
                    timeout_s=600, run_root=tmp_path / name))
            assert study.result_class == "CERTIFIED_PRODUCT"
            studies.append(study)
        a, b = studies
        assert a.result_id() == b.result_id()
        assert a.pareto_ids == b.pareto_ids
        assert a.selected_candidate_id == b.selected_candidate_id
        assert [r.candidate_id for r in a.records] == \
            [r.candidate_id for r in b.records]
        for ra, rb in zip(a.records, b.records):
            assert ra.performance_result_id == rb.performance_result_id
            assert ra.requirement_report_id == rb.requirement_report_id
            assert ra.objective_values == rb.objective_values
            assert ra.constraint_verdicts == rb.constraint_verdicts

    def test_12_studio_regeneration_twice_is_byte_identical(
            self, binary, tmp_path):
        from veritx_dse.tools import generate_studio_fixtures as engine

        committed = REPO / "apps/studio/fixtures"
        roots = [tmp_path / "fixtures-A", tmp_path / "fixtures-B"]
        for root in roots:
            root.mkdir()
            for path in committed.glob("*.json"):
                shutil.copy2(path, root / path.name)
        old = engine.FIXTURE_DIR
        try:
            for root in roots:
                engine.FIXTURE_DIR = str(root)
                engine.main()
        finally:
            engine.FIXTURE_DIR = old
        names_a = sorted(p.name for p in roots[0].glob("*.json"))
        names_b = sorted(p.name for p in roots[1].glob("*.json"))
        assert names_a == names_b
        assert names_a, "generator produced no fixtures"
        for name in names_a:
            assert (roots[0] / name).read_bytes() == \
                (roots[1] / name).read_bytes(), \
                f"{name} differs between two fresh generation roots"


# ── verifier follow-up: generation-aware consumption ────────────────────────

class TestGenerationAwareConsumption:
    """v1 acceptance semantics preserved; v2 closed at every consumer.

    Blocker 1: historical v1 evidence still verifies
    ``producer_tool_identity`` (the v2 split must not relax the old
    acceptance). Blocker 2: v2 documents are schema-closed at
    consumption, so leaked-back attempt metadata is refused before any
    field is used.
    """

    @staticmethod
    def _v2_doc(**over) -> dict:
        return _evidence(**over).to_dict()

    @staticmethod
    def _v1_doc(**over) -> dict:
        """The exact historical v1 shape (attempt fields included)."""
        doc = _evidence(**over).to_dict()
        doc.pop("schema_version")
        doc.update({
            "exact_fabric_eligible": True,
            "wall_time_s": 0.008,
            "command": ["/opt/booksim", "config.cfg"],
            "backend_dir": "/tmp/run/backend",
            "producer_tool_identity": "Linux-test-x86_64",
        })
        return doc

    @staticmethod
    def _producer(**over) -> ProducerIdentity:
        kw = dict(binary_sha256="8" * 64, binary_size=1,
                  source_revision="a" * 40, source_dirty=False,
                  source_dirty_digest="9" * 64,
                  tool_identity="Linux-test-x86_64")
        kw.update(over)
        return ProducerIdentity(**kw)

    def test_v2_clean_document_round_trips(self):
        doc = self._v2_doc()
        assert validate_evidence_document(doc) == doc

    @pytest.mark.parametrize("key,value", [
        ("wall_time_s", 0.25),
        ("backend_dir", "/tmp/run-a/backend"),
        ("producer_tool_identity", "Linux-x86_64"),
        ("arbitrary_extra", {"forged": True}),
    ])
    def test_v2_closed_schema_rejects_leaked_attempt_fields(self, key,
                                                            value):
        doc = self._v2_doc()
        doc[key] = value
        with pytest.raises(BackendEvidenceError, match="mismatch"):
            validate_evidence_document(doc)

    def test_v2_unknown_schema_version_refuses(self):
        doc = self._v2_doc()
        doc["schema_version"] = "veritx/backend-scientific-evidence/v3"
        with pytest.raises(BackendEvidenceError, match="unsupported"):
            validate_evidence_document(doc)

    def test_v2_reuse_refuses_leaked_attempt_field(self, tmp_path):
        doc = self._v2_doc()
        doc["wall_time_s"] = 0.25
        ref = write_evidence(tmp_path, doc)
        with pytest.raises(BackendEvidenceError, match="mismatch"):
            verify_reusable_evidence(
                ref, backend_config_hash="1" * 64,
                backend_input_hash="2" * 64, producer=self._producer())

    def test_authenticated_open_refuses_leaked_attempt_field(
            self, tmp_path):
        from veritx_dse.application.authenticated_evaluation import (
            _open_evidence,
        )
        from veritx_dse.performance.network import NetworkWindowBinding
        doc = self._v2_doc()
        doc["wall_time_s"] = 0.25
        ref = write_evidence(tmp_path, doc)
        binding = NetworkWindowBinding(
            workload_parent_id="7" * 64, schema_version=2,
            physical_traffic_id="a" * 64,
            backend_config_hash="1" * 64, backend_input_hash="2" * 64,
            evidence_sha256=ref.sha256, stats_sha256="b" * 64,
            network_clock_hz=None,
            window_kind="BARRIER_TRAFFIC_WINDOW", duration=None)
        with pytest.raises(EvidenceInvalid, match="evidence"):
            _open_evidence(ref.path, binding)

    def test_historical_v1_exact_document_still_reuses(self, tmp_path):
        ref = write_evidence(tmp_path, self._v1_doc())
        got = verify_reusable_evidence(
            ref, backend_config_hash="1" * 64,
            backend_input_hash="2" * 64, producer=self._producer())
        assert got["producer_tool_identity"] == "Linux-test-x86_64"

    def test_historical_v1_changed_tool_identity_refuses(self, tmp_path):
        ref = write_evidence(tmp_path, self._v1_doc())
        with pytest.raises(ProducerError, match="differs in"):
            verify_reusable_evidence(
                ref, backend_config_hash="1" * 64,
                backend_input_hash="2" * 64,
                producer=self._producer(tool_identity="Darwin-arm64"))

    def test_v2_changed_platform_text_still_reuses(self, tmp_path):
        ref = write_evidence(tmp_path, self._v2_doc())
        got = verify_reusable_evidence(
            ref, backend_config_hash="1" * 64,
            backend_input_hash="2" * 64,
            producer=self._producer(tool_identity="Darwin-arm64"))
        assert "producer_tool_identity" not in got

    def test_historical_v1_missing_minimum_keys_refuses(self):
        with pytest.raises(BackendEvidenceError, match="missing"):
            validate_evidence_document({"backend_config_hash": "1" * 64})

    def test_historical_v1_producer_fields_still_required(self, tmp_path):
        doc = self._v1_doc()
        del doc["producer_tool_identity"]
        ref = write_evidence(tmp_path, doc)
        with pytest.raises(ProducerError, match="missing"):
            verify_reusable_evidence(
                ref, backend_config_hash="1" * 64,
                backend_input_hash="2" * 64, producer=self._producer())
