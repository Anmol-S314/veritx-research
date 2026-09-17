"""veritx_dse.core.serving — serving-result identity (PR6 Slice B seam).

One concept: *how* a serving result was produced. A run that replays
trace durations exits 0 with plausible TTFT/TPOT but simulated no
network — so the execution mode rides with every serving result as
data, and the golden gate is a pure predicate over it.

Deliberately concrete: no Runner/Backend classes, no analytical
generalization (that is PR7's slice). Shared mechanics get extracted
only after slices B and C expose what actually repeats.
"""
from __future__ import annotations

from typing import Any

# PR6 §17.4: the only two execution modes a serving result may claim.
# REAL_SIMULATION = packets/flits contended in a network backend.
# TRACE_REPLAY   = recorded durations replayed, fabric untouched
#                  (downstream `--booksim-replay-only`, the default).
NETWORK_MODES = ("REAL_SIMULATION", "TRACE_REPLAY")


def serving_provenance(*, engine: str, network_backend: str,
                       network_mode: str,
                       semantic_losses: list[str]) -> dict[str, Any]:
    """Build the identity block for one serving result.

    Raises ValueError on an unknown mode and TypeError when
    semantic_losses is not a list — a loss must be declared to be
    visible, never smuggled in as a bare string or None.
    """
    if network_mode not in NETWORK_MODES:
        raise ValueError(
            f"unknown network_mode {network_mode!r} — must be one of "
            f"{NETWORK_MODES}. Execution mode is data, not prose.")
    if not isinstance(semantic_losses, list) or not all(
            isinstance(s, str) for s in semantic_losses):
        raise TypeError(
            "semantic_losses must be a list of strings "
            f"(got {semantic_losses!r})")
    return {
        "engine": engine,
        "network_backend": network_backend,
        "network_mode": network_mode,
        "semantic_losses": list(semantic_losses),
    }


def passes_serving_golden_gate(provenance: dict[str, Any]) -> bool:
    """PR6 golden gate (§17.8): real simulation AND zero semantic loss.

    Pure predicate so tests — not eyeballs — enforce it. A replay-only
    run fails here even with perfect metrics; so does a real run that
    discarded load-bearing semantics (e.g. pp_stage_boundaries).
    """
    return (provenance.get("network_mode") == "REAL_SIMULATION"
            and provenance.get("semantic_losses") == [])
