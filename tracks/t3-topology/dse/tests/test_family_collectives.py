"""Family -> collective patterns: the declared mapping that used to be missing.

Covers the contract this module exists to hold:

* every family except ``custom`` derives a pattern;
* ``custom`` still refuses (explicit collectives required — unchanged);
* derivation NEVER invents a payload: no declared compute means refusal;
* an unsplit axis contributes no collective (a single-member group would be
  refused by lowering, so skipping states the truth);
* authoring completion fills a bare draft, and leaves an explicit author's
  collectives untouched.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import sys

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import (  # noqa: E402
    CollectiveDimension,
    CollectiveKind,
    ModelFamily,
)
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.workload.family_collectives import (  # noqa: E402
    FAMILY_PATTERNS,
    PAYLOAD_ROLES,
    FamilyCollectiveUnsupported,
    complete_family_collectives,
    declared_payloads,
    derive_family_collectives,
)

REPO = DSE.parents[2]
COMPUTE_DOC = (REPO / "tracks/t3-topology/examples"
               / "qwen3_moe_tp2_ep4_16tiles-v4.json")


def _with_compute():
    """A v4 request that declares compute stages (so payloads are derivable)."""
    return parse_request_doc(json.loads(COMPUTE_DOC.read_text()))


def _bare(family: ModelFamily, **parallelism):
    base = _with_compute()
    workload = replace(base.workload, model_family=family, collectives=(),
                       **parallelism)
    return replace(base, workload=workload)


class TestPatternTable:
    def test_every_family_is_declared(self):
        assert set(FAMILY_PATTERNS) == set(ModelFamily)

    def test_custom_has_no_pattern(self):
        assert FAMILY_PATTERNS[ModelFamily.CUSTOM] == ()

    def test_no_pattern_uses_pp(self):
        # PP-dimension collectives are refused by lowering; a pattern that
        # declared one would be unlowerable by construction.
        for family, patterns in FAMILY_PATTERNS.items():
            for pattern in patterns:
                assert pattern.dimension is not CollectiveDimension.PP, family

    def test_every_payload_role_maps_to_a_declared_field(self):
        for pattern in (p for ps in FAMILY_PATTERNS.values() for p in ps):
            assert pattern.payload_role in PAYLOAD_ROLES


class TestDerivation:
    @pytest.mark.parametrize("family", [
        ModelFamily.DENSE_TRANSFORMER,
        ModelFamily.MOE,
        ModelFamily.DIFFUSION,
        ModelFamily.CNN,
    ])
    def test_supported_family_derives(self, family):
        request = _bare(family, ep=4)
        derived = derive_family_collectives(
            family, tp=request.workload.tp, pp=request.workload.pp,
            ep=request.workload.ep, dp=request.workload.dp,
            payloads=declared_payloads(request))
        assert derived, f"{family.value} derived nothing"
        for collective in derived:
            assert isinstance(collective.kind, CollectiveKind)
            assert collective.payload_bytes > 0

    def test_custom_derives_nothing(self):
        request = _bare(ModelFamily.CUSTOM)
        assert derive_family_collectives(
            ModelFamily.CUSTOM, tp=8, pp=1, ep=4, dp=1,
            payloads=declared_payloads(request)) == ()

    def test_moe_declares_dispatch_and_combine(self):
        request = _bare(ModelFamily.MOE, ep=4)
        derived = derive_family_collectives(
            ModelFamily.MOE, tp=request.workload.tp, pp=1, ep=4, dp=1,
            payloads=declared_payloads(request))
        classes = [c.traffic_class for c in derived]
        assert "ep_dispatch" in classes
        assert "ep_combine" in classes
        assert all(c.dimension is CollectiveDimension.EP
                   for c in derived if c.traffic_class.startswith("ep_"))

    def test_unsplit_axis_contributes_no_collective(self):
        # ep=1: no expert parallel split, so MoE contributes only TP.
        request = _bare(ModelFamily.MOE, ep=1)
        derived = derive_family_collectives(
            ModelFamily.MOE, tp=request.workload.tp, pp=1, ep=1, dp=1,
            payloads=declared_payloads(request))
        assert [c.dimension for c in derived] == [CollectiveDimension.TP]

    def test_missing_payload_refuses_rather_than_inventing(self):
        # No payloads supplied at all: must refuse, never substitute a size.
        with pytest.raises(FamilyCollectiveUnsupported):
            derive_family_collectives(
                ModelFamily.DENSE_TRANSFORMER, tp=8, pp=1, ep=1, dp=1,
                payloads={})


class TestAuthoringCompletion:
    def test_bare_draft_gets_its_family_pattern(self):
        request = _bare(ModelFamily.MOE, ep=4)
        completed = complete_family_collectives(request)
        assert len(completed.workload.collectives) == len(
            FAMILY_PATTERNS[ModelFamily.MOE])

    def test_completion_is_identity_bearing(self):
        request = _bare(ModelFamily.DIFFUSION)
        completed = complete_family_collectives(request)
        assert completed.design_hash() != request.design_hash()

    def test_explicit_collectives_are_never_overwritten(self):
        base = _with_compute()
        assert base.workload.collectives, "fixture must declare collectives"
        assert complete_family_collectives(base) is base

    def test_custom_is_left_for_lowering_to_refuse(self):
        request = _bare(ModelFamily.CUSTOM)
        assert complete_family_collectives(request) is request

    def test_no_declared_compute_leaves_request_alone(self):
        # Without compute there is no honest payload source, so the request
        # must reach lowering unchanged and get lowering's own refusal.
        base = _with_compute()
        stripped = replace(base, workload=replace(base.workload,
                                                 collectives=()))
        object.__setattr__(stripped, "compute", None)
        assert complete_family_collectives(stripped) is stripped

    def test_completed_request_lowers(self):
        from veritx_dse.application.views import lowering_view
        for family in (ModelFamily.DENSE_TRANSFORMER, ModelFamily.MOE,
                       ModelFamily.DIFFUSION, ModelFamily.CNN):
            completed = complete_family_collectives(_bare(family, ep=4))
            lowered = lowering_view(completed)
            assert lowered["participant_count"] > 0, family.value
