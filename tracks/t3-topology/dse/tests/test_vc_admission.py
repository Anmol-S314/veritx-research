"""tests/test_vc_admission.py — P1B.3: workload ↔ VC admission.

A compiled fabric offering {A, B} with DEFAULT messages must refuse
before any backend spawn. DEFAULT is a guaranteed base class (VC0);
admission is proven per message class against the fabric's own VC
map, VC existence, and route-class binding.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veritx_dse.core.errors import UnsupportedSemantics  # noqa: E402
from veritx_dse.model.compile_model import CompileRequest  # noqa: E402
from veritx_dse.application.fabric_compiler import (  # noqa: E402
    FabricCompiler,
)
from veritx_dse.verification.gates import (  # noqa: E402
    assert_vc_admission, assert_workload_ready,
)
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    lower_compile_workload,
)
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifactV2,
)
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifactV2,
)

REPO_EXAMPLE = (DSE.parent / "examples" / "llama_dense_64tiles.json")


def _example_bundle():
    req = CompileRequest.from_dict(json.loads(REPO_EXAMPLE.read_text()))
    comp = FabricCompiler().compile(req)
    assert comp.status == "COMPILED"
    return req, comp.bundle


def _example_traffic(bundle=None, traffic_class="DEFAULT"):
    req, real_bundle = _example_bundle()
    graph = lower_compile_workload(req)
    logical = LogicalMessageArtifactV2(
        graph=graph, traffic_class=traffic_class)
    return PhysicalTrafficArtifactV2(
        logical=logical, bundle=bundle or real_bundle)


class TestDefaultBaseClass:
    def test_default_is_always_a_base_class(self):
        _, bundle = _example_bundle()
        classes = dict(bundle.vc_assignment.traffic_class_to_vcs)
        assert classes["DEFAULT"] == (0,)

    def test_default_admitted_passes(self):
        assert_workload_ready(_example_traffic())

    def test_dependency_classes_still_separate(self):
        _, bundle = _example_bundle()
        classes = dict(bundle.vc_assignment.traffic_class_to_vcs)
        assert set(classes) == {"DEFAULT", "prefill-attn", "prefill-ffn"}


class TestAdmissionRefusals:
    def test_absent_class_refuses(self):
        pt = _example_traffic(traffic_class="BOGUS")
        with pytest.raises(UnsupportedSemantics, match="BOGUS"):
            assert_workload_ready(pt)

    def test_class_referencing_unknown_vc_refuses(self):
        pt = _example_traffic()
        vc = SimpleNamespace(
            traffic_class_to_vcs=(("DEFAULT", (7,)),),
            vc_to_routing_class=((0, "DOR_XY"),))
        stub = SimpleNamespace(
            logical=pt.logical,
            bundle=SimpleNamespace(
                vc_assignment=vc,
                resolved_route=SimpleNamespace(
                    routing_classes=("DOR_XY",))))
        with pytest.raises(UnsupportedSemantics, match="no.*binding|VC 7"):
            assert_vc_admission(stub)

    def test_vc_referencing_missing_route_class_refuses(self):
        pt = _example_traffic()
        vc = SimpleNamespace(
            traffic_class_to_vcs=(("DEFAULT", (0,)),),
            vc_to_routing_class=((0, "NOPE"),))
        stub = SimpleNamespace(
            logical=pt.logical,
            bundle=SimpleNamespace(
                vc_assignment=vc,
                resolved_route=SimpleNamespace(
                    routing_classes=("DOR_XY",))))
        with pytest.raises(UnsupportedSemantics, match="NOPE"):
            assert_vc_admission(stub)

    def test_foreign_vc_artifact_transplant_refuses(self):
        """A valid standalone VC structure from a fabric that never
        derived DEFAULT (the pre-P1B.3 shape) transplanted into this
        bundle: DEFAULT messages refuse at the admission seam — the
        earliest boundary, before bundle revalidation would also
        fail. (Same-route-class transplants with matching maps pass
        the gate legitimately; the certificate's resolved-route
        binding is what detects those.)"""
        _, host = _example_bundle()
        va = host.vc_assignment
        stripped = dataclasses.replace(
            va, traffic_class_to_vcs=tuple(
                p for p in va.traffic_class_to_vcs if p[0] != "DEFAULT"))
        assert "DEFAULT" not in dict(stripped.traffic_class_to_vcs)
        tampered = dataclasses.replace(host, vc_assignment=stripped)
        pt = _example_traffic()
        stub = SimpleNamespace(logical=pt.logical, bundle=tampered)
        with pytest.raises(UnsupportedSemantics, match="DEFAULT"):
            assert_workload_ready(stub)
