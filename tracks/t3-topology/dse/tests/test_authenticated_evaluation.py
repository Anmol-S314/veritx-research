"""Verifier-named tests: authenticated backend evaluation proof.

Creation (``authenticate_backend_evaluation``) dereferences the real
evidence bytes; consumption (``verify_authenticated_backend_evaluation``)
re-checks the whole chain and returns derived claims. A synthetic
``VerifiedPerformanceResult`` (A3's ``build_verified`` style, invented
digests) is refused, and no caller-supplied claim survives consumption.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest

from veritx_dse.application.authenticated_evaluation import (
    authenticate_backend_evaluation,
    verify_authenticated_backend_evaluation,
)
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.backend.evidence import (
    EvidenceArtifact,
    EvidenceRef,
    stats_sha256_of,
)
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput
from veritx_dse.core.paths import REPO
from veritx_dse.core.time import QTime
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
from veritx_dse.performance.model import (
    ClockDef,
    PerformanceModel,
    ResourceDef,
)
from veritx_dse.performance.network import (
    WINDOW_KIND_BARRIER,
    NetworkWindowBinding,
)
from veritx_dse.performance.result import (
    PerformanceEventGraph,
    build_performance_result,
)
from veritx_dse.performance.scheduler import schedule_workload
from veritx_dse.performance.workload import (
    EVENT_NETWORK_TRAFFIC_WINDOW,
    TemporalEvent,
    TemporalWorkload,
)
from veritx_dse.simulation.booksim import find_booksim_bin
from veritx_dse.workload.intent_lowering import lower_compile_workload


def _request(*, payload=2048, tp=4, dp=1):
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=tp, dp=dp,
            collectives=(CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.GLOBAL,
                payload_bytes=payload,
                traffic_class="tp_collective"),)),
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=10 ** 9, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=tp * dp),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


@pytest.fixture(scope="module")
def genuine(tmp_path_factory):
    """One REAL BookSim evaluation through the product pipeline."""
    request = _request()
    root = tmp_path_factory.mktemp("authenticated")
    product = evaluate_product(
        request, binary=str(find_booksim_bin(REPO)),
        run_dir=str(root / "run"), network_clock_hz=10 ** 9,
        timeout_s=600)
    assert product.status == "EVALUATED", product.reason
    return product


@pytest.fixture(scope="module")
def genuine_proof(genuine):
    return authenticate_backend_evaluation(
        compilation=genuine.compilation, workload=genuine.lowered.graph,
        verified_result=genuine.outcome.performance_result,
        evidence_path=genuine.outcome.evidence_path,
        producer_identity=genuine.outcome.producer_identity)


def _synthetic_verified(request, *, evidence_sha256, stats_sha256,
                        backend_input_hash, backend_config_hash,
                        resolved_fabric_hash, physical_traffic_id,
                        cycles=100):
    """A B-boundary-valid result whose binding names chosen digests.

    Used only to drive the evidence cross-checks: it is NOT a backend
    execution and ``authenticate_backend_evaluation`` refuses it unless
    the binding digests actually match the persisted evidence bytes.
    """
    graph = lower_compile_workload(request).graph
    clock = Fraction(10 ** 9)
    model = PerformanceModel(
        clocks=(ClockDef("network", clock),),
        resources=(ResourceDef("fabric.network_window", "EXCLUSIVE",
                               capacity=1),),
        network_clock="network")
    event = TemporalEvent("network_traffic_window",
                          EVENT_NETWORK_TRAFFIC_WINDOW, QTime.zero())
    temporal = TemporalWorkload(performance_model=model, events=(event,))
    binding = NetworkWindowBinding(
        workload_parent_id=graph.workload_id(), schema_version=2,
        physical_traffic_id=physical_traffic_id,
        backend_config_hash=backend_config_hash,
        backend_input_hash=backend_input_hash,
        evidence_sha256=evidence_sha256, stats_sha256=stats_sha256,
        network_clock_hz=clock, window_kind=WINDOW_KIND_BARRIER,
        duration=QTime.from_cycles(int(cycles), clock))
    chain = {
        "design_hash": request.design_hash(),
        "workload_graph_id": graph.workload_id(),
        "physical_traffic_id": physical_traffic_id,
        "resolved_fabric_hash": resolved_fabric_hash,
        "message_artifact_id": "synthetic-message",
        "backend_config_hash": backend_config_hash,
        "backend_input_hash": backend_input_hash,
        "evidence_sha256": evidence_sha256,
        "stats_sha256": stats_sha256,
    }
    egraph = PerformanceEventGraph(
        workload=temporal, network_binding=binding,
        wave_d_chain=chain)
    schedule = schedule_workload(
        temporal, network_durations=egraph.network_durations())
    perf = build_performance_result(graph=egraph, schedule=schedule)
    from veritx_dse.application.requirements import (
        verify_performance_result,
    )
    return graph, verify_performance_result(perf, workload=temporal)


def _rewrite_evidence(source_path, target_path, mutate):
    """Copy + mutate the persisted evidence JSON; return (path, digest)."""
    doc = json.loads(Path(source_path).read_text())
    mutate(doc)
    payload = json.dumps(doc)
    Path(target_path).write_text(payload)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return str(target_path), digest


class TestCreationAuthenticates:
    def test_genuine_result_authenticates(self, genuine, genuine_proof):
        proof = genuine_proof
        assert proof.design_hash == genuine.request.design_hash()
        assert proof.workload_id == genuine.lowered.graph.workload_id()
        assert proof.physical_traffic_id == \
            genuine.outcome.physical_traffic_id
        assert proof.backend_input_hash == genuine.outcome.backend_input_hash
        assert proof.evidence_ref.sha256 == \
            genuine.outcome.raw_evidence_digest
        assert proof.evidence_artifact.raw_evidence_sha256 == \
            genuine.outcome.raw_evidence_digest
        assert proof.evidence_artifact.stats_sha256 == \
            genuine.outcome.stats_digest
        assert proof.producer_identity == genuine.outcome.producer_identity
        assert proof.binding.evidence_sha256 == \
            genuine.outcome.raw_evidence_digest
        assert proof.requirement_report["performance_result_id"] == \
            genuine.outcome.performance_result_id

    def test_synthetic_build_verified_style_object_is_refused(
            self, genuine):
        """A3's ``build_verified``-style synthetic result (invented
        evidence hashes, no backend execution) cannot authenticate."""
        from p2_verified_support import build_verified
        graph, synthetic = build_verified(genuine.request)
        with pytest.raises(EvidenceInvalid) as excinfo:
            authenticate_backend_evaluation(
                compilation=genuine.compilation, workload=graph,
                verified_result=synthetic,
                evidence_path=genuine.outcome.evidence_path)
        assert "evidence" in str(excinfo.value)

    def test_modified_evidence_digest_refuses(self, genuine, tmp_path):
        path, _ = _rewrite_evidence(
            genuine.outcome.evidence_path, tmp_path / "evidence.json",
            lambda doc: doc["stats"].__setitem__(
                "completion_time", doc["stats"]["completion_time"] + 1))
        # Flip a byte so the file digest no longer matches the binding.
        raw = Path(path).read_bytes()
        Path(path).write_bytes(raw + b"\n")
        with pytest.raises(EvidenceInvalid) as excinfo:
            authenticate_backend_evaluation(
                compilation=genuine.compilation,
                workload=genuine.lowered.graph,
                verified_result=genuine.outcome.performance_result,
                evidence_path=path)
        assert "digest" in str(excinfo.value)

    def test_modified_stats_digest_refuses(self, genuine, genuine_proof,
                                           tmp_path):
        binding = genuine_proof.binding
        path, digest = _rewrite_evidence(
            genuine.outcome.evidence_path, tmp_path / "stats.json",
            lambda doc: doc["stats"].__setitem__(
                "completion_time", doc["stats"]["completion_time"] + 1))
        doc = json.loads(Path(path).read_text())
        _, synthetic = _synthetic_verified(
            genuine.request, evidence_sha256=digest,
            stats_sha256=binding.stats_sha256,
            backend_input_hash=doc["backend_input_hash"],
            backend_config_hash=doc["backend_config_hash"],
            resolved_fabric_hash=doc["resolved_fabric_hash"],
            physical_traffic_id=binding.physical_traffic_id)
        with pytest.raises(EvidenceInvalid) as excinfo:
            authenticate_backend_evaluation(
                compilation=genuine.compilation,
                workload=genuine.lowered.graph,
                verified_result=synthetic, evidence_path=path)
        assert "stats" in str(excinfo.value)

    def test_modified_backend_input_hash_refuses(self, genuine,
                                                 genuine_proof, tmp_path):
        binding = genuine_proof.binding
        path, digest = _rewrite_evidence(
            genuine.outcome.evidence_path, tmp_path / "input.json",
            lambda doc: doc.__setitem__("backend_input_hash", "a" * 64))
        doc = json.loads(Path(path).read_text())
        _, synthetic = _synthetic_verified(
            genuine.request, evidence_sha256=digest,
            stats_sha256=stats_sha256_of(doc["stats"]),
            backend_input_hash=binding.backend_input_hash,
            backend_config_hash=doc["backend_config_hash"],
            resolved_fabric_hash=doc["resolved_fabric_hash"],
            physical_traffic_id=binding.physical_traffic_id)
        with pytest.raises(EvidenceInvalid) as excinfo:
            authenticate_backend_evaluation(
                compilation=genuine.compilation,
                workload=genuine.lowered.graph,
                verified_result=synthetic, evidence_path=path)
        assert "backend_input" in str(excinfo.value)


class TestConsumptionRechecks:
    def test_derived_claims_are_returned(self, genuine, genuine_proof):
        claims = verify_authenticated_backend_evaluation(
            genuine.request, genuine_proof)
        assert claims.design_hash == genuine.request.design_hash()
        assert claims.workload_id == genuine.lowered.graph.workload_id()
        assert claims.performance_result_id == \
            genuine.outcome.performance_result_id
        assert claims.requirement_report["performance_result_id"] == \
            genuine.outcome.performance_result_id
        assert claims.requirement_report_id
        assert claims.metrics
        assert claims.metric_evidence
        for handle in claims.metric_evidence:
            assert handle.evidence_sha256 == \
                genuine.outcome.raw_evidence_digest
            assert handle.stats_sha256 == genuine.outcome.stats_digest
        assert claims.producer_identity == genuine.outcome.producer_identity
        assert claims.backend
        assert claims.backend_config_hash == \
            genuine_proof.binding.backend_config_hash
        assert claims.backend_input_hash == \
            genuine_proof.binding.backend_input_hash
        assert claims.resolved_fabric_hash == \
            genuine.compilation.bundle.resolved_fabric.\
            resolved_fabric_hash()

    def test_fabricated_proof_object_refuses(self, genuine, genuine_proof):
        """Attack 1: a hand-built proof with plausible fields is refused
        because the verifier rebuilds the artifact/binding/report."""
        invented = EvidenceArtifact.build(
            backend="FORGED", backend_input_id="0" * 64,
            backend_input_sha256="0" * 64, raw_evidence_sha256="1" * 64,
            stats={"completion_time": 1})
        forged = dataclasses.replace(genuine_proof,
                                     evidence_artifact=invented)
        with pytest.raises(EvidenceInvalid) as excinfo:
            verify_authenticated_backend_evaluation(genuine.request, forged)
        assert "evidence_artifact" in str(excinfo.value)

    def test_real_result_with_dummy_evidence_hashes_refuses(
            self, genuine, genuine_proof):
        """Attack 2: a B-boundary-valid result whose binding names dummy
        evidence hashes refuses at the evidence dereference."""
        from p2_verified_support import build_verified
        graph, synthetic = build_verified(genuine.request)
        synthetic_binding = NetworkWindowBinding.from_dict(
            synthetic.get("network_binding"))
        forged = dataclasses.replace(
            genuine_proof,
            verified_result=synthetic,
            binding=synthetic_binding,
            evidence_ref=EvidenceRef(
                path=genuine.outcome.evidence_path,
                sha256=synthetic_binding.evidence_sha256))
        with pytest.raises(EvidenceInvalid) as excinfo:
            verify_authenticated_backend_evaluation(genuine.request, forged)
        assert "evidence" in str(excinfo.value)

    def test_wrong_evidence_ref_sha_refuses(self, genuine, genuine_proof):
        """Attack 3: real evidence bytes but a wrong EvidenceRef.sha256."""
        forged = dataclasses.replace(
            genuine_proof,
            evidence_ref=dataclasses.replace(
                genuine_proof.evidence_ref, sha256="0" * 64))
        with pytest.raises(EvidenceInvalid) as excinfo:
            verify_authenticated_backend_evaluation(genuine.request, forged)
        assert "sha256" in str(excinfo.value)

    def test_mismatched_artifact_input_hash_refuses(self, genuine,
                                                    genuine_proof):
        """Attack 4: valid EvidenceRef but a mismatched EvidenceArtifact."""
        forged_artifact = dataclasses.replace(
            genuine_proof.evidence_artifact,
            backend_input_sha256="0" * 64)
        forged = dataclasses.replace(genuine_proof,
                                     evidence_artifact=forged_artifact)
        with pytest.raises(EvidenceInvalid) as excinfo:
            verify_authenticated_backend_evaluation(genuine.request, forged)
        assert "evidence_artifact" in str(excinfo.value)

    def test_transplanted_request_refuses(self, genuine, genuine_proof):
        """Attack 5: valid evidence chain but a transplanted request."""
        other = _request(payload=4096)
        with pytest.raises(EvidenceInvalid) as excinfo:
            verify_authenticated_backend_evaluation(other, genuine_proof)
        assert "transplant" in str(excinfo.value)
        # A proof whose design hash matches but whose workload id is
        # transplanted refuses at the workload-identity check too.
        forged = dataclasses.replace(genuine_proof,
                                     workload_id="0" * 64)
        with pytest.raises(EvidenceInvalid) as excinfo:
            verify_authenticated_backend_evaluation(genuine.request, forged)
        assert "workload_id" in str(excinfo.value)

    def test_fabricated_report_refuses(self, genuine, genuine_proof):
        tampered = copy.deepcopy(genuine_proof.requirement_report)
        tampered["entries"][0]["verdict"] = "VIOLATED"
        forged = dataclasses.replace(genuine_proof,
                                     requirement_report=tampered)
        with pytest.raises(EvidenceInvalid) as excinfo:
            verify_authenticated_backend_evaluation(genuine.request, forged)
        assert "requirement_report" in str(excinfo.value)

    def test_wrong_proof_type_refuses(self, genuine):
        with pytest.raises(InvalidInput):
            verify_authenticated_backend_evaluation(genuine.request, {})
        with pytest.raises(InvalidInput):
            verify_authenticated_backend_evaluation(object(), object())

    def test_booksim_error_still_maps_to_failed(self, monkeypatch,
                                                tmp_path):
        """Verifier-named test 8: the execution failure taxonomy survives
        the authenticated layer (which only wraps EVALUATED outcomes)."""
        from test_p1b_fabric_evaluator import (
            _anynet_bundle_2node,
            _compilation_for,
            _fake_binary,
            _lowered,
            _stub_qualified_booksim,
        )
        from veritx_dse.application.fabric_evaluator import (
            EvaluationOptions,
            FabricEvaluator,
        )
        from veritx_dse.core.errors import BookSimError
        fake_bin, _ = _fake_binary(tmp_path)
        _stub_qualified_booksim(
            monkeypatch, raise_exc=BookSimError("simulator crashed"))
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = FabricEvaluator().evaluate(
            comp, _lowered(comp),
            EvaluationOptions(traffic_class="A", network_clock_hz=10 ** 9,
                              binary=fake_bin, run_dir=str(tmp_path)))
        assert out.status == "FAILED"
        assert "crashed" in (out.reason or "")


def test_module_has_no_broad_except_or_assert_gates():
    """Structural audit: the proof module refuses with typed conditionals
    and never launders unexpected programming errors."""
    import ast
    source = (Path(__file__).resolve().parents[1] / "veritx_dse" /
              "application" / "authenticated_evaluation.py").read_text()
    assert "except Exception" not in source
    tree = ast.parse(source)
    asserts = [node.lineno for node in ast.walk(tree)
               if isinstance(node, ast.Assert)]
    assert asserts == [], asserts
    broad = [node.lineno for node in ast.walk(tree)
             if isinstance(node, ast.ExceptHandler) and node.type is None]
    assert broad == [], broad
