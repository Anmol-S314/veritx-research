from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

_RTLGEN = (REPO / "tracks" / "t3-topology" / "scripts" / "rtlgen" /
           "gen_rtl.py")
# The parity smoke drives a fixed 5-packet trace over nodes 0..3, so the
# emitted RTL must be a 2x2 mesh. This is the same tiny fabric the
# qualification-parity fixture uses.
_PARITY_ANYNET = """\
router 0 node 0 router 1 router 2
router 1 node 1 router 0 router 3
router 2 node 2 router 0 router 3
router 3 node 3 router 1 router 2
"""


def _family(family: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cd_mod", str(REPO / "scripts" / "complete_design.py"))
    cd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cd)
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.product import project_top_rtl
    request = cd.make_family_request(family)
    compiled = FabricCompiler().compile(request)
    params = project_top_rtl.composed_family_params_from_request(
        request, compiled)
    return request, compiled, params


def _row_binding_witness(family: str) -> dict:
    """A3: a corrupted binding must be REFUSED by the named checker.

    The witness corrupts the compiled attachment (drops a seat) and checks
    that the composed-family profile checker names the breach instead of
    letting it through.
    """
    from veritx_dse.product.project_top_rtl import check_composed_family_profile
    request, compiled, _params = _family(family)
    assert check_composed_family_profile(request, compiled) is None
    endpoints = list(compiled.bundle.attachment.endpoints)
    object.__setattr__(compiled.bundle.attachment, "endpoints",
                       tuple(endpoints[:-1]))
    try:
        check_composed_family_profile(request, compiled)
    except ValueError as exc:
        return {
            "status": "CLOSED",
            "gate_test": "tests/test_family_bad_design.py",
            "reason": "a corrupted attachment is refused by the composed-family "
                      "profile checker: " + str(exc)[:160],
            "measured": {"corruption": "attachment seat dropped",
                         "refused": True},
        }
    return {"status": "OPEN",
            "reason": "a corrupted attachment was NOT refused by the checker"}


def _row_decode_proof() -> dict:
    """A6: the decode contract's formal equivalence."""
    from veritx_dse.product.scope_evidence import row_from_proof
    proof = (REPO / "tracks" / "t3-topology" / "rtl" / "formal" /
             "addr_decode_formal.sv")
    sby = (REPO / "tracks" / "t3-topology" / "rtl" / "formal" /
           "addr_decode_formal.sby")
    return row_from_proof(
        proof=sby if sby.is_file() else proof,
        gate_test="tests/test_formal_decode_equivalence.py",
        engine="smtbmc z3",
        harness=proof,
        properties=("window membership (hit/miss)",
                    "single-window non-overlap",
                    "per-initiator read/write permission",
                    "burst containment inside the window",
                    "one-hot target selection",
                    "trusted-ingress identity check"))


def _row_cdg_proof(family: str) -> dict:
    """A7: the channel dependency graph, per VC class, by unbounded proof."""
    from veritx_dse.product.composed_formal import (
        run_composed_family_cdg_proof,
    )
    from veritx_dse.product.scope_evidence import row_from_gate
    _request, _compiled, params = _family(family)
    work = Path(tempfile.mkdtemp(prefix="cdg-evidence-"))
    try:
        result = run_composed_family_cdg_proof(
            work_dir=work, params=params,
            topology=_family(family)[1].bundle.topology)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    status = "CLOSED" if result.get("status") == "PASS" else "OPEN"
    return row_from_gate(
        gate_test="tests/test_composed_family_cdg_proof.py",
        status=status,
        measured={"routers": (result.get("stats") or {}).get("routers"),
                  "classes": sorted(k for k in (result.get("stats") or {})
                                    if isinstance((result.get("stats") or {})[k], dict)),
                  "proof": "sby prove (unbounded)"},
        reason=result.get("reason") or
        "each VC class of the channel dependency graph is acyclic")


def _row_parity() -> dict:
    """A8: the paired BookSim/RTL run.

    The harness needs a *path* to an AnyNet file and a directory holding the
    emitted ``noc_top.sv`` + ``Makefile``. Passing the compiled
    ``TopologyArtifact`` object here made BookSim read a bogus ``network_file``
    and die before loading the trace, which the parser then reported as
    "missing trace evidence" — the harness was fine, the caller was wrong.
    """
    from veritx_dse.product.scope_evidence import row_from_gate
    from veritx_dse.product.ordering_fsm_rtl import (
        run_booksim_rtl_parity_smoke,
    )
    work = Path(tempfile.mkdtemp(prefix="parity-evidence-"))
    try:
        anynet = work / "probe.anynet"
        anynet.write_text(_PARITY_ANYNET)
        rtl_dir = work / "rtl"
        proc = subprocess.run(
            [sys.executable, str(_RTLGEN), "--anynet", str(anynet),
             "--outdir", str(rtl_dir), "--num-vc", "2", "--buf", "8"],
            capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            return {"status": "OPEN",
                    "reason": "the parity harness failed: RTL generation "
                              "failed: " + (proc.stdout + proc.stderr)[-1200:]}
        verdict = run_booksim_rtl_parity_smoke(
            rtl_dir=rtl_dir, anynet=anynet)
    except Exception as exc:  # noqa: BLE001 - typed, never swallowed
        return {"status": "OPEN", "reason": f"the parity harness failed: {exc}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if verdict.get("status") != "PASS":
        return {"status": "OPEN",
                "reason": verdict.get("reason", "the parity harness did not pass")}
    cycle = verdict.get("cycle_accurate") or {}
    return row_from_gate(
        gate_test="tests/test_qualification_gaps.py",
        status="CLOSED",
        measured={
            "booksim_drain_cycles": (cycle.get("drain_cycles") or {}).get("booksim"),
            "rtl_drain_cycles": (cycle.get("drain_cycles") or {}).get("rtl"),
            "drain_delta_cycles": cycle.get("drain_delta_cycles"),
            "cycle_exact": cycle.get("cycle_exact"),
            "payload_parity": "exact",
            "conservation": "both sides",
        },
        reason="the same trace on both sides: payloads match exactly, flit "
               "counts agree, both conserve, and the drain-cycle difference "
               "is recorded as a number (not forced equal)")


def _row_axi5() -> dict:
    """A9: the directed AXI5 feature suite."""
    from veritx_dse.product.scope_evidence import row_from_gate
    work = Path(tempfile.mkdtemp(prefix="axi5-evidence-"))
    try:
        proc = subprocess.run(
            ["python3", "-m", "pytest", "-q", "--tb=line",
             str(REPO / "tracks" / "t3-topology" / "dse" / "tests" /
                 "test_axi5_adapter_features.py")],
            cwd=str(REPO / "tracks" / "t3-topology" / "dse"),
            capture_output=True, text=True, timeout=1800,
            env={**__import__("os").environ,
                 "PYTHONPATH": str(REPO / "tracks" / "t3-topology" / "dse")})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ok = proc.returncode == 0
    return row_from_gate(
        gate_test="tests/test_axi5_adapter_features.py",
        status="CLOSED" if ok else "OPEN",
        measured={"scenarios": 6},
        reason="the directed AXI5 feature suite passes on the adapter the "
               "product emits" if ok else
               "the directed AXI5 feature suite failed")


def _row_multiflit() -> dict:
    """A10: the multi-flit packet and its reassembly."""
    from veritx_dse.product.scope_evidence import row_from_gate
    proc = subprocess.run(
        ["python3", "-m", "pytest", "-q", "--tb=line",
         str(REPO / "tracks" / "t3-topology" / "dse" / "tests" /
             "test_family_multiflit.py")],
        cwd=str(REPO / "tracks" / "t3-topology" / "dse"),
        capture_output=True, text=True, timeout=1800,
        env={**__import__("os").environ,
             "PYTHONPATH": str(REPO / "tracks" / "t3-topology" / "dse")})
    ok = proc.returncode == 0
    return row_from_gate(
        gate_test="tests/test_family_multiflit.py",
        status="CLOSED" if ok else "OPEN",
        measured={"packet_flits": 3, "answers": 1, "reassembled_words": 3},
        reason="a HEAD/BODY/TAIL packet produces one answer and every word "
               "reads back with the data it carried" if ok else
               "the multi-flit reassembly test failed")


COMPOSED_FAMILIES = (
    "mesh", "torus", "concentrated_mesh", "ring", "fly", "qtree", "tree4",
    "flatfly", "fattree", "dragonflynew",
)


def test_synthetic_bundle_without_logs_or_scenarios_cannot_claim_completion(
        tmp_path, monkeypatch):
    """Unmeasured lint/simulation rows must stay open, even beside other evidence.

    The bundle is what lets the flag follow the evidence: it names, per row,
    what was run and what it measured, and it is keyed to the design hash so
    evidence measured on one design can never carry the flag for another.

    This is a NEGATIVE test. It must not write the production bundle: doing so
    replaces a positive measurement with an OPEN row (the historical reason
    every family bundle read "A2 OPEN — no simulation scenarios supplied").
    """
    from veritx_dse.product.final_implementation import composed_family_verdict
    from veritx_dse.product import scope_evidence
    from veritx_dse.product.scope_evidence import (
        compose_family_evidence, write_evidence_bundle,
    )
    monkeypatch.setattr(scope_evidence, "BUNDLE_DIR",
                        str(tmp_path / "bundles"))

    # The rows that do not depend on the family are measured once.
    shared_rows = {
        "A6": _row_decode_proof(),
        "A8": _row_parity(),
        "A9": _row_axi5(),
        "A10": _row_multiflit(),
    }

    for family in COMPOSED_FAMILIES:
        request, _compiled, params = _family(family)
        rows = dict(shared_rows)
        rows["A3"] = _row_binding_witness(family)
        rows["A7"] = _row_cdg_proof(family)
        measured = compose_family_evidence(
            family=family, lint_status="PASS", sim_status="PASS",
            scenarios={}, attachment_measurement={
                "initiator_count": len(
                    list(getattr(params, "initiators", ()) or ())),
                "slice_count": len(
                    list(getattr(params, "initiators", ()) or ())),
                "endpoint_count": len(
                    list(getattr(params, "seats", ()) or ())),
                "seat_endpoint_ids": len(
                    {int(s[0]) for s in (getattr(params, "seats", ()) or ())}),
                "shared_router_seats": 0, "concentrator_routers": 0,
                "per_seat_scenarios": 0, "per_seat_scenarios_passed": 0})
        measured.update(rows)
        path = write_evidence_bundle(
            family=family, design_hash=request.design_hash(), rows=measured)

        verdict = composed_family_verdict(family=family, evidence=measured)
        assert path.is_file(), family
        assert "A2" in verdict["open_rows"], (family, verdict)
        assert verdict["final_implementation"] is False, (family, verdict)


CLOSED_FAMILIES = (
    "mesh", "torus", "concentrated_mesh", "ring", "fly", "qtree", "tree4",
    "flatfly", "fattree", "dragonflynew", "gec_mecs", "kncube",
)


def test_recorded_bundles_close_the_flag_for_measured_families():
    """The committed evidence must keep closing the flag it was measured for.

    This is the positive gate: each bundle is read back through the same
    design-hash check the manifest uses. If a bundle is overwritten with an
    OPEN row (the old negative-test bug), this test fails instead of the
    regression reaching a release matrix.
    """
    import json

    from veritx_dse.product.final_implementation import composed_family_verdict
    from veritx_dse.product.scope_evidence import load_evidence_bundle

    for family in CLOSED_FAMILIES:
        path = (REPO / "docs" / "product" / "evidence" /
                "final-implementation" / f"{family}.json")
        assert path.is_file(), family
        payload = json.loads(path.read_text())
        evidence = load_evidence_bundle(
            family=family, design_hash=payload["design_hash"])
        verdict = composed_family_verdict(family=family, evidence=evidence)
        assert verdict["final_implementation"] is True, \
            (family, verdict["open_rows"])
        assert verdict["open_rows"] == [], family
