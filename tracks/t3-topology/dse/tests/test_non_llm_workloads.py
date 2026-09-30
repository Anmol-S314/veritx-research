"""Non-LLM workloads: the lowering consumes declared collectives, not family.

`ModelFamily` declares DIFFUSION/CNN/CUSTOM, and the compiler certifies such
requests — but the lowering used to refuse every non-transformer family. That
produced contradictory verdicts for the same document (compile PASS,
evaluation BLOCKED). These tests pin the corrected precondition: state your
collectives and the family does not matter.
"""
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.errors import UnsupportedSemantics
from veritx_dse.model.compile_model import (
    CollectiveDimension, CollectiveIntent, CollectiveKind, DependencyGraph,
    ModelFamily, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.compute_intent import ComputeIntent, ComputeStage
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.model.noc_controls import NocControls
from veritx_dse.workload.intent_lowering import lower_compile_workload


def _request(*, family, collectives=(), stages=()):
    return CompileRequestV4(
        workload=WorkloadV3(model_family=family, model_name="non-llm",
                            tp=4, ep=1, pp=1, dp=1,
                            collectives=tuple(collectives)),
        dependencies=DependencyGraph(()),
        agents=(),
        topology=MeshIntent(side_length=2, concentration=1),
        noc_controls=NocControls(),
        compute=ComputeIntent(stages=tuple(stages)))


SKA_ALLTOALL = CollectiveIntent(
    kind=CollectiveKind.ALLTOALL, dimension=CollectiveDimension.TP,
    payload_bytes=8192, traffic_class="station_ingest")


def test_a_non_transformer_family_with_declared_collectives_lowers():
    lowered = lower_compile_workload(_request(
        family=ModelFamily.CUSTOM, collectives=(SKA_ALLTOALL,)))
    kinds = {op.kind for op in lowered.graph.operations}
    assert "COLLECTIVE" in kinds


def test_a_non_transformer_family_with_nothing_declared_still_refuses():
    with pytest.raises(UnsupportedSemantics, match="declares no collectives"):
        lower_compile_workload(_request(family=ModelFamily.CNN))


def test_the_refusal_names_the_remedy_not_just_the_family():
    with pytest.raises(UnsupportedSemantics,
                       match="state its collectives explicitly"):
        lower_compile_workload(_request(family=ModelFamily.DIFFUSION))


def test_transformer_families_are_unchanged():
    lowered = lower_compile_workload(_request(
        family=ModelFamily.DENSE_TRANSFORMER, collectives=(SKA_ALLTOALL,)))
    assert lowered.graph.operations


def test_an_empty_transformer_still_reports_the_empty_intent():
    from veritx_dse.core.errors import InvalidInput
    with pytest.raises(InvalidInput, match="no collectives and no compute"):
        lower_compile_workload(_request(family=ModelFamily.DENSE_TRANSFORMER))
