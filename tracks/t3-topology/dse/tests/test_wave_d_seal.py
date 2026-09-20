"""Wave D-SEAL proof tests — product integration and authenticity closure.

Every test here feeds a REAL mutated object into a REAL production
validator/loader. The suite covers:

  1  transitive immutability of every Wave-D semantic artifact
  2  same-world / different-geometry transposition refusal
  4  strict persisted-resource parsing (type, version, ID, fields)
  5  round-trip verification of the whole semantic chain
  7  verified loaders (filename == embedded == recomputed, parents)
  8  parent-transplant attacks against persisted resources
 10  real logical/physical separation (two valid bundles)
 11  real packet-format mutation (a genuinely different flit width)
 13  the Wave-C product path consuming Wave-D semantics
 14  legacy packet traces explicitly distinguished from Wave-D workloads
 16  plan identity separating Wave-D from legacy at identical bytes
 20  reuse identity separation
 23  end-to-end product certification (real qualified BookSim)
 24  product tamper: a tampered Wave-D parent invalidates the result
"""
from __future__ import annotations

import dataclasses
import json
import sys
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_fabric_artifact import build_chain  # noqa: E402
from test_backend_bundle import make_bundle  # noqa: E402

from veritx_dse.application.errors import ControlPlaneError, ErrorCode  # noqa: E402
from veritx_dse.application.service import SrotaControlPlane  # noqa: E402
from veritx_dse.application.store import ResourceStore  # noqa: E402
from veritx_dse.application.waved_resources import (  # noqa: E402
    load_verified_messages, load_verified_operation_graph,
    load_verified_parallelism, load_verified_traffic,
    load_verified_waved_semantics, load_verified_waved_workload,
    messages_record, operation_graph_record, parallelism_record,
    traffic_record, waved_chain_ids_from_traffic, waved_semantics_record,
    waved_workload_record,
)
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.waved.errors import (  # noqa: E402
    EvidenceInvalid, InvalidInput, MappingInvalid,
)
from veritx_dse.waved.immutable import FrozenMap  # noqa: E402
from veritx_dse.waved.messages import LogicalMessageArtifact  # noqa: E402
from veritx_dse.waved.operations import (  # noqa: E402
    KIND_COLLECTIVE, KIND_P2P, CollectiveIntent, OperationGraph,
    OperationNode, P2PTransfer,
)
from veritx_dse.waved.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.waved.semantics import WaveDWorkloadSemantics  # noqa: E402
from veritx_dse.waved.traffic import PhysicalTrafficArtifact  # noqa: E402
from veritx_dse.waved.workload import WaveDOperation, WaveDWorkload  # noqa: E402

REPO = DSE.parents[2]
METRICS = ["sim.latency.avg_cycles", "sim.delivered.packets",
           "sim.flits.injected"]


# ── fixtures and builders ────────────────────────────────────────────────

@pytest.fixture()
def cp(tmp_path):
    return SrotaControlPlane(store_root=tmp_path / "store",
                             repo_root=REPO)


def _collective(cid="c0", kind="ALLREDUCE", participants=(0, 1, 2, 3),
                payload=1024, owner=0, step=0, deps=()):
    return {"operation_id": cid, "kind": KIND_COLLECTIVE, "owner": owner,
            "phase": "DECODE", "step": step, "deps": list(deps),
            "detail": {"collective_id": cid, "collective_kind": kind,
                       "participants": list(participants),
                       "payload_bytes": payload}}


def _p2p(tid="t0", src=0, dst=2, payload=300, owner=0, step=1, deps=()):
    return {"operation_id": tid, "kind": KIND_P2P, "owner": owner,
            "phase": "DECODE", "step": step, "deps": list(deps),
            "detail": {"transfer_id": tid, "src_rank": src,
                       "dst_rank": dst, "payload_bytes": payload}}


def _intent(*, preset="mesh4", tp=1, pp=1, ep=1, dp=4, operations=None,
            name="waved-e2e", seed=7, metrics=METRICS, timeout_s=120):
    return {
        "schema_version": 1, "name": name, "fabric_preset": preset,
        "fabric_overrides": {"workload.tp": tp, "workload.pp": pp,
                             "workload.ep": ep, "workload.dp": dp},
        "workload": {"wave_d": {
            "parallelism": {"tp": tp, "pp": pp, "ep": ep, "dp": dp},
            "semantics": {"phase": "DECODE"},
            "operations": operations or [
                _collective(participants=tuple(range(dp))),
                _p2p(dst=min(2, dp - 1), deps=("c0",)),
            ],
        }},
        "backend_target": "BOOKSIM_STANDALONE", "seed": seed,
        "metrics": list(metrics), "timeout_s": timeout_s,
    }


def _legacy_intent(*, trace=None, trace_file=None, preset="mesh4",
                   name="legacy", seed=7, metrics=METRICS):
    workload = {"trace": trace} if trace else {"trace_file": trace_file}
    return {
        "schema_version": 1, "name": name, "fabric_preset": preset,
        "workload": workload, "backend_target": BOOKSIM_STANDALONE(),
        "seed": seed, "metrics": list(metrics), "timeout_s": 120,
    }


def BOOKSIM_STANDALONE():
    return "BOOKSIM_STANDALONE"


def _bundle(tp=2, pp=1, ep=1, dp=2, n_agents=4, link_width=None):
    return make_bundle(build_chain(tp=tp, pp=pp, ep=ep, dp=dp,
                                   n_agents=n_agents,
                                   family=TopologyFamily.MESH,
                                   link_width=link_width))


def _artifact_graph(pa, *, workload_id="w", collectives=(), p2p=()):
    nodes = [OperationNode(f"coll{i}", KIND_COLLECTIVE, "DECODE",
                           c.participants[0], 0, (),
                           {"collective_id": c.collective_id})
             for i, c in enumerate(collectives)]
    nodes += [OperationNode(f"p2p{i}", KIND_P2P, "DECODE", t.src_rank, 0,
                            (), {"transfer_id": t.transfer_id})
              for i, t in enumerate(p2p)]
    return OperationGraph(
        parallelism=pa, semantics=WaveDWorkloadSemantics(phase="DECODE"),
        workload_id=workload_id, nodes=tuple(nodes),
        collectives=tuple(collectives), p2p_transfers=tuple(p2p))


# ══ 1. transitive immutability ═══════════════════════════════════════════

def _assert_no_mutable_containers(obj, path="artifact"):
    """Every WAVE-D field must be immutable (no dict/list/set).

    ``PhysicalTrafficArtifact.bundle`` is a sealed Wave-B proof carrier:
    its own immutability contract belongs to Wave B, so the sweep does
    not re-litigate it here.
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        for f in fields(obj):
            if f.name == "bundle":
                continue
            value = getattr(obj, f.name)
            _assert_no_mutable_containers(value, f"{path}.{f.name}")
        return
    if isinstance(obj, (dict, list, set, bytearray)):
        raise AssertionError(
            f"{path} is a mutable {type(obj).__name__} inside a frozen "
            f"Wave-D artifact")
    if isinstance(obj, (FrozenMap, tuple)):
        for i, item in enumerate(obj.values() if isinstance(obj, FrozenMap)
                                 else obj):
            _assert_no_mutable_containers(item, f"{path}[{i}]")


class TestDeepImmutability:
    def test_shape_metadata_caller_dict_is_copied(self):
        shape = {"num_layers": 32}
        art = WaveDWorkloadSemantics(phase="DECODE",
                                     shape_metadata=shape)
        before = art.semantics_id()
        shape["num_layers"] = 64
        shape["hidden_size"] = 4096
        assert art.semantics_id() == before
        assert art.shape_metadata["num_layers"] == 32
        assert "hidden_size" not in art.shape_metadata
        assert art.to_dict()["shape_metadata"] == {"num_layers": 32}

    def test_nested_detail_caller_dict_is_copied_deeply(self):
        inner = {"peer": "c0"}
        detail = {"collective_id": "c0", "nested": inner}
        node = OperationNode("c0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                             detail)
        inner["peer"] = "forged"
        detail["collective_id"] = "forged"
        assert node.detail["collective_id"] == "c0"
        assert node.detail["nested"]["peer"] == "c0"
        assert node.canonical()["detail"]["nested"]["peer"] == "c0"

    def test_mutating_a_parent_cannot_change_a_lowered_child(self):
        """The nightmare state: new parent identity + old child semantics."""
        detail = {"collective_id": "c0"}
        pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
        graph = OperationGraph(
            parallelism=pa, semantics=WaveDWorkloadSemantics(phase="DECODE"),
            workload_id="w",
            nodes=(OperationNode("c0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                                 detail),),
            collectives=(CollectiveIntent("ALLREDUCE", (0, 1, 2, 3), 1024,
                                          "c0"),))
        logical = LogicalMessageArtifact(graph=graph)
        graph_id = graph.operation_graph_id()
        message_id = logical.message_artifact_id()
        messages = logical.messages
        detail["collective_id"] = "forged"
        assert graph.operation_graph_id() == graph_id
        assert logical.message_artifact_id() == message_id
        assert logical.messages == messages
        assert graph.node("c0").detail["collective_id"] == "c0"

    def test_frozen_map_refuses_assignment(self):
        art = WaveDWorkloadSemantics(phase="DECODE",
                                     shape_metadata={"num_layers": 1})
        with pytest.raises(TypeError):
            art.shape_metadata["num_layers"] = 2  # type: ignore[index]
        node = OperationNode("c0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                             {"collective_id": "c0"})
        with pytest.raises(TypeError):
            node.detail["collective_id"] = "x"  # type: ignore[index]

    def test_workload_operation_detail_is_frozen(self):
        detail = {"collective_id": "c0", "collective_kind": "ALLREDUCE",
                  "participants": [0, 1], "payload_bytes": 512}
        op = WaveDOperation("c0", KIND_COLLECTIVE, 0, "DECODE", 0, (),
                            detail)
        before = op.to_dict()
        detail["payload_bytes"] = 999999
        detail["participants"].append(2)
        assert op.to_dict() == before
        assert op.detail["payload_bytes"] == 512

    def test_every_semantic_artifact_field_is_immutable(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        semantics = WaveDWorkloadSemantics(
            phase="DECODE", shape_metadata={"num_layers": 4})
        bundle = _bundle()
        graph = _artifact_graph(
            pa, collectives=(CollectiveIntent("ALLREDUCE", (0, 1), 512,
                                              "c0"),),
            p2p=(P2PTransfer(0, 2, 300, "t0"),))
        logical = LogicalMessageArtifact(graph=graph)
        traffic = PhysicalTrafficArtifact(logical=logical, bundle=bundle)
        workload = WaveDWorkload(
            parallelism=pa, semantics=semantics,
            operations=(WaveDOperation(
                "c0", KIND_COLLECTIVE, 0, "DECODE", 0, (),
                {"collective_id": "c0", "collective_kind": "ALLREDUCE",
                 "participants": [0, 1], "payload_bytes": 512}),))
        for artifact in (pa, semantics, workload, graph, logical, traffic):
            _assert_no_mutable_containers(artifact, type(artifact).__name__)
        for node in graph.nodes:
            _assert_no_mutable_containers(node, "OperationNode")
        for record in graph.collectives:
            _assert_no_mutable_containers(record, "CollectiveIntent")
        for msg in logical.messages:
            _assert_no_mutable_containers(msg, "LogicalMessage")
        for row in traffic.conservation_ledger():
            _assert_no_mutable_containers(row, "OperationLedgerEntry")

    def test_identity_is_stable_across_repeated_reads(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        graph = _artifact_graph(
            pa, collectives=(CollectiveIntent("ALLREDUCE", (0, 1), 512,
                                              "c0"),))
        logical = LogicalMessageArtifact(graph=graph)
        traffic = PhysicalTrafficArtifact(logical=logical, bundle=_bundle())
        assert len({graph.operation_graph_id() for _ in range(5)}) == 1
        assert len({logical.message_artifact_id() for _ in range(5)}) == 1
        assert len({traffic.physical_traffic_id() for _ in range(5)}) == 1


# ══ 2. same-world / different-geometry transposition ════════════════════

class TestGeometrySeam:
    def test_same_world_size_different_geometry_refused(self):
        bundle = _bundle(tp=2, pp=2, ep=1, dp=1)
        assert bundle.inventory.parallelism.world_size == 4
        pa = ParallelismArtifact(tp=4, pp=1, ep=1, dp=1)
        assert pa.world_size == 4
        graph = _artifact_graph(
            pa, p2p=(P2PTransfer(0, 2, 300, "t0"),))
        logical = LogicalMessageArtifact(graph=graph)
        with pytest.raises(MappingInvalid) as exc:
            PhysicalTrafficArtifact(logical=logical, bundle=bundle)
        assert "geometry" in str(exc.value)

    def test_matching_geometry_accepted(self):
        bundle = _bundle(tp=2, pp=2, ep=1, dp=1)
        pa = ParallelismArtifact(tp=2, pp=2, ep=1, dp=1)
        logical = LogicalMessageArtifact(graph=_artifact_graph(
            pa, p2p=(P2PTransfer(0, 2, 300, "t0"),)))
        traffic = PhysicalTrafficArtifact(logical=logical, bundle=bundle)
        traffic.validate_against_bundle()
        assert traffic.physical_traffic_id().startswith("sha256:")

    def test_control_plane_refuses_geometry_mismatch(self, cp):
        # mesh4 compiles a DP=1 design; the workload declares DP=4.
        doc = _intent(dp=4)
        doc["fabric_overrides"] = {}
        with pytest.raises(ControlPlaneError) as exc:
            cp.compile(doc)
        assert exc.value.code == ErrorCode.INVALID_INTENT
        assert "semantic equivalence" in exc.value.message

    def test_bundle_revalidation_runs_before_lowering(self):
        """A bundle assembled around a stale child is refused."""
        bundle = _bundle()
        other = _bundle(link_width=128)
        stale = replace(bundle, packet_format=other.packet_format)
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        logical = LogicalMessageArtifact(graph=_artifact_graph(
            pa, p2p=(P2PTransfer(0, 2, 300, "t0"),)))
        with pytest.raises(MappingInvalid):
            PhysicalTrafficArtifact(logical=logical, bundle=stale)


# ══ 4/5/7. strict parsing and verified loaders ═══════════════════════════

@pytest.fixture()
def persisted(cp):
    """Compile one Wave-D intent; return the store and every chain ID."""
    compiled = cp.compile(_intent())
    return cp, compiled["wave_d"], compiled


class TestStrictParsing:
    def test_parallelism_requires_type_version_and_id(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        good = pa.to_dict()
        assert ParallelismArtifact.from_dict(good, strict=True) == pa
        for drop in ("type", "schema_version", "parallelism_id"):
            doc = {k: v for k, v in good.items() if k != drop}
            with pytest.raises(InvalidInput):
                ParallelismArtifact.from_dict(doc, strict=True)
        bad_type = {**good, "type": "srota/Other"}
        with pytest.raises(InvalidInput):
            ParallelismArtifact.from_dict(bad_type, strict=True)
        bad_version = {**good, "schema_version": 99}
        with pytest.raises(InvalidInput):
            ParallelismArtifact.from_dict(bad_version, strict=True)
        unknown = {**good, "extra": 1}
        with pytest.raises(InvalidInput):
            ParallelismArtifact.from_dict(unknown, strict=True)

    def test_parallelism_forged_id_refused(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        doc = {**pa.to_dict(), "parallelism_id": "sha256:" + "0" * 64}
        with pytest.raises(EvidenceInvalid):
            ParallelismArtifact.from_dict(doc, strict=True)

    def test_semantics_requires_type_version_and_id(self):
        art = WaveDWorkloadSemantics(phase="DECODE",
                                     shape_metadata={"num_layers": 4})
        good = art.to_dict()
        assert WaveDWorkloadSemantics.from_dict(good, strict=True) == art
        for drop in ("type", "schema_version", "wave_d_semantics_id"):
            doc = {k: v for k, v in good.items() if k != drop}
            with pytest.raises(InvalidInput):
                WaveDWorkloadSemantics.from_dict(doc, strict=True)
        with pytest.raises(InvalidInput):
            WaveDWorkloadSemantics.from_dict({**good, "phase": "SERVING"},
                                             strict=True)

    def test_operation_graph_requires_verified_parents(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        semantics = WaveDWorkloadSemantics(phase="DECODE")
        graph = _artifact_graph(
            pa, collectives=(CollectiveIntent("ALLREDUCE", (0, 1), 512,
                                              "c0"),))
        doc = graph.to_dict()
        assert OperationGraph.from_dict(
            doc, parallelism=pa, semantics=semantics, strict=True) \
            .operation_graph_id() == graph.operation_graph_id()
        other_pa = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)
        with pytest.raises(InvalidInput):
            OperationGraph.from_dict(doc, parallelism=other_pa,
                                     semantics=semantics, strict=True)
        other_sem = WaveDWorkloadSemantics(phase="PREFILL")
        with pytest.raises(InvalidInput):
            OperationGraph.from_dict(doc, parallelism=pa,
                                     semantics=other_sem, strict=True)

    def test_operation_graph_rejects_tampered_node(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        semantics = WaveDWorkloadSemantics(phase="DECODE")
        graph = _artifact_graph(
            pa, collectives=(CollectiveIntent("ALLREDUCE", (0, 1), 512,
                                              "c0"),))
        doc = graph.to_dict()
        doc["nodes"][0]["owner"] = 1
        with pytest.raises(EvidenceInvalid):
            OperationGraph.from_dict(doc, parallelism=pa,
                                     semantics=semantics, strict=True)

    def test_messages_require_verified_graph_parent(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        graph = _artifact_graph(
            pa, collectives=(CollectiveIntent("ALLREDUCE", (0, 1), 512,
                                              "c0"),))
        logical = LogicalMessageArtifact(graph=graph)
        doc = logical.to_dict()
        assert LogicalMessageArtifact.from_dict(
            doc, graph=graph, strict=True).message_artifact_id() \
            == logical.message_artifact_id()
        other = _artifact_graph(
            pa, collectives=(CollectiveIntent("ALLREDUCE", (0, 1), 1024,
                                              "c0"),))
        with pytest.raises(InvalidInput):
            LogicalMessageArtifact.from_dict(doc, graph=other, strict=True)

    def test_messages_reject_a_forged_schedule_row(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        graph = _artifact_graph(
            pa, collectives=(CollectiveIntent("ALLREDUCE", (0, 1), 512,
                                              "c0"),))
        logical = LogicalMessageArtifact(graph=graph)
        doc = logical.to_dict()
        doc["schedules"][0]["payload_bytes"] = 4096
        with pytest.raises(EvidenceInvalid):
            LogicalMessageArtifact.from_dict(doc, graph=graph, strict=True)


class TestVerifiedLoaders:
    def test_every_resource_round_trips_through_its_loader(self, persisted):
        cp, chain, _ = persisted
        store = cp.store
        assert load_verified_parallelism(
            store, chain["parallelism_id"]).parallelism_id() \
            == chain["parallelism_id"]
        assert load_verified_waved_semantics(
            store, chain["wave_d_semantics_id"]).semantics_id() \
            == chain["wave_d_semantics_id"]
        workload = load_verified_waved_workload(
            store, chain["waved_workload_id"])
        assert workload.workload_id() == chain["waved_workload_id"]
        graph = load_verified_operation_graph(
            store, chain["operation_graph_id"])
        assert graph.operation_graph_id() == chain["operation_graph_id"]
        logical = load_verified_messages(
            store, chain["message_artifact_id"])
        assert logical.message_artifact_id() == chain["message_artifact_id"]
        traffic, record = load_verified_traffic(
            store, chain["physical_traffic_id"])
        assert traffic.physical_traffic_id() == \
            chain["physical_traffic_id"]
        assert record["artifact"]["design_id"]
        assert waved_chain_ids_from_traffic(traffic) == chain

    def test_loader_refuses_a_forged_filename_id(self, persisted):
        cp, chain, _ = persisted
        store = cp.store
        record = store.get("opgraph", chain["operation_graph_id"])
        forged = {**record, "resource_id": "not-the-filename"}
        store.put("opgraph", "forged-name", forged)
        with pytest.raises(ControlPlaneError) as exc:
            load_verified_operation_graph(store, "forged-name")
        assert exc.value.code == ErrorCode.EVIDENCE_INVALID

    def test_loader_refuses_unknown_fields(self, persisted):
        cp, chain, _ = persisted
        store = cp.store
        record = store.get("parallelism", chain["parallelism_id"])
        store.put("parallelism", "extra-field",
                  {**record, "resource_id": "extra-field",
                   "artifact": {**record["artifact"], "surprise": 1}})
        with pytest.raises(ControlPlaneError):
            load_verified_parallelism(store, "extra-field")

    def test_missing_parent_refused(self, persisted):
        cp, chain, _ = persisted
        store = cp.store
        record = store.get("messages", chain["message_artifact_id"])
        store.put("messages", "orphan",
                  {**record, "resource_id": "orphan",
                   "artifact": {**record["artifact"],
                                "operation_graph_id": "sha256:" + "1" * 64}})
        with pytest.raises(ControlPlaneError) as exc:
            load_verified_messages(store, "orphan")
        assert exc.value.code == ErrorCode.EVIDENCE_INVALID


# ══ 8. parent-transplant attacks on persisted resources ═════════════════

@pytest.fixture()
def two_chains(cp):
    """Two valid Wave-D chains with disjoint semantic identities."""
    a = cp.compile(_intent(name="chain-a"))
    b = cp.compile(_intent(
        name="chain-b",
        operations=[_collective(cid="c0", participants=(0, 1, 2, 3),
                                payload=2048)]))
    return cp, a["wave_d"], b["wave_d"]


def _transplant(store, kind, source_id, *, field, value, new_id):
    record = store.get(kind, source_id)
    artifact = dict(record["artifact"])
    artifact[field] = value
    store.put(kind, new_id, {**record, "resource_id": new_id,
                             "artifact": artifact})


class TestParentTransplants:
    def test_operation_graph_parent_transplants_refused(self, two_chains):
        cp, a, b = two_chains
        store = cp.store
        for i, (field, value) in enumerate((
                ("workload_id", b["waved_workload_id"]),
                ("parallelism_id", b["parallelism_id"]),
                ("wave_d_semantics_id", b["wave_d_semantics_id"]))):
            new_id = f"transplant-{i}"
            _transplant(store, "opgraph", a["operation_graph_id"],
                        field=field, value=value, new_id=new_id)
            with pytest.raises(ControlPlaneError):
                load_verified_operation_graph(store, new_id)

    def test_messages_graph_transplant_refused(self, two_chains):
        cp, a, b = two_chains
        store = cp.store
        _transplant(store, "messages", a["message_artifact_id"],
                    field="operation_graph_id",
                    value=b["operation_graph_id"], new_id="msg-transplant")
        with pytest.raises(ControlPlaneError):
            load_verified_messages(store, "msg-transplant")

    def test_traffic_parent_transplants_refused(self, two_chains):
        cp, a, b = two_chains
        store = cp.store
        for i, (field, value) in enumerate((
                ("message_artifact_id", b["message_artifact_id"]),
                ("resolved_fabric_hash", "f" * 64),
                ("packet_format_hash", "e" * 64))):
            new_id = f"traffic-transplant-{i}"
            _transplant(store, "traffic", a["physical_traffic_id"],
                        field=field, value=value, new_id=new_id)
            with pytest.raises(ControlPlaneError):
                load_verified_traffic(store, new_id)

    def test_traffic_content_tamper_refused(self, two_chains):
        cp, a, b = two_chains
        store = cp.store
        record = store.get("traffic", a["physical_traffic_id"])
        artifact = json.loads(json.dumps(record["artifact"]))
        artifact["traffic"][0][0]["flit_count"] += 1
        store.put("traffic", "traffic-tamper",
                  {**record, "resource_id": "traffic-tamper",
                   "artifact": artifact})
        with pytest.raises(ControlPlaneError):
            load_verified_traffic(store, "traffic-tamper")

    def test_workload_parent_transplant_refused(self, two_chains):
        cp, a, b = two_chains
        store = cp.store
        _transplant(store, "wavedworkload", a["waved_workload_id"],
                    field="parallelism_id", value=b["parallelism_id"],
                    new_id="workload-transplant")
        with pytest.raises(ControlPlaneError):
            load_verified_waved_workload(store, "workload-transplant")

    def test_semantics_swap_between_chains_refused(self, two_chains):
        cp, a, b = two_chains
        store = cp.store
        # Same operation content, different semantics envelope: the
        # graph must not accept the other chain's semantics resource.
        _transplant(store, "opgraph", a["operation_graph_id"],
                    field="wave_d_semantics_id",
                    value=b["wave_d_semantics_id"], new_id="sem-swap")
        with pytest.raises(ControlPlaneError):
            load_verified_operation_graph(store, "sem-swap")


# ══ 10/11. real separation and real packet-format mutation ══════════════

class TestLogicalPhysicalBinding:
    def test_two_valid_presets_move_only_the_physical_chain(self, cp):
        narrow = cp.compile(_intent(preset="mesh4", name="narrow"))
        wide = cp.compile(_intent(preset="mesh4_wide128", name="wide"))
        # Same declared workload and geometry ...
        assert narrow["wave_d"]["waved_workload_id"] == \
            wide["wave_d"]["waved_workload_id"]
        assert narrow["wave_d"]["parallelism_id"] == \
            wide["wave_d"]["parallelism_id"]
        assert narrow["wave_d"]["wave_d_semantics_id"] == \
            wide["wave_d"]["wave_d_semantics_id"]
        assert narrow["wave_d"]["operation_graph_id"] == \
            wide["wave_d"]["operation_graph_id"]
        assert narrow["wave_d"]["message_artifact_id"] == \
            wide["wave_d"]["message_artifact_id"]
        # ... different wire layout, therefore different physical traffic.
        assert narrow["wave_d"]["packet_format_hash"] != \
            wide["wave_d"]["packet_format_hash"]
        assert narrow["wave_d"]["resolved_fabric_hash"] != \
            wide["wave_d"]["resolved_fabric_hash"]
        assert narrow["wave_d"]["physical_traffic_id"] != \
            wide["wave_d"]["physical_traffic_id"]

    def test_packet_format_identity_is_really_different(self, cp):
        narrow = cp.compile(_intent(preset="mesh4", name="n1"))
        wide = cp.compile(_intent(preset="mesh4_wide128", name="n2"))
        pt_narrow, _ = load_verified_traffic(
            cp.store, narrow["wave_d"]["physical_traffic_id"])
        pt_wide, _ = load_verified_traffic(
            cp.store, wide["wave_d"]["physical_traffic_id"])
        assert pt_narrow.bundle.packet_format.flit_width_bits == 64
        assert pt_wide.bundle.packet_format.flit_width_bits == 128
        assert pt_narrow.totals()["flit_count"] \
            > pt_wide.totals()["flit_count"]
        assert pt_narrow.totals()["transmitted_bits"] \
            != pt_wide.totals()["transmitted_bits"]

    def test_plan_identity_separates_the_two_presets(self, cp):
        narrow = cp.plan(_intent(preset="mesh4", name="p1"))
        wide = cp.plan(_intent(preset="mesh4_wide128", name="p2"))
        assert narrow["plan"]["resource_id"] != wide["plan"]["resource_id"]
        # The DECLARED semantic workload is design-independent; the
        # derived workload resource is not (it binds the wire layout).
        assert narrow["wave_d"]["waved_workload_id"] == \
            wide["wave_d"]["waved_workload_id"]
        assert narrow["workload"]["resource_id"] != \
            wide["workload"]["resource_id"]


# ══ 14/16/21. legacy classification and identity separation ═════════════

class TestLegacyBoundary:
    def test_legacy_workload_is_classified_and_has_no_wave_d(self, cp):
        compiled = cp.compile(_legacy_intent(trace="tiny2"))
        assert compiled["workload"]["workload_kind"] == "LEGACY_TRACE"
        assert "wave_d" not in compiled["workload"]
        assert "wave_d" not in compiled
        plan = cp.plan(_legacy_intent(trace="tiny2"))["plan"]
        assert "wave_d" not in plan

    def test_validate_reports_the_provenance_kind(self, cp):
        legacy = cp.validate(_legacy_intent(trace="tiny2"))
        assert legacy["workload_kind"] == "LEGACY_TRACE"
        assert legacy["trace_sha256"]
        waved = cp.validate(_intent())
        assert waved["workload_kind"] == "WAVE_D_SEMANTIC"
        assert waved["trace_sha256"] is None
        assert waved["waved_workload_id"].startswith("sha256:")

    def test_identical_rendered_bytes_never_share_identity(self, cp,
                                                           tmp_path):
        """The anti-collision rule, proven with real identical bytes."""
        waved = cp.compile(_intent())
        traffic, _ = load_verified_traffic(
            cp.store, waved["wave_d"]["physical_traffic_id"])
        from veritx_dse.waved.backend import render_waved_trace
        derived = render_waved_trace(traffic)
        path = tmp_path / "derived.trace"
        path.write_bytes(derived)

        legacy = cp.compile(_legacy_intent(trace_file=str(path),
                                           name="same-bytes"))
        # Precondition: the bytes really are identical.
        assert legacy["workload"]["trace_sha256"] == \
            waved["workload"]["trace_sha256"]
        assert legacy["workload"]["trace_bytes"] == \
            waved["workload"]["trace_bytes"]
        # ... and the identities are not.
        assert legacy["workload"]["resource_id"] != \
            waved["workload"]["resource_id"]
        assert legacy["workload"]["workload_kind"] == "LEGACY_TRACE"
        assert waved["workload"]["workload_kind"] == "WAVE_D_SEMANTIC"
        legacy_plan = cp.plan(_legacy_intent(trace_file=str(path),
                                             name="same-bytes"))["plan"]
        waved_plan = cp.plan(_intent())["plan"]
        assert legacy_plan["resource_id"] != waved_plan["resource_id"]

    def test_wave_d_plan_binds_the_whole_chain(self, cp):
        plan = cp.plan(_intent())["plan"]
        assert set(plan["wave_d"]) >= {
            "waved_workload_id", "parallelism_id", "wave_d_semantics_id",
            "operation_graph_id", "message_artifact_id",
            "physical_traffic_id", "resolved_fabric_hash",
            "packet_format_hash"}


# ══ 20. reuse identity separation ═══════════════════════════════════════

class TestReuseIdentity:
    def test_same_chain_reproduces_the_same_identities(self, cp):
        first = cp.plan(_intent())
        second = cp.plan(_intent())
        assert first["plan"]["resource_id"] == \
            second["plan"]["resource_id"]
        assert first["workload"]["resource_id"] == \
            second["workload"]["resource_id"]

    def test_changed_operation_semantics_changes_plan_identity(self, cp):
        base = cp.plan(_intent())
        changed = cp.plan(_intent(operations=[
            _collective(participants=(0, 1, 2, 3), payload=4096)]))
        assert changed["wave_d"]["operation_graph_id"] != \
            base["wave_d"]["operation_graph_id"]
        assert changed["plan"]["resource_id"] != \
            base["plan"]["resource_id"]

    def test_changed_packet_format_changes_plan_identity(self, cp):
        base = cp.plan(_intent(preset="mesh4"))
        wide = cp.plan(_intent(preset="mesh4_wide128"))
        assert wide["wave_d"]["message_artifact_id"] == \
            base["wave_d"]["message_artifact_id"]
        assert wide["wave_d"]["physical_traffic_id"] != \
            base["wave_d"]["physical_traffic_id"]
        assert wide["plan"]["resource_id"] != base["plan"]["resource_id"]

    def test_transplanted_result_link_never_reuses(self, cp, tmp_path):
        """A link pointing at another experiment's result is not reuse."""
        from veritx_dse.application.requests import resolve_intent
        from veritx_dse.application.resources import ExperimentRecord
        from veritx_dse.application.results import load_verified_result
        from veritx_dse.core.spec import canonical_json
        first = cp.evaluate(_intent(name="reuse-a"))
        second = cp.evaluate(_intent(
            name="reuse-b",
            operations=[_collective(participants=(0, 1, 2, 3),
                                    payload=4096)]))
        assert first["resource_id"] != second["resource_id"]
        # Point A's link at B's result (direct file tamper: the store
        # itself refuses to overwrite, which is why the attack needs
        # filesystem access).
        link_id = f"experiment-result-{first['experiment_id']}"
        link_path = cp.store.root / "links" / f"{link_id}.json"
        link_path.write_text(canonical_json(
            {"result_id": second["resource_id"],
             "experiment_id": first["experiment_id"]}))
        with pytest.raises(ControlPlaneError):
            load_verified_result(cp.store, second["resource_id"],
                                 expected_experiment_id=first["experiment_id"])
        # The reuse gate must therefore decline (never adopt B's
        # science under A's identity).
        record = cp.store.get("experiment", first["experiment_id"])
        intent, _, _ = resolve_intent(_intent(name="reuse-a"))
        plan = cp.store.get("plan", record["plan_id"])
        assert cp._try_reuse(ExperimentRecord(
            experiment_id=record["resource_id"],
            plan_id=record["plan_id"],
            backend_config_hash=record["backend_config_hash"],
            backend_input_hash=record["backend_input_hash"],
            execution_mode=record["execution_mode"]), plan, intent) is None

    def test_result_provenance_block_matches_the_chain(self, cp):
        result = cp.evaluate(_intent())
        traffic, _ = load_verified_traffic(
            cp.store, result["wave_d"]["physical_traffic_id"])
        chain = waved_chain_ids_from_traffic(traffic)
        for key, value in chain.items():
            assert result["wave_d"][key] == value
        assert result["wave_d"]["expected_packets"] > 0
        assert result["wave_d"]["expected_flits"] > 0


# ══ 13/23. end-to-end product certification (real qualified BookSim) ════

def _binary_available():
    from veritx_dse.simulation.booksim import find_booksim_bin
    try:
        find_booksim_bin(REPO)
        return True
    except FileNotFoundError:
        return False


requires_binary = pytest.mark.skipif(
    not _binary_available(), reason="no runnable BookSim binary")


@requires_binary
class TestProductCertification:
    def test_wave_d_end_to_end_through_the_control_plane(self, cp):
        doc = _intent()
        compiled = cp.compile(doc)
        planned = cp.plan(doc)
        result = cp.evaluate(doc)
        assert result["status"] == "SUCCEEDED"
        assert result["qualification"]
        chain = planned["wave_d"]
        assert compiled["wave_d"] == chain
        assert result["wave_d"]["physical_traffic_id"] == \
            chain["physical_traffic_id"]

        from veritx_dse.application.results import load_verified_result
        verified = load_verified_result(cp.store, result["resource_id"])
        assert verified["resource_id"] == result["resource_id"]

        # Walk backward through every persisted verified parent.
        workload = load_verified_waved_workload(
            cp.store, chain["waved_workload_id"])
        graph = load_verified_operation_graph(
            cp.store, chain["operation_graph_id"])
        logical = load_verified_messages(
            cp.store, chain["message_artifact_id"])
        traffic, _ = load_verified_traffic(
            cp.store, chain["physical_traffic_id"])
        assert graph.workload_id == workload.workload_id()
        assert logical.graph.operation_graph_id() == graph.operation_graph_id()
        assert traffic.logical.message_artifact_id() == \
            logical.message_artifact_id()
        assert waved_chain_ids_from_traffic(traffic) == chain
        # The executed trace is DERIVED from that verified traffic.
        from veritx_dse.backend.contracts import sha256_bytes
        from veritx_dse.waved.backend import render_waved_trace
        assert sha256_bytes(render_waved_trace(traffic)) == \
            result["workload_hash"]

    def test_evidence_binds_the_derived_backend_input(self, cp):
        result = cp.evaluate(_intent(name="evidence-bind"))
        experiment = cp.store.get("experiment", result["experiment_id"])
        assert experiment["backend_input_hash"] == \
            result["backend_input_hash"]
        assert result["workload_hash"] == \
            cp.store.get("workload", result["workload_id"])["trace_sha256"]
        assert result["wave_d"]["delivered_packets"] == \
            result["wave_d"]["expected_packets"]
        assert result["wave_d"]["flits_injected"] == \
            result["wave_d"]["expected_flits"]
        assert result["wave_d"]["flits_accepted"] == \
            result["wave_d"]["expected_flits"]

    def test_inspect_navigates_the_wave_d_chain(self, cp):
        result = cp.evaluate(_intent(name="inspect-chain"))
        for kind, key in (("wavedworkload", "waved_workload_id"),
                          ("parallelism", "parallelism_id"),
                          ("wavedsemantics", "wave_d_semantics_id"),
                          ("opgraph", "operation_graph_id"),
                          ("messages", "message_artifact_id"),
                          ("traffic", "physical_traffic_id")):
            resource_id = result["wave_d"][key]
            described = cp.inspect(resource_id)
            assert described["kind"] == kind
            assert described["integrity"]["state"] == "VERIFIED"
        plan_view = cp.inspect(result["plan_id"])
        assert any(k.startswith("wave_d.") for k in plan_view["related"])


# ══ 24. product tamper invalidates the result ═══════════════════════════

def _tamper_graph(doc):
    doc["artifact"]["nodes"][0]["owner"] = 3


def _tamper_messages(doc):
    doc["artifact"]["messages"][0]["payload_bytes"] += 8


def _tamper_traffic(doc):
    doc["artifact"]["traffic"][0][0]["payload_bits"] += 8


_TAMPERERS = {
    ("opgraph", "operation_graph_id"): _tamper_graph,
    ("messages", "message_artifact_id"): _tamper_messages,
    ("traffic", "physical_traffic_id"): _tamper_traffic,
}


@requires_binary
class TestProductTamper:
    def _tamper_file(self, cp, kind, resource_id, mutate):
        """Tamper the persisted bytes directly (as an attacker would)."""
        from veritx_dse.core.spec import canonical_json
        path = cp.store.root / kind / f"{resource_id}.json"
        doc = json.loads(path.read_text())
        mutate(doc)
        path.write_text(canonical_json(doc))

    @pytest.mark.parametrize("kind,field", [
        ("opgraph", "operation_graph_id"),
        ("messages", "message_artifact_id"),
        ("traffic", "physical_traffic_id"),
    ])
    def test_tampered_parent_invalidates_the_result(self, cp, kind, field):
        from veritx_dse.application.results import load_verified_result
        result = cp.evaluate(_intent(name=f"tamper-{kind}"))
        assert load_verified_result(cp.store, result["resource_id"])
        key = {"opgraph": "operation_graph_id",
               "messages": "message_artifact_id",
               "traffic": "physical_traffic_id"}[kind]
        target = result["wave_d"][key]
        self._tamper_file(cp, kind, target,
                          _TAMPERERS[(kind, field)])
        with pytest.raises(ControlPlaneError) as exc:
            load_verified_result(cp.store, result["resource_id"])
        assert exc.value.code == ErrorCode.EVIDENCE_INVALID

    def test_tampered_operation_row_invalidates_the_result(self, cp):
        from veritx_dse.application.results import load_verified_result
        result = cp.evaluate(_intent(name="tamper-row"))
        target = result["wave_d"]["operation_graph_id"]

        def mutate(doc):
            doc["artifact"]["nodes"][0]["owner"] = 3

        self._tamper_file(cp, "opgraph", target, mutate)
        with pytest.raises(ControlPlaneError):
            load_verified_result(cp.store, result["resource_id"])

    def test_tampered_message_row_invalidates_the_result(self, cp):
        from veritx_dse.application.results import load_verified_result
        result = cp.evaluate(_intent(name="tamper-msg"))
        target = result["wave_d"]["message_artifact_id"]

        def mutate(doc):
            doc["artifact"]["messages"][0]["payload_bytes"] += 8

        self._tamper_file(cp, "messages", target, mutate)
        with pytest.raises(ControlPlaneError):
            load_verified_result(cp.store, result["resource_id"])

    def test_tampered_traffic_row_invalidates_the_result(self, cp):
        from veritx_dse.application.results import load_verified_result
        result = cp.evaluate(_intent(name="tamper-traffic"))
        target = result["wave_d"]["physical_traffic_id"]

        def mutate(doc):
            doc["artifact"]["traffic"][0][0]["payload_bits"] += 8

        self._tamper_file(cp, "traffic", target, mutate)
        with pytest.raises(ControlPlaneError):
            load_verified_result(cp.store, result["resource_id"])

    def test_tampered_result_wave_d_block_invalidates_the_result(self, cp):
        from veritx_dse.application.results import load_verified_result
        result = cp.evaluate(_intent(name="tamper-block"))

        def mutate(doc):
            doc["wave_d"]["resolved_fabric_hash"] = "0" * 64

        self._tamper_file(cp, "result", result["resource_id"], mutate)
        with pytest.raises(ControlPlaneError):
            load_verified_result(cp.store, result["resource_id"])
