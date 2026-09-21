"""tests/test_p1b_certificate_provenance.py — P1B A1: deadlock provenance.

The P1.4 certificate certified DEADLOCK_FREE with router_behavior_hash=""
while channel_vc_cdg.certify_channel_vc_deadlock accepts (and binds) the
real hash. certificate.py now passes
bundle.router_behavior.router_behavior_hash() and preserves the
authenticated parent identities in the obligation evidence.

Proves: the binding is live (non-empty, equals the bundle's behavior),
tampering the router behavior fails certification (and the evidence
names the tampered hash instead of silently keeping the old one), and a
VC artifact transplanted from another route fails the deadlock
obligation itself (not only the VC-validity seam).
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.application.compile import compile_bundle  # noqa: E402
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.model.router_behavior import (  # noqa: E402
    derive_router_behavior,
)
from veritx_dse.verification.certificate import (  # noqa: E402
    verify_compiled_fabric,
)


def _mesh_bundle(**kw):
    kw.setdefault("tp", 2)
    kw.setdefault("pp", 1)
    kw.setdefault("ep", 1)
    kw.setdefault("dp", 2)
    kw.setdefault("n_agents", 4)
    kw.setdefault("family", TopologyFamily.MESH)
    return compile_bundle(build_chain(**kw).cr)


def _deadlock_evidence(cert):
    return next(
        o for o in cert.obligations if o.obligation == "DEADLOCK_FREE")


class TestRouterBehaviorBound:
    def test_deadlock_evidence_binds_the_live_behavior_hash(self):
        bundle = _mesh_bundle()
        cert = verify_compiled_fabric(bundle)
        assert cert.overall == "PASS"
        ev = _deadlock_evidence(cert).evidence
        assert ev["router_behavior_hash"] == \
            bundle.router_behavior.router_behavior_hash()
        assert ev["router_behavior_hash"] != ""

    def test_parent_identities_preserved_in_obligation_evidence(self):
        bundle = _mesh_bundle()
        cert = verify_compiled_fabric(bundle)
        assert cert.overall == "PASS"
        ev = _deadlock_evidence(cert).evidence
        assert ev["topology_hash"] == bundle.topology.topology_hash()
        assert ev["resolved_route_hash"] == \
            bundle.resolved_route.resolved_route_hash()
        assert ev["router_route_hash"] == bundle.router_route.artifact_hash
        assert ev["vc_assignment_hash"] == \
            bundle.vc_assignment.vc_assignment_hash()
        assert ev["router_behavior_hash"] == \
            bundle.router_behavior.router_behavior_hash()


class TestTamperedRouterBehavior:
    def test_tampered_router_behavior_fails_certification(self):
        bundle = _mesh_bundle()
        assert verify_compiled_fabric(bundle).overall == "PASS"
        # A different-but-internally-valid behavior for the SAME VC
        # structure: the tamper is a content substitution, not a
        # malformed artifact.
        tampered_rb = derive_router_behavior(
            vc_assignment=bundle.vc_assignment, buffer_depth_flits=16)
        assert tampered_rb.router_behavior_hash() != \
            bundle.router_behavior.router_behavior_hash()
        tampered = dataclasses.replace(bundle,
                                       router_behavior=tampered_rb)
        cert = verify_compiled_fabric(tampered)
        assert cert.overall == "FAIL"
        failed = {o.obligation for o in cert.obligations
                  if o.status != "PASS"}
        assert failed  # the substitution is detected, never certified

    def test_tamper_evidence_names_the_tampered_hash(self):
        bundle = _mesh_bundle()
        tampered_rb = derive_router_behavior(
            vc_assignment=bundle.vc_assignment, buffer_depth_flits=16)
        tampered = dataclasses.replace(bundle,
                                       router_behavior=tampered_rb)
        cert = verify_compiled_fabric(tampered)
        ev = _deadlock_evidence(cert).evidence
        # The deadlock proof is ABOUT the tampered behavior (no silent
        # "" and no stale pre-tamper hash): provenance moved with the
        # substitution, and the bundle seam fails the certificate.
        assert ev["router_behavior_hash"] == \
            tampered_rb.router_behavior_hash()


class TestTransplantedVcArtifact:
    def test_vc_from_another_route_fails_the_deadlock_obligation(self):
        bundle = _mesh_bundle()
        other = _mesh_bundle(tp=4, pp=1, ep=1, dp=1, n_agents=8)
        assert other.vc_assignment.vc_assignment_hash() != \
            bundle.vc_assignment.vc_assignment_hash()
        transplanted = dataclasses.replace(
            bundle, vc_assignment=other.vc_assignment)
        cert = verify_compiled_fabric(transplanted)
        assert cert.overall == "FAIL"
        deadlock = _deadlock_evidence(cert)
        assert deadlock.status == "FAIL"
        assert "does not bind this resolved route" in \
            deadlock.evidence.get("failure_reason", "")
