"""L2 Recommend objective module — implements the locked decisions.

F2 (LOCKED): latency-first with a HARD throughput constraint. A config must
sustain the offered workload injection rate without saturating; saturated
configs are rejected from the recommendation, not just ranked last.

F4 (LOCKED): in-house grid/Bayesian first. This module is the pluggable score
so a surrogate can slot in later (ArchGym deferred).
"""
from typing import List, Optional

from space import SimResult

SATURATION_MARGIN = 0.95


def is_saturated(result: SimResult, injection_rate: float) -> bool:
    if result.throughput is None:
        return False
    return result.throughput < SATURATION_MARGIN * injection_rate


def config_cost(result: SimResult) -> float:
    vcs = result.point.values.get("vcs", 4)
    vc_buf = result.point.values.get("vc_buf", 8)
    banks = result.point.values.get("banks", 4)
    return float(vcs * vc_buf * (banks / 4.0))


def objective_score(result: SimResult, injection_rate: float) -> Optional[float]:
    if not result.ok:
        return None
    if is_saturated(result, injection_rate):
        deficit = (SATURATION_MARGIN * injection_rate) - result.throughput
        return 1e9 + deficit * 1e6
    base = result.avg_latency
    if result.energy_pj is not None:
        base = base + result.energy_pj * 1e-6
    return base


def bottleneck_score(phase_latencies: dict, mode: str = "worst") -> Optional[float]:
    """Compute objective from per-phase latencies.
    
    Modes:
        worst:   max(phase_latencies) — optimize for bottleneck
        balanced: mean + 0.5 * std — penalize variance
        weighted: weighted average (equal weight for now)
    
    phase_latencies: dict of {phase_name: latency}
    Returns score (lower is better) or None if invalid.
    """
    valid = {k: v for k, v in phase_latencies.items() if v is not None and v < 1e9}
    if not valid:
        return None
    
    lats = list(valid.values())
    
    if mode == "worst":
        return max(lats)
    elif mode == "balanced":
        mean = sum(lats) / len(lats)
        std = (sum((l - mean) ** 2 for l in lats) / len(lats)) ** 0.5
        return mean + 0.5 * std
    elif mode == "weighted":
        return sum(lats) / len(lats)
    else:
        return max(lats)


def rank_f2(results: List[SimResult], injection_rate: float, lat_eps: float = 0.1) -> List[SimResult]:
    scored = []
    for r in results:
        ir = r.point.values.get("injection_rate", injection_rate)
        scored.append((objective_score(r, ir), r))

    def key(item):
        s, r = item
        if s is None:
            return (3, 0.0, 0.0)
        if s >= 1e9:
            return (2, s, 0.0)
        # feasible: primary = latency (F2), secondary = resource cost (axis-2 tie-break)
        return (0, round(r.avg_latency / lat_eps), config_cost(r))

    scored.sort(key=key)
    feasible = [r for s, r in scored if s is not None and s < 1e9]
    rejected = [r for s, r in scored if s is not None and s >= 1e9]
    failed = [r for s, r in scored if s is None]
    return feasible + rejected + failed
