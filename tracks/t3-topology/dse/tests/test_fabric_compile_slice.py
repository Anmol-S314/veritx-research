"""tests/test_fabric_compile_slice.py — P1.5: one mesh, every layer.

Canonical scenario mesh_dense_64 driven across the compiler layers
with shared fixtures: request → inventory → mapping → topology →
attachment → route → VC → fabric → resolved fabric → certificate.
Plus metamorphic checks (FREE/label changes must not move fabric
semantics; link-width must; cycles must separate or refuse) and
tamper/transplant attacks on the certificate.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.application.compile import compile_bundle  # noqa: E402
from veritx_dse.application.fabric_compiler import (  # noqa: E402
    FabricCompiler,
)
from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequest, NocConfig, OutputFormat, TopologyFamily,
)
from veritx_dse.verification.certificate import (  # noqa: E402
    verify_compiled_fabric,
)

REPO_EXAMPLE = (DSE.parent / "examples" /
                "llama_dense_64tiles.json")


def _chain(**kw):
    kw.setdefault("tp", 8)
    kw.setdefault("pp", 1)
    kw.setdefault("ep", 1)
    kw.setdefault("dp", 1)
    kw.setdefault("n_agents", 64)
    kw.setdefault("hbm_count", 8)
    return build_chain(**kw)


def _replace_request(cr: CompileRequest, **kw) -> CompileRequest:
    return dataclasses.replace(cr, **kw)


class TestMeshDenseLayers:
    def test_layers_link_by_hash(self):
        bundle = compile_bundle(_chain().cr)
        assert bundle.attachment.attachment_hash() is not None
        assert bundle.router_route.topology_hash == \
            bundle.topology.topology_hash()
        assert bundle.resolved_route is not None
        assert bundle.vc_assignment.resolved_route_hash == \
            bundle.resolved_route.resolved_route_hash()
        assert [rc for _, rc in
                bundle.vc_assignment.vc_to_routing_class] == \
            ["DOR_XY"] * bundle.vc_assignment.vc_count
        assert bundle.fabric.fabric_hash() is not None
        assert bundle.resolved_fabric.fabric_hash == \
            bundle.fabric.fabric_hash()

    def test_full_certificate_passes(self):
        bundle = compile_bundle(_chain().cr)
        cert = verify_compiled_fabric(bundle)
        assert cert.overall == "PASS"
        assert cert.resolved_fabric_hash == \
            bundle.resolved_fabric.resolved_fabric_hash()


class TestMetamorphic:
    def test_free_output_format_moves_design_not_fabric(self):
        base = _chain().cr
        other = _replace_request(
            base, noc_config=dataclasses.replace(
                base.noc_config,
                output_formats=(OutputFormat.JSON, OutputFormat.PDF)))
        assert other.design_hash() != base.design_hash()
        a = compile_bundle(base)
        b = compile_bundle(other)
        assert b.fabric.fabric_hash() == a.fabric.fabric_hash()
        assert b.topology.topology_hash() == a.topology.topology_hash()
        assert b.vc_assignment.vc_assignment_hash() == \
            a.vc_assignment.vc_assignment_hash()

    def test_link_width_moves_fabric_not_mapping(self):
        base = _chain().cr
        other = _replace_request(
            base, noc_config=dataclasses.replace(
                base.noc_config, link_width=128))
        a = compile_bundle(base)
        b = compile_bundle(other)
        assert b.topology.topology_hash() != a.topology.topology_hash()
        assert b.fabric.fabric_hash() != a.fabric.fabric_hash()
        assert b.resolved_fabric.resolved_fabric_hash() != \
            a.resolved_fabric.resolved_fabric_hash()
        assert b.mapping.mapping_hash() == a.mapping.mapping_hash()

    def test_label_only_change_moves_design_not_fabric(self):
        base = _chain().cr
        other = _replace_request(
            base, workload=dataclasses.replace(
                base.workload, model_name="renamed-only"))
        assert other.design_hash() != base.design_hash()
        a = compile_bundle(base)
        b = compile_bundle(other)
        assert b.fabric.fabric_hash() == a.fabric.fabric_hash()

    def test_blocking_cycle_separates_vcs(self):
        from veritx_dse.model.compile_model import (
            Dependency, DepKind, DependencyGraph,
        )
        base = _chain().cr
        acyclic = _replace_request(
            base, dependencies=DependencyGraph(
                [Dependency("A", "B", DepKind.BLOCKING)]))
        cyclic = _replace_request(
            base, dependencies=DependencyGraph(
                [Dependency("A", "B", DepKind.BLOCKING),
                 Dependency("B", "A", DepKind.BLOCKING)]))
        va = compile_bundle(acyclic).vc_assignment
        vc = compile_bundle(cyclic).vc_assignment
        assert va.vc_count == 1
        assert vc.vc_count == 2
        assert verify_compiled_fabric(
            compile_bundle(cyclic)).overall == "PASS"


class TestCertificateAttacks:
    def test_tampered_route_fails_certificate(self):
        a = compile_bundle(_chain().cr)
        b = compile_bundle(_chain(link_width=128).cr)
        tampered = dataclasses.replace(a, router_route=b.router_route)
        cert = verify_compiled_fabric(tampered)
        assert cert.overall == "FAIL"
        failed = {o.obligation for o in cert.obligations
                  if o.status != "PASS"}
        assert "ROUTE_LEGAL" in failed

    def test_transplanted_vc_fails_certificate(self):
        a = compile_bundle(_chain().cr)
        b = compile_bundle(_chain(link_width=128).cr)
        tampered = dataclasses.replace(a, vc_assignment=b.vc_assignment)
        cert = verify_compiled_fabric(tampered)
        assert cert.overall == "FAIL"
        failed = {o.obligation for o in cert.obligations
                  if o.status != "PASS"}
        assert "VC_ASSIGNMENT_VALID" in failed


class TestCliVerticalSlice:
    def test_veritx_compile_example(self, tmp_path):
        assert REPO_EXAMPLE.is_file(), "example request missing"
        out = tmp_path / "build"
        proc = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "compile",
             str(REPO_EXAMPLE), "--out", str(out)],
            cwd=DSE, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stderr[-2000:]
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["status"] == "COMPILED"
        for name in ("compile_request.json", "resolved_fabric.json",
                     "topology.json", "mapping.json", "route.json",
                     "vc_assignment.json",
                     "verification/certificate.json"):
            assert (out / name).is_file(), name
        cert = json.loads(
            (out / "verification/certificate.json").read_text())
        assert cert["overall"] == "PASS"
        assert manifest["certificate_id"] == cert["certificate_id"]
