"""Phase 1 T3 — fidelity identity lands in serve results.

Replay must be machine-distinguishable from simulation in the result
itself (not just a stdout tagline), and `cmd_serve` may not call
returncode 0 a success without terminal validation: known fidelity,
acceptable losses, and every requested request retired per the CSV.
"""
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.core.serving import (
    fidelity_for_mode,
    mode_for_backend,
    passes_serving_golden_gate,
    retired_from_csv,
    serving_provenance,
)
from veritx_dse.core.paths import REPO

SERVING_ROOT = REPO / "third_party" / "llmservingsim"


class TestModeMapping:
    def test_default_booksim_is_replay(self):
        assert mode_for_backend("booksim", False) == "TRACE_REPLAY"

    def test_cycle_accurate_booksim_is_real(self):
        assert mode_for_backend("booksim", True) == "REAL_SIMULATION"

    def test_analytical_is_real_not_replay(self):
        assert mode_for_backend("analytical", False) == "REAL_SIMULATION"
        assert mode_for_backend("analytical", True) == "REAL_SIMULATION"

    def test_unknown_backend_refused(self):
        with pytest.raises(ValueError, match="network_mode"):
            mode_for_backend("vibes", False)


class TestFidelityMapping:
    def test_replay_fidelity(self):
        assert fidelity_for_mode("booksim", "TRACE_REPLAY") == "TRACE_REPLAY"

    def test_real_booksim_fidelity(self):
        assert fidelity_for_mode("booksim", "REAL_SIMULATION") == \
            "SYSTEM_SERVING_SIMULATION"

    def test_analytical_fidelity(self):
        assert fidelity_for_mode("analytical", "REAL_SIMULATION") == \
            "ANALYTICAL_ESTIMATE"

    def test_unknown_combination_refused(self):
        with pytest.raises(ValueError, match="fidelity"):
            fidelity_for_mode("booksim", "VIBES_BASED")


class TestGateAtVeritXLevel:
    def test_default_booksim_path_cannot_pass_golden_gate(self):
        """The Phase-1 gate clause: replay stays supported but ineligible."""
        mode = mode_for_backend("booksim", False)
        prov = serving_provenance(
            engine="llmservingsim", network_backend="booksim2",
            network_mode=mode, semantic_losses=[])
        assert passes_serving_golden_gate(prov) is False


class TestRetirementCount:
    def _csv(self, tmp_path, rows):
        p = tmp_path / "out.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["request id", "instance id", "TTFT (ns)"])
            w.writerows(rows)
        return p

    def test_counts_data_rows(self, tmp_path):
        p = self._csv(tmp_path, [["0", "0", "1"], ["1", "1", "2"]])
        assert retired_from_csv(p) == 2

    def test_header_only_is_zero_retired(self, tmp_path):
        assert retired_from_csv(self._csv(tmp_path, [])) == 0

    def test_missing_csv_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            retired_from_csv(tmp_path / "nope.csv")


@pytest.mark.skipif(not (SERVING_ROOT / "serving" / "__main__.py").exists(),
                    reason="LLMServingSim not vendored")
@pytest.mark.skipif(not (SERVING_ROOT / "configs" / "cluster"
                         / "single_node_single_instance.json").exists(),
                    reason="serving fixtures not present")
def test_serve_emits_structured_result(tmp_path, capsys):
    """Live analytical 1-req serve: stdout JSON carries the full identity."""
    from veritx_dse.cli.cli import cmd_serve
    from veritx_dse.core.logging import Ctx

    out_csv = tmp_path / "req.csv"
    args = SimpleNamespace(
        cluster_config=str(SERVING_ROOT / "configs" / "cluster"
                           / "single_node_single_instance.json"),
        dataset=str(SERVING_ROOT / "workloads" / "example_trace.jsonl"),
        num_reqs=1, network_backend="analytical", log_level="WARNING",
        output=str(out_csv), no_cleanup=True, no_prefix_caching=False,
        cycle_accurate=False, timeout=120, dtype=None,
        max_num_seqs=None, max_num_batched_tokens=None,
        long_prefill_token_threshold=None, block_size=None,
        npu_memory_utilization=None, log_interval=None, kv_cache_dtype=None,
        request_routing_policy=None, expert_routing_policy=None,
        prefix_storage=None, skip_prefill=False, save_trace_text=False,
        enable_prefix_sharing=False, enable_local_offloading=False,
        enable_attn_offloading=False, enable_sub_batch_interleaving=False,
        no_chunked_prefill=False, no_block_copy=False,
        no_reserve_full_isl=False,
    )
    cmd_serve(Ctx(verbosity=0, json_mode=True), args)
    out = capsys.readouterr().out
    # The child streams its own stdout past us; decode the first JSON
    # document (our structured record) wherever it lands.
    result, _ = json.JSONDecoder().raw_decode(out[out.index("{"):])
    assert result["engine"] == "llmservingsim"
    assert result["network_mode"] == "REAL_SIMULATION"
    assert result["fidelity"] == "ANALYTICAL_ESTIMATE"
    assert result["semantic_losses"] == []
    assert result["requests_retired"] == 1
    assert result["requests_requested"] == 1
    assert result["backend_binaries"], "binary identity must be recorded"
