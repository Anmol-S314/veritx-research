"""tests/test_phase9_workload_corpus.py — the OLD authority's corpus.

Slice 2c merges two workload authorities. The Wave-D corpus
(test_domain_corpus_identity.py) pins the new graph's identities. This
one pins what the OLD canonical path produces TODAY, captured before any
2c edit, so the merge can be proven to be a UNION rather than an
amputation of everything Wave D never modelled.

The builder lives in tests/fixtures/phase9_workload_corpus.py and is
checked in so the corpus is reproducible rather than a frozen blob.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
FIXTURES = DSE / "tests" / "fixtures"
sys.path.insert(0, str(DSE))

PINNED_PHASE9_CORPUS_SHA256 = (
    "68f7401ec8cb32a34c9309481d33db0eb3641ddc1f55421844933f15e049ad0e")


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "phase9_workload_corpus",
        FIXTURES / "phase9_workload_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def corpus() -> dict:
    return _load_builder().build_corpus()


def test_phase9_corpus_digest_is_pinned(corpus):
    """If the old path changes, 2c must say so explicitly."""
    digest = _load_builder().corpus_digest(corpus)
    assert len(corpus) > 150, f"corpus shrank to {len(corpus)} entries"
    assert digest == PINNED_PHASE9_CORPUS_SHA256, (
        "the Phase-9/14/16 workload path changed. Before accepting this, "
        "confirm the canonical WorkloadGraph preserves the same semantics "
        "and update the pin with a written reason")


class TestOldAuthoritySemanticsAreCaptured:
    """The union checklist: each of these must survive into WorkloadGraph."""

    @pytest.mark.parametrize("field", [
        "duration_ns", "input_bytes", "weight_bytes", "output_bytes",
    ])
    def test_compute_operand_fields_present(self, corpus, field):
        op = corpus["op/compute_only/c0"]
        assert field in op, f"{field} not captured from the old authority"

    def test_default_valued_fields_are_omitted_not_lost(self, corpus):
        """to_dict() is a COMPRESSED canonical form, not a lossy one.

        Defaults (loc LOCAL, batch_tag NONE) are omitted; non-default
        values appear. Identity is built from this same dict, so anything
        omitted is omitted from identity too — consistently.
        """
        default_op = corpus["op/compute_only/c0"]
        assert "input_loc" not in default_op      # LOCAL is the default
        assert "batch_tag" not in default_op      # NONE is the default
        nondefault = corpus["op/memory_operands/m0"]
        assert nondefault["batch_tag"] == "B1"
        # a non-LOCAL location DOES serialize, and the resolver is where
        # the location law refuses it (never at construction)
        for loc in ("REMOTE", "CXL", "STORAGE"):
            assert corpus[f"loc/{loc}/op_to_dict"]["input_loc"] == loc
            assert corpus[f"loc/{loc}/resolver"]["type"], loc

    def test_dimensional_scope_present(self, corpus):
        scoped = corpus["op/scope_tp_only/g0"]
        assert scoped["scope"] == [True, False, False, False]
        assert corpus["op/scope_explicit_all/g0"]["scope"] == "ALL"

    def test_broadcast_source_present(self, corpus):
        assert corpus["op/broadcast/g0"]["src"] == 2

    def test_expert_markers_present(self, corpus):
        begin = [op for op in corpus["expert_with_collective/op_dicts"]
                 if op["kind"] == "EXPERT_BEGIN"][0]
        assert begin["expert_num"] == 3
        assert begin["comm_kind"] == "ALLTOALL"
        end = [op for op in corpus["op/expert_marker_only/c0"]
               .values()] if False else None
        kinds = [op["kind"] for op in
                 corpus["expert_marker_only/op_dicts"]]
        assert kinds == ["COMPUTE", "EXPERT_BEGIN", "EXPERT_END"]

    def test_trace_row_roundtrip_is_byte_identical(self, corpus):
        for tag in ("serving_dense_allreduce", "serving_multi_comm",
                    "serving_expert_rows"):
            assert corpus[f"trace/{tag}/rows_roundtrip_equal"] is True, tag

    def test_et_lowering_is_captured(self, corpus):
        for tag in ("serving_dense_allreduce", "serving_multi_comm"):
            assert corpus[f"trace/{tag}/et_count"] >= 1, tag
            assert corpus[f"trace/{tag}/et_sha256s"], tag

    def test_memory_artifact_is_conserved(self, corpus):
        assert corpus["memory/operands_local/conserved"] is True
        assert corpus["trace/serving_dense_allreduce/memory_conserved"] \
            is True

    def test_refusals_are_captured(self, corpus):
        """The old authority's refusals are semantics too."""
        refusals = {k.split("/")[1]: v for k, v in corpus.items()
                    if k.startswith("refusal/")}
        assert refusals["compute_with_comm_bytes"]["type"] == "WorkloadError"
        assert refusals["duplicate_ids"]["type"] == "WorkloadError"
        assert refusals["empty_ops"]["type"] == "WorkloadError"
        assert refusals["participant_out_of_range"]["type"] == "WorkloadError"
        assert refusals["negative_duration"]["type"] == "WorkloadError"

    def test_known_permissive_cases_are_recorded_not_assumed(self, corpus):
        """Recorded findings, not assertions of correctness.

        The old authority does NOT enforce the Wave-D divisibility law,
        does not validate the operation kind at CONSTRUCTION time (the
        artifact does), and accepts REMOTE/CXL/STORAGE locations at
        construction (the memory RESOLVER refuses them). A canonical graph
        that tightens any of these is a behaviour change and must be
        reported, not slipped in.
        """
        assert corpus["refusal/non_divisible_allreduce"] == "NO REFUSAL"
        assert corpus["refusal/unknown_kind"] == "NO REFUSAL"
        assert corpus["refusal/remote_operand_loc"] == "NO REFUSAL"
        assert corpus["refusal/cxl_operand_loc"] == "NO REFUSAL"
        # ... but construction is not acceptance: the memory RESOLVER
        # refuses the unsupported tiers. Both halves are captured.
        for loc in ("REMOTE", "CXL", "STORAGE"):
            entry = corpus[f"loc/{loc}/resolver"]
            assert isinstance(entry, dict) and entry["type"], (loc, entry)
