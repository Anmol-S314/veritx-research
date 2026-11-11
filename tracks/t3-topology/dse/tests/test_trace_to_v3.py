"""LLMServingSim trace rows must reach lowering, with nothing invented.

Rationale: docs/decisions/modules/workload.md
"""
import pytest

from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CollectiveDimension,
    CompileRequestV3,
    DependencyGraph,
    ModelFamily,
    NocConfig,
    TopologyFamily,
)
from veritx_dse.workload.canonical import Parallelism, artifact_from_trace_rows
from veritx_dse.workload.intent_lowering import lower_compile_workload
from veritx_dse.workload.trace_to_v3 import (
    TraceAdapterUnsupported,
    dimension_size,
    workload_v3_from_trace,
)

# The documented 11-field row grammar:
# label comp_ns in_loc in_bytes w_loc w_bytes out_loc out_bytes comm comm_size tag
DENSE_ROWS = [
    ("attention", "1000", "LOCAL", "2048", "LOCAL", "4096", "LOCAL", "2048",
     "ALLREDUCE:1,0", "2048", "BATCH_1"),
    ("mlp", "700", "LOCAL", "512", "LOCAL", "1024", "LOCAL", "512",
     "NONE", "0", "BATCH_1"),
]
# A real MoE layer mixes a TP all-reduce with an EP all-to-all.
MOE_ROWS = [
    ("attention", "1000", "LOCAL", "2048", "LOCAL", "4096", "LOCAL", "2048",
     "ALLREDUCE:1,0", "2048", "BATCH_1"),
    ("EXPERT 0 ALLTOALL:1,0 4096",),
    ("expert_mlp", "800", "LOCAL", "4096", "LOCAL", "8192", "LOCAL", "4096",
     "NONE", "0", "BATCH_1"),
    ("EXPERT END",),
]


def _artifact(rows=DENSE_ROWS, tp=8, ep=1):
    return artifact_from_trace_rows(
        rows, workload_id="trace-probe",
        parallelism=Parallelism(tp=tp, ep=ep), num_participants=tp)


class _Op:
    def __init__(self, *, kind="ALLREDUCE", op_id="coll-0", size=2048,
                 participants=None, scope=(True, False), comm_kind=None):
        self.kind, self.op_id, self.bytes = kind, op_id, size
        self.participants = participants if participants is not None \
            else tuple(range(8))
        self.scope = scope
        self.comm_kind = comm_kind


class _Artifact:
    def __init__(self, ops, parallelism):
        self._ops, self.parallelism = ops, parallelism

    def comm_ops(self):
        return tuple(self._ops)


def _fake(ops, parallelism):
    return _Artifact(ops, parallelism)


def _convert(artifact, **kwargs):
    if "dimension_of_kind" not in kwargs:
        kwargs.setdefault("dimension", CollectiveDimension.TP)
    return workload_v3_from_trace(
        artifact, model_family=ModelFamily.DENSE_TRANSFORMER,
        traffic_class="tp_collective", **kwargs)


def _request(workload, ranks=8):
    return CompileRequestV3(
        workload=workload, requirements=(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=ranks),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(
            topology_family=TopologyFamily.MESH, concentration=1))


def test_dense_trace_becomes_declared_intents():
    workload = _convert(_artifact())
    assert workload.tp == 8
    assert len(workload.collectives) == 1
    intent = workload.collectives[0]
    assert intent.payload_bytes == 2048          # the row's own comm_size
    assert intent.dimension is CollectiveDimension.TP
    assert intent.traffic_class == "tp_collective"


def test_adapter_output_reaches_lowering():
    """The whole point: the import path used to end one type short."""
    lowered = lower_compile_workload(_request(_convert(_artifact())))
    assert len(lowered.graph.of_kind("COLLECTIVE")) == 1
    assert lowered.design_hash


def test_moe_trace_splits_tp_allreduce_from_ep_alltoall():
    workload = _convert(
        _artifact(MOE_ROWS, tp=8, ep=8),
        dimension_of_kind={
            "ALLREDUCE": CollectiveDimension.TP,
            "ALLTOALL": CollectiveDimension.EP,
        })
    by_kind = {intent.kind.value: intent for intent in workload.collectives}
    assert sorted(by_kind) == ["allreduce", "alltoall"]
    assert by_kind["allreduce"].dimension is CollectiveDimension.TP
    assert by_kind["alltoall"].dimension is CollectiveDimension.EP
    assert by_kind["alltoall"].payload_bytes == 4096   # the EXPERT row's size


def test_refuses_a_collective_with_no_declared_dimension():
    # The trace has an ALLTOALL but dimension_of_kind names none for it.
    with pytest.raises(TraceAdapterUnsupported, match="names no dimension"):
        _convert(_artifact(MOE_ROWS, tp=8, ep=8),
                 dimension_of_kind={"ALLREDUCE": CollectiveDimension.TP})


def test_refuses_a_trace_whose_participants_disagree_with_its_parallelism():
    # tp=1 while the rows address eight ranks: internally inconsistent.
    fake = _fake([_Op()], Parallelism(tp=1))
    with pytest.raises(TraceAdapterUnsupported, match="addresses 8 ranks"):
        _convert(fake)


def test_refuses_the_pipeline_dimension():
    with pytest.raises(TraceAdapterUnsupported, match="PP is refused"):
        _convert(_artifact(), dimension=CollectiveDimension.PP)


def test_refuses_an_all_scope_narrowed_to_one_dimension():
    # scope ALL says every dimension; calling it TP would be a narrowing.
    fake = _fake([_Op(scope="ALL")], Parallelism(tp=8))
    with pytest.raises(TraceAdapterUnsupported, match="all-dimension"):
        _convert(fake)


def test_accepts_an_all_scope_as_global():
    fake = _fake([_Op(scope="ALL")], Parallelism(tp=8))
    workload = _convert(fake, dimension=CollectiveDimension.GLOBAL)
    assert workload.collectives[0].dimension is CollectiveDimension.GLOBAL


def test_refuses_a_multi_dimension_scope():
    fake = _fake([_Op(scope=[True, True])], Parallelism(tp=8, dp=2))
    with pytest.raises(TraceAdapterUnsupported, match="participates on 2"):
        _convert(fake)


def test_refuses_an_undeclared_payload():
    fake = _fake([_Op(size=0)], Parallelism(tp=8))
    with pytest.raises(TraceAdapterUnsupported, match="DECLARED"):
        _convert(fake)


def test_refuses_broadcast_because_the_dialect_has_no_root():
    fake = _fake([_Op(kind="BROADCAST")], Parallelism(tp=8))
    with pytest.raises(TraceAdapterUnsupported, match="no root"):
        _convert(fake)


def test_refuses_an_unknown_collective_kind():
    fake = _fake([_Op(kind="SCATTER")], Parallelism(tp=8))
    with pytest.raises(TraceAdapterUnsupported, match="no v3 intent mapping"):
        _convert(fake)


def test_an_expert_marker_without_a_collective_contributes_no_intent():
    fake = _fake([_Op(kind="EXPERT_BEGIN", comm_kind=None),
                  _Op(kind="EXPERT_END", comm_kind=None)], Parallelism(tp=8))
    assert _convert(fake).collectives == ()


def test_requires_a_declared_rank_space():
    # Neither dimension nor dimension_of_kind: refused, never defaulted.
    with pytest.raises(TraceAdapterUnsupported, match="exactly one of"):
        workload_v3_from_trace(
            _artifact(), model_family=ModelFamily.DENSE_TRANSFORMER,
            traffic_class="tp_collective")
    # Both: ambiguous, refused.
    with pytest.raises(TraceAdapterUnsupported, match="exactly one of"):
        workload_v3_from_trace(
            _artifact(), model_family=ModelFamily.DENSE_TRANSFORMER,
            traffic_class="tp_collective",
            dimension=CollectiveDimension.TP,
            dimension_of_kind={"ALLREDUCE": CollectiveDimension.TP})


def test_family_and_traffic_class_are_required():
    # No defaults: a caller cannot inherit a family or a QoS identity.
    with pytest.raises(TypeError):
        workload_v3_from_trace(_artifact())  # type: ignore[call-arg]


def test_dimension_size_reads_the_declared_parallelism():
    parallelism = Parallelism(tp=8, dp=2, ep=4, pp=2)
    assert dimension_size(parallelism, CollectiveDimension.TP) == 8
    assert dimension_size(parallelism, CollectiveDimension.EP) == 4
    assert dimension_size(parallelism, CollectiveDimension.GLOBAL) == 128
