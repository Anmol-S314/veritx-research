"""Phase 1 T2 — PP semantics fail closed in the Chakra converter.

The `convert_rows` shim used to warn
"pp_stage_boundaries=... ignored (converter predates PP support)" and
continue with exit 0, handing every rank the full unpartitioned graph.
Now a PP header raises UNSUPPORTED_WORKLOAD_SEMANTIC instead.

Two-copy discipline (program T2: "installed/imported converter must
actually be the modified code"): the vendored tree is the source of
truth AND the test pins that the effective import is byte-identical —
editing one without the other fails loudly here, not silently in a run.
"""
from pathlib import Path

import pytest

llm_converter = pytest.importorskip("chakra.src.converter.llm_converter")

REPO = Path(__file__).resolve().parents[4]
VENDORED = (REPO / "third_party" / "astra-sim" / "extern" / "graph_frontend"
            / "chakra" / "src" / "converter" / "llm_converter.py")

ROWS = [
    ["embedding_0", "5323", "REMOTE:0", "40", "LOCAL", "622329856",
     "LOCAL", "40960", "NONE", "0", "NONE"],
    ["layernorm_1", "2128", "LOCAL", "40960", "LOCAL", "4096",
     "LOCAL", "40960", "NONE", "0", "NONE"],
    ["sampler_2", "25933", "LOCAL", "2565120", "LOCAL", "0",
     "REMOTE:0", "40", "NONE", "0", "NONE"],
]


def _convert(tmp_path, header, rows=ROWS):
    conv = llm_converter.LLMConverter(
        str(tmp_path / "in.txt"), str(tmp_path / "out"), 1, 0, False)
    conv.convert_rows(header, rows)
    return conv


class TestPPFailClosed:
    def test_pp_header_raises_unsupported(self, tmp_path):
        with pytest.raises(ValueError, match="UNSUPPORTED_WORKLOAD_SEMANTIC"):
            _convert(tmp_path,
                     "COLOCATED model_parallel_NPU_group: 2 "
                     "pp_stage_boundaries: 2")

    def test_refusal_names_field_and_value(self, tmp_path):
        with pytest.raises(ValueError) as e:
            _convert(tmp_path,
                     "COLOCATED model_parallel_NPU_group: 2 "
                     "pp_stage_boundaries: 289")
        msg = str(e.value)
        assert "pp_stage_boundaries" in msg
        assert "289" in msg
        assert "convert_rows" in msg

    def test_vendored_source_carries_the_same_guard(self):
        assert VENDORED.is_file(), "vendored converter tree must exist"
        assert "UNSUPPORTED_WORKLOAD_SEMANTIC" in VENDORED.read_text(), (
            "fix landed only in the installed copy — the vendored source "
            "of truth diverged")

    def test_effective_copy_matches_vendored_tree(self):
        effective = Path(llm_converter.__file__)
        assert effective.read_bytes() == VENDORED.read_bytes(), (
            f"imported {effective} differs from {VENDORED} — reinstall "
            "chakra from the vendored tree (compile.sh: pip3 install .)")


class TestPPFreeUnchanged:
    def test_pp_free_header_still_converts(self, tmp_path):
        _convert(tmp_path, "COLOCATED model_parallel_NPU_group: 1")
        ets = list(tmp_path.glob("out*.et")) + list(tmp_path.glob("*.et"))
        assert ets, "pp_size==1 conversion must still emit .et output"
        assert all(p.stat().st_size > 0 for p in ets)
