"""tests/test_v1_v2_differential.py — M2: prove M1 scientifically.

M2 adds almost no production code. It takes representative v1 workloads
and their canonical v2 equivalents (via the migration boundary) and
requires the SAME science:

    operation IDs, logical endpoints, logical bytes, packet count,
    flit count, headers, padding, BookSim input bytes + SHA,
    projection summary, performance output (totals)

Expected ancestry IDs may move (message/traffic artifact ids live in
different identity domains) — scientific behavior preserved, identity
ancestry corrected.

Then the cross-generation attack matrix: v1 artifacts inside v2
parents (and the reverse), tampered bindings/hashes with re-signed
outer ids — all refuse.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.application.errors import ControlPlaneError  # noqa: E402
from veritx_dse.backend.contracts import sha256_bytes  # noqa: E402
from veritx_dse.backend.projection import (  # noqa: E402
    render_waved_trace, verify_trace_projection,
)
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.graph import WaveDOperation, WaveDWorkload  # noqa: E402
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifact, LogicalMessageArtifactV2,
)
from veritx_dse.workload.migration import migrate_waved_workload  # noqa: E402
from veritx_dse.workload.operations import (  # noqa: E402
    KIND_COLLECTIVE, KIND_MULTICAST, KIND_P2P, REPLICATION_SOURCE,
)
from veritx_dse.workload.semantics import (  # noqa: E402
    WaveDWorkloadSemantics,
)
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifact, PhysicalTrafficArtifactV2,
)

PA = ParallelismArtifact(tp=1, pp=1, ep=1, dp=4)


def _bundle():
    return make_bundle(build_chain(tp=1, pp=1, ep=1, dp=4, n_agents=4,
                                   family=TopologyFamily.MESH))


def _decl(*ops) -> WaveDWorkload:
    return WaveDWorkload(
        parallelism=PA,
        semantics=WaveDWorkloadSemantics(phase="DECODE"),
        operations=tuple(ops))


def _collective(op_id, kind, participants, payload, deps=()):
    return WaveDOperation(
        operation_id=op_id, kind=KIND_COLLECTIVE, owner=0,
        phase="DECODE", step=0, deps=tuple(deps),
        detail={"collective_id": op_id, "collective_kind": kind,
                "participants": list(participants),
                "payload_bytes": payload})


def _p2p(op_id, src, dst, payload, deps=()):
    return WaveDOperation(
        operation_id=op_id, kind=KIND_P2P, owner=0,
        phase="DECODE", step=1, deps=tuple(deps),
        detail={"transfer_id": op_id, "src_rank": src,
                "dst_rank": dst, "payload_bytes": payload})


def _multicast(op_id, source, dests, payload, deps=()):
    return WaveDOperation(
        operation_id=op_id, kind=KIND_MULTICAST, owner=0,
        phase="DECODE", step=2, deps=tuple(deps),
        detail={"multicast_id": op_id, "source_rank": source,
                "destinations": list(dests), "payload_bytes": payload,
                "replication": REPLICATION_SOURCE})


def _workloads():
    participants = (0, 1, 2, 3)
    return {
        "allreduce_p2p": _decl(
            _collective("c0", "ALLREDUCE", participants, 1024),
            _p2p("t0", 0, 2, 300, deps=("c0",))),
        "broadcast": _decl(
            _collective("b0", "BROADCAST", participants, 512)),
        "multicast_allgather": _decl(
            _multicast("m0", 0, (1, 2, 3), 256),
            _collective("c1", "ALLGATHER", participants, 512,
                        deps=("m0",))),
    }


def _lower_v1(decl, bundle):
    graph = decl.to_graph()
    logical = LogicalMessageArtifact(graph=graph)
    logical.validate_conservation()
    traffic = PhysicalTrafficArtifact(logical=logical, bundle=bundle)
    traffic.validate_conservation()
    return graph, logical, traffic


def _lower_v2(decl, bundle):
    graph = migrate_waved_workload(decl)
    logical = LogicalMessageArtifactV2(graph=graph)
    logical.validate_conservation()
    traffic = PhysicalTrafficArtifactV2(logical=logical, bundle=bundle)
    traffic.validate_conservation()
    return graph, logical, traffic


def _science(logical, traffic):
    return {
        "operation_ids": [m.operation_id for m in logical.messages],
        "endpoints": [(m.src_rank, m.dst_rank) for m in logical.messages],
        "logical_bytes": [m.payload_bytes for m in logical.messages],
        "totals": traffic.totals(),
        "trace": render_waved_trace(traffic),
        "summary": verify_trace_projection(traffic),
    }


class TestV1V2ScientificDifferential:
    @pytest.mark.parametrize("name", ["allreduce_p2p", "broadcast"])
    def test_same_science(self, name):
        """Same messages, same packets, same BookSim bytes.

        These workloads are order-compatible: v1's kind-grouped
        emission coincides with dependency order, so byte equality
        holds all the way down to the BookSim input SHA.
        """
        decl = _workloads()[name]
        bundle = _bundle()
        _, logical_v1, traffic_v1 = _lower_v1(decl, bundle)
        _, logical_v2, traffic_v2 = _lower_v2(decl, bundle)
        s1, s2 = _science(logical_v1, traffic_v1), _science(
            logical_v2, traffic_v2)
        assert s2["operation_ids"] == s1["operation_ids"]
        assert s2["endpoints"] == s1["endpoints"]
        assert s2["logical_bytes"] == s1["logical_bytes"]
        assert s2["totals"] == s1["totals"]
        assert s2["trace"] == s1["trace"]
        assert sha256_bytes(s2["trace"]) == sha256_bytes(s1["trace"])
        assert s2["summary"] == s1["summary"]

    def test_mixed_kind_order_correction(self):
        """Multiset-equal, order-corrected.

        v1 emits kind-grouped (ALL collectives before ALL multicasts),
        ignoring declared dependencies: here it emits c1 before m0
        even though c1 DEPENDS on m0. v2 emits dependency order. The
        packet multiset, totals and projection summary are identical;
        the emission order differs, and v2's is the defensible one.
        This is a documented behavior correction, not a regression:
        timestamps are injection order, so dependency-violating order
        was never a semantic worth preserving.
        """
        decl = _workloads()["multicast_allgather"]
        bundle = _bundle()
        _, logical_v1, traffic_v1 = _lower_v1(decl, bundle)
        _, logical_v2, traffic_v2 = _lower_v2(decl, bundle)
        s1, s2 = _science(logical_v1, traffic_v1), _science(
            logical_v2, traffic_v2)
        # v1 violates the declared dependency in emission order ...
        assert s1["operation_ids"].index("c1") < \
            s1["operation_ids"].index("m0")
        # ... v2 respects it
        assert s2["operation_ids"].index("m0") < \
            s2["operation_ids"].index("c1")
        # same multiset of messages ...
        assert sorted(s2["operation_ids"]) == sorted(s1["operation_ids"])
        assert sorted(s2["endpoints"]) == sorted(s1["endpoints"])
        assert sorted(s2["logical_bytes"]) == sorted(s1["logical_bytes"])
        # ... same wire volumes ...
        assert s2["totals"] == s1["totals"]
        assert s2["summary"] == s1["summary"]
        # ... same per-packet (endpoint, flit) multiset, order aside
        def cells(trace):
            return sorted(tuple(int(x) for x in ln.split()[1:])
                          for ln in trace.decode().splitlines())
        assert cells(s2["trace"]) == cells(s1["trace"])

    @pytest.mark.parametrize("name", sorted(_workloads()))
    def test_ancestry_moves_but_products_stay_named(self, name):
        """Ancestry corrected: v1 names Wave-D runtime parents, v2 the
        canonical graph; products stay artifact-id named in both."""
        from veritx_dse.application.waved_resources import (
            chain_ids_from_traffic, chain_version, semantic_chain_ids_v2,
            waved_chain_ids,
        )
        decl = _workloads()[name]
        bundle = _bundle()
        g1, l1, t1 = _lower_v1(decl, bundle)
        g2, l2, t2 = _lower_v2(decl, bundle)
        c1 = waved_chain_ids(decl, g1, l1, t1, bundle)
        c2 = semantic_chain_ids_v2(g2, l2, t2, bundle)
        assert chain_version(c1) == 1
        assert c2["chain_schema_version"] == 2
        assert "operation_graph_id" in c1
        assert "workload_graph_id" not in c1
        assert "workload_graph_id" in c2
        assert "operation_graph_id" not in c2
        # the dispatcher agrees with the constructors
        assert chain_ids_from_traffic(t1) == c1
        assert chain_ids_from_traffic(t2) == c2


class TestCrossGenerationAttacks:
    def _pair(self, name="allreduce_p2p"):
        decl = _workloads()[name]
        bundle = _bundle()
        g1, l1, t1 = _lower_v1(decl, bundle)
        g2, l2, t2 = _lower_v2(decl, bundle)
        return bundle, (g1, l1, t1), (g2, l2, t2)

    def test_v1_messages_never_parse_as_v2(self):
        _, (g1, l1, _), (g2, _, _) = self._pair()
        with pytest.raises(Exception):
            LogicalMessageArtifactV2.from_dict(
                l1.to_dict(), graph=g2, strict=True)

    def test_v2_messages_never_parse_as_v1(self):
        _, (g1, _, _), (_, l2, _) = self._pair()
        with pytest.raises(Exception):
            LogicalMessageArtifact.from_dict(
                l2.to_dict(), graph=g1, strict=True)

    def test_v1_traffic_never_parses_as_v2(self):
        bundle, (_, _, t1), (_, l2, _) = self._pair()
        with pytest.raises(Exception):
            PhysicalTrafficArtifactV2.from_dict(
                t1.to_dict(), logical=l2, bundle=bundle, strict=True)

    def test_v2_traffic_never_parses_as_v1(self):
        bundle, (_, l1, _), (_, _, t2) = self._pair()
        doc = t2.to_dict()
        with pytest.raises(Exception):
            PhysicalTrafficArtifact.from_dict(
                doc, logical=l1, bundle=bundle, strict=True)

    def test_tampered_mapping_binding_refuses(self):
        bundle, _, (_, l2, t2) = self._pair()
        import json
        doc = json.loads(json.dumps(t2.to_dict()))
        doc["participant_endpoint_mapping_id"] = "sha256:" + "0" * 64
        with pytest.raises(Exception):
            PhysicalTrafficArtifactV2.from_dict(
                doc, logical=l2, bundle=bundle, strict=True)

    def test_tampered_v2_parent_refuses(self):
        bundle, _, (g2, _, t2) = self._pair()
        import json
        from veritx_dse.workload.canonical_graph import (
            WorkloadGraph, collective_detail,
        )
        from veritx_dse.workload.canonical_graph import (
            KIND_COLLECTIVE, OperationNode,
        )
        other = WorkloadGraph(
            parallelism=PA, participant_count=4,
            operations=(OperationNode(
                "zz", KIND_COLLECTIVE, (),
                collective_detail(
                    collective_kind="ALLREDUCE",
                    participants=(0, 1, 2, 3), payload_bytes=8,
                    participant_count=4)),))
        l_other = LogicalMessageArtifactV2(other)
        doc = json.loads(json.dumps(t2.to_dict()))
        # re-sign the outer id against the WRONG logical parent: the
        # message_artifact_id check must refuse before any packet row
        # is even compared
        doc["message_artifact_id"] = l_other.message_artifact_id()
        with pytest.raises(Exception):
            PhysicalTrafficArtifactV2.from_dict(
                doc, logical=l_other, bundle=bundle, strict=True)
        assert g2.workload_id() != other.workload_id()

    def test_v1_result_block_refuses_under_a_v2_plan(self, tmp_path):
        """Cross-generation transplant at the result layer: a v1-shaped
        result block (same products, old ancestry) never verifies
        against a v2 plan."""
        import json
        from veritx_dse.application.results import load_verified_result
        from veritx_dse.application.service import SrotaControlPlane
        from veritx_dse.application.waved_resources import (
            RESULT_WAVE_D_KEYS_V1, waved_chain_ids,
            waved_execution_block,
        )
        from veritx_dse.core.spec import canonical_json
        cp = SrotaControlPlane(store_root=tmp_path / "store",
                               repo_root=DSE.parent.parent.parent)
        decl = _workloads()["allreduce_p2p"]
        bundle = _bundle()
        g1, l1, t1 = _lower_v1(decl, bundle)
        summary = verify_trace_projection(t1)
        counters = {"delivered_packets": summary["num_packets"],
                    "flits_injected": summary["flits_total"],
                    "flits_accepted": summary["flits_total"]}
        v1_block = waved_execution_block(
            waved_chain_ids(decl, g1, l1, t1, bundle), summary, counters)
        assert set(v1_block) == set(RESULT_WAVE_D_KEYS_V1)
        # a live v2 result to transplant under
        import sys as _sys
        _sys.path.insert(0, str(DSE / "tests"))
        from test_wave_d_seal import _intent  # noqa: E402
        result = cp.evaluate(_intent(name="m2-xgen"))
        path = cp.store.root / "result" / f"{result['resource_id']}.json"
        doc = json.loads(path.read_text())
        assert set(doc["wave_d"]) != set(v1_block)
        doc["wave_d"] = v1_block
        path.write_text(canonical_json(doc))
        with pytest.raises(ControlPlaneError):
            load_verified_result(cp.store, result["resource_id"])
