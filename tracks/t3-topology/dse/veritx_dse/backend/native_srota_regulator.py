"""Opt-in native simulator accounting experiment, NOT backend qualification.

Uses native full buckets, rate-zero BYPASS, reserve/spend/end-step refund.
Never compares native timing with ABSTRACT_LOCAL_ISLAND_V1. Exact replay is
bounded to dyadic rates/bursts representable without floating-point rounding.
"""
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import re
import subprocess

from veritx_dse.core.artifact import content_id
from veritx_dse.backend.booksim_projection import (
    PreparedBookSimInput, prepare_booksim_input, trace_class_map, parse_config_values)
from veritx_dse.backend.booksim_execution import parse_booksim_stats, assert_execution_gate

PROFILE = "NATIVE_SROTA_REGULATOR_DIAGNOSTIC_V1"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class NativeRegulatorExperiment:
    prepared: PreparedBookSimInput
    classes: tuple[str, ...]
    rates: tuple[Fraction, ...]
    burst: int
    bypass: bool
    parent_prepared_id: str
    arrival_cycles: tuple[int, ...]
    horizon: int
    sidebuf_depth: int

    def identity_dict(self):
        return {"profile": PROFILE, "prepared_id": self.prepared.prepared_id(),
                "parent_prepared_id": self.parent_prepared_id,
                "class_rank": [[c, i] for i, c in enumerate(self.classes)],
                "rates": [[r.numerator, r.denominator] for r in self.rates],
                "burst": self.burst, "bypass": self.bypass,
                "arrival_cycles": list(self.arrival_cycles), "horizon": self.horizon,
                "sidebuf_depth": self.sidebuf_depth,
                "schedule_scope": "EXPLICIT_RETIMED_DIAGNOSTIC_NOT_ORIGINAL_TIMING",
                "semantics": "FULL_REFILL_RESERVE_SPEND_END_STEP_REFUND_ZERO_BYPASS",
                "qualification": False}

    def identity(self):
        return content_id(PROFILE, self.identity_dict())


def prepare_native_regulator(parents, *, rates, burst, seed, bypass, arrival_cycles, horizon, sidebuf_depth):
    """Explicit simulator-owned overlay; canonical parents are not modified."""
    _require(type(seed) is int and seed >= 0 and type(bypass) is bool, "explicit seed/bypass required")
    _require(type(burst) is int and 1 <= burst <= 65536, "burst must be integer 1..65536")
    _require(type(sidebuf_depth) is int and 1 <= sidebuf_depth <= 16, "explicit simulator sidebuffer depth 1..16 required")
    classes = trace_class_map(parents.physical_traffic)
    _require(set(rates) == set(classes), "complete explicit canonical class rate binding required")
    values = tuple(rates[c] for c in classes)
    for rate in values:
        _require(type(rate) is Fraction and 0 < rate <= 1 and
                 rate.denominator <= 65536 and rate.denominator & (rate.denominator - 1) == 0,
                 "rates must be positive exact dyadic Fraction <=1, denominator<=65536")
    prepared = prepare_booksim_input(parents, seed=seed)
    config = parse_config_values(prepared.config_text)
    _require(config.get("topology") == "srota" and config.get("srota_router") == "sidebuf"
             and config.get("subnets") == "1" and int(config.get("srota_island_col_map", "0")) > 0,
             "requires single Plane D sidebuf with explicit islands")
    _require(config.get("srota_deflect", "0") == "0", "deflection unsupported")
    _require(config.get("srota_path_en") == "3" and config.get("srota_isl_route") == "colfirst",
             "diagnostic envelope requires direct row/column shapes and island column-first, no Valiant")
    rows = [tuple(map(int, row.split())) for row in prepared.trace_text.splitlines() if row.strip()]
    _require(rows and all(len(row) == 5 and row[4] == 1 for row in rows), "single-flit nonempty trace required")
    _require(type(horizon) is int and 1 <= horizon <= 1000000, "finite horizon 1..1000000 required")
    _require(type(arrival_cycles) is tuple and len(arrival_cycles) == len(rows) and
             all(type(t) is int and 0 <= t < horizon for t in arrival_cycles) and
             tuple(sorted(arrival_cycles)) == arrival_cycles,
             "explicit nondecreasing exact arrival cycle per canonical packet required")
    trace = "".join(" ".join(map(str, (cycle, *row[1:]))) + "\n"
                    for cycle, row in zip(arrival_cycles, rows))
    _require({row[2] for row in rows} == set(range(len(classes))), "trace class coverage mismatch")
    # Three regulator knobs and instrumentation have experiment-owned read
    # closure. Existing canonical profile defaults/audit remain unchanged.
    overlay = {"srota_isl_rate": "{" + ",".join("0" if bypass else str(float(r)) for r in values) + "}",
               "srota_isl_burst": str(burst), "srota_isl_class": "class",
               "srota_diagnostic_ledger": "1", "srota_diagnostic_max_cycles": str(horizon),
               "srota_sb_depth": str(sidebuf_depth), "srota_sb_watermark": str(sidebuf_depth - 1),
               "srota_deflect": "0", "classes": str(len(classes)),
               "speculative": "1", "sw_allocator": "islip", "vc_allocator": "islip",
               "alloc_iters": "1", "sw_alloc_delay": "1", "vc_alloc_delay": "1",
               "routing_delay": "1", "credit_delay": "1", "st_prepare_delay": "0",
               "st_final_delay": "1", "input_speedup": "1", "output_speedup": "1",
               "internal_speedup": "1.0", "hold_switch_for_packet": "0",
               "sample_period": str(min(horizon, prepared.sample_period)),
               "max_samples": "1", "warmup_periods": "0"}
    text = prepared.config_text
    for name, value in overlay.items():
        text = re.sub(r"(?m)^" + re.escape(name) + r"\s*=.*?;\s*$", "", text)
        text += f"\n{name} = {value};\n"
    return NativeRegulatorExperiment(replace(prepared, config_text=text, trace_text=trace), classes, values,
                                     burst, bypass, prepared.prepared_id(), arrival_cycles, horizon, sidebuf_depth)


def replay_native_ledger(text, *, rates, burst, depth, router_count, horizon=None):
    """Strict ordered per-router token/hold/sidebuffer/credit ledger.

    Returns accounting checks, not independent fabric timing predictions.
    Missing begin/end, sequence gaps, unknown/malformed events fail closed.
    """
    routers = {}
    counts = {}
    for line in text.splitlines():
        if not line.startswith("SrotaLedger"):
            continue
        parts = line.split()
        _require(len(parts) == 12 and parts[0] == "SrotaLedger", "malformed ledger row")
        try:
            rid, seq, cycle = map(int, parts[1:4]); event = parts[4]
            q, fid, slot = map(int, parts[5:8])
            # Native precision-17 output round-trips exact double values;
            # decimal string itself need not be an exact dyadic spelling.
            before, after = (Fraction.from_float(float(t)) for t in parts[8:10])
            dt, occ = map(int, parts[10:12])
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            raise ValueError("nonfinite/malformed ledger value") from exc
        _require(0 <= rid < router_count and cycle >= 0 and 0 <= occ <= depth and
                 (horizon is None or cycle < horizon), "router/time/occupancy bound")
        _require(event == "refill" or dt == 0, "unexpected non-refill delta")
        if event not in ("begin", "init", "refill", "reserve", "refund", "spend", "defer", "end"):
            _require(before == 0 and after == 0, "unexpected non-token event balance")
        if event == "begin":
            _require(rid not in routers and seq == 0 and before == burst and after == depth and q in (0, 1), "bad/duplicate begin")
            routers[rid] = dict(seq=-1, cycle=cycle, island=bool(q), tokens={}, holds={}, sb={},
                                credits=set(), departed=set(), ended=False, refill={}, refund_cycle=None,
                                pending_credit=None, pending_depart=None, step=False,
                                refund_started=False, activity=False, arrived={}, granted={},
                                deferrals={}, spent={}, depart_kind=None, step_cycle=None,
                                step_refills=set())
        _require(rid in routers, "missing router begin")
        r = routers[rid]
        _require(not r["ended"] and seq == r["seq"] + 1 and cycle >= r["cycle"], "ledger sequence/time/end mismatch")
        if r["pending_credit"] is not None:
            _require(event == "credit" and (fid, slot) == r["pending_credit"], "capture requires immediate unique early credit")
        if r["pending_depart"] is not None:
            _require(event in ("depart", "depart_buffered") and (fid, slot) == r["pending_depart"], "credit/drain requires departure")
        r["seq"], r["cycle"] = seq, cycle
        counts[event] = counts.get(event, 0) + 1
        if r["step"]:
            _require(cycle == r["step_cycle"], "cycle changed within native internal step")
        if event not in ("begin", "init", "end", "step_begin"):
            _require(r["step"], "event outside native internal step")
        if r["refund_started"]:
            _require(event in ("refund", "step_end"), "event after end-step refund")
        if event not in ("begin", "init", "step_begin", "refill"):
            r["activity"] = True
        if event == "begin":
            pass
        elif event == "init":
            _require(q not in r["tokens"] and 0 <= q < len(rates) and before == rates[q] and after == burst, "init class/rate mismatch")
            r["tokens"][q] = after
        elif event == "step_begin":
            _require(not r["step"] and not r["holds"], "overlapping native steps")
            _require(r["step_cycle"] is None or cycle > r["step_cycle"],
                     "native step cycles must strictly advance (internal_speedup=1)")
            r["step_cycle"], r["step_refills"] = cycle, set()
            r["step"], r["refund_started"], r["activity"] = True, False, False
        elif event in ("arrive", "grant"):
            _require(r["island"] and 0 <= q < len(rates) and fid >= 0 and slot >= 0, "invalid island event class")
            if event == "arrive":
                _require(fid not in r["arrived"], "duplicate island arrival")
                r["arrived"][fid] = (q, slot)
            else:
                _require(r["arrived"].get(fid) == (q, slot) and fid not in r["granted"], "grant without unique matching arrival")
                _require(rates[q] == 0 or r["spent"].get(fid) == (q, slot, cycle), "regulated grant lacks same-step token spend")
                r["granted"][fid] = (q, slot)
        elif event in ("refill", "reserve", "refund", "spend", "defer"):
            _require(r["island"] and q in r["tokens"] and rates[q] > 0 and before == r["tokens"][q], "token prestate/class mismatch")
            expected = before
            if event == "refill":
                _require(not r["activity"] and q not in r["step_refills"] and dt > 0 and
                         cycle - r["refill"].get(q, 0) == dt and not r["holds"], "refill order/delta mismatch")
                r["refill"][q] = cycle
                r["step_refills"].add(q)
                expected = min(burst, before + rates[q] * dt)
            elif event == "reserve":
                _require(before >= 1 and fid >= 0 and slot >= 0 and fid not in r["holds"], "invalid reservation")
                expected = before - 1
                r["holds"][fid] = (q, slot, cycle)
            elif event in ("refund", "spend"):
                _require(r["holds"].pop(fid, None) == (q, slot, cycle), "missing/wrong/same-step hold")
                if event == "refund":
                    r["refund_started"] = True
                    expected = min(burst, before + 1)
                else:
                    _require(fid not in r["spent"], "duplicate token spend")
                    r["spent"][fid] = (q, slot, cycle)
            else:
                _require(before < 1 and fid >= 0 and slot >= 0, "defer with available token")
                r["deferrals"][q] = r["deferrals"].get(q, 0) + 1
            _require(after == expected and 0 <= after <= burst, "token balance/cap mismatch")
            r["tokens"][q] = after
        elif event == "allocation_loss":
            _require(fid >= 0 and slot >= 0, "invalid allocation loss identity")
        elif event == "capture":
            _require(slot >= 0 and fid >= 0 and slot not in r["sb"] and len(r["sb"]) < depth, "sidebuffer capture bound/FIFO")
            r["sb"][slot] = fid
            r["pending_credit"] = (fid, slot)
        elif event == "credit":
            _require(fid >= 0 and slot >= 0 and fid not in r["credits"], "duplicate upstream credit")
            r["credits"].add(fid)
            if r["pending_credit"] is not None:
                r["pending_credit"] = None
            else:
                _require(slot not in r["sb"], "second credit on buffered departure")
                r["pending_depart"] = (fid, slot)
                r["depart_kind"] = "depart"
        elif event == "drain":
            _require(r["sb"].pop(slot, None) == fid and fid in r["credits"], "drain without capture/credit")
            r["pending_depart"] = (fid, slot)
            r["depart_kind"] = "depart_buffered"
        elif event in ("depart", "depart_buffered"):
            _require(event == r["depart_kind"] and fid in r["credits"] and fid not in r["departed"] and r["pending_depart"] == (fid, slot), "departure credit/conservation mismatch")
            r["pending_depart"] = None
            r["departed"].add(fid)
        elif event == "full":
            _require(len(r["sb"]) == depth and fid not in r["credits"], "full rejection without full buffer")
        elif event in ("step_end", "end"):
            _require(not r["holds"] and set(r["tokens"]) == set(range(len(rates))), "unrefunded hold or missing class initialization")
            if event == "step_end":
                expected_refills = {q for q, rate in enumerate(rates)
                                    if cycle > 0 and r["island"] and rate > 0}
                _require(r["step_refills"] == expected_refills, "missing per-step refill")
                r["step"], r["refund_started"] = False, False
            if event == "end":
                _require(not r["step"] and before == 0 and after == 0 and not r["sb"] and
                         r["credits"] == r["departed"] and r["arrived"] == r["granted"] and
                         set(r["spent"]) == {fid for fid, (q, _) in r["granted"].items() if rates[q] > 0} and
                         set(r["granted"]) <= r["departed"], "undrained end/credit/island imbalance")
                r["ended"] = True
        else:
            raise ValueError("unknown ledger event")
        _require(occ == len(r["sb"]), "sidebuffer occupancy mismatch")
    _require(set(routers) == set(range(router_count)) and all(r["ended"] for r in routers.values()), "missing/truncated native ledger")
    _require(counts.get("depart", 0) + counts.get("depart_buffered", 0) > 0, "vacuous native ledger")
    counts["classes"] = {q: {"arrive": sum(sum(cl == q for cl, _ in r["arrived"].values()) for r in routers.values()),
                              "grant": sum(sum(cl == q for cl, _ in r["granted"].values()) for r in routers.values()),
                              "defer_cycles": sum(r["deferrals"].get(q, 0) for r in routers.values())}
                         for q in range(len(rates))}
    return counts


def parse_native_srota_stats(text):
    """Exact typed native aggregate rows; malformed/duplicate rows refuse."""
    side_keys = ("routers", "storage_flits", "alloc_loss", "sb_fill", "sb_drain",
                 "sb_full_reject", "sb_peak", "sb_mean_occ_per_router",
                 "sb_full_router_cycles", "sb_watermark_router_cycles", "router_cycles")
    island_keys = ("class", "arrive", "grant", "deferred_flits", "defer_flit_cycles")
    side = None
    islands = []
    for line in text.splitlines():
        if not line.startswith("SrotaStats:"):
            continue
        if line.startswith("SrotaStats: sidebuf "):
            _require(side is None and line.endswith("  (whole run, incl. warm-up)"),
                     "duplicate/malformed sidebuffer aggregate")
            pairs = line[len("SrotaStats: sidebuf "):-len("  (whole run, incl. warm-up)")].split()
            keys = side_keys
        elif line.startswith("SrotaStats: island "):
            pairs = line[len("SrotaStats: island "):].split()
            keys = island_keys
        else:
            raise ValueError("unknown native diagnostic telemetry row")
        _require(len(pairs) == len(keys) and all(pair.startswith(key + "=") for pair, key in zip(pairs, keys)),
                 "malformed native diagnostic telemetry fields")
        values = {}
        for key, pair in zip(keys, pairs):
            token = pair.split("=", 1)[1]
            if key == "sb_mean_occ_per_router":
                try:
                    value = float(token)
                    _require(0 <= value < float("inf"), "nonfinite occupancy")
                except ValueError as exc:
                    raise ValueError("malformed occupancy telemetry") from exc
            else:
                _require(re.fullmatch(r"0|[1-9][0-9]*", token) is not None, "malformed integer native telemetry")
                value = int(token)
            values[key] = value
        if keys == side_keys:
            side = values
        else:
            _require(values["class"] not in {row[0] for row in islands}, "duplicate island class telemetry")
            islands.append(tuple(values[key] for key in keys))
    _require(side is not None and islands, "missing sidebuffer/island telemetry")
    return {"sidebuf": side, "island_rows": islands}


def native_source_inventory(source_root):
    """Actual standalone producer inputs; a dirty snapshot is NOT a checkout."""
    root = Path(source_root).resolve()
    files = []
    for path in sorted(root.rglob("*")):
        _require(not (path.is_symlink() and path.is_dir()), "source directory symlinks unsupported")
        if path.is_file() and (path.suffix in (".cpp", ".hpp", ".l", ".y") or
                               path.name in ("Makefile", "rng.c", "rng-double.c")):
            _require(not path.is_symlink(), "source input symlinks unsupported")
            files.append([str(path.relative_to(root)), _sha(path.read_bytes()), path.stat().st_size])
    _require(files and any(row[0] == "routers/srota_router_d.cpp" for row in files), "native source inputs missing")
    return {"state": "DIAGNOSTIC_SOURCE_CONTENT_ONLY_UNQUALIFIED", "files": files}


def run_native_regulator(experiment, *, parents, binary, source_root, source_inventory, run_dir, timeout=120):
    """Execute an unpinned externally built producer and bind actual bytes."""
    _require(type(timeout) is int and 1 <= timeout <= 900, "finite timeout required")
    validate_native_experiment(experiment, parents)
    binary = Path(binary).resolve()
    inventory = Path(source_inventory).read_bytes()
    _require(json.loads(inventory) == native_source_inventory(source_root), "source inventory drift/mismatch")
    before = _sha(binary.read_bytes())
    directory = Path(run_dir)
    _require(not directory.exists(), "run directory must be fresh")
    experiment.prepared.prepare_directory(directory)
    _validate_retained_prepared_inputs(experiment, directory)
    outcome = subprocess.run([str(binary), "config.cfg"], cwd=directory,
                             capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    (directory / "stdout.txt").write_text(outcome.stdout)
    (directory / "stderr.txt").write_text(outcome.stderr)
    _require("SrotaDiagnostic: BOUNDED_INCOMPLETE" not in outcome.stdout,
             "BOUNDED_INCOMPLETE: native horizon reached; no PASS evidence")
    _require(outcome.returncode == 0 and _sha(binary.read_bytes()) == before, "native failure/binary drift")
    _require(json.loads(inventory) == native_source_inventory(source_root), "source drift during native run")
    _validate_retained_prepared_inputs(experiment, directory)
    evidence = _native_evidence(experiment, outcome.stdout, outcome.stderr, before, inventory)
    evidence["source_provenance"] = native_source_provenance(source_root)
    evidence["evidence_id"] = content_id(PROFILE + "/evidence", {k: v for k, v in evidence.items() if k != "evidence_id"})
    (directory / "diagnostic-evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True))
    return evidence


def native_source_provenance(source_root):
    """Honest scoped git facts, never infer unknown status as clean."""
    root = Path(source_root).resolve()
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "."], capture_output=True, text=True)
    return {"revision": revision.stdout.strip() if revision.returncode == 0 else None,
            "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
            "scope": str(root), "pinned": False, "qualification": False}


def validate_native_experiment(experiment, parents):
    expected = prepare_native_regulator(parents, rates=dict(zip(experiment.classes, experiment.rates)),
        burst=experiment.burst, seed=experiment.prepared.seed, bypass=experiment.bypass,
        arrival_cycles=experiment.arrival_cycles, horizon=experiment.horizon, sidebuf_depth=experiment.sidebuf_depth)
    _require(json.dumps(expected.identity_dict(), sort_keys=True) ==
             json.dumps(experiment.identity_dict(), sort_keys=True) and
             expected.prepared.files() == experiment.prepared.files(),
             "experiment differs from actual canonical parents/explicit overlay")


def _native_evidence(experiment, stdout, stderr, before, inventory):
    _require("SrotaDiagnostic: BOUNDED_INCOMPLETE" not in stdout, "BOUNDED_INCOMPLETE ledger cannot pass")
    stats = parse_booksim_stats(stdout, stderr)
    _require(stats["completion_cycles"] <= experiment.horizon, "completion exceeds diagnostic horizon")
    assert_execution_gate(stats, expected_packets=experiment.prepared.expected_packets,
                          expected_flits=experiment.prepared.expected_flits, require_conservation=True)
    config = parse_config_values(experiment.prepared.config_text)
    rates = tuple(Fraction(0) if experiment.bypass else r for r in experiment.rates)
    counts = replay_native_ledger(stdout, rates=rates, burst=experiment.burst,
                                  depth=int(config["srota_sb_depth"]), router_count=experiment.prepared.router_count,
                                  horizon=experiment.horizon)
    telemetry = parse_native_srota_stats(stdout)
    sb = telemetry["sidebuf"]
    fill, drain, peak = sb["sb_fill"], sb["sb_drain"], sb["sb_peak"]
    _require(sb["alloc_loss"] == counts.get("allocation_loss", 0) and
             sb["sb_full_reject"] == counts.get("full", 0), "allocation-loss/backpressure telemetry mismatch")
    # Fully expressed direct-shape SROTA has one hop per unequal coordinate,
    # plus each source/local ejection switch. This checks coverage independently
    # of the event stream, not merely credits against logged departures.
    k, c = int(config["k"]), int(config["c"])
    expected_departures = 0
    for row in experiment.prepared.trace_text.splitlines():
        _, src, _, dst, size = map(int, row.split())
        a, b = src // c, dst // c
        expected_departures += size * (1 + int(a % k != b % k) + int(a // k != b // k))
    _require(counts.get("depart", 0) + counts.get("depart_buffered", 0) == expected_departures,
             "geometry-bound switch/credit event coverage mismatch")
    _require(fill == counts.get("capture", 0) == drain == counts.get("drain", 0)
             and peak <= int(config["srota_sb_depth"]), "aggregate/ledger sidebuffer mismatch")
    rows = telemetry["island_rows"]
    _require(rows and len({row[0] for row in rows}) == len(rows) and all(a == g and int(a) > 0 for _, a, g, _, _ in rows), "missing/duplicate/incomplete island accounting")
    _require(all(0 <= int(q) < len(rates) for q, *_ in rows), "foreign class accounting")
    _require(sum(int(cyc) for *_, cyc in rows) == counts.get("defer", 0), "deferral telemetry mismatch")
    for q, a, g, _, cyc in rows:
        _require(counts["classes"][int(q)] == {"arrive": int(a), "grant": int(g), "defer_cycles": int(cyc)},
                 "per-class island aggregate/ledger mismatch")
    _require({int(row[0]) for row in rows} == {q for q, c in counts["classes"].items() if c["arrive"]},
             "missing nonzero class telemetry")
    if not experiment.bypass:
        _require(counts.get("defer", 0) > 0 and counts.get("spend", 0) > 0, "regulated experiment is vacuous")
    evidence = {"profile": PROFILE, "experiment": experiment.identity_dict(),
                "experiment_id": experiment.identity(), "binary_sha256": before,
                "source_inventory_sha256": _sha(inventory), "stdout_sha256": _sha(stdout.encode()),
                "stderr_sha256": _sha(stderr.encode()), "counts": counts, "stats": stats,
                "island_rows": rows, "state": "DIAGNOSTIC_LEDGER_CHECKED_UNQUALIFIED",
                "native_equivalence": False, "qualification": False}
    evidence["evidence_id"] = content_id(PROFILE + "/evidence", evidence)
    return evidence


def _validate_retained_prepared_inputs(experiment, directory):
    """The prepared identity binds every executed input byte, not only logs."""
    for name, expected in experiment.prepared.files().items():
        path = directory / name
        _require(path.is_file() and path.read_bytes() == expected,
                 f"retained prepared input missing or differs: {name}")


def load_native_regulator_evidence(value, experiment, *, parents, binary, source_root, source_inventory, run_dir):
    """Recompute log evidence against actual parents/source/binary; no rerun."""
    validate_native_experiment(experiment, parents)
    inventory = Path(source_inventory).read_bytes()
    _require(json.loads(inventory) == native_source_inventory(source_root), "source inventory mismatch")
    directory = Path(run_dir)
    _validate_retained_prepared_inputs(experiment, directory)
    expected = _native_evidence(experiment, (directory / "stdout.txt").read_text(),
                               (directory / "stderr.txt").read_text(), _sha(Path(binary).read_bytes()), inventory)
    expected["source_provenance"] = native_source_provenance(source_root)
    expected["evidence_id"] = content_id(PROFILE + "/evidence", {k: v for k, v in expected.items() if k != "evidence_id"})
    _require(json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True),
             "native diagnostic evidence differs from recomputed logs/parents/producer")
    return expected
