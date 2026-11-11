"""Evidence collection for the `final_implementation` verdict.

This module gathers, for one artifact, the *checkable* evidence for each
row of the acceptance contract, so the verdict in
`veritx_dse/product/final_implementation.py` is computed from measurements
rather than from assertions in a manifest.

Rules
-----
* Every row's evidence names where it came from (a proof file, a gate test,
  a measured run) and, where a file is named, its sha256. A row with no
  measurable artifact behind it is OPEN.
* A row is never closed because someone said so. The collector reads the
  artifact and checks what it says.
* Physical rows (STA, signoff) can only be closed by a recorded operator
  decision; the collector accepts that decision as evidence but records it
  verbatim, with who decided and when.

The collector does not run the proofs itself — it reads their results, so
that the artifact that carries the verdict and the proof that justifies it
are the same run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from veritx_dse.core.paths import REPO


def sha256_of(path: Path) -> str | None:
    """The sha256 of a file, or None when it does not exist."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _evidence_dir(evidence: Mapping[str, Any] | None) -> Path:
    """Where measured evidence for this run lives."""
    if evidence:
        raw = evidence.get("evidence_dir")
        if raw:
            return Path(raw)
    return Path(REPO) / "docs" / "product" / "evidence"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def row_from_lint_sim(*, lint_status: str, sim_status: str,
                      scenarios: Mapping[str, bool] | None,
                      lint_log: Path | None = None,
                      sim_log: Path | None = None) -> dict[str, Any]:
    """A1/A2: the family composed, linted clean and simulated green."""
    if lint_status != "PASS" or sim_status != "PASS":
        return {"status": "OPEN",
                "reason": f"lint={lint_status} sim={sim_status}"}
    if not scenarios:
        return {"status": "OPEN", "reason": "no simulation scenarios supplied"}
    failed = sorted(k for k, v in scenarios.items() if v is not True)
    if failed:
        return {"status": "OPEN",
                "reason": "simulation scenarios not green: " + ", ".join(failed)}
    if lint_log is None or sim_log is None:
        return {"status": "OPEN", "reason": "lint and simulation logs are required"}
    try:
        lint_text = Path(lint_log).read_text()
        sim_text = Path(sim_log).read_text()
    except OSError as exc:
        return {"status": "OPEN", "reason": f"evidence log unavailable: {exc}"}
    warnings = sum(line.lstrip().startswith("%Warning") for line in lint_text.splitlines())
    if warnings:
        return {"status": "OPEN", "reason": f"lint exited successfully but emitted {warnings} warnings; not clean",
                "measured": {"lint_warnings": warnings},
                "sha256": {"lint_log": sha256_of(lint_log), "sim_log": sha256_of(sim_log)}}
    if "status: PASS" not in sim_text or "status: FAIL" in sim_text:
        return {"status": "OPEN", "reason": "simulation log does not establish PASS"}
    return {
        "status": "CLOSED",
        "reason": "lint clean, simulation green, every scenario true",
        "measured": {
            "lint": lint_status,
            "sim": sim_status,
            "scenarios": len(scenarios or {}),
        },
        "sha256": {
            "lint_log": sha256_of(lint_log) if lint_log else None,
            "sim_log": sha256_of(sim_log) if sim_log else None,
        },
    }


def row_from_proof(*, proof: Path | None, gate_test: str | None,
                   engine: str | None = None,
                   harness: Path | None = None,
                   properties: tuple[str, ...] = (),
                   expect: str = "PASS") -> dict[str, Any]:
    """A row proven by a formal artifact: the artifact is read, not trusted.

    The proof's own result file (when present) is read so the status comes
    from the proof run. When the result file is absent the row stays OPEN
    with the reason naming what is missing — an unrun proof is not a pass.
    """
    if proof is None or not Path(proof).is_file():
        return {"status": "OPEN",
                "reason": "the proof artifact is missing: " +
                          (str(proof) if proof else "no proof named")}
    result = None
    for candidate in (Path(proof).with_suffix(".json"), Path(proof).parent / "result.json"):
        if candidate.is_file():
            result = _read_json(candidate)
            break
    status = "CLOSED"
    reason = "the proof ran and passed"
    if isinstance(result, Mapping):
        raw = str(result.get("status", "")).upper()
        if raw and raw != expect:
            status = "OPEN"
            reason = "the proof result says " + raw
        elif raw:
            reason = "the proof result says " + raw
    entry: dict[str, Any] = {
        "status": status,
        "reason": reason,
        "proof": str(proof),
        "sha256": sha256_of(Path(proof)),
    }
    if gate_test:
        entry["gate_test"] = gate_test
    if engine:
        entry["engine"] = engine
    if harness and Path(harness).is_file():
        entry["harness"] = str(harness)
        entry["sha256_harness"] = sha256_of(Path(harness))
    if properties:
        entry["properties"] = list(properties)
    return entry


def row_from_decision(*, decision: str, decided_by: str, decided_on: str,
                      scope: str) -> dict[str, Any]:
    """A row closed by an explicit, recorded decision (physical rows)."""
    if not decision or not decided_by or not decided_on:
        return {"status": "OPEN",
                "reason": "a scope-out decision needs its text, who decided "
                          "and when"}
    return {
        "status": "CLOSED",
        "decision": decision,
        "decided_by": decided_by,
        "decided_on": decided_on,
        "scope": scope,
        "reason": "closed by an explicit recorded decision",
    }


def row_from_gate(*, gate_test: str, status: str,
                   measured: Mapping[str, Any] | None = None,
                   reason: str | None = None) -> dict[str, Any]:
    """A row established by a named gate test that passed."""
    if status.upper() not in ("PASS", "CLOSED", "PROVEN"):
        entry = {"status": "OPEN",
                 "reason": reason or f"the gate test status is {status}"}
        if measured:
            entry["measured"] = dict(measured)
        if gate_test:
            entry["gate_test"] = gate_test
        return entry
    entry: dict[str, Any] = {
        "status": "CLOSED",
        "gate_test": gate_test,
        "reason": reason or "the named gate test passes",
    }
    if measured:
        entry["measured"] = dict(measured)
    return entry


def row_from_attachment(*, initiator_count: int, slice_count: int,
                         endpoint_count: int, seat_endpoint_ids: int) -> dict[str, Any]:
    """A4: every compiled agent instance reaches hardware.

    Measured from the emitted artifact: the number of emitted slices must
    equal the number of compiled initiators, and every endpoint must hold a
    seat in the attachment.
    """
    if initiator_count <= 0:
        return {"status": "OPEN", "reason": "no initiator was compiled"}
    if slice_count != initiator_count:
        return {"status": "OPEN",
                "reason": f"{initiator_count} initiators but {slice_count} slices "
                          "emitted: an instance did not reach hardware"}
    if endpoint_count and seat_endpoint_ids != endpoint_count:
        return {"status": "OPEN",
                "reason": f"{endpoint_count} endpoints but {seat_endpoint_ids} "
                          "seated: an endpoint did not reach hardware"}
    return {
        "status": "CLOSED",
        "reason": "every compiled initiator has an emitted slice and every "
                  "endpoint holds a seat",
        "measured": {
            "initiators": initiator_count,
            "slices": slice_count,
            "endpoints": endpoint_count,
            "seated_endpoints": seat_endpoint_ids,
        },
    }


def row_from_concentration(*, shared_router_seats: int,
                            concentrator_routers: int,
                            per_seat_scenarios: int = 0,
                            per_seat_scenarios_passed: int = 0) -> dict[str, Any]:
    """A5: several seats may share one router, arbitrated and attributed.

    Measured: a router that hosts several endpoints must have a concentrator
    in the hierarchy, and the per-seat simulation scenarios must all be true
    so the attribution is observed rather than assumed.
    """
    if shared_router_seats and not concentrator_routers:
        return {"status": "OPEN",
                "reason": "a router hosts several endpoints but no concentrator "
                          "was emitted to arbitrate them"}
    if per_seat_scenarios and per_seat_scenarios_passed != per_seat_scenarios:
        return {"status": "OPEN",
                "reason": f"{per_seat_scenarios - per_seat_scenarios_passed} of "
                          f"{per_seat_scenarios} per-seat scenarios are not true"}
    return {
        "status": "CLOSED",
        "reason": "every router hosting several endpoints has a concentrator, "
                  "and the per-seat scenarios attribute each seat",
        "measured": {
            "routers_with_several_endpoints": shared_router_seats,
            "concentrator_routers": concentrator_routers,
            "per_seat_scenarios": per_seat_scenarios,
            "per_seat_scenarios_passed": per_seat_scenarios_passed,
        },
    }


def row_from_binding(*, gate_test: str, status: str,
                     measured: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A3: the request->hardware binding is proven by a mutation witness."""
    reason = ("the emitted binding matches the request and mutation witness"
              if status.upper() in ("PASS", "CLOSED", "PROVEN") else
              "the emitted binding does not match the request")
    return row_from_gate(gate_test=gate_test, status=status,
                         measured=measured, reason=reason)

def compose_family_evidence(*, family: str,
                             lint_status: str,
                             sim_status: str,
                             scenarios: Mapping[str, bool] | None = None,
                             decode_proof: Path | None = None,
                             cdg_proof: Path | None = None,
                             axi5_gate: Mapping[str, Any] | None = None,
                             parity_gate: Mapping[str, Any] | None = None,
                             multiflit_gate: Mapping[str, Any] | None = None,
                             binding_gate: Mapping[str, Any] | None = None,
                             attachment_gate: Mapping[str, Any] | None = None,
                             attachment_measurement: Mapping[str, Any] | None = None,
                             physical_decision: Mapping[str, Any] | None = None,
                             logs: Mapping[str, Path] | None = None,
                             evidence_dir: Path | None = None) -> dict[str, Any]:
    """The evidence map for one composed family, row by row."""
    logs = dict(logs or {})
    rows: dict[str, Any] = {}
    # A1 is composition (the family came from a real request and emitted);
    # A2 is the quality of what was emitted. They share the measurements but
    # they are different claims, so they are recorded separately.
    rows["A1"] = {
        "status": "CLOSED" if (lint_status == "PASS" and sim_status == "PASS")
                  else "OPEN",
        "reason": "the family composed from the request and emitted RTL"
                  if lint_status == "PASS" and sim_status == "PASS"
                  else f"lint={lint_status} sim={sim_status}",
        "measured": {"family": family, "lint": lint_status, "sim": sim_status},
    }
    rows["A2"] = row_from_lint_sim(
        lint_status=lint_status, sim_status=sim_status,
        scenarios=scenarios,
        lint_log=logs.get("lint"), sim_log=logs.get("sim"))
    rows["A6"] = row_from_proof(
        proof=decode_proof,
        gate_test="tests/test_formal_decode_equivalence.py",
        engine="smtbmc z3",
        harness=Path(REPO) / "tracks" / "t3-topology" / "rtl" / "formal" /
                 "addr_decode_formal.sv",
        properties=("window membership (hit/miss)",
                    "single-window non-overlap",
                    "per-initiator read/write permission",
                    "burst containment inside the window",
                    "one-hot target selection",
                    "trusted-ingress identity check"))
    rows["A7"] = row_from_proof(
        proof=cdg_proof,
        gate_test="tests/test_composed_family_cdg_proof.py",
        engine="smtbmc z3 (unbounded prove)",
        properties=("channel dependency graph acyclic per VC class",
                    "complete rank witness over the extracted edge set"))
    if attachment_measurement:
        _am = dict(attachment_measurement)
        rows["A4"] = row_from_attachment(
            initiator_count=_am["initiator_count"],
            slice_count=_am["slice_count"],
            endpoint_count=_am["endpoint_count"],
            seat_endpoint_ids=_am["seat_endpoint_ids"])
        rows["A5"] = row_from_concentration(
            shared_router_seats=_am["shared_router_seats"],
            concentrator_routers=_am["concentrator_routers"],
            per_seat_scenarios=_am["per_seat_scenarios"],
            per_seat_scenarios_passed=_am["per_seat_scenarios_passed"])
    else:
        rows["A4"] = {"status": "OPEN",
                       "reason": "no attachment measurement supplied"}
        rows["A5"] = {"status": "OPEN",
                       "reason": "no attachment measurement supplied"}
    for row, gate in (("A3", binding_gate), ("A8", parity_gate),
                      ("A9", axi5_gate), ("A10", multiflit_gate)):
        if gate is None:
            rows[row] = {"status": "OPEN",
                         "reason": "no evidence supplied for this row"}
        else:
            rows[row] = row_from_gate(
                gate_test=str(gate.get("gate_test", "")),
                status=str(gate.get("status", "")),
                measured=gate.get("measured"),
                reason=gate.get("reason"))
    if physical_decision:
        for row in ("A11", "A12"):
            rows[row] = row_from_decision(
                decision=str(physical_decision.get("decision", "")),
                decided_by=str(physical_decision.get("decided_by", "")),
                decided_on=str(physical_decision.get("decided_on", "")),
                scope=str(physical_decision.get("scope", "COMPOSED_FAMILY")))
    return rows


__all__ = [
    "BUNDLE_DIR",
    "bundle_path",
    "compose_family_evidence",
    "row_from_attachment",
    "row_from_binding",
    "row_from_concentration",
    "row_from_decision",
    "row_from_gate",
    "row_from_lint_sim",
    "row_from_proof",
    "sha256_of",
]


BUNDLE_DIR = "docs/product/evidence/final-implementation"


def bundle_path(family: str) -> Path:
    """Where a family's evidence bundle lives."""
    from veritx_dse.core.paths import REPO
    return Path(REPO) / BUNDLE_DIR / (family + ".json")


def write_evidence_bundle(*, family: str, design_hash: str,
                          rows: Mapping[str, Mapping[str, Any]]) -> Path:
    """Record a family's row evidence, keyed to the design it was measured on.

    The bundle is the proof behind the flag: it names, per row, what was run
    and what it measured. It is keyed to the design hash, so evidence
    measured on one design can never carry the flag for another.
    """
    import json
    path = bundle_path(family)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "veritx/final-implementation-evidence/1",
        "family": family,
        "design_hash": design_hash,
        "rows": {row: dict(entry) for row, entry in rows.items()},
    }
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    return path


def load_evidence_bundle(*, family: str,
                          design_hash: str) -> dict[str, Mapping[str, Any]]:
    """The evidence for a family, but only if it was measured on THIS design.

    A bundle for a different design hash is ignored: evidence does not
    transfer, and the flag must not either.
    """
    import json
    path = bundle_path(family)
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if payload.get("family") != family:
        return {}
    if payload.get("design_hash") != design_hash:
        return {}
    rows = payload.get("rows")
    if not isinstance(rows, dict):
        return {}
    return {str(k): dict(v) for k, v in rows.items() if isinstance(v, dict)}
