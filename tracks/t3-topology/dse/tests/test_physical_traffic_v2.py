"""tests/test_physical_traffic_v2.py — M1.1 + M1.3.

PhysicalTrafficArtifactV2 projects the canonical logical messages through an
IDENTIFIED participant→endpoint binding:

    participant rank → MappingArtifact (rank→agent) → attachment
                     → ParticipantEndpointMapping → endpoint

A 4-participant workload on an 8-rank geometry lowers through its own
explicit binding; it refuses only when a participant has no authenticated
binding. Logical rank is never assumed to equal a physical endpoint.
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
from test_wave_d_physical import _bundle_with_permuted_mapping  # noqa: E402

from veritx_dse.core.artifact import EvidenceInvalid  # noqa: E402
from veritx_dse.core.errors import MappingInvalid  # noqa: E402
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, WorkloadSemantics,
    collective_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2  # noqa: E402
from veritx_dse.workload.traffic import (  # noqa: E402
    ParticipantEndpointMapping, PhysicalTrafficArtifactV2,
)


def bundle(tp=4, pp=1, ep=1, dp=2, n_agents=8):
    return make_bundle(build_chain(tp=tp, pp=pp, ep=ep, dp=dp,
                                   n_agents=n_agents,
                                   family=TopologyFamily.MESH))


def graph(participant_count, *, parallelism=None, source=2):
    pa = parallelism or ParallelismArtifact(tp=4, pp=1, ep=1, dp=2)
    op = OperationNode(
        "bc", KIND_COLLECTIVE, (),
        collective_detail(collective_kind="BROADCAST",
                          participants=tuple(range(participant_count)),
                          payload_bytes=512,
                          participant_count=participant_count,
                          scope="ALL", source=source))
    return WorkloadGraph(parallelism=pa, participant_count=participant_count,
                         operations=(op,), semantics=WorkloadSemantics())


def lowered(g, b):
    return PhysicalTrafficArtifactV2(logical=LogicalMessageArtifactV2(g),
                                     bundle=b)


class TestParticipantBinding:
    def test_four_participants_on_eight_ranks_lowers(self):
        art = lowered(graph(4), bundle())
        pem = art.participant_endpoint_mapping()
        assert pem.participant_count == 4
        assert [r for r, _ in pem.rank_to_endpoint] == [0, 1, 2, 3]
        assert art.totals()["message_count"] == 3
        art.validate_conservation()

    def test_endpoints_come_from_the_mapping(self):
        art = lowered(graph(4), bundle())
        pem = art.participant_endpoint_mapping()
        for t in art.traffic:
            assert t.src.endpoint_id == pem.endpoint_for(t.src.rank)
            assert t.dst.endpoint_id == pem.endpoint_for(t.dst.rank)
            assert t.src.agent_instance_id

    def test_participant_without_a_binding_refuses(self):
        """World 4, participants 8: ranks 4..7 have no binding."""
        b = bundle(tp=2, pp=1, ep=1, dp=2, n_agents=4)
        g = graph(8, parallelism=ParallelismArtifact(tp=2, pp=1, ep=1, dp=2))
        with pytest.raises(MappingInvalid, match="no authenticated"):
            lowered(g, b)

    def test_mapping_refuses_out_of_range_lookup(self):
        pem = ParticipantEndpointMapping(
            participant_count=2, rank_to_endpoint=((0, 5), (1, 7)),
            fabric_id="f" * 8)
        assert pem.endpoint_for(1) == 7
        with pytest.raises(MappingInvalid, match="outside"):
            pem.endpoint_for(2)

    def test_mapping_is_its_own_identified_artifact(self):
        a = lowered(graph(4), bundle())
        b = lowered(graph(4), bundle())
        assert a.participant_endpoint_mapping().binding_id() == \
            b.participant_endpoint_mapping().binding_id()


class TestIdentityDag:
    def test_mapping_change_moves_traffic_but_not_the_logical_artifact(self):
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        g = graph(4, parallelism=pa)
        logical = LogicalMessageArtifactV2(g)
        plain = bundle(tp=2, pp=1, ep=1, dp=2, n_agents=4)
        swapped = _bundle_with_permuted_mapping(
            (1, 0, 3, 2), tp=2, pp=1, ep=1, dp=2, n_agents=4)
        a = PhysicalTrafficArtifactV2(logical=logical, bundle=plain)
        b = PhysicalTrafficArtifactV2(logical=logical, bundle=swapped)
        assert a.participant_endpoint_mapping().binding_id() != \
            b.participant_endpoint_mapping().binding_id()
        assert a.physical_traffic_id() != b.physical_traffic_id()
        assert a.logical.message_artifact_id() == \
            b.logical.message_artifact_id()

    def test_payload_change_moves_the_traffic_identity(self):
        b = bundle()
        a = lowered(graph(4), b)
        other = graph(4)
        op = other.operations[0]
        # rebuild with a larger payload through the detail builder
        bigger = WorkloadGraph(
            parallelism=other.parallelism,
            participant_count=other.participant_count,
            operations=(OperationNode(
                "bc", KIND_COLLECTIVE, (),
                collective_detail(collective_kind="BROADCAST",
                                  participants=(0, 1, 2, 3),
                                  payload_bytes=1024,
                                  participant_count=4,
                                  scope="ALL", source=2)),),
            semantics=WorkloadSemantics())
        assert a.physical_traffic_id() != lowered(bigger, b).physical_traffic_id()

    def test_identity_is_deterministic(self):
        ids = {lowered(graph(4), bundle()).physical_traffic_id()
               for _ in range(5)}
        assert len(ids) == 1


class TestStrictLoader:
    def test_round_trip(self):
        g = graph(4)
        logical = LogicalMessageArtifactV2(g)
        art = PhysicalTrafficArtifactV2(logical=logical, bundle=bundle())
        again = PhysicalTrafficArtifactV2.from_dict(
            art.to_dict(), logical=logical, bundle=art.bundle, strict=True)
        assert again.physical_traffic_id() == art.physical_traffic_id()

    def test_tampered_packet_row_refuses(self):
        g = graph(4)
        logical = LogicalMessageArtifactV2(g)
        art = PhysicalTrafficArtifactV2(logical=logical, bundle=bundle())
        d = art.to_dict()
        d["traffic"][0] = []          # forged content
        with pytest.raises(EvidenceInvalid):
            PhysicalTrafficArtifactV2.from_dict(d, logical=logical,
                                                bundle=art.bundle,
                                                strict=True)

    def test_tampered_mapping_binding_refuses(self):
        g = graph(4)
        logical = LogicalMessageArtifactV2(g)
        art = PhysicalTrafficArtifactV2(logical=logical, bundle=bundle())
        d = art.to_dict()
        d["participant_endpoint_mapping_id"] = "0" * 64
        with pytest.raises(EvidenceInvalid):
            PhysicalTrafficArtifactV2.from_dict(d, logical=logical,
                                                bundle=art.bundle,
                                                strict=True)

    def test_another_logical_parent_refuses(self):
        g = graph(4)
        logical = LogicalMessageArtifactV2(g)
        art = PhysicalTrafficArtifactV2(logical=logical, bundle=bundle())
        other = LogicalMessageArtifactV2(graph(4, source=1))
        with pytest.raises(Exception, match="message_artifact_id"):
            PhysicalTrafficArtifactV2.from_dict(art.to_dict(), logical=other,
                                                bundle=art.bundle,
                                                strict=True)
