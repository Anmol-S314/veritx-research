"""tests/test_domain_corpus_identity.py — pin the semantic corpus.

Slice 2b dissolved ``veritx_dse/waved/`` into domain owners. Path-only
moves must not move a single identity, so a representative corpus was
captured from the pre-move tree and compared after the move: 69 entries,
**zero differences** (parallelism ids and group derivations, semantics,
operation graphs, logical message and schedule ids, packetization and
flitization, physical traffic ids, conservation ledgers, rendered trace
bytes, trace-projection summaries, prepared BookSim config/input hashes).

This test keeps that guarantee for slices 2c/3/4: it recomputes the same
corpus from the current tree and compares one digest against the pinned
value. If a later slice legitimately changes an identity, this fails and
the change must be argued explicitly — which is the point.

Corpus construction mirrors /tmp/wd_corpus.py, which was the equality
oracle for the move.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(DSE / "tests"))

PINNED_CORPUS_SHA256 = \
    "cdfc6a00321dbec2af9d6af06dd20fc2aae1112e6ac0c8051af8e43a63325779"


def _build_corpus() -> dict:
    from test_wave_d_physical import _bundle

    from veritx_dse.backend.projection import (
        prepare_waved_booksim, render_waved_trace, verify_trace_projection,
    )
    from veritx_dse.model.parallelism import ParallelismArtifact
    from veritx_dse.workload.graph import WaveDWorkload  # noqa: F401
    from veritx_dse.workload.messages import LogicalMessageArtifact
    from veritx_dse.workload.operations import (
        KIND_COLLECTIVE, KIND_MULTICAST, KIND_P2P, CollectiveIntent,
        MulticastIntent, OperationGraph, OperationNode, P2PTransfer,
    )
    from veritx_dse.workload.semantics import WaveDWorkloadSemantics
    from veritx_dse.workload.traffic import PhysicalTrafficArtifact

    corpus: dict[str, object] = {}
    rec = corpus.__setitem__

    for dims in ((1, 1, 1, 1), (2, 1, 1, 2), (2, 2, 2, 2), (4, 2, 1, 1)):
        pa = ParallelismArtifact(*dims)
        tag = "x".join(map(str, dims))
        rec(f"parallelism/{tag}/id", pa.parallelism_id())
        rec(f"parallelism/{tag}/to_dict", pa.to_dict())
        for family in ("TP", "EP", "DP", "PP"):
            rec(f"parallelism/{tag}/groups/{family}",
                [[list(g.index), list(g.members)] for g in pa.groups(family)])
            rec(f"parallelism/{tag}/group_of/{family}",
                {str(r): list(pa.group_of(family, r).members)
                 for r in range(pa.world_size)})

    for phase in ("PREFILL", "DECODE"):
        rec(f"semantics/{phase}/to_dict",
            WaveDWorkloadSemantics(phase=phase).to_dict())

    pa4 = ParallelismArtifact(2, 1, 1, 2)
    for kind in ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER", "ALLTOALL",
                 "BROADCAST"):
        coll = CollectiveIntent(kind, (0, 1, 2, 3), 1024, "c0")
        graph = OperationGraph(
            parallelism=pa4,
            semantics=WaveDWorkloadSemantics(phase="DECODE"),
            workload_id="w",
            nodes=(OperationNode("coll0", KIND_COLLECTIVE, "DECODE", 0, 0,
                                 (), {"collective_id": "c0"}),),
            collectives=(coll,))
        rec(f"graph/{kind}/id", graph.operation_graph_id())
        rec(f"graph/{kind}/to_dict", graph.to_dict())

    mixed = OperationGraph(
        parallelism=pa4, semantics=WaveDWorkloadSemantics(phase="DECODE"),
        workload_id="w",
        nodes=(OperationNode("coll0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                             {"collective_id": "c0"}),
               OperationNode("p2p0", KIND_P2P, "DECODE", 0, 0, (),
                             {"transfer_id": "t0"}),
               OperationNode("mc0", KIND_MULTICAST, "DECODE", 1, 0, (),
                             {"multicast_id": "m0"})),
        collectives=(CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0"),),
        p2p_transfers=(P2PTransfer(0, 2, 300, "t0"),),
        multicasts=(MulticastIntent(1, (0, 2, 3), 256,
                                    "SOURCE_REPLICATION", "m0"),))
    rec("graph/mixed/id", mixed.operation_graph_id())
    rec("graph/mixed/to_dict", mixed.to_dict())

    logical = LogicalMessageArtifact(graph=mixed)
    rec("messages/id", logical.message_artifact_id())
    rec("messages/to_dict", logical.to_dict())
    rec("messages/schedule_ids", [r.schedule_id for r in logical.schedules])

    bundle = _bundle()
    pt = PhysicalTrafficArtifact(logical=logical, bundle=bundle)
    pt.validate_conservation()
    rec("traffic/id", pt.to_dict().get("physical_traffic_id")
        or pt.to_dict().get("traffic_id"))
    rec("traffic/to_dict_sha",
        hashlib.sha256(
            json.dumps(pt.to_dict(), sort_keys=True,
                       separators=(",", ":")).encode()).hexdigest())
    rec("traffic/packets",
        [[t.message_id, p.packet_index, p.payload_bits, p.flit_count,
          p.padding_bits, p.transmitted_bits]
         for t in pt._traffic for p in t.packets])
    rec("traffic/totals", pt.totals())
    rec("traffic/ledger", [
        {"operation_id": e.operation_id,
         "generated_message_bytes": e.generated_message_bytes,
         "scheduled_message_bytes": e.scheduled_message_bytes}
        for e in pt.conservation_ledger()])

    trace = render_waved_trace(pt)
    rec("render/sha256", hashlib.sha256(trace).hexdigest())
    rec("render/bytes", len(trace))
    rec("render/first_lines", trace.decode().splitlines()[:6])
    rec("projection/summary_sha",
        hashlib.sha256(json.dumps(verify_trace_projection(pt),
                                  sort_keys=True, default=str,
                                  separators=(",", ":")).encode()).hexdigest())

    prepared, summary = prepare_waved_booksim(pt)
    rec("prepare/summary_sha",
        hashlib.sha256(json.dumps(summary, sort_keys=True, default=str,
                                  separators=(",", ":")).encode()).hexdigest())
    rec("prepare/config_sha",
        getattr(getattr(prepared, "config", None), "config_hash", None)
        or getattr(prepared, "config_hash", None))
    rec("prepare/input_sha", getattr(prepared, "input_hash", None))
    return corpus


def test_domain_corpus_identity_is_stable():
    corpus = _build_corpus()
    canonical = json.dumps(corpus, sort_keys=True, separators=(",", ":"),
                           default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    assert len(corpus) == 69
    assert digest == PINNED_CORPUS_SHA256, (
        "domain corpus identity moved. If this is intentional (a schema "
        "version bump, not a refactor), update PINNED_CORPUS_SHA256 and "
        "explain why in ARCHITECTURE-CONSOLIDATION.md")
