"""Checks: compare the canonical run against the independent authority.

Every check records its authority class and independence so a report can
never present a same-engine comparison as if it were independent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EXACT = "exact"
MISMATCH = "mismatch"
UNSUPPORTED = "unsupported"

#: authority class -> independence level
INDEPENDENCE = {
    "hand_calculated": "independent",
    "conservation": "independent",
    "monotonicity": "independent",
    "standalone_booksim": "semi_independent",
    "canonical_altrouting": "semi_independent",
    "rtl": "independent",
    "rtl_calibrated": "semi_independent",
    "astra": "independent",
    "ramulator": "independent",
    "hardware": "independent",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    authority_class: str
    detail: str
    verdict: str
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def independence(self) -> str:
        return INDEPENDENCE.get(self.authority_class, "unknown")


def _verdict(ok: bool) -> str:
    return EXACT if ok else MISMATCH


def run_checks(*, spec, built, veritx_stats: dict, authority,
               authority_alt=None) -> list[CheckResult]:
    results: list[CheckResult] = []
    expected = spec.expected
    declared_packets = built.packets

    # ── conservation (independent) ─────────────────────────────────────
    if "conservation" in spec.checks:
        problems: list[str] = []
        if veritx_stats["loaded_trace_packets"] != declared_packets:
            problems.append(
                f"VERITX loaded {veritx_stats['loaded_trace_packets']} != "
                f"declared {declared_packets}")
        injected = veritx_stats.get("injected_trace_packets")
        if injected is not None and injected != declared_packets:
            problems.append(
                f"VERITX injected {injected} != declared {declared_packets}")
        if authority.loaded_packets != declared_packets:
            problems.append(
                f"authority loaded {authority.loaded_packets} != declared "
                f"{declared_packets}")
        if authority.injected_flits is not None \
                and authority.accepted_flits is not None \
                and authority.injected_flits != authority.accepted_flits:
            problems.append(
                f"authority flits injected {authority.injected_flits} != "
                f"accepted {authority.accepted_flits}")
        if authority.injected_flits is not None \
                and authority.injected_flits != built.flits:
            problems.append(
                f"authority injected flits {authority.injected_flits} != "
                f"canonical flits {built.flits}")
        results.append(CheckResult(
            name="conservation", authority_class="conservation",
            detail="; ".join(problems) or "packets and flits close exactly",
            verdict=_verdict(not problems),
            values={"packets": declared_packets, "flits": built.flits,
                    "authority_injected_flits": authority.injected_flits,
                    "authority_accepted_flits": authority.accepted_flits}))

    # ── hand counts (independent) ──────────────────────────────────────
    if "hand_counts" in spec.checks and expected.packets is not None:
        problems = []
        if built.packets != expected.packets:
            problems.append(f"packets {built.packets} != {expected.packets}")
        if expected.flits is not None and built.flits != expected.flits:
            problems.append(f"flits {built.flits} != {expected.flits}")
        results.append(CheckResult(
            name="hand_counts", authority_class="hand_calculated",
            detail="; ".join(problems) or "packet/flit counts match by hand",
            verdict=_verdict(not problems),
            values={"packets": built.packets, "flits": built.flits}))

    # ── hand route (independent) ───────────────────────────────────────
    if "hand_route" in spec.checks:
        problems = []
        if expected.route_hops is None:
            problems.append("experiment declares no route_hops")
        elif built.canonical_hops_avg is None:
            problems.append("canonical hop count not derivable")
        else:
            if abs(built.canonical_hops_avg - expected.route_hops) > 1e-9:
                problems.append(
                    f"canonical router hops {built.canonical_hops_avg} != "
                    f"hand {expected.route_hops}")
            # BookSim's Flit::hops is incremented once per router
            # traversal, INCLUDING the destination ejection
            # (routers/iq_router.cpp), so its reported hop average is the
            # router-to-router count plus one. The corpus pins that exact
            # relationship rather than demanding equality.
            if authority.hops_avg is None:
                problems.append("authority reported no hops average")
            else:
                expected_authority = expected.route_hops + 1
                if abs(authority.hops_avg - expected_authority) > 1e-6:
                    problems.append(
                        f"authority hops {authority.hops_avg} != hand "
                        f"{expected.route_hops} + 1 (ejection accounting) = "
                        f"{expected_authority}")
        results.append(CheckResult(
            name="hand_route", authority_class="hand_calculated",
            detail="; ".join(problems)
            or ("router hops match hand arithmetic; authority = hand + 1 "
                "(destination ejection counted)"),
            verdict=_verdict(not problems),
            values={"hand_router_hops": expected.route_hops,
                    "canonical_hops_avg": built.canonical_hops_avg,
                    "authority_hops_avg": authority.hops_avg,
                    "authority_expected": (expected.route_hops + 1
                                           if expected.route_hops is not None
                                           else None)}))

    # ── standalone parity (semi-independent) ───────────────────────────
    if "standalone_parity" in spec.checks:
        v = veritx_stats["completion_cycles"]
        a = authority.completion_cycles
        ok = v == a
        results.append(CheckResult(
            name="standalone_parity", authority_class="standalone_booksim",
            detail=(f"VERITX completion {v} == authority {a}" if ok else
                    f"VERITX completion {v} != authority {a}"),
            verdict=_verdict(ok),
            values={"veritx_completion": v, "authority_completion": a,
                    "veritx_window": veritx_stats.get("sample_window_cycles"),
                    "authority_window": authority.sample_window_cycles}))

    # ── window invariance (semi-independent) ───────────────────────────
    if "window_invariance" in spec.checks:
        v = veritx_stats["completion_cycles"]
        problems = []
        windows = {"veritx": veritx_stats.get("sample_window_cycles"),
                   "authority": authority.sample_window_cycles}
        if v != authority.completion_cycles:
            problems.append(
                f"completion differs across windows: {v} vs "
                f"{authority.completion_cycles}")
        if authority_alt is not None:
            windows["authority_alt"] = authority_alt.sample_window_cycles
            if authority_alt.completion_cycles != authority.completion_cycles:
                problems.append(
                    f"authority completion moved with its window: "
                    f"{authority.completion_cycles} -> "
                    f"{authority_alt.completion_cycles}")
        for label, w in windows.items():
            if w is not None and v > w:
                problems.append(f"completion {v} exceeds {label} window {w}")
        results.append(CheckResult(
            name="window_invariance", authority_class="standalone_booksim",
            detail="; ".join(problems)
            or "completion invariant across independent windows",
            verdict=_verdict(not problems),
            values={"completion": v, "windows": windows}))

    return results


def monotonicity_check(spec, points: list[dict]) -> CheckResult:
    """Layer 4: the swept quantity must move in the physically known way.

    ``points`` is an ascending list of
    ``{"value", "quantity", "authority_quantity"}``. The direction is
    declared by the spec's sweep rule; a curve that moves the wrong way is
    a mismatch, not a curiosity.
    """
    sweep = spec.sweep
    if sweep is None:
        raise ValueError("monotonicity_check requires a sweep spec")
    problems: list[str] = []
    quantities = [p["quantity"] for p in points]
    pairs = list(zip(points, points[1:]))
    for (a, b) in pairs:
        qa, qb = a["quantity"], b["quantity"]
        if sweep.direction == "non_increasing" and qb > qa:
            problems.append(
                f"{sweep.param} {a['value']}->{b['value']}: "
                f"{sweep.quantity} increased {qa}->{qb} (must not increase)")
        elif sweep.direction == "non_decreasing" and qb < qa:
            problems.append(
                f"{sweep.param} {a['value']}->{b['value']}: "
                f"{sweep.quantity} decreased {qa}->{qb} (must not decrease)")
    # the authority must show the same direction
    authority_quantities = [p.get("authority_quantity") for p in points]
    if all(q is not None for q in authority_quantities):
        for (a, b) in zip(points, points[1:]):
            qa, qb = a["authority_quantity"], b["authority_quantity"]
            if sweep.direction == "non_increasing" and qb > qa:
                problems.append(
                    f"authority {sweep.quantity} increased {qa}->{qb} across "
                    f"{sweep.param} {a['value']}->{b['value']}")
            elif sweep.direction == "non_decreasing" and qb < qa:
                problems.append(
                    f"authority {sweep.quantity} decreased {qa}->{qb} across "
                    f"{sweep.param} {a['value']}->{b['value']}")
    return CheckResult(
        name="monotonicity", authority_class="monotonicity",
        detail="; ".join(problems)
        or (f"{sweep.quantity} is {sweep.direction} across "
            f"{sweep.param}={list(sweep.values)} for VERITX and authority"),
        verdict=_verdict(not problems),
        values={"param": sweep.param, "quantity": sweep.quantity,
                "direction": sweep.direction,
                "series": {str(p["value"]): p["quantity"] for p in points},
                "authority_series": {str(p["value"]): p.get(
                    "authority_quantity") for p in points}})


def run_rtl_checks(*, spec, built, veritx_stats: dict, rtl) -> list[CheckResult]:
    """Layer 3 with a different engine: T3 2D mesh RTL vs the canonical path.

    Conservation and route parity are independent; absolute latency is
    semi-independent because the testbench was calibrated to the BookSim
    cycle model.
    """
    results: list[CheckResult] = []
    expected = spec.expected

    problems = []
    if rtl.injected_packets != built.packets:
        problems.append(
            f"RTL injected {rtl.injected_packets} != canonical "
            f"packets {built.packets}")
    if rtl.ejected_packets != built.packets:
        problems.append(
            f"RTL ejected {rtl.ejected_packets} != canonical "
            f"packets {built.packets}")
    if rtl.ejected_flits != built.flits:
        problems.append(
            f"RTL ejected flits {rtl.ejected_flits} != canonical "
            f"flits {built.flits}")
    results.append(CheckResult(
        name="rtl_conservation", authority_class="rtl",
        detail="; ".join(problems) or "RTL injects and ejects the exact workload",
        verdict=_verdict(not problems),
        values={"rtl_injected_packets": rtl.injected_packets,
                "rtl_ejected_packets": rtl.ejected_packets,
                "rtl_ejected_flits": rtl.ejected_flits,
                "canonical_packets": built.packets,
                "canonical_flits": built.flits}))

    if expected.route_hops is not None:
        problems = []
        bad = [p for p in rtl.packets if p.hops != expected.route_hops]
        if bad:
            problems.append(
                f"{len(bad)}/{len(rtl.packets)} RTL packets routed "
                f"{bad[0].hops} hops, hand says {expected.route_hops}")
        results.append(CheckResult(
            name="rtl_route", authority_class="rtl",
            detail="; ".join(problems)
            or (f"every RTL packet routes {expected.route_hops} hops "
                "(matches hand Manhattan)"),
            verdict=_verdict(not problems),
            values={"hand_router_hops": expected.route_hops,
                    "rtl_hops": sorted({p.hops for p in rtl.packets})}))

        problems = []
        v = veritx_stats["completion_cycles"]
        rtl_latency = (max(p.latency for p in rtl.packets)
                       if rtl.packets else None)
        if rtl_latency != v:
            problems.append(
                f"RTL latency {rtl_latency} != canonical completion {v}")
        results.append(CheckResult(
            name="rtl_latency", authority_class="rtl_calibrated",
            detail="; ".join(problems)
            or (f"RTL latency {rtl_latency} == canonical completion {v} "
                "(tb calibrated to the BookSim cycle model)"),
            verdict=_verdict(not problems),
            values={"veritx_completion": v, "rtl_latency": rtl_latency,
                    "rtl_law": "7 + 5*hop"}))
    return results
