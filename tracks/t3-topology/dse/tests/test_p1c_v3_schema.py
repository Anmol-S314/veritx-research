"""P1C v3 schema tests: v2 frozen + v3 envelope + migration + source ingest.

Run: cd tracks/t3-topology/dse && python3 -m pytest tests/test_p1c_v3_schema.py -q
"""
from __future__ import annotations

import pytest

from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequest,
    CompileRequestV3,
    CompileRequestV3SchemaError,
    Dependency,
    DependencyGraph,
    DepKind,
    ModelFamily,
    NocConfig,
    QoSClass,
    Requirement,
    RequirementV3,
    ServingMode,
    TopologyFamily,
    Workload,
    WorkloadV3,
    WorkloadSourceRef,
    derive_v3_traffic_classes,
    ingest_workload_source,
    ingest_workload_source_file,
    migrate_v2_to_v3,
)


def _agents(n=32):
    return (Agent(kind=AgentKind.COMPUTE_TILE, count=n),)


def _v3_request(**kw):
    workload = kw.pop("workload", WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=8, dp=4,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE,
            dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),)))
    return CompileRequestV3(
        workload=workload,
        requirements=kw.pop("requirements", (RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=5000, binding=True),)),
        agents=kw.pop("agents", _agents()),
        dependencies=kw.pop("dependencies", DependencyGraph([])),
        noc_config=kw.pop("noc_config", NocConfig(
            topology_family=TopologyFamily.MESH)),
        **kw,
    )


class TestV2Frozen:
    """v2 interpretation is unchanged by the v3 addition."""

    def test_v2_envelope_constants_untouched(self):
        from veritx_dse.model.compile_model import (
            COMPILE_REQUEST_SCHEMA_VERSION, COMPILER_SEMANTICS_VERSION)
        assert COMPILE_REQUEST_SCHEMA_VERSION == 2
        assert COMPILER_SEMANTICS_VERSION == 2

    def test_v2_still_refuses_v3_schema(self):
        doc = _v3_request().to_dict()
        assert doc["schema_version"] == 3
        with pytest.raises(Exception):
            CompileRequest.from_dict(doc)

    def test_v2_requirement_still_has_no_traffic_class(self):
        import veritx_dse.model.compile_model as cm
        assert "traffic_class" not in cm._REQUIREMENT_KEYS
        assert "qos_class" in cm._REQUIREMENT_KEYS

    def test_v2_collective_keys_unchanged(self):
        import veritx_dse.model.compile_model as cm
        assert cm._COLLECTIVE_KEYS == frozenset(
            {"kind", "group_size", "bytes_per_element"})


class TestV3Envelope:
    def test_versions_and_distinct_hash_domain(self):
        r = _v3_request()
        assert r.schema_version == 3
        assert r.compiler_semantics_version == 3
        assert len(r.design_hash()) == 64
        assert r.guardrail_hash() == r.design_hash()

    def test_roundtrip_lossless(self):
        r = _v3_request()
        assert CompileRequestV3.from_dict(r.to_dict()).to_dict() == r.to_dict()

    def test_identity_pinned(self):
        # Drift detector: this exact document hashes to this exact value.
        assert _v3_request().design_hash() == \
            "575dccaa64233f178fabac65ada25a065c9b75ec6f1516c0bc3ae1ef316af8be"

    def test_v3_refuses_v2_documents(self):
        v2 = CompileRequest(
            workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER),
            requirements=(), agents=_agents(1),
            dependencies=DependencyGraph([]), noc_config=NocConfig())
        with pytest.raises(CompileRequestV3SchemaError):
            CompileRequestV3.from_dict(v2.to_dict())

    def test_strict_unknown_fields_refuse(self):
        doc = _v3_request().to_dict()
        doc["workload"]["collectives"][0]["bytes_per_element"] = 2048
        with pytest.raises(CompileRequestV3SchemaError):
            CompileRequestV3.from_dict(doc)

    def test_tampered_hash_refuses(self):
        doc = _v3_request().to_dict()
        doc["design_hash"] = "0" * 64
        with pytest.raises(CompileRequestV3SchemaError):
            CompileRequestV3.from_dict(doc)


class TestCollectiveIntent:
    def test_broadcast_requires_source(self):
        with pytest.raises(ValueError):
            CollectiveIntent(kind=CollectiveKind.BROADCAST,
                             dimension=CollectiveDimension.GLOBAL,
                             payload_bytes=1024, traffic_class="bcast")

    def test_non_broadcast_refuses_source(self):
        with pytest.raises(ValueError):
            CollectiveIntent(kind=CollectiveKind.ALLREDUCE,
                             dimension=CollectiveDimension.TP,
                             payload_bytes=1024, traffic_class="t",
                             source_rank=0)

    def test_broadcast_with_source_ok(self):
        c = CollectiveIntent(kind=CollectiveKind.BROADCAST,
                             dimension=CollectiveDimension.GLOBAL,
                             payload_bytes=1024, traffic_class="bcast",
                             source_rank=0)
        assert c.source_rank == 0

    def test_traffic_class_required_nonempty(self):
        with pytest.raises(ValueError):
            CollectiveIntent(kind=CollectiveKind.ALLREDUCE,
                             dimension=CollectiveDimension.TP,
                             payload_bytes=1024, traffic_class="")


class TestRequirementV3:
    def test_identity_distinct_from_policy(self):
        r = RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL,
                          traffic_class="tp_collective",
                          latency_ceiling_cycles=100, binding=True)
        assert r.traffic_class == "tp_collective"
        assert r.qos_class == QoSClass.LATENCY_CRITICAL

    def test_fabric_wide_default(self):
        assert RequirementV3(qos_class=QoSClass.BANDWIDTH).traffic_class is None


class TestSourceRef:
    def test_ingest_binds_bytes_not_paths(self, tmp_path):
        p = tmp_path / "trace.bin"
        p.write_bytes(b"packet-bytes-fixture")
        ref, data = ingest_workload_source_file(
            p, format="packet_trace", artifact_identity="fx")
        assert data == b"packet-bytes-fixture"
        assert ref.size_bytes == len(data)
        assert ref.content_digest.startswith("sha256:")
        assert ref == ingest_workload_source(b"packet-bytes-fixture",
                                             format="packet_trace",
                                             artifact_identity="fx")

    def test_mutated_bytes_change_identity(self):
        a = ingest_workload_source(b"v1", format="packet_trace")
        b = ingest_workload_source(b"v2", format="packet_trace")
        assert a.content_digest != b.content_digest

    def test_bad_digest_refuses(self):
        with pytest.raises(ValueError):
            WorkloadSourceRef(content_digest="runs/traces/x.trace",
                              format="packet_trace")

    def test_v3_workload_has_no_path_field(self):
        import veritx_dse.model.compile_model as cm
        assert "trace_path" not in cm._WORKLOAD_V3_KEYS
        assert "workload_source_ref" in cm._WORKLOAD_V3_KEYS


class TestMigration:
    def _v2(self, **kw):
        return CompileRequest(
            workload=Workload(
                model_family=ModelFamily.DENSE_TRANSFORMER, tp=8, dp=1,
                collectives=kw.pop("collectives", ()),
                trace_path=kw.pop("trace_path", None)),
            requirements=(Requirement(
                qos_class=QoSClass.LATENCY_CRITICAL,
                latency_ceiling_cycles=5000, binding=True),),
            agents=_agents(8),
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH))

    def test_no_collectives_migrates_clean(self):
        v3 = migrate_v2_to_v3(self._v2(), collective_specs=[])
        assert isinstance(v3, CompileRequestV3)
        assert v3.workload.collectives == ()
        assert v3.requirements[0].traffic_class is None  # fabric-wide

    def test_spec_count_mismatch_refuses(self):
        from veritx_dse.model.compile_model import CollectiveOp
        v2 = self._v2(collectives=(
            CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8,
                         bytes_per_element=2048),))
        with pytest.raises(CompileRequestV3SchemaError):
            migrate_v2_to_v3(v2, collective_specs=[])  # no guessing

    def test_explicit_spec_migrates(self):
        from veritx_dse.model.compile_model import CollectiveOp
        v2 = self._v2(collectives=(
            CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8,
                         bytes_per_element=2048),))
        v3 = migrate_v2_to_v3(v2, collective_specs=[{
            "dimension": "TP", "payload_bytes": 8192,
            "traffic_class": "tp_collective"}])
        c = v3.workload.collectives[0]
        assert (c.kind, c.dimension, c.payload_bytes, c.traffic_class) == (
            CollectiveKind.ALLREDUCE, CollectiveDimension.TP, 8192,
            "tp_collective")

    def test_trace_path_without_ingest_refuses(self):
        with pytest.raises(CompileRequestV3SchemaError):
            migrate_v2_to_v3(self._v2(trace_path="runs/traces/x.trace"),
                             collective_specs=[])

    def test_trace_path_with_ingest_ok(self):
        ref = ingest_workload_source(b"bytes", format="packet_trace")
        v3 = migrate_v2_to_v3(self._v2(trace_path="runs/traces/x.trace"),
                              collective_specs=[], source_ref=ref)
        assert v3.workload.source_ref == ref


class TestTrafficRegistry:
    def test_registry_is_sorted_distinct(self):
        r = _v3_request(workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=4, dp=2,
            collectives=(
                CollectiveIntent(kind=CollectiveKind.ALLREDUCE,
                                 dimension=CollectiveDimension.TP,
                                 payload_bytes=2048,
                                 traffic_class="tp_collective"),
                CollectiveIntent(kind=CollectiveKind.ALLGATHER,
                                 dimension=CollectiveDimension.DP,
                                 payload_bytes=1024,
                                 traffic_class="dp_collective"),)))
        assert derive_v3_traffic_classes(r) == (
            "dp_collective", "tp_collective")
