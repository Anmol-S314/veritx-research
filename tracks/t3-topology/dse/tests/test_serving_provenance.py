"""PR6 (§17.4/17.5/17.8) — serving network-mode provenance + golden gate.

A serving run that replays trace durations is not a network simulation,
even when it exits 0 with plausible TTFT/TPOT. Every serving result
therefore carries its execution mode, and the golden gate is a pure
predicate over that provenance — so a replay-only run *cannot* satisfy
it, by construction rather than by convention.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.core.runs import FIDELITY_CATEGORIES, metric
from veritx_dse.core.serving import (
    NETWORK_MODES,
    passes_serving_golden_gate,
    serving_provenance,
)


class TestTraceReplayFidelity:
    def test_trace_replay_is_a_known_fidelity(self):
        assert "TRACE_REPLAY" in FIDELITY_CATEGORIES

    def test_replay_latency_types_as_replay_not_simulation(self):
        m = metric("ttft_mean", 9.64, "ms",
                   producer="llmservingsim", fidelity="TRACE_REPLAY")
        assert m["fidelity"] == "TRACE_REPLAY"
        assert m["fidelity"] != "SYSTEM_SERVING_SIMULATION"


class TestServingProvenance:
    def test_replay_provenance_shape(self):
        p = serving_provenance(engine="llmservingsim",
                               network_backend="booksim2",
                               network_mode="TRACE_REPLAY",
                               semantic_losses=["pp_stage_boundaries"])
        assert p["network_mode"] == "TRACE_REPLAY"
        assert p["semantic_losses"] == ["pp_stage_boundaries"]

    def test_unknown_mode_refused(self):
        with pytest.raises(ValueError, match="network_mode"):
            serving_provenance(engine="llmservingsim",
                               network_backend="booksim2",
                               network_mode="VIBES_BASED",
                               semantic_losses=[])

    def test_semantic_losses_must_be_a_list(self):
        with pytest.raises(TypeError, match="semantic_losses"):
            serving_provenance(engine="llmservingsim",
                               network_backend="booksim2",
                               network_mode="REAL_SIMULATION",
                               semantic_losses="pp_stage_boundaries")


class TestGoldenGate:
    def test_replay_only_cannot_pass_the_gate(self):
        """§17.8: the dangerous false-success class — plausible numbers,
        no network simulated — is excluded by the gate, not by eyeballing."""
        p = serving_provenance(engine="llmservingsim",
                               network_backend="booksim2",
                               network_mode="TRACE_REPLAY",
                               semantic_losses=[])
        assert passes_serving_golden_gate(p) is False

    def test_real_simulation_with_losses_cannot_pass(self):
        p = serving_provenance(engine="llmservingsim",
                               network_backend="booksim2",
                               network_mode="REAL_SIMULATION",
                               semantic_losses=["pp_stage_boundaries"])
        assert passes_serving_golden_gate(p) is False

    def test_real_simulation_without_losses_passes(self):
        p = serving_provenance(engine="llmservingsim",
                               network_backend="booksim2",
                               network_mode="REAL_SIMULATION",
                               semantic_losses=[])
        assert passes_serving_golden_gate(p) is True

    def test_modes_are_exactly_two(self):
        assert set(NETWORK_MODES) == {"REAL_SIMULATION", "TRACE_REPLAY"}
