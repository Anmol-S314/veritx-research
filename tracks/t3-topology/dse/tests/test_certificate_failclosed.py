"""Certificate fail-closed boundary (§5.1/§5.2).

A software fault in a trusted internal function must ABORT certification;
it must never be laundered into an obligation FAIL (which is a design
verdict). A genuine semantic invalidity may become FAIL. These two paths
are not interchangeable, and this module pins the difference.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_rt_chain_helpers import (  # noqa: E402
    build_chain, compose, make_resolved_fabric,
)

from veritx_dse.model.resolved_bundle import (  # noqa: E402
    make_resolved_fabric_bundle,
)
from veritx_dse.model.vc_assignment import VCAssignmentError  # noqa: E402
from veritx_dse.verification import certificate as cert_module  # noqa: E402
from veritx_dse.verification.certificate import (  # noqa: E402
    verify_compiled_fabric,
)


def _bundle():
    chain = build_chain()
    fabric = compose(chain)
    rf = make_resolved_fabric(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad, fabric=fabric)
    return make_resolved_fabric_bundle(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=chain.vc,
        packet_format=chain.pf, router_behavior=chain.rb,
        address_decode=chain.ad, fabric=fabric, resolved_fabric=rf)


def test_valid_bundle_passes_certificate():
    assert verify_compiled_fabric(_bundle()).overall == "PASS"


def test_semantic_invalidity_becomes_obligation_fail(monkeypatch):
    """An expected semantic refusal is a design verdict, not an abort."""
    bundle = _bundle()

    def refuse(self, *_a, **_k):
        raise VCAssignmentError("injected semantic refusal")

    monkeypatch.setattr(
        type(bundle.vc_assignment), "validate_against", refuse)
    cert = verify_compiled_fabric(bundle)
    assert cert.overall == "FAIL"
    ob = {o.obligation: o for o in cert.obligations}
    assert ob["VC_ASSIGNMENT_VALID"].status == "FAIL"
    assert "injected semantic refusal" in \
        ob["VC_ASSIGNMENT_VALID"].evidence["failure_reason"]


@pytest.mark.parametrize("fault", [
    RuntimeError("injected programmer fault"),
    AttributeError("injected programmer fault"),
    NameError("injected programmer fault"),
    TypeError("injected programmer fault"),
])
def test_programmer_fault_aborts_certification(monkeypatch, fault):
    bundle = _bundle()

    def boom(self, *_a, **_k):
        raise fault

    monkeypatch.setattr(type(bundle.attachment), "validate_against", boom)
    with pytest.raises(type(fault)):
        verify_compiled_fabric(bundle)


def test_deadlock_diagnostic_failure_aborts_not_pass(monkeypatch):
    """The removed ``except Exception: pass`` must not hide a diagnostic
    fault on the DEADLOCK_FREE PASS path."""
    bundle = _bundle()

    def boom(_adj):
        raise RuntimeError("injected diagnostic fault")

    monkeypatch.setattr(cert_module, "_scc_count", boom)
    with pytest.raises(RuntimeError):
        verify_compiled_fabric(bundle)
