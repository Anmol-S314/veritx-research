"""Checks: compare the canonical run against independent authorities.

Every check carries an explicit AUTHORITY CLASS mapped to an independence
CATEGORY, so a report can never present a same-engine comparison as if it
were independent. Categories (weakest to strongest evidence):

    independent_oracle              arithmetic from first principles
    independent_execution_engine    a genuinely different engine
    calibrated_cross_engine         a different engine tuned to match
    semi_independent_shared_engine  a different configuration of one engine
    engine_qualification            the engine runs at all (liveness)
    integration_gate                the product consumed its own output
    refusal_gate                    a corruption is refused
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .oracle import graph_conformance, ring_allreduce_oracle

EXACT = "exact"
MISMATCH = "mismatch"
UNSUPPORTED = "unsupported"

#: authority_class -> independence category
TAXONOMY = {
    "hand_calculated": "independent_oracle",
    "monotonicity": "independent_oracle",
    "ring_oracle": "independent_oracle",
    "rtl_execution": "independent_execution_engine",
    "rtl_calibrated": "calibrated_cross_engine",
    "standalone_booksim": "semi_independent_shared_engine",
    "trace_conservation": "integration_gate",
    "astra": "engine_qualification",
    "ramulator": "engine_qualification",
    "rtl_selfcheck": "engine_qualification",
    "mutation": "refusal_gate",
}

#: what each category can and cannot falsify (for the report)
CATEGORY_MEANING = {
    "independent_oracle": "first-principles arithmetic; can falsify both "
                          "lowering and execution",
    "independent_execution_engine": "a different engine; can falsify the "
                                    "shared trace's execution, not the "
                                    "lowering that produced it",
    "calibrated_cross_engine": "a different engine tuned to match BookSim; "
                               "can detect drift, not independent physics",
    "semi_independent_shared_engine": "same engine, different configuration; "
                                      "can falsify the projector, not the "
                                      "engine",
    "engine_qualification": "liveness/qualification only; no scientific "
                            "parity claim",
    "integration_gate": "the product consumed its own output; no external "
                        "claim",
    "refusal_gate": "a corruption must be refused",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    authority_class: str
    detail: str
    verdict: str
    values: dict[str, Any] = field(default_factory=dict)
    #: a known, filed finding whose failure does not count as a new
    #: regression (e.g. F-0004 withdraws network-performance claims)
    quarantined: bool = False
    finding: str | None = None

    @property
    def independence(self) -> str:
        return TAXONOMY.get(self.authority_class, "unknown")


def _verdict(ok: bool) -> str:
    return EXACT if ok else MISMATCH


def _require_nonempty(checks: list[CheckResult], where: str) -> list[CheckResult]:
    """A check set is never empty: an empty all() is not a PASS."""
    if not checks:
        raise ValueError(
            f"{where} produced zero checks; an empty check set is not a PASS")
    return checks


def _logical_message_stats(logical) -> tuple[int, int]:
    messages = getattr(logical, "messages", None)
    if messages is None:
        raise ValueError("logical artifact exposes no messages")
    return len(messages), sum(int(m.payload_bytes) for m in messages)


def run_checks(*, spec, built, veritx_stats: dict, authority,
               authority_alt=None) -> list[CheckResult]:
    results: list[CheckResult] = []
    expected = spec.expected
    declared_packets = built.packets
    quarantine = bool(getattr(spec, "network_claims_quarantined", False))

    # ── trace execution conservation (integration gate) ────────────────
    # The authority consumes the SAME trace VERITX produced, so this proves
    # the engine consumed the stimulus; it does NOT prove the stimulus is
    # the right one. That is the oracle check below.
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
            name="trace_execution_conservation",
            authority_class="trace_conservation",
            detail="; ".join(problems)
            or "the engine consumed exactly the produced trace",
            verdict=_verdict(not problems),
            values={"packets": declared_packets, "flits": built.flits,
                    "authority_injected_flits": authority.injected_flits,
                    "authority_accepted_flits": authority.accepted_flits}))

    # ── workload-lowering oracle (independent) ─────────────────────────
    # First-principles ring-ALLREDUCE arithmetic vs VERITX's lowering.
    if spec.workload.kind == "collective" \
            and spec.workload.collective_kind == "ALLREDUCE":
        problems = []
        try:
            oracle = ring_allreduce_oracle(
                ranks=spec.fabric.compute_tiles,
                payload_bytes=spec.workload.payload_bytes,
                flit_width_bits=spec.fabric.link_width)
            n_messages, total_bytes = _logical_message_stats(built.logical)
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult(
                name="workload_lowering_conservation",
                authority_class="ring_oracle",
                detail=f"oracle unavailable: {type(exc).__name__}: {exc}",
                verdict=UNSUPPORTED))
        else:
            if n_messages != oracle.messages:
                problems.append(
                    f"messages {n_messages} != ring oracle "
                    f"{oracle.messages} (=2k(k-1))")
            if total_bytes != oracle.total_bytes:
                problems.append(
                    f"bytes {total_bytes} != ring oracle "
                    f"{oracle.total_bytes} (=2(k-1)B)")
            if built.flits != oracle.total_flits:
                problems.append(
                    f"flits {built.flits} != oracle {oracle.total_flits}")
            if built.packets != oracle.total_packets:
                problems.append(
                    f"packets {built.packets} != oracle "
                    f"{oracle.total_packets}")
            results.append(CheckResult(
                name="workload_lowering_conservation",
                authority_class="ring_oracle",
                detail="; ".join(problems)
                or ("lowering matches ring ALLREDUCE arithmetic "
                    f"(messages={oracle.messages}, bytes={oracle.total_bytes}, "
                    f"flits={oracle.total_flits}, "
                    f"packets={oracle.total_packets})"),
                verdict=_verdict(not problems),
                values=oracle.as_dict()))

        # ── communication-graph conformance (independent) ──────────────
        # The counts above cannot see WHICH ranks talk. Ring ALLREDUCE
        # moves data only between logical neighbours; a schedule that uses
        # every pair is a different algorithm (F-0004).
        try:
            from collections import Counter
            observed = Counter((m.src_rank, m.dst_rank)
                               for m in built.logical.messages)
            conf = graph_conformance(spec.fabric.compute_tiles, dict(observed))
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult(
                name="collective_graph_conformance",
                authority_class="ring_oracle",
                detail=f"conformance oracle unavailable: "
                       f"{type(exc).__name__}: {exc}",
                verdict=UNSUPPORTED))
        else:
            conforms = conf["conforms"]
            if conforms:
                detail = ("every pair is a ring neighbour pair with "
                          "multiplicity 2(k-1)")
            else:
                detail = (
                    f"{len(conf['extra_non_neighbour_pairs'])} non-neighbour "
                    f"pairs used (e.g. "
                    f"{sorted(conf['extra_non_neighbour_pairs'])[:3]}); the "
                    "communication graph is NOT a ring")
            results.append(CheckResult(
                name="collective_graph_conformance",
                authority_class="ring_oracle",
                detail=detail,
                verdict=_verdict(conforms),
                values=conf,
                quarantined=(not conforms and quarantine),
                finding=(None if conforms else "F-0004")))

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
            values={"packets": built.packets, "flits": built.flits,
                    "packets_provenance": expected.provenance("packets"),
                    "flits_provenance": expected.provenance("flits")}))

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
            # BookSim's Flit::hops counts the destination ejection, so its
            # reported hop average is router-to-router hops + 1.
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
                    "route_hops_provenance":
                        expected.provenance("route_hops"),
                    "canonical_hops_avg": built.canonical_hops_avg,
                    "authority_hops_avg": authority.hops_avg,
                    "authority_expected": (expected.route_hops + 1
                                           if expected.route_hops is not None
                                           else None)}))

    # ── standalone parity (same engine, different config) ──────────────
    if "standalone_parity" in spec.checks:
        v = veritx_stats["completion_cycles"]
        a = authority.completion_cycles
        ok = v == a
        results.append(CheckResult(
            name="standalone_parity", authority_class="standalone_booksim",
            detail=(f"VERITX completion {v} == authority {a}" if ok else
                    f"VERITX completion {v} != authority {a}"),
            verdict=_verdict(ok),
            quarantined=quarantine, finding=("F-0004" if quarantine else None),
            values={"veritx_completion": v, "authority_completion": a,
                    "veritx_window": veritx_stats.get("sample_window_cycles"),
                    "authority_window": authority.sample_window_cycles}))

    # ── window invariance ──────────────────────────────────────────────
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
            quarantined=quarantine, finding=("F-0004" if quarantine else None),
            values={"completion": v, "windows": windows}))

    return _require_nonempty(results, "run_checks")


def monotonicity_check(spec, points: list[dict]) -> CheckResult:
    """Layer 4: the swept quantity must move in the physically known way."""
    sweep = spec.sweep
    if sweep is None:
        raise ValueError("monotonicity_check requires a sweep spec")
    if len(points) < 2:
        raise ValueError("monotonicity needs at least two points")
    problems: list[str] = []
    for (a, b) in zip(points, points[1:]):
        qa, qb = a["quantity"], b["quantity"]
        if sweep.direction == "non_increasing" and qb > qa:
            problems.append(
                f"{sweep.param} {a['value']}->{b['value']}: "
                f"{sweep.quantity} increased {qa}->{qb} (must not increase)")
        elif sweep.direction == "non_decreasing" and qb < qa:
            problems.append(
                f"{sweep.param} {a['value']}->{b['value']}: "
                f"{sweep.quantity} decreased {qa}->{qb} (must not decrease)")
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
    """RTL (a different engine) executing the canonical trace.

    Two claims are made and never conflated:

      rtl_execution_conservation   INDEPENDENT execution engine: the RTL
                                   injects and ejects exactly the trace
                                   VERITX produced.
      rtl_calibrated_hop_equivalent / rtl_completion
                                   CALIBRATED cross-engine: the RTL's
                                   latency was tuned to the BookSim cycle
                                   model, so this detects drift, not
                                   independent physics. It does NOT
                                   observe the route (see below).
    """
    results: list[CheckResult] = []
    expected = spec.expected
    quarantine = bool(getattr(spec, "network_claims_quarantined", False))

    if not rtl.packets:
        results.append(CheckResult(
            name="rtl_execution_conservation",
            authority_class="rtl_execution",
            detail="RTL ejected nothing; refusing a vacuous pass",
            verdict=MISMATCH))
        return results

    problems = []
    if rtl.injected_flits != built.flits:
        problems.append(
            f"RTL injected {rtl.injected_flits} flits != canonical "
            f"{built.flits}")
    if rtl.ejected_flits != built.flits:
        problems.append(
            f"RTL ejected {rtl.ejected_flits} flits != canonical "
            f"{built.flits}")
    if rtl.flit_lines != built.flits:
        problems.append(
            f"RTL dump carries {rtl.flit_lines} ejected flits != canonical "
            f"{built.flits}")
    results.append(CheckResult(
        name="rtl_execution_conservation", authority_class="rtl_execution",
        detail="; ".join(problems)
        or "the RTL injected and ejected exactly the produced trace",
        verdict=_verdict(not problems),
        values={"rtl_injected_flits": rtl.injected_flits,
                "rtl_ejected_flits": rtl.ejected_flits,
                "rtl_dump_flits": rtl.flit_lines,
                "canonical_flits": built.flits}))

    if expected.route_hops is not None:
        # HONEST LABEL: the RTL dump carries latency, not a route. Hops are
        # INFERRED by inverting the calibrated law latency = 7 + 5*hop, so
        # this is a hop-equivalent, not an observed route. A different
        # equal-length route would pass. Genuine route identity needs RTL
        # instrumentation to dump (router, output port, next router).
        problems = []
        values = {"hand_router_hops": expected.route_hops,
                  "route_hops_provenance": expected.provenance("route_hops")}
        for p in rtl.packets:
            if p.hops is None or p.hops != expected.route_hops:
                problems.append(
                    f"RTL calibrated hop-equivalent {p.hops} != hand "
                    f"{expected.route_hops}")
                break
        values["rtl_hop_equivalents"] = sorted(
            {p.hops for p in rtl.packets})
        results.append(CheckResult(
            name="rtl_calibrated_hop_equivalent",
            authority_class="rtl_calibrated",
            detail="; ".join(problems)
            or (f"every RTL flit's calibrated hop-equivalent is "
                f"{expected.route_hops} (path LENGTH, not identity)"),
            verdict=_verdict(not problems),
            quarantined=quarantine, finding=("F-0004" if quarantine else None),
            values=values))

    problems = []
    v = veritx_stats["completion_cycles"]
    rtl_completion = rtl.completion_cycles
    tolerance = expected.rtl_completion_tolerance
    if tolerance == 0:
        if rtl_completion != v:
            problems.append(
                f"RTL completion {rtl_completion} != canonical "
                f"completion {v}")
    else:
        delta = rtl_completion - v
        if abs(delta) > tolerance:
            problems.append(
                f"|RTL {rtl_completion} - canonical {v}| = {abs(delta)} "
                f"exceeds tolerance {tolerance}")
    if tolerance == 0:
        detail = (f"RTL completion {rtl_completion} == canonical "
                  f"completion {v}")
    else:
        detail = (f"RTL completion {rtl_completion} vs canonical {v} "
                  f"(delta {rtl_completion - v:+d}, tolerance "
                  f"+/-{tolerance})")
    results.append(CheckResult(
        name="rtl_completion", authority_class="rtl_calibrated",
        detail="; ".join(problems) or detail,
        verdict=_verdict(not problems),
        quarantined=quarantine, finding=("F-0004" if quarantine else None),
        values={"veritx_completion": v, "rtl_completion": rtl_completion,
                "tolerance": tolerance, "delta": rtl_completion - v}))

    return _require_nonempty(results, "run_rtl_checks")
