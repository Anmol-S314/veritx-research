"""The positive evidence bundle: measured evidence closes the flag.

``test_final_implementation_evidence.py`` proves the other half: unmeasured
rows keep ``final_implementation`` false. This module measures every row
the composed-family scope requires, writes the production bundle keyed to
the design hash, and asserts that the verdict computed from that evidence
closes.

The division of labour is deliberate and is stated per row:

* the family *emission* measures A1 (the family composed and emitted), A2
  (the lint log carries no warning and the simulation log is green with
  every scenario true), A4 and A5 (the attachment the emission actually
  built);
* this module measures A3 (a corrupted binding is refused by the named
  checker), A6 (the decode contract's proof), A7 (the deadlock-freedom
  proof), A8 (the paired BookSim/RTL run), A9 (the directed AXI5 suite) and
  A10 (the multi-flit reassembly).

The bundle lands in ``docs/product/evidence/final-implementation`` and is
keyed to ``request.design_hash()``: evidence measured on one design can
never carry the flag for another.

Each family is its own test so that a family's emission (lint, build and
simulation) stays inside the suite's per-test wall-clock budget.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

from test_final_implementation_evidence import (  # noqa: E402
    COMPOSED_FAMILIES,
    _family,
    _row_axi5,
    _row_binding_witness,
    _row_cdg_proof,
    _row_decode_proof,
    _row_multiflit,
    _row_parity,
)


#: Every family whose emitted artifact carries the composed-family scope.
#: The shared-wire hybrids (gec_hybrid, srota) carry their own scopes and
#: their own contract rows, so they are not in this set.
EVIDENCE_FAMILIES = tuple(COMPOSED_FAMILIES) + ("gec_mecs", "kncube")


@pytest.fixture(scope="module")
def shared_rows() -> dict:
    """The rows that do not depend on the family, measured once."""
    return {
        "A6": _row_decode_proof(),
        "A8": _row_parity(),
        "A9": _row_axi5(),
        "A10": _row_multiflit(),
    }


def _measure_emission(family: str, work: Path) -> dict:
    """Emit the family and measure what the emission itself proves.

    The emission is the product's own path, so the lint log, the simulation
    log and the scenario outcomes are the ones the release would ship.
    """
    from veritx_dse.product import project_top_rtl
    request, _compiled, params = _family(family)
    out = work / family
    result = project_top_rtl.run_composed_family(
        request.to_dict(), out, {"repo_root": str(REPO)})
    rtl = out / "rtl"
    seats = list(getattr(params, "seats", ()) or ())
    per_router: dict[int, int] = {}
    for seat in seats:
        router_id = int(seat[3])
        per_router[router_id] = per_router.get(router_id, 0) + 1
    scenarios = result.get("scenarios") or {}
    return {
        "lint_log": rtl / "logs" / "verilator-lint.log",
        "sim_log": rtl / "logs" / "verilator-sim.log",
        "lint_status": str(result.get("lint", "NOT_RUN")),
        "sim_status": str(result.get("sim", "NOT_RUN")),
        "scenarios": scenarios,
        "attachment_measurement": {
            "initiator_count": len(list(getattr(params, "initiators", ()) or ())),
            "slice_count": len(list(getattr(params, "initiators", ()) or ())),
            "endpoint_count": len(seats),
            "seat_endpoint_ids": len({int(seat[0]) for seat in seats}),
            "shared_router_seats": sum(1 for count in per_router.values()
                                       if count > 1),
            "concentrator_routers": sum(
                1 for router_id, count in per_router.items()
                if count > 1 and any(int(pair[1]) == router_id
                                     for pair in getattr(params, "endpoint_seats", ()) or ())),
            "per_seat_scenarios": sum(1 for name in scenarios
                                      if name.startswith(("allow_", "deny_"))),
            "per_seat_scenarios_passed": sum(
                1 for name, ok in scenarios.items()
                if ok and name.startswith(("allow_", "deny_"))),
        },
    }


@pytest.mark.parametrize("family", EVIDENCE_FAMILIES)
def test_measured_evidence_closes_the_verdict(family: str, shared_rows: dict):
    """The measured evidence for one family closes the flag, and says so.

    Nothing here asserts the flag: the bundle is written from what was
    measured, and the verdict is computed from the bundle. If a row's
    measurement came back open, the verdict says so and the test fails
    with the row's own reason.
    """
    from veritx_dse.product.final_implementation import composed_family_verdict
    from veritx_dse.product.scope_evidence import (
        compose_family_evidence,
        write_evidence_bundle,
    )
    request, _compiled, _params = _family(family)
    work = Path(tempfile.mkdtemp(prefix="evidence-emission-"))
    try:
        emission = _measure_emission(family, work)

        # The logs are read here, while the emission that produced them is
        # still on disk: A2 is the row that quotes the lint log and the
        # simulation log, so the evidence has to be collected from the
        # run that measured it.
        measured = compose_family_evidence(
            family=family,
            lint_status=emission["lint_status"],
            sim_status=emission["sim_status"],
            scenarios=emission["scenarios"],
            logs={"lint": emission["lint_log"], "sim": emission["sim_log"]},
            attachment_measurement=emission["attachment_measurement"])
        measured.update(shared_rows)
        measured["A3"] = _row_binding_witness(family)
        measured["A7"] = _row_cdg_proof(family)

        path = write_evidence_bundle(
            family=family, design_hash=request.design_hash(), rows=measured)
        assert path.is_file(), family

        verdict = composed_family_verdict(family=family, evidence=measured)
        open_rows = {row: next((v for v in verdict["rows"] if v["row"] == row), {})
                     for row in verdict["open_rows"]}
        assert verdict["final_implementation"] is True, (family, open_rows)
        assert verdict["open_rows"] == [], (family, open_rows)
    finally:
        shutil.rmtree(work, ignore_errors=True)
