"""Wave B3.7g tests — closed-world backend parameter audit + VC predicates.

Pins the invariant: no result-affecting value consumed by the certified
BookSim path comes from an unnamed compiled default. Every active field
is either emitted (with an owner) or documented inactive with a source
location; every BACKEND_PROFILE value is explicit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import (  # noqa: E402
    TRACE, lower_booksim_standalone, rebuild_bundle,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_backend_execution_qualification import _vc  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    BOOKSIM_CONFIG_KEY_ORDER, BOOKSIM_STANDALONE_OWNERSHIP,
    prepare_booksim_standalone,
)
from veritx_dse.backend.booksim_profile import (  # noqa: E402
    BOOKSIM_CERTIFIED_CONFIG_AUDIT, BOOKSIM_SERVING_PROFILE,
    BOOKSIM_STANDALONE_PROFILE,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    CertificationEffect, ParameterOwner, RepresentationStatus,
    SemanticDimension,
)
from veritx_dse.backend.serving import (  # noqa: E402
    SERVING_BOOKSIM2_OWNERSHIP, prepare_serving_booksim,
)

_PROFILE = BOOKSIM_STANDALONE_PROFILE
_SERVING = BOOKSIM_SERVING_PROFILE


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


def _config_keys(prepared):
    return tuple(line.split(" = ")[0]
                 for line in prepared.rendered.file("config.cfg")
                 .decode().splitlines())


class TestAuditTable:
    def test_every_field_has_source_and_unique_name(self):
        names = [row.name for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT]
        assert len(names) == len(set(names))
        for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT:
            assert row.source, row.name
            assert isinstance(row.owner, ParameterOwner)

    def test_inactive_fields_state_why_and_pin_nothing(self):
        inactive = [row for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT
                    if row.owner is ParameterOwner.INACTIVE_FOR_PROFILE]
        assert inactive, "audit must document inactive fields"
        for row in inactive:
            assert row.note, f"{row.name} needs an inactivity reason"
            assert row.pin is None, f"{row.name} must not pin"

    def test_backend_profile_fields_are_explicit(self):
        # traffic/sample_period are per-target workload values in the base
        # audit; every other BACKEND_PROFILE row carries a literal pin.
        for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT:
            if row.owner is ParameterOwner.BACKEND_PROFILE \
                    and row.name not in ("traffic", "sample_period"):
                assert row.pin is not None, f"{row.name} needs an explicit pin"

    def test_active_sets_match_between_targets(self):
        assert _PROFILE.active_names() == _SERVING.active_names()
        assert _PROFILE.inactive_names() == _SERVING.inactive_names()

    def test_ownership_tables_derive_from_the_profiles(self):
        assert BOOKSIM_STANDALONE_OWNERSHIP == _PROFILE.ownership()
        assert SERVING_BOOKSIM2_OWNERSHIP == _SERVING.ownership()
        # P1B-Q1: the master key order covers EVERY certified profile;
        # each profile emits its own active subset in master order.
        from veritx_dse.backend.booksim import (
            BOOKSIM_MESH_DOR_PROFILE, profile_key_order,
        )
        from veritx_dse.backend.booksim_profile import (
            BOOKSIM_MESH_DOR_PROFILE as MESH_SPEC,
        )
        assert set(_PROFILE.active_names()) <= set(BOOKSIM_CONFIG_KEY_ORDER)
        assert set(MESH_SPEC.active_names()) <= \
            set(BOOKSIM_CONFIG_KEY_ORDER)
        assert profile_key_order(_PROFILE) == tuple(
            k for k in BOOKSIM_CONFIG_KEY_ORDER
            if k in _PROFILE.active_names())
        assert profile_key_order(MESH_SPEC) == tuple(
            k for k in BOOKSIM_CONFIG_KEY_ORDER
            if k in MESH_SPEC.active_names())
        assert BOOKSIM_MESH_DOR_PROFILE == MESH_SPEC.profile_id

    def test_source_locations_spot_check(self):
        assert "iq_router.cpp:61" in _PROFILE.source_of("speculative")
        assert "iq_router.cpp:57" in _PROFILE.source_of("vc_busy_when_full")
        assert "vc.cpp:70" in _PROFILE.source_of("vc_priority_donation")
        assert "buffer_state.cpp:90" in _PROFILE.source_of("buf_size")
        assert "trafficmanager.cpp:227" in _PROFILE.source_of("traffic")
        assert "anynet.cpp:83" in _PROFILE.source_of("routing_dump_file")


class TestClosedWorldEmission:
    def test_standalone_config_is_exactly_the_active_audit_set(
            self, bundle):
        from veritx_dse.backend.booksim import profile_key_order
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        keys = _config_keys(prepared)
        assert keys == profile_key_order(_PROFILE)
        assert set(keys) == _PROFILE.active_names()
        assert not (set(keys) & _PROFILE.inactive_names())

    def test_every_backend_profile_pin_is_emitted_verbatim(
            self, bundle):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        cfg = {}
        for line in prepared.rendered.file("config.cfg").decode().splitlines():
            key, value = line.split(" = ", 1)
            cfg[key] = value.rstrip(";")
        for name, value in _PROFILE.pinned_values().items():
            expected = ("1" if value is True else "0" if value is False
                        else repr(value) if isinstance(value, float)
                        else str(value))
            assert cfg[name] == expected, name

    def test_fabric_derived_values_come_from_artifacts(self, bundle):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        cfg = dict(line.split(" = ", 1)
                   for line in prepared.rendered.file("config.cfg")
                   .decode().splitlines())
        assert cfg["num_vcs"] == f"{bundle.vc_assignment.vc_count};"
        assert cfg["vc_buf_size"] == \
            f"{bundle.router_behavior.input_buffer_depth_flits_per_vc};"
        assert cfg["vc_allocator"] == \
            f"{bundle.router_behavior.vc_allocator.value};"

    def test_serving_config_is_the_same_closed_set(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        keys = _config_keys(prepared)
        assert set(keys) == _SERVING.active_names()
        assert not (set(keys) & _SERVING.inactive_names())

    def test_packet_size_is_not_an_authority(self, bundle, tmp_path):
        for prepared in (
                prepare_booksim_standalone(bundle, workload_trace=TRACE),
                prepare_serving_booksim(bundle, out_dir=tmp_path,
                                        physical_dims=(2, 2))):
            assert "packet_size" not in _config_keys(prepared)

    def test_inactive_fields_never_emitted(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        keys = set(_config_keys(prepared))
        for name in _PROFILE.inactive_names():
            assert name not in keys, name


class TestVCSupportPredicate:
    def test_golden_multi_class_assignment_is_coarsened(self, bundle):
        art = lower_booksim_standalone(bundle)
        row = art.binding(SemanticDimension.VC_CLASS_ASSIGNMENT)
        assert row.representation_status is RepresentationStatus.COARSENED
        assert row.supported_domain == ""

    def test_single_class_all_vcs_is_exact_with_domain(self, chain):
        vc = _vc(chain, classes={"DEFAULT": [0, 1]})
        art = lower_booksim_standalone(rebuild_bundle(chain, vc=vc))
        row = art.binding(SemanticDimension.VC_CLASS_ASSIGNMENT)
        assert row.representation_status is RepresentationStatus.EXACT
        assert "single traffic class" in row.supported_domain

    def test_identity_transitions_are_exact_with_domain(self, bundle):
        row = lower_booksim_standalone(bundle) \
            .binding(SemanticDimension.VC_TRANSITIONS)
        assert row.representation_status is RepresentationStatus.EXACT
        assert "identity" in row.supported_domain

    def test_cross_vc_transitions_are_unrepresentable(self, chain):
        vc = _vc(chain, transitions=((0, 1), (1, 0)))
        art = lower_booksim_standalone(rebuild_bundle(chain, vc=vc))
        row = art.binding(SemanticDimension.VC_TRANSITIONS)
        assert row.representation_status is \
            RepresentationStatus.UNREPRESENTABLE
        assert row.certification_effect is \
            CertificationEffect.BLOCKS_EXACT_FABRIC
        assert row.supported_domain == ""
        assert not art.exact_fabric_eligible()

    def test_empty_escape_is_exact_with_domain(self, bundle):
        row = lower_booksim_standalone(bundle) \
            .binding(SemanticDimension.ESCAPE_VCS)
        assert row.representation_status is RepresentationStatus.EXACT
        assert "escape_vcs == ()" in row.supported_domain

    def test_nonempty_escape_blocks_exact_fabric(self, chain):
        art = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, escape=(0,))))
        row = art.binding(SemanticDimension.ESCAPE_VCS)
        assert row.representation_status is \
            RepresentationStatus.UNREPRESENTABLE
        assert row.certification_effect is \
            CertificationEffect.BLOCKS_EXACT_FABRIC
        assert not art.exact_fabric_eligible()

    def test_every_exact_binding_declares_a_domain(self, bundle):
        art = lower_booksim_standalone(bundle)
        for row in art.semantic_bindings:
            if row.representation_status in (
                    RepresentationStatus.EXACT,
                    RepresentationStatus.DERIVED_EXACT):
                assert row.supported_domain, row.dimension.value

    def test_conditional_domains_name_their_restriction(self, bundle):
        art = lower_booksim_standalone(bundle)
        assert "uniform" in art.binding(
            SemanticDimension.CHANNEL_LATENCY).supported_domain
        assert "route_weight == 1" in art.binding(
            SemanticDimension.ROUTE_WEIGHT).supported_domain
        assert "ANYNET_MIN_HOPS" in art.binding(
            SemanticDimension.VC_ROUTING_CLASS).supported_domain
        assert "max_packet_flits" in art.binding(
            SemanticDimension.PACKET_MAX_FLITS).supported_domain
