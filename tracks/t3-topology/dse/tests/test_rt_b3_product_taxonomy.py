"""RT-final Worker B — B3: product taxonomy over documented refusals.

``evaluate_product()`` must map the full documented refusal space of
lowering / admission / FabricEvaluator / RequirementEvaluator into the
product taxonomy deliberately, never raise a typed refusal, and never
spawn backend work for a refusal determinable before backend work.
"""
from __future__ import annotations

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.core.errors import MappingInvalid
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
from veritx_dse.workload.intent_lowering import lower_compile_workload


# ── builders ────────────────────────────────────────────────────────────

def _intent(*, kind="allreduce", dim="TP", payload=2048,
            tc="tp_collective", source=None):
    return CollectiveIntent(kind=CollectiveKind(kind),
                            dimension=CollectiveDimension(dim),
                            payload_bytes=payload, traffic_class=tc,
                            source_rank=source)


def _request(collectives, *, tp=4, dp=1,
             requirement_classes=("tp_collective",)):
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=tp, dp=dp,
            collectives=tuple(collectives)),
        requirements=tuple(
            RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL,
                          traffic_class=tc,
                          latency_ceiling_cycles=10 ** 9, binding=True)
            for tc in requirement_classes),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=tp * dp),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


class TestProductTaxonomy:
    def test_unsupported_semantics_from_lowering(self, tmp_path):
        pp = _intent(kind="allreduce", dim="PP")
        run = tmp_path / "run"
        product = evaluate_product(
            _request([pp]), run_dir=str(run),
            binary=str(tmp_path / "no-such-booksim"))
        assert product.compilation.status == "COMPILED"
        assert product.status == "UNSUPPORTED"
        assert "UnsupportedSemantics" in (product.reason or "")
        assert product.lowered is None
        assert product.outcome is None
        assert not run.exists()

    def test_unsupported_schedule_from_lowering(self, tmp_path):
        # ALLREDUCE requires B % k == 0; 2047 over 4 ranks is indivisible.
        run = tmp_path / "run"
        product = evaluate_product(
            _request([_intent(payload=2047)]), run_dir=str(run),
            binary=str(tmp_path / "no-such-booksim"))
        assert product.compilation.status == "COMPILED"
        assert product.status == "UNSUPPORTED"
        assert "UnsupportedSchedule" in (product.reason or "")
        assert product.lowered is None
        assert not run.exists()

    def test_invalid_input_from_lowering(self, tmp_path):
        bad_root = _intent(kind="broadcast", source=99)
        run = tmp_path / "run"
        product = evaluate_product(
            _request([bad_root]), run_dir=str(run),
            binary=str(tmp_path / "no-such-booksim"))
        assert product.compilation.status == "COMPILED"
        assert product.status == "INVALID"
        assert "InvalidInput" in (product.reason or "")
        assert product.lowered is None
        assert not run.exists()

    def test_requirement_scope_over_absent_traffic_refuses_pre_backend(
            self, tmp_path):
        """The only request-only RequirementEvaluator refusal must be
        decided before backend work (INVALID), never after a spawn."""
        request = _request([_intent()],
                           requirement_classes=("tp_collective",
                                                "ghost_class"))
        run = tmp_path / "run"
        product = evaluate_product(
            request, run_dir=str(run),
            binary=str(tmp_path / "no-such-booksim"))
        assert product.compilation.status == "COMPILED"
        assert product.lowered is not None
        assert product.status == "INVALID"
        assert "InvalidInput" in (product.reason or "")
        assert "ghost_class" in (product.reason or "")
        assert product.outcome is None
        assert product.requirement_report is None
        assert not run.exists()

    def test_traffic_class_admission_mapping_invalid_is_unsupported(
            self, monkeypatch, tmp_path):
        import veritx_dse.application.product_evaluator as pe

        def _refuse(lowered, vc_assignment):
            raise MappingInvalid(
                "traffic class 'tp_collective' has no legal VC mapping in "
                "the VC assignment — refusing an unroutable class")

        monkeypatch.setattr(pe, "assert_traffic_classes_bound", _refuse)
        run = tmp_path / "run"
        product = pe.evaluate_product(
            _request([_intent()]), run_dir=str(run),
            binary=str(tmp_path / "no-such-booksim"))
        assert product.compilation.status == "COMPILED"
        assert product.status == "UNSUPPORTED"
        assert "MappingInvalid" in (product.reason or "")
        assert product.lowered is None
        assert not run.exists()

    def test_fabric_identity_refusal_maps_to_product_invalid(
            self, monkeypatch, tmp_path):
        """A FabricEvaluator identity precondition reaches the product
        taxonomy deliberately (INVALID_INTENT -> INVALID), never as a
        raised exception."""
        import veritx_dse.application.product_evaluator as pe
        request_a = _request([_intent(payload=2048)])
        lowered_b = lower_compile_workload(
            _request([_intent(payload=4096)]))

        def _transplant(request):
            return lowered_b

        monkeypatch.setattr(pe, "lower_compile_workload", _transplant)
        run = tmp_path / "run"
        product = pe.evaluate_product(
            request_a, run_dir=str(run),
            binary=str(tmp_path / "no-such-booksim"))
        assert product.status == "INVALID"
        assert "INVALID_INTENT" in (product.reason or "")
        assert "transplant" in (product.reason or "")
        assert not run.exists()

    def test_bad_option_refusal_is_typed_not_raised(self, tmp_path):
        """FabricEvaluator's option preconditions are reachable from the
        product call and must map (INVALID_INTENT -> INVALID), never
        escape as a raised exception."""
        run = tmp_path / "run"
        product = evaluate_product(
            _request([_intent()]), timeout_s=0, run_dir=str(run),
            binary=str(tmp_path / "no-such-booksim"))
        assert product.status == "INVALID"
        assert "INVALID_INTENT" in (product.reason or "")
        assert product.outcome is None
        assert not run.exists()

    def test_multi_class_refuses_before_backend(self, tmp_path):
        request = _request(
            [_intent(tc="tp_collective"),
             _intent(kind="allgather", dim="DP", payload=1024,
                     tc="dp_collective")],
            tp=8, dp=4)
        run = tmp_path / "run"
        product = evaluate_product(
            request, run_dir=str(run),
            binary=str(tmp_path / "no-such-booksim"))
        assert product.status == "UNSUPPORTED"
        assert product.outcome is not None
        assert product.outcome.performance_result is None
        assert not run.exists()

    def test_backend_unavailable_is_typed(self, tmp_path):
        product = evaluate_product(
            _request([_intent()]),
            binary=str(tmp_path / "no-such-booksim"),
            run_dir=str(tmp_path / "run"))
        assert product.status == "BACKEND_UNAVAILABLE", product.reason
        assert product.outcome is not None
        assert product.outcome.performance_result is None
        assert product.requirement_report is None
        assert product.requirements_pass is None
