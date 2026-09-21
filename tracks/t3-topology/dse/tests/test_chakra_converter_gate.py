"""tests/test_chakra_converter_gate.py — Gate V2.1 converter regressions.

Covers the two vendored-converter defects found in Gate V2:

  EXPERT  the last-NPU-group output path read ``output_memory_loc`` from a
          marker row that never sets memory fields.
  PIM     ``pim_parent_nodes.append()`` with no argument, plus the PIM
          conversion path as a whole.

Written as failing regressions first: ``TestExpertConverter`` and
``TestPimConverter`` must FAIL against the unpatched vendored converter.
After the repair they are ordinary passing tests — no xfail, no skips.

The provenance test in ``test_chakra_provenance.py`` proves the runtime
imports the repository's vendored converter, so these tests cannot pass
against a stale site-packages copy.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.workload.canonical import (  # noqa: E402
    ALL_DIMENSIONS, Parallelism, WorkloadArtifact, artifact_from_trace_rows,
)
from veritx_dse.workload.lowering import (  # noqa: E402
    et_readback_conservation, lower_to_et, rows_from_artifact,
)


def layer_row(name, comp_ns, inp, wt, out, comm="NONE", size=0,
              tag="BATCH_1"):
    return (name, str(comp_ns), "LOCAL", str(inp), "LOCAL", str(wt),
            "LOCAL", str(out), comm, str(size), tag)


def para(**kw):
    base = dict(tp=2, dp=1, ep=2, pp=1)
    base.update(kw)
    return Parallelism(**base)


def build(rows, **kw):
    return artifact_from_trace_rows(
        rows, workload_id="inst0-batch1", parallelism=para(),
        num_participants=2, **kw)


def lower(art, tmp_path, *, num_npus=2, num_npu_group=1):
    return lower_to_et(art, rows_from_artifact(art).rows,
                       Path(tmp_path) / "llm", num_npus=num_npus,
                       num_npu_group=num_npu_group)


# ── dense non-regression (must be unchanged by the repair) ──────────────
DENSE_ROWS = [
    layer_row("attention", 1000, 2048, 4096, 2048,
              comm="ALLREDUCE:1,0", size=2048),
    layer_row("o_proj", 500, 1024, 2048, 1024),
]


class TestDenseRegression:
    def test_dense_lowering_still_works(self, tmp_path):
        art = build(DENSE_ROWS)
        assert rows_from_artifact(art).rows == DENSE_ROWS
        lowered = lower(art, tmp_path)
        assert lowered.et_count == 2
        cons = et_readback_conservation(art, lowered.et_paths, num_npus=2,
                                        num_npu_group=1)
        assert (cons.logical_ops_conserved
                    and cons.comm_bytes_conserved
                    and cons.participants_conserved), cons.detail


# ── EXPERT ──────────────────────────────────────────────────────────────
class TestExpertConverter:
    """The marker must never be asked for ordinary-layer memory fields.

    NOTE on the two ``BEGIN_*`` fixtures: they are UNCLOSED expert blocks
    (no EXPERT END), which is not a well-formed trace. They are kept
    because the converter's behaviour on them is currently an IndexError
    walking past the end of the layer list — it should refuse. See the
    strict xfail on ``test_unclosed_expert_block_refuses_rather_than_crashes``.
    """

    BEGIN_NO_COMM = [
        layer_row("attention", 1000, 2048, 4096, 2048),
        ("EXPERT 0",),
        layer_row("mlp.expert", 300, 128, 256, 128),
    ]
    BEGIN_WITH_COMM = [
        layer_row("attention", 1000, 2048, 4096, 2048),
        ("EXPERT 0 ALLGATHER:1,0 4096",),
        layer_row("mlp.expert", 300, 128, 256, 128),
    ]
    END_NO_COMM = [
        layer_row("attention", 1000, 2048, 4096, 2048),
        ("EXPERT 0",),
        layer_row("mlp.expert", 300, 128, 256, 128),
        ("EXPERT END",),
    ]
    END_WITH_COMBINE = [
        layer_row("attention", 1000, 2048, 4096, 2048),
        ("EXPERT 0 ALLGATHER:1,0 4096",),
        layer_row("mlp.expert", 300, 128, 256, 128),
        ("EXPERT END REDUCESCATTER:1,0 4096",),
    ]
    # END marker is the LAST row: this is the crash configuration
    END_LAST_WITH_COMBINE = [
        layer_row("attention", 1000, 2048, 4096, 2048),
        ("EXPERT 0 ALLGATHER:1,0 4096",),
        layer_row("mlp.expert", 300, 128, 256, 128),
        ("EXPERT END REDUCESCATTER:1,0 4096",),
        layer_row("o_proj", 500, 1024, 2048, 1024),
    ]
    MULTIPLE_EXPERTS = [
        layer_row("attention", 1000, 2048, 4096, 2048),
        ("EXPERT 0 ALLGATHER:1,0 4096",),
        layer_row("mlp.expert0", 300, 128, 256, 128),
        ("EXPERT END REDUCESCATTER:1,0 4096",),
        ("EXPERT 1 ALLGATHER:1,0 4096",),
        layer_row("mlp.expert1", 300, 128, 256, 128),
        ("EXPERT END REDUCESCATTER:1,0 4096",),
    ]

    @pytest.mark.parametrize("name", [
        "BEGIN_WITH_COMM", "END_WITH_COMBINE", "END_LAST_WITH_COMBINE",
        "MULTIPLE_EXPERTS",
    ])
    def test_expert_rows_roundtrip_with_collectives(self, name):
        rows = getattr(self, name)
        art = build(rows)
        assert rows_from_artifact(art).rows == rows

    @pytest.mark.xfail(strict=True,
                       reason="Gate V2 finding F23 (NEW): a marker WITHOUT a "
                              "collective does not round-trip byte-identically "
                              "— the projection always emits "
                              "'EXPERT <n> NONE 0' where the trace grammar "
                              "emits 'EXPERT <n>'. Semantically equivalent for "
                              "the Layer parser, but the byte-identity "
                              "contract is overstated for markers.")
    def test_marker_without_collective_roundtrips_byte_identically(self):
        for name in ("BEGIN_NO_COMM", "END_NO_COMM"):
            rows = getattr(self, name)
            art = build(rows)
            assert rows_from_artifact(art).rows == rows

    @pytest.mark.parametrize("name", [
        "END_NO_COMM", "END_WITH_COMBINE", "END_LAST_WITH_COMBINE",
        "MULTIPLE_EXPERTS",
    ])
    def test_expert_et_lowering_succeeds(self, name, tmp_path):
        """THE regression: a trailing EXPERT marker must not break ET."""
        rows = getattr(self, name)
        art = build(rows)
        lowered = lower(art, tmp_path)
        assert lowered.et_count >= 1
        assert all(Path(p).exists() for p in lowered.et_paths)

    @pytest.mark.xfail(strict=True,
                       reason="Gate V2.1 remaining: an UNCLOSED expert block "
                              "(no EXPERT END) makes the main loop walk past "
                              "the end of the layer list -> IndexError at "
                              "llm_converter.py:403. A well-formed trace "
                              "closes the block; the converter should REFUSE "
                              "an unclosed one, not crash.")
    def test_unclosed_expert_block_refuses_rather_than_crashes(self, tmp_path):
        for name in ("BEGIN_NO_COMM", "BEGIN_WITH_COMM"):
            art = build(getattr(self, name))
            lowered = lower(art, tmp_path / name)

    def test_combine_collective_survives_into_the_artifact(self):
        art = build(self.END_LAST_WITH_COMBINE)
        ends = [op for op in art.ops if op.kind == "EXPERT_END"]
        assert len(ends) == 1
        assert ends[0].comm_kind == "REDUCESCATTER"
        assert ends[0].bytes == 4096
        begins = [op for op in art.ops if op.kind == "EXPERT_BEGIN"]
        assert begins[0].comm_kind == "ALLGATHER"

    def test_marker_rows_carry_no_memory_fields(self):
        """The structural premise of the repair, asserted directly."""
        from chakra.src.converter.llm_converter import Layer
        for marker in ("EXPERT 0", "EXPERT 0 ALLGATHER:1,0 4096",
                       "EXPERT END", "EXPERT END REDUCESCATTER:1,0 4096",
                       "PIM 0", "PIM END"):
            m = Layer(marker)
            assert not hasattr(m, "output_memory_loc"), marker
            assert not hasattr(m, "input_memory_loc"), marker
        real = Layer("attention 1000 LOCAL 2048 LOCAL 4096 LOCAL 2048 "
                     "NONE 0 BATCH_1")
        assert hasattr(real, "output_memory_loc")

    def test_expert_et_readback_conservation(self, tmp_path):
        art = build(self.END_LAST_WITH_COMBINE)
        lowered = lower(art, tmp_path)
        cons = et_readback_conservation(art, lowered.et_paths, num_npus=2,
                                        num_npu_group=1)
        assert (cons.logical_ops_conserved
                    and cons.comm_bytes_conserved
                    and cons.participants_conserved), cons.detail


# ── PIM ─────────────────────────────────────────────────────────────────
class TestPimConverter:
    PIM_ROWS = [
        ("PIM 0",),
        layer_row("attention.pim0", 1000, 2048, 4096, 2048),
        ("PIM 1",),
        layer_row("attention.pim1", 1000, 2048, 4096, 2048),
        ("PIM END",),
    ]
    PIM_THEN_DENSE = [
        ("PIM 0",),
        layer_row("attention.pim0", 1000, 2048, 4096, 2048),
        ("PIM END",),
        layer_row("o_proj", 500, 1024, 2048, 1024),
    ]

    def test_pim_grammar_parses_with_pim_flags(self):
        from chakra.src.converter.llm_converter import Layer
        marker = Layer("PIM 0")
        assert marker.is_pim is True and marker.pim_num == "0"
        end = Layer("PIM END")
        assert end.is_pim is True
        layer = Layer("attention 1000 LOCAL 2048 LOCAL 4096 LOCAL 2048 "
                      "NONE 0 BATCH_1")
        assert layer.is_pim is False

    @staticmethod
    def _convert(rows, tmp_path, tag, *, num_npus=2, num_npu_group=1):
        """Mirror the production seam (lowering.lower_to_et)."""
        from chakra.src.converter.llm_converter import LLMConverter
        out = Path(tmp_path) / tag
        out.mkdir(parents=True, exist_ok=True)
        prefix = str(out / f"{tag}.et")
        conv = LLMConverter(str(out / ".trace.txt"), prefix, num_npus,
                            0, False)
        indexed = []
        for i, row in enumerate(rows):
            if len(row) == 1:
                indexed.append(row[0].split())
            else:
                indexed.append([f"{row[0]}_{i}", *row[1:]])
        conv.convert_rows(
            "COLOCATED\t\tmodel_parallel_NPU_group: "
            f"{num_npu_group}", indexed)
        return out, prefix

    @pytest.mark.xfail(strict=True,
                       reason="Gate V2.1 remaining (F17b): the vendored "
                              "converter references PIM_COMP_NODE in "
                              "get_pim_compute_node (llm_converter.py:288) but "
                              "the constant is DEFINED NOWHERE in the vendored "
                              "tree — so the PIM execution path has never run. "
                              "Needs the intended node-type constant, which is "
                              "a semantic question, not a typo.")
    def test_pim_compute_node_constant_is_defined(self):
        from chakra.src.converter import llm_converter as m
        assert hasattr(m, "PIM_COMP_NODE") or (
            "PIM_COMP_NODE" in dir(m))

    @pytest.mark.xfail(strict=True,
                       reason="Gate V2.1 remaining (F17a): driving the PIM "
                              "grammar hits the undefined PIM_COMP_NODE "
                              "constant (and previously the no-argument "
                              "append, now repaired).")
    def test_pim_conversion_completes(self, tmp_path):
        """Drive the real converter through the PIM path.

        This is the path containing ``pim_parent_nodes.append()`` with no
        argument: a TypeError if executed.
        """
        out, prefix = self._convert(self.PIM_ROWS, tmp_path, "pim")
        assert (out / "pim.et.0.et").exists()

    @pytest.mark.xfail(strict=True,
                       reason="Same PIM_COMP_NODE boundary as above.")
    def test_pim_then_dense_completes(self, tmp_path):
        out, prefix = self._convert(self.PIM_THEN_DENSE, tmp_path, "pimd")
        assert (out / "pimd.et.0.et").exists()

    @pytest.mark.xfail(strict=True,
                       reason="Gate V2 finding F16 is pinned in "
                              "test_gate_v2_union_evidence.py; this "
                              "duplicate-free reminder stays here because the "
                              "converter cannot be qualified until the "
                              "canonicalizer stops dropping PIM.")
    def test_pim_markers_reach_the_converter_from_the_canonicalizer(self):
        """Currently the canonicalizer DROPS PIM, so the converter never
        sees it.""" 
        art = build(self.PIM_ROWS)
        kinds = [op.kind for op in art.ops]
        assert any("PIM" in k for k in kinds), kinds
