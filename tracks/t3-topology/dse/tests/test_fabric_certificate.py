"""tests/test_fabric_certificate.py — P1.4: verified fabric or no fabric.

The certificate binds the resolved fabric to one verdict per LOCKED
obligation with method + evidence. A failing obligation means the
compiler does not present a bundle (INVALID with the certificate as
evidence); refused semantics mean UNSUPPORTED.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.application.fabric_compiler import (  # noqa: E402
    Compilation, FabricCompiler,
)
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.verification.certificate import (  # noqa: E402
    OBLIGATIONS, VerificationCertificate, verify_compiled_fabric,
)


def _mesh_chain(**kw):
    kw.setdefault("tp", 1)
    kw.setdefault("pp", 1)
    kw.setdefault("ep", 1)
    kw.setdefault("dp", 4)
    kw.setdefault("n_agents", 4)
    return build_chain(**kw)


class TestCertificate:
    def test_mesh_compiles_with_passing_certificate(self):
        comp = FabricCompiler().compile(_mesh_chain().cr)
        assert comp.status == "COMPILED"
        assert comp.bundle is not None
        cert = comp.certificate
        assert cert.overall == "PASS"
        assert sorted(o.obligation for o in cert.obligations) == \
            sorted(OBLIGATIONS)
        assert all(o.status == "PASS" for o in cert.obligations)
        assert cert.resolved_fabric_hash == \
            comp.bundle.resolved_fabric.resolved_fabric_hash()
        by_name = {o.obligation: o for o in cert.obligations}
        assert by_name["DEADLOCK_FREE"].method == "channel-vc-cdg/v1"
        assert by_name["DEADLOCK_FREE"].evidence["acyclic"] is True
        assert by_name["DEADLOCK_FREE"].evidence["sccs_gt_1"] == 0

    def test_certificate_round_trips(self):
        comp = FabricCompiler().compile(_mesh_chain().cr)
        doc = comp.certificate.to_dict()
        loaded = VerificationCertificate.from_dict(doc)
        assert loaded.certificate_id() == comp.certificate.certificate_id()

    def test_resigned_certificate_refuses(self):
        comp = FabricCompiler().compile(_mesh_chain().cr)
        doc = comp.certificate.to_dict()
        doc["obligations"][0]["evidence"]["routers"] = 999
        with pytest.raises(Exception, match="certificate_id"):
            VerificationCertificate.from_dict(doc)

    def test_transplanted_vc_fails_certification(self):
        """Another route's VC structure inside this fabric: the VC
        obligation fails and no bundle is presented."""
        from veritx_dse.application.compile import compile_bundle
        a = compile_bundle(_mesh_chain().cr)
        b = compile_bundle(_mesh_chain(link_width=128).cr)
        assert a.vc_assignment.vc_assignment_hash() != \
            b.vc_assignment.vc_assignment_hash()
        tampered = dataclasses.replace(a, vc_assignment=b.vc_assignment)
        cert = verify_compiled_fabric(tampered)
        assert cert.overall == "FAIL"
        by_name = {o.obligation: o for o in cert.obligations}
        assert by_name["VC_ASSIGNMENT_VALID"].status == "FAIL"

    def test_torus_is_unsupported_not_invalid(self):
        comp = FabricCompiler().compile(
            _mesh_chain(family=TopologyFamily.TORUS).cr)
        assert comp.status == "UNSUPPORTED"
        assert comp.bundle is None
        assert comp.certificate is None
        assert "UNSUPPORTED" in comp.error

    def test_contradictory_certificate_refuses(self):
        comp = FabricCompiler().compile(_mesh_chain().cr)
        good = list(comp.certificate.obligations)
        bad = dataclasses.replace(good[0], status="FAIL")
        with pytest.raises(Exception, match="contradictory"):
            VerificationCertificate(
                resolved_fabric_hash=comp.certificate.resolved_fabric_hash,
                compiler_semantics_version=comp.certificate
                .compiler_semantics_version,
                obligations=tuple([bad] + good[1:]), overall="PASS")

    def test_compilation_holds_no_bundle_on_invalid(self):
        with pytest.raises(Exception, match="must not present a bundle"):
            Compilation(status="INVALID", request=_mesh_chain().cr,
                        bundle=object(), certificate=None, error="x")
