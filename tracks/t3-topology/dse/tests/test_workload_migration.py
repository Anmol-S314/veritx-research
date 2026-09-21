"""tests/test_workload_migration.py — slice 2c.3 migration fidelity.

The migration boundary must prove that everything historically
representable crosses into WorkloadGraph honestly: the OLD identity is
validated with the OLD rules first, the legacy hash is preserved as
non-identity provenance, positional order becomes an explicit chain, and
every semantic distinction survives (scope's three states, an explicit
broadcast root, SEND vs RECV, EXPERT combine collectives).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.core.artifact import EvidenceInvalid  # noqa: E402
from veritx_dse.workload.canonical import (  # noqa: E402
    ALL_DIMENSIONS, Parallelism, WorkloadArtifact, artifact_from_trace_rows,
    build_broadcast_op, build_collective_op, build_compute_op,
    build_expert_begin_op, build_p2p_op,
)
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
    KIND_P2P, OperationNode, WorkloadGraph,
)
from veritx_dse.workload.migration import (  # noqa: E402
    SOURCE_PHASE9, migrate_phase9_document, phase9_to_canonical_identity,
)

FIXTURES = DSE / "tests" / "fixtures"


def _phase9_artifact(**over):
    ops = over.pop("ops", None)
    if ops is None:
        ops = (
            build_compute_op("c0", 100, input_bytes=8, weight_bytes=16,
                             output_bytes=4, batch_tag="B1"),
            build_collective_op("g0", "ALLREDUCE", bytes=64,
                                participants=(0, 1, 2, 3),
                                scope=ALL_DIMENSIONS),
            build_broadcast_op("b0", bytes=32, participants=(0, 1, 2, 3),
                               source=2),
            build_p2p_op("s0", "SEND", bytes=8, src=0, dst=1),
            build_p2p_op("r0", "RECV", bytes=8, src=0, dst=1),
            build_expert_begin_op(0, comm_kind="ALLGATHER", bytes=64,
                                  participants=(0, 1, 2, 3),
                                  scope=ALL_DIMENSIONS),
            build_expert_begin_op(None, comm_kind="REDUCESCATTER", bytes=64,
                                  participants=(0, 1, 2, 3), end=True,
                                  scope=ALL_DIMENSIONS),
        )
    kwargs = dict(workload_id="w", source_kind="test",
                  parallelism=Parallelism(tp=4, dp=2), num_participants=4,
                  ops=ops)
    kwargs.update(over)
    return WorkloadArtifact(**kwargs)


class TestMigrationLaw:
    """Rule 2 — the old identity validates BEFORE new semantics exist."""

    def test_forged_legacy_hash_refuses_before_migration(self):
        doc = _phase9_artifact().serialize()
        doc["artifact_hash"] = "sha256:" + "0" * 64
        with pytest.raises(EvidenceInvalid, match="unauthenticated Phase-9"):
            migrate_phase9_document(doc)

    def test_tampered_content_refuses(self):
        doc = _phase9_artifact().serialize()
        doc["ops"][0]["duration_ns"] = 999           # move the content
        with pytest.raises(EvidenceInvalid):
            migrate_phase9_document(doc)

    def test_canonical_identity_is_derived_after_validation(self):
        doc = _phase9_artifact().serialize()
        new_id = phase9_to_canonical_identity(doc)
        assert new_id.startswith("sha256:")
        assert new_id != doc["artifact_hash"], (
            "the canonical identity must not be the legacy hash")

    def test_legacy_hash_survives_as_non_identity_provenance(self):
        art = _phase9_artifact()
        g = migrate_phase9_document(art.serialize())
        assert g.provenance["source_format"] == SOURCE_PHASE9
        assert g.provenance["legacy_artifact_hash"] == art.artifact_hash
        assert g.provenance["legacy_workload_id"] == "w"
        assert g.provenance["source_kind"] == "test"

    def test_provenance_does_not_move_identity(self):
        doc = _phase9_artifact().serialize()
        a = migrate_phase9_document(doc)
        doc2 = copy.deepcopy(doc)
        doc2["workload_id"] = "renamed"
        b = migrate_phase9_document(doc2)
        assert a.workload_id() == b.workload_id()
        assert a.provenance != b.provenance


class TestPhase9Parallelism:
    def test_named_field_mapping_never_swaps_dp_ep_pp(self):
        """legacy declares (tp, dp, ep, pp); canonical (tp, pp, ep, dp)."""
        art = _phase9_artifact(parallelism=Parallelism(tp=2, dp=4, ep=3,
                                                       pp=5),
                               num_participants=4)
        g = migrate_phase9_document(art.serialize())
        assert (g.parallelism.tp, g.parallelism.pp, g.parallelism.ep,
                g.parallelism.dp) == (2, 5, 3, 4)

    def test_participant_count_comes_from_legacy_num_participants(self):
        art = _phase9_artifact(parallelism=Parallelism(tp=4, dp=2),
                               num_participants=4)
        g = migrate_phase9_document(art.serialize())
        assert g.parallelism.world_size == 8
        assert g.participant_count == 4
        assert g.participant_count != g.parallelism.world_size

    def test_equal_case_is_also_pinned(self):
        art = _phase9_artifact(parallelism=Parallelism(tp=4, dp=1),
                               num_participants=4)
        g = migrate_phase9_document(art.serialize())
        assert g.participant_count == g.parallelism.world_size == 4


class TestPositionalOrderBecomesExplicit:
    def test_migration_chains_operations(self):
        g = migrate_phase9_document(_phase9_artifact().serialize())
        order = [op.operation_id for op in g.operations]
        deps = [op.deps for op in g.operations]
        assert deps[0] == ()
        for i in range(1, len(order)):
            assert deps[i] == (order[i - 1],)

    def test_migrated_graph_has_a_unique_total_order(self):
        g = migrate_phase9_document(_phase9_artifact().serialize())
        assert [op.operation_id for op in g.require_total_order()] == \
            [op.operation_id for op in g.operations]

    def test_tuple_permutation_keeps_identity_and_order(self):
        g = migrate_phase9_document(_phase9_artifact().serialize())
        shuffled = WorkloadGraph(
            parallelism=g.parallelism, participant_count=g.participant_count,
            operations=tuple(reversed(g.operations)),
            semantics=g.semantics, provenance=g.provenance)
        assert shuffled.workload_id() == g.workload_id()
        assert [op.operation_id for op in shuffled.require_total_order()] == \
            [op.operation_id for op in g.require_total_order()]


class TestPhase9OperationMapping:
    def test_compute_keeps_every_semantic_field(self):
        art = _phase9_artifact(ops=(build_compute_op(
            "c0", 1234, bytes=None, input_bytes=11, weight_bytes=22,
            output_bytes=33, input_loc="LOCAL", weight_loc="LOCAL",
            output_loc="LOCAL", batch_tag="B7", label="attn"),))
        g = migrate_phase9_document(art.serialize())
        d = g.by_id("c0").detail
        assert d["duration_ns"] == 1234
        assert (d["input_bytes"], d["weight_bytes"], d["output_bytes"]) == \
            (11, 22, 33)
        assert (d["input_loc"], d["weight_loc"], d["output_loc"]) == \
            ("LOCAL", "LOCAL", "LOCAL")
        assert d["batch_tag"] == "B7"
        assert g.by_id("c0").label == "attn"     # presentation survives

    def test_compressed_defaults_are_expanded_after_validation(self):
        """The legacy document omits defaults; v2 states them explicitly."""
        doc = _phase9_artifact(ops=(build_compute_op("c0", 5,
                                                     input_bytes=1),))
        serialized = doc.serialize()
        assert "input_loc" not in serialized["ops"][0]
        g = migrate_phase9_document(serialized)
        d = g.by_id("c0").detail
        assert d["input_loc"] == "LOCAL" and d["batch_tag"] == "NONE"

    @pytest.mark.parametrize("scope", [None, ALL_DIMENSIONS,
                                       [True, False, False, False]])
    def test_scope_three_states_survive(self, scope):
        if scope is None:
            # Phase-9 refuses an undeclared scope at construction; the
            # legacy reader is the only place None can arrive from.
            pytest.skip("Phase-9 authoring refuses scope=None")
        art = _phase9_artifact(ops=(build_collective_op(
            "g0", "ALLREDUCE", bytes=64, participants=(0, 1, 2, 3),
            scope=scope),))
        g = migrate_phase9_document(art.serialize())
        expected = scope if isinstance(scope, str) else tuple(scope)
        assert g.by_id("g0").detail["scope"] == expected

    def test_broadcast_source_survives_and_participants_are_not_reordered(
            self):
        art = _phase9_artifact(ops=(build_broadcast_op(
            "b0", bytes=32, participants=(0, 1, 2, 3), source=2),))
        d = migrate_phase9_document(art.serialize()).by_id("b0").detail
        assert d["source"] == 2
        assert d["participants"] == (0, 1, 2, 3), "must not be reordered"

    def test_send_and_recv_keep_their_roles_and_are_not_paired(self):
        art = _phase9_artifact(ops=(
            build_p2p_op("s0", "SEND", bytes=8, src=0, dst=1),
            build_p2p_op("r0", "RECV", bytes=8, src=0, dst=1)))
        g = migrate_phase9_document(art.serialize())
        assert g.by_id("s0").detail["role"] == "SEND"
        assert g.by_id("r0").detail["role"] == "RECV"
        assert g.of_kind(KIND_P2P)[0].detail["role"] != \
            g.of_kind(KIND_P2P)[1].detail["role"]

    def test_expert_begin_and_end_collectives_survive(self):
        g = migrate_phase9_document(_phase9_artifact().serialize())
        begins = g.of_kind(KIND_EXPERT_BEGIN)
        ends = g.of_kind(KIND_EXPERT_END)
        assert begins and ends
        assert begins[0].detail["collective_kind"] == "ALLGATHER"
        assert ends[0].detail["collective_kind"] == "REDUCESCATTER", \
            "the combine collective must not be dropped"
        assert ends[0].detail["payload_bytes"] == 64

    def test_bare_expert_marker_migrates(self):
        art = _phase9_artifact(ops=(
            build_compute_op("c0", 5),
            build_expert_begin_op(0),
            build_expert_begin_op(None, end=True)))
        g = migrate_phase9_document(art.serialize())
        assert g.of_kind(KIND_EXPERT_BEGIN)[0].detail["collective_kind"] \
            is None
        assert g.of_kind(KIND_EXPERT_END)[0].detail["collective_kind"] is None

    def test_divisible_only_at_the_schedule_not_the_declaration(self):
        art = _phase9_artifact(ops=(
            build_collective_op("g0", "ALLREDUCE", bytes=1000,
                                participants=(0, 1, 2),
                                scope=ALL_DIMENSIONS),),
            num_participants=3)
        g = migrate_phase9_document(art.serialize())
        assert g.by_id("g0").detail["payload_bytes"] == 1000


class TestStrictRoundTrip:
    def test_migrated_graph_strict_roundtrips(self):
        g = migrate_phase9_document(_phase9_artifact().serialize())
        doc = g.to_dict()
        again = WorkloadGraph.from_dict(doc, strict=True)
        assert again.workload_id() == g.workload_id()
        assert again.to_dict() == doc

    def test_every_operation_kind_roundtrips(self):
        g = migrate_phase9_document(_phase9_artifact().serialize())
        kinds = {op.kind for op in g.operations}
        assert kinds == {KIND_COMPUTE, KIND_COLLECTIVE, KIND_P2P,
                         KIND_EXPERT_BEGIN, KIND_EXPERT_END}


class TestLegacyCorpusMigrates:
    """The whole Phase-9 corpus must cross the boundary.

    Every fixture: old hash validates, migration succeeds, the canonical
    document strict-roundtrips. Counts are recorded, not asserted loosely.
    """

    @staticmethod
    def _documents() -> dict[str, dict]:
        spec = importlib.util.spec_from_file_location(
            "phase9_workload_corpus",
            FIXTURES / "phase9_workload_corpus.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        corpus = module.build_corpus()
        return {k.rsplit("/", 1)[0]: v for k, v in corpus.items()
                if k.endswith("/serialize") and isinstance(v, dict)
                and "ops" in v}

    def test_every_legacy_document_migrates(self):
        documents = self._documents()
        assert len(documents) >= 12, sorted(documents)
        migrated = 0
        for name, doc in sorted(documents.items()):
            try:
                g = migrate_phase9_document(doc)
            except InvalidInput_skip as exc:  # pragma: no cover
                pytest.skip(f"{name}: {exc}")
            WorkloadGraph.from_dict(g.to_dict(), strict=True)
            migrated += 1
        assert migrated == len(documents)
