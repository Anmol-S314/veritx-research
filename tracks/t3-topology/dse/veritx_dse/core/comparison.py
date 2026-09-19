"""veritx_dse.core.comparison — scientific comparison gate (Phase 8).

Core principle: a comparison is valid only when every scientifically
relevant difference is either (1) controlled and equal, or (2) an
explicitly declared experimental variable. Undeclared material
differences fail closed. This module is the gate; it is deliberately
NOT a generic data-analysis framework (Phase 8 §16).

Three seams, each pure and unit-tested at:

  * fingerprint resolution — from immutable run manifests
    (``fingerprint_from_run``) or from legacy compare rows
    (``fingerprint_from_legacy_row``, which marks what it could NOT
    resolve instead of guessing);
  * ``evaluate_comparability`` — controlled-vs-variable verdict over a
    candidate set, including the fidelity policy (§5), metric
    capability (§7), and the semantic-loss ban (§9);
  * ``pareto_with_scope`` — dominance computed only over the comparable
    set, with every excluded candidate visible and the evaluated scope
    stated in the output (§8/§11).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .spec import canonical_json

__all__ = [
    "ComparisonSpecError",
    "ComparisonIntent",
    "ComparisonVerdict",
    "resolve_intent",
    "fingerprint_from_run",
    "fingerprint_from_legacy_row",
    "evaluate_comparability",
    "eval_metric_compatibility",
    "pareto_with_scope",
    "PARETO_STATUSES",
]


class ComparisonSpecError(ValueError):
    """Invalid comparison intent or unfingerprintable candidate."""


# ── Metric semantics (§6) ────────────────────────────────────────────────────
# A JSON key is not a metric. These tables are the closed vocabulary a
# number must belong to before two results may be compared on it.

KNOWN_UNITS = frozenset({
    "cycles", "ns", "s",          # time (never cross-compared without proof)
    "requests", "flits", "packets", "bytes",
    "GiB", "ratio",
})

# name → units this metric may legally carry
KNOWN_METRICS: dict[str, frozenset[str]] = {
    "latency": frozenset({"cycles"}),
    "hops": frozenset({"ratio"}),
    "throughput": frozenset({"ratio"}),
    "exposed_communication": frozenset({"cycles"}),
    # Phase 5 canonical serving vocabulary (schema v1, unit-pinned)
    "sim_clock": frozenset({"ns"}),
    "request_arrival_time": frozenset({"ns"}),
    "request_completion_time": frozenset({"ns"}),
    "request_latency": frozenset({"ns"}),
    "TTFT": frozenset({"ns"}),
    "TPOT": frozenset({"ns"}),
    "ITL": frozenset({"ns"}),
    "requests_submitted": frozenset({"requests"}),
    "requests_retired": frozenset({"requests"}),
    "wall_time": frozenset({"s"}),
}

# §7: metrics an engine does not semantically produce. The congestion-
# unaware analytical frontend emits exposed communication as a constant
# 0 (no congestion model) — that zero is an engine property, never a
# measurement, so the metric is not comparable for such candidates.
METRIC_CAPABILITY: dict[str, dict[str, Any]] = {
    "exposed_communication": {
        "engines_without": frozenset({"congestion_unaware"}),
        "reason": ("metric is not semantically produced by this engine "
                   "(congestion-unaware analytical reports a constant 0)"),
    },
}


def eval_metric_compatibility(left: dict[str, Any], right: dict[str, Any],
                              name: str) -> tuple[bool, str | None]:
    """Whether two typed metrics may be compared on ``name``.

    Returns (ok, reason). Refusals, in check order: unknown metric
    semantics, unknown unit, unit mismatch, engine capability.
    """
    spec = KNOWN_METRICS.get(name)
    if spec is None:
        return False, "UNKNOWN_METRIC"
    for m in (left, right):
        if m.get("unit") not in KNOWN_UNITS:
            return False, "UNKNOWN_UNIT"
    if left.get("unit") != right.get("unit"):
        return False, "UNIT_MISMATCH"
    cap = METRIC_CAPABILITY.get(name)
    if cap is not None:
        # A constant zero from an engine that does not produce the metric
        # must never read as a measured zero (§7).
        for m in (left, right):
            producer = str(m.get("producer", ""))
            if ("analytical" in producer and m.get("value") == 0):
                return False, "METRIC_NOT_COMPARABLE"
    return True, None


# ── Comparison intent (§2/§4) ────────────────────────────────────────────────

@dataclass(frozen=True)
class ComparisonIntent:
    comparison_id: str
    kind: str                                    # DESIGN_COMPARISON | CROSS_FIDELITY_CALIBRATION
    objectives: tuple[str, ...]
    experimental_variables: frozenset[str]
    controlled_dimensions: dict[str, str]

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ComparisonIntent":
        unknown = set(d) - {
            "comparison_id", "kind", "objectives",
            "experimental_variables", "controlled_dimensions",
        }
        if unknown:
            raise ComparisonSpecError(
                f"unknown comparison fields: {sorted(unknown)}")
        kind = d.get("kind", "DESIGN_COMPARISON")
        if kind not in ("DESIGN_COMPARISON", "CROSS_FIDELITY_CALIBRATION"):
            raise ComparisonSpecError(f"unknown comparison kind {kind!r}")
        variables = frozenset(d.get("experimental_variables", ()))
        controlled = dict(d.get("controlled_dimensions", {}))
        objectives = tuple(d.get("objectives", ("latency",)))
        payload = canonical_json({
            "kind": kind, "objectives": list(objectives),
            "variables": sorted(variables), "controlled": controlled,
        })
        cid = d.get("comparison_id") or hashlib.sha256(
            payload.encode()).hexdigest()[:16]
        return ComparisonIntent(cid, kind, objectives, variables, controlled)


def resolve_intent(d: dict[str, Any]) -> ComparisonIntent:
    """Strict boundary for user-supplied comparison intent (§15).

    An empty declaration is legal and maximally conservative: it treats
    every fingerprint dimension as controlled, so ANY material
    difference between candidates refuses (fail closed). The refusal
    comes from the differences, never from the shape of the request.
    """
    return ComparisonIntent.from_dict(d)


# ── Fingerprints (§3) ────────────────────────────────────────────────────────

# Fields that materially affect comparison validity. Order is diagnostic
# order; only fields present in a fingerprint are checked.
FINGERPRINT_FIELDS = (
    "workload_hash", "model_identity", "node_count", "participant_count",
    "packetization", "topology", "routing", "vc_count",
    "simulator", "network_engine", "network_mode", "fidelity",
    "seed_policy", "tp", "dp", "ep", "pp", "instance_mapping",
    "metric_schema", "binary_sha256",
)

# Required dimensions per evidence class. A memory comparison must not
# demand network VCs; a fabric comparison must not ignore packetization.
# Unknown fidelities skip this gate (kind policy still applies) — an
# unwired evidence class is not a license to invent its requirements.
REQUIRED_BY_FIDELITY = {
    "NETWORK_SIMULATION": frozenset({
        "workload_hash", "participant_count", "topology", "routing",
        "vc_count", "packetization", "fidelity"}),
    "SYSTEM_SERVING_SIMULATION": frozenset({
        "workload_hash", "participant_count", "topology", "routing",
        "vc_count", "packetization", "fidelity", "network_mode",
        "instance_mapping"}),
    "ANALYTICAL_ESTIMATE": frozenset({
        "workload_hash", "participant_count", "topology", "routing",
        "fidelity"}),
    "TRACE_REPLAY": frozenset({"workload_hash", "fidelity"}),
}


def fingerprint_from_run(run_dir: Path) -> dict[str, Any]:
    """Resolve the comparison fingerprint of one immutable run.

    Reads only what the run dir actually records (spec.resolved.json +
    manifest.json). Missing files raise INSUFFICIENT_PROVENANCE — a
    fingerprint is never guessed (§14).
    """
    run_dir = Path(run_dir)
    spec_path = run_dir / "spec.resolved.json"
    manifest_path = run_dir / "manifest.json"
    if not spec_path.is_file() or not manifest_path.is_file():
        raise ComparisonSpecError(
            f"INSUFFICIENT_PROVENANCE: {run_dir.name} is missing "
            "spec.resolved.json or manifest.json — cannot fingerprint")
    spec = json.loads(spec_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    results = manifest.get("results") or []
    prov = next((r.get("provenance") for r in reversed(results)
                 if isinstance(r, dict) and r.get("provenance")), None)
    serving = spec.get("serving")
    sim = spec.get("simulation", {})

    # Workload identity: canonical first, fixture identity as fallback.
    # Phase 9: a run whose serving slice canonicalized its saved traces
    # carries <run>/workload/index.json with content-addressed
    # WorkloadArtifact hashes — those ARE the workload identity, and the
    # fingerprint is certified. Without them, fall back to hashing the
    # resolved workload/serving inputs (fixture identity subsumes
    # cluster parallelism) and mark the identity uncertified: two runs
    # of the same fixture provably share semantics only through the
    # canonical artifact, never through config equality alone.
    wl_index_path = run_dir / "workload" / "index.json"
    workload_certified = False
    if wl_index_path.is_file():
        try:
            wl_index = json.loads(wl_index_path.read_text())
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise RuntimeError(
                f"workload index {wl_index_path} unreadable/malformed: {e} "
                "— refusing to guess workload identity (fail-closed)")
        from ..workload.serve import workload_identity
        # Shared identity rule (slice provenance uses the same); raises
        # WorkloadError on an empty artifact set — fail-closed, never a
        # guessed identity.
        workload_hash = workload_identity(wl_index)
        workload_certified = True
    else:
        wl_index = None
        wl_payload = canonical_json({
            "workload": spec.get("workload"), "serving": serving,
        })
        workload_hash = hashlib.sha256(wl_payload.encode()).hexdigest()

    instance_mapping = None
    if serving is not None and wl_index is not None:
        try:
            from .mapping import mapping_from_workload_index
            instance_mapping = mapping_from_workload_index(
                wl_index, serving.get("cluster")).mapping_hash
        except Exception:
            instance_mapping = None

    if serving is not None:
        simulator = f"llmservingsim/{serving.get('network_backend', '?')}"
        network_mode = (prov or {}).get("network_mode")
        fidelity = (prov or {}).get("fidelity")
        semantic_losses = (prov or {}).get("semantic_losses")
    else:
        # Slice A: standalone BookSim cycle simulation.
        simulator = sim.get("network_simulator", "booksim")
        network_mode = "REAL_SIMULATION"
        fidelity = "NETWORK_SIMULATION"
        semantic_losses = []

    # Fabric identity comes from the run's EXECUTED-fabric record
    # (FabricArtifact parsed from the BookSim config that actually ran),
    # not from spec claims: spec.network never reaches the serving
    # child's generated config. Unrecorded ⇒ None, uncertified.
    fabric = next(
        (r.get("fabric") or r.get("executed_fabric") for r in reversed(results)
         if isinstance(r, dict)
         and isinstance(r.get("fabric") or r.get("executed_fabric"), dict)),
        None)
    if fabric and not fabric.get("unrecorded"):
        try:
            vc_count = int(fabric["num_vcs"]) if fabric.get("num_vcs") else None
        except (TypeError, ValueError):
            vc_count = None
        try:
            packetization = (int(fabric["packet_size"])
                             if fabric.get("packet_size") else None)
        except (TypeError, ValueError):
            packetization = None
        if serving is not None:
            fab_topo, fab_routing = fabric.get("topology"), fabric.get("routing")
        else:
            fab_topo, fab_routing = None, None
    else:
        fabric, vc_count, packetization, fab_topo, fab_routing = \
            None, None, None, None, None

    repl = spec.get("replication", {})
    metric_schema = next((r.get("metric_schema") for r in reversed(results)
                          if isinstance(r, dict) and r.get("metric_schema")),
                         None)
    if serving is not None:
        topo_id, routing_id = fab_topo, fab_routing
    else:
        net = spec.get("network") or {}
        topo_id = net.get("topology")
        routing_id = net.get("routing")
    return {
        "workload_hash": workload_hash,
        "model_identity": (serving or {}).get("cluster"),
        "node_count": spec.get("system", {}).get("nodes"),
        "participant_count": spec.get("system", {}).get("nodes"),
        "topology": topo_id,
        "routing": routing_id,
        "vc_count": vc_count,
        "packetization": packetization,
        "simulator": simulator,
        "network_engine": next((r.get("network_engine") for r in
                                reversed(results)
                                if isinstance(r, dict)
                                and r.get("network_engine")), None),
        "network_mode": network_mode,
        "fidelity": fidelity,
        "semantic_losses": semantic_losses,
        "seed_policy": (f"{repl.get('mode')}:{repl.get('seeds')}"
                        if repl else None),
        "tp": spec.get("system", {}).get("tp_size"),
        "dp": None, "ep": None, "pp": None,  # inside cluster identity
        "instance_mapping": instance_mapping,
        "binary_sha256": next((
            b.get("sha256") for r in reversed(results)
            if isinstance(r, dict)
            for b in ([r.get("booksim_binary")] if r.get("booksim_binary")
                      else (r.get("backend_binaries") or []))
            if isinstance(b, dict) and b.get("sha256")), None),
        "metric_schema": metric_schema,
        "workload_certified": workload_certified,
        "certified": workload_certified and fabric is not None,
        **({"fabric_artifact_hash": fabric.get("artifact_hash"),
            "fabric_config_sha256": fabric.get("config_sha256")}
           if fabric else {}),
        "run_id": manifest.get("run_id", run_dir.name),
    }


def fingerprint_from_legacy_row(row: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint a legacy compare row, marking what cannot be resolved.

    The legacy compare pipeline runs one trace against several BookSim
    topologies; rows record topology/nodes/seed/latency but not VC
    config, packetization, or tool versions. Unresolvable dimensions are
    listed in ``unresolved_dimensions`` and the fingerprint is marked
    ``certified: False`` — the comparison can still run, but its output
    can never carry a certified claim (§14).
    """
    unresolved = ["vc_count", "packetization", "simulator",
                  "network_engine", "network_mode", "metric_schema",
                  "participant_count", "instance_mapping"]
    if row.get("trace") is None:
        unresolved.append("workload_hash")
    fp = {
        "workload_hash": row.get("trace"),
        "node_count": row.get("nodes"),
        "topology": row.get("topology") or row.get("name"),
        "routing": None,
        "fidelity": "NETWORK_SIMULATION",
        "fidelity_provenance": "adapter_default_booksim_latency",
        "seed_policy": (f"deterministic:[{row['seed']}]"
                        if row.get("seed") is not None else None),
        "certified": False,
        "unresolved_dimensions": unresolved,
        "run_id": row.get("name"),
    }
    return fp


# ── Comparability verdict (§4/§5/§7/§9) ──────────────────────────────────────

@dataclass
class ComparisonVerdict:
    status: str                                   # COMPARABLE | INVALID_COMPARISON | INSUFFICIENT_PROVENANCE
    comparison_kind: str
    differences: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    experimental_variables: list[str] = field(default_factory=list)
    certified: bool = True
    unresolved_dimensions: list[str] = field(default_factory=list)


def _diff(field: str, left: Any, right: Any, reason: str,
          **extra: Any) -> dict[str, Any]:
    return {"field": field, "left": left, "right": right,
            "reason": reason, **extra}


def evaluate_comparability(
    fingerprints: list[dict[str, Any]],
    intent: dict[str, Any] | ComparisonIntent,
    metric_lookup: Callable[[dict[str, Any], str], Any] | None = None,
) -> ComparisonVerdict:
    """Verdict over a candidate set: may these results be compared?

    Two tiers (brief §8/§13):

      * SET-level incoherence → INVALID_COMPARISON, no comparison is
        interpretable: undeclared material differences (§4),
        TRACE_REPLAY mixed with simulation (§5), fidelity mixing under
        DESIGN_COMPARISON (§5).
      * CANDIDATE-level problems → the comparison stays valid over the
        rest; the candidate is excluded with a visible status:
        SEMANTIC_LOSS (§9), NOT_COMPARABLE (engine capability, §7),
        MISSING_METRIC (when a metric lookup is supplied).

    Declared variables that stay constant are a degenerate axis, not an
    error — the rule is one-directional: differing ⇒ must be declared.
    """
    if isinstance(intent, dict):
        intent = ComparisonIntent.from_dict(intent)
    fps = list(fingerprints)
    diffs: list[dict[str, Any]] = []

    def _vals(name: str) -> list[Any]:
        return [fp.get(name) for fp in fps]

    # Provenance gate (§14): a candidate whose fidelity is unknown or
    # unrecorded has no provenance contract — the set is ineligible
    # regardless of kind. Calibration exempts known-class differences,
    # never an unknown class. Two identical unknown strings are not
    # evidence of comparability.
    if fps and any(fp.get("fidelity") not in REQUIRED_BY_FIDELITY
                   for fp in fps):
        unknown = sorted({str(fp.get("fidelity")) for fp in fps
                          if fp.get("fidelity") not in REQUIRED_BY_FIDELITY})
        diffs.append(_diff("fidelity", unknown, None, "UNKNOWN_FIDELITY"))
        return ComparisonVerdict(
            status="INSUFFICIENT_PROVENANCE",
            comparison_kind=intent.kind,
            differences=diffs,
            candidates=[{"run_id": fp.get("run_id"),
                         "status": "INSUFFICIENT_PROVENANCE"}
                        for fp in fps],
            experimental_variables=sorted(intent.experimental_variables),
            certified=False,
            unresolved_dimensions=["fidelity"],
        )
    # Required controlled dimensions unrecorded for every candidate make
    # a DESIGN_COMPARISON ineligible — never comparable. Required set
    # follows the candidates' evidence class, minus declared axes.
    if intent.kind == "DESIGN_COMPARISON" and fps:
        fids = {fp.get("fidelity") for fp in fps} - {None}
        required: set[str] = set()
        if len(fids) == 1:
            required = set(REQUIRED_BY_FIDELITY[next(iter(fids))])
        required -= set(intent.experimental_variables)
        unresolved = sorted(
            d for d in required if all(fp.get(d) is None for fp in fps))
        if unresolved:
            for d in unresolved:
                diffs.append(_diff(d, None, None, "INSUFFICIENT_PROVENANCE"))
            return ComparisonVerdict(
                status="INSUFFICIENT_PROVENANCE",
                comparison_kind=intent.kind,
                differences=diffs,
                candidates=[{"run_id": fp.get("run_id"),
                             "status": "INSUFFICIENT_PROVENANCE"}
                            for fp in fps],
                experimental_variables=sorted(intent.experimental_variables),
                certified=False,
                unresolved_dimensions=unresolved,
            )

    def _vals(name: str) -> list[Any]:
        return [fp.get(name) for fp in fps]

    # ── hard rule: TRACE_REPLAY never mixes with simulation (§5) ──────
    modes = set(_vals("network_mode")) - {None}
    if len(modes) > 1 and "TRACE_REPLAY" in modes:
        others = sorted(modes - {"TRACE_REPLAY"})
        diffs.append(_diff("network_mode", "TRACE_REPLAY", others[0],
                           "TRACE_REPLAY_MIXED"))

    # ── kind policy (§5) ───────────────────────────────────────────────
    if intent.kind == "DESIGN_COMPARISON":
        fids = set(_vals("fidelity")) - {None}
        if len(fids) > 1:
            ordered = sorted(str(f) for f in fids)
            diffs.append(_diff("fidelity", ordered[0], ordered[1],
                               "FIDELITY_MISMATCH"))
        if len(modes) > 1 and "TRACE_REPLAY" not in modes:
            ordered = sorted(str(m) for m in modes)
            diffs.append(_diff("network_mode", ordered[0], ordered[1],
                               "NETWORK_MODE_MISMATCH"))

    # ── generic controlled-vs-variable loop (§4) ──────────────────────
    # Kind-exempted fields: a calibration study is *about* differing
    # simulators/fidelities/modes. A declared variable that happens to be
    # constant across candidates is a degenerate axis, not an error —
    # the rule is one-directional: differing ⇒ must be declared.
    exempt = {"simulator", "fidelity", "network_mode"} \
        if intent.kind == "CROSS_FIDELITY_CALIBRATION" else set()
    for fname in FINGERPRINT_FIELDS:
        values = _vals(fname)
        if all(v is None for v in values):
            continue
        distinct = {json.dumps(v, sort_keys=True) for v in values}
        if len(distinct) > 1:
            if fname in exempt:
                continue
            if fname in intent.experimental_variables:
                continue
            pair = _first_pair(values)
            diffs.append(_diff(fname, pair[0], pair[1],
                               "UNDECLARED_DIFFERENCE"))

    # ── candidate-level statuses (visible exclusions, §8/§9/§7) ───────
    candidates = []
    for fp in fps:
        status = "COMPARABLE"
        detail: dict[str, Any] = {}
        if fp.get("semantic_losses"):
            # §9: ineligible for normal scientific comparison by default.
            status = "SEMANTIC_LOSS"
            detail = {"reason": f"semantic_losses: "
                      f"{fp['semantic_losses']}"}
        else:
            for obj in intent.objectives:
                cap = METRIC_CAPABILITY.get(obj)
                if cap is None:
                    continue
                if fp.get("network_engine") in cap["engines_without"]:
                    # §7: the engine does not semantically produce the
                    # metric (e.g. unaware exposed=0) — never a measured
                    # zero, never silently dropped.
                    status = "NOT_COMPARABLE"
                    detail = {"reason": cap["reason"], "metric": obj,
                              "network_engine": fp.get("network_engine")}
                    break
        entry = {"run_id": fp.get("run_id"), "status": status, **detail}
        if metric_lookup is not None and status == "COMPARABLE":
            entry["objectives_status"] = {
                obj: ("OK" if metric_lookup(fp, obj) is not None
                      else "MISSING_METRIC")
                for obj in intent.objectives}
        candidates.append(entry)

    certified = bool(fps) and all(fp.get("certified", True) for fp in fps)
    return ComparisonVerdict(
        status="INVALID_COMPARISON" if diffs else "COMPARABLE",
        comparison_kind=intent.kind,
        differences=diffs,
        candidates=candidates,
        experimental_variables=sorted(intent.experimental_variables),
        certified=certified,
    )


def _first_pair(values: list[Any]) -> tuple[Any, Any]:
    seen: dict[str, Any] = {}
    for v in values:
        k = json.dumps(v, sort_keys=True)
        if k in seen and seen[k] != v:
            return seen[k], v
        seen[k] = v
    first = next(v for v in values if v is not None)
    other = next(v for v in values
                 if json.dumps(v, sort_keys=True)
                 != json.dumps(first, sort_keys=True))
    return first, other


# ── Scoped Pareto (§8/§11) ───────────────────────────────────────────────────

PARETO_STATUSES = ("COMPARABLE", "FAILED_EXECUTION", "INCOMPATIBLE",
                   "MISSING_METRIC", "SEMANTIC_LOSS", "INVALID_FIDELITY",
                   "NOT_COMPARABLE")


def _dominates(a: dict[str, Any], b: dict[str, Any],
               keys: list[str]) -> bool:
    """a dominates b: a <= b on all keys and < on at least one."""
    le = all(a[k] <= b[k] for k in keys)
    lt = any(a[k] < b[k] for k in keys)
    return le and lt


def pareto_with_scope(candidates: list[dict[str, Any]],
                      objectives: list[str],
                      *, kind: str = "DESIGN_COMPARISON") -> dict[str, Any]:
    """Pareto over the comparable set, with every candidate visible.

    The banned shape is ``pareto_front([x for x in c if x.ok])`` followed
    by output that pretends the excluded candidates never existed. Here
    every requested candidate appears in ``candidates`` with a status;
    only COMPARABLE candidates with every objective present enter the
    frontier; and the output states the evaluated scope.
    """
    if kind == "DESIGN_COMPARISON":
        fids = {c.get("fidelity") for c in candidates
                if c.get("fidelity") is not None}
        if len(fids) > 1:
            raise ComparisonSpecError(
                "DESIGN_COMPARISON pareto over mixed fidelities "
                f"{sorted(str(f) for f in fids)} — declare "
                "CROSS_FIDELITY_CALIBRATION or compare like with like")

    processed: list[dict[str, Any]] = []
    comparable: list[dict[str, Any]] = []
    for c in candidates:
        status = c.get("status", "COMPARABLE")
        metrics = dict(c.get("metrics") or {})
        missing = [k for k in objectives if k not in metrics]
        if status == "COMPARABLE" and missing:
            status = "MISSING_METRIC"
        entry = {"run_id": c.get("run_id"), "status": status,
                 "metrics": metrics}
        if c.get("reason"):
            entry["reason"] = c["reason"]
        processed.append(entry)
        if status == "COMPARABLE":
            comparable.append(entry)

    front: list[str] = []
    dominated: list[str] = []
    for p in comparable:
        others = [q for q in comparable if q is not p]
        if any(_dominates(q["metrics"], p["metrics"], objectives)
               for q in others):
            dominated.append(p["run_id"])
        else:
            front.append(p["run_id"])

    excluded = [{"run_id": e["run_id"], "status": e["status"],
                 **({"reason": e["reason"]} if e.get("reason") else {})}
                for e in processed if e["status"] != "COMPARABLE"]
    return {
        "comparison_kind": kind,
        "objectives": list(objectives),
        "candidate_count": len(candidates),
        "comparable_count": len(comparable),
        "candidates": processed,
        "excluded": excluded,
        "front": front,
        "dominated": dominated,
        "pareto_scope": {"candidate_count": len(comparable),
                         "objectives": list(objectives)},
    }
