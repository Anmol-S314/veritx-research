"""Wave B3.7a tests — backend projection/input identity contracts.

No execution is wired here: these tests pin the identity algebra, strict
parsing and immutability before any lowerer exists.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend.contracts import (  # noqa: E402
    BACKEND_CONFIG_SCHEMA_VERSION, BACKEND_INPUT_SCHEMA_VERSION,
    BackendConfigArtifact, BackendConfigError, BackendInputError,
    BackendInputManifest, BackendTarget, CertificationEffect, RenderedInput,
    RepresentationStatus, SemanticBinding, SemanticDimension,
)

H64 = "a" * 64
H64B = "b" * 64
H64C = "c" * 64


def _binding(dim, *, status=RepresentationStatus.EXACT, effect=None,
             fields=(), reason="", source=H64):
    if effect is None:
        effect = (CertificationEffect.NONE
                  if status in (RepresentationStatus.EXACT,
                                RepresentationStatus.DERIVED_EXACT)
                  else CertificationEffect.FIDELITY_DOWNGRADE)
    if not reason and status not in (RepresentationStatus.EXACT,
                                     RepresentationStatus.DERIVED_EXACT):
        reason = f"{dim.value} is not exact in this test"
    return SemanticBinding(
        dimension=dim, source_identity=source, representation_status=status,
        backend_fields=tuple(sorted(fields)), reason=reason,
        certification_effect=effect,
    )


def _bindings(**overrides):
    """One binding per dimension; override per dimension name."""
    out = []
    for dim in SemanticDimension:
        out.append(_binding(dim, **overrides.get(dim.value, {})))
    return tuple(out)


def _artifact(**kw):
    defaults = dict(
        backend_target=BackendTarget.BOOKSIM_STANDALONE,
        backend_profile="CERTIFIED_TEST_V1",
        backend_semantics_version="test-1",
        lowerer_version="B37/1",
        resolved_fabric_hash=H64,
        fabric_hash=H64B,
        normalized_parameters=(("num_vcs", 4), ("vc_buf_size", 8)),
        semantic_bindings=_bindings(),
    )
    defaults.update(kw)
    return BackendConfigArtifact(**defaults)


def _manifest(**kw):
    defaults = dict(
        backend_config_hash=_artifact().backend_config_hash(),
        workload_hash=H64C,
        execution_mode="REAL_SIMULATION",
        seed=7,
        seed_policy="explicit",
        rendered_inputs=(RenderedInput(
            role="topology", logical_name="topology.anynet",
            sha256="d" * 64, size=123),),
        invocation_args=(("config", "config.cfg"),),
    )
    defaults.update(kw)
    return BackendInputManifest(**defaults)


# ── config artifact identity algebra ────────────────────────────────────

class TestConfigIdentity:
    def test_config_hash_is_domain_separated_sha256(self):
        import hashlib
        from veritx_dse.core.spec import canonical_json
        a = _artifact()
        body = (("srota/BackendConfig/v1\0")
                + canonical_json(a.identity_dict()))
        assert a.backend_config_hash() == hashlib.sha256(
            body.encode()).hexdigest()
        assert len(a.backend_config_hash()) == 64
        assert a.schema_version == BACKEND_CONFIG_SCHEMA_VERSION == 1

    def test_same_semantics_different_path_same_hash(self):
        # Path-INDEPENDENT identity: only logical names enter the artifact,
        # and absolute paths are refused outright.
        a = _artifact(normalized_parameters=(
            ("network_file", "topology.anynet"), ("num_vcs", 4)))
        b = _artifact(normalized_parameters=(
            ("network_file", "topology.anynet"), ("num_vcs", 4)))
        assert a.backend_config_hash() == b.backend_config_hash()

    def test_absolute_path_in_parameters_refused(self):
        with pytest.raises(BackendConfigError, match="absolute path"):
            _artifact(normalized_parameters=(
                ("network_file", "/tmp/run-A/topology.anynet"),))

    def test_absolute_path_nested_refused(self):
        with pytest.raises(BackendConfigError, match="absolute path"):
            _artifact(normalized_parameters=(
                ("args", ("--trace", "/tmp/x")),))

    def test_same_semantics_different_json_formatting_same_hash(self):
        a = _artifact()
        blob = a.to_dict()
        # Re-parse from equivalent-but-reformatted JSON (dict key order and
        # whitespace are irrelevant to canonical JSON).
        import json
        shuffled = json.loads(json.dumps(blob, indent=4, sort_keys=False))
        b = BackendConfigArtifact.from_dict(shuffled)
        assert b.backend_config_hash() == a.backend_config_hash()

    def test_lowerer_version_changes_hash(self):
        b = _artifact(lowerer_version="B37/2")
        assert b.backend_config_hash() != _artifact().backend_config_hash()

    def test_target_change_changes_hash(self):
        b = _artifact(backend_target=BackendTarget.SERVING_BOOKSIM2)
        assert b.backend_config_hash() != _artifact().backend_config_hash()

    def test_profile_change_changes_hash(self):
        b = _artifact(backend_profile="OTHER_PROFILE")
        assert b.backend_config_hash() != _artifact().backend_config_hash()

    def test_semantics_version_change_changes_hash(self):
        b = _artifact(backend_semantics_version="test-2")
        assert b.backend_config_hash() != _artifact().backend_config_hash()

    def test_parent_hash_change_changes_hash(self):
        b = _artifact(fabric_hash="e" * 64)
        assert b.backend_config_hash() != _artifact().backend_config_hash()

    def test_parameter_change_changes_hash(self):
        b = _artifact(normalized_parameters=(
            ("num_vcs", 8), ("vc_buf_size", 8)))
        assert b.backend_config_hash() != _artifact().backend_config_hash()

    def test_exact_binding_field_change_changes_hash(self):
        binds = list(_bindings())
        idx = next(i for i, b in enumerate(binds)
                   if b.dimension is SemanticDimension.VC_COUNT)
        binds[idx] = _binding(SemanticDimension.VC_COUNT,
                              fields=(("num_vcs", 8),))
        b = _artifact(semantic_bindings=tuple(binds))
        assert b.backend_config_hash() != _artifact().backend_config_hash()

    def test_loss_classification_change_changes_hash(self):
        coarsened = _bindings(**{"VC_COUNT": {
            "status": RepresentationStatus.COARSENED,
            "effect": CertificationEffect.FIDELITY_DOWNGRADE}})
        blocked = _bindings(**{"VC_COUNT": {
            "status": RepresentationStatus.UNREPRESENTABLE,
            "effect": CertificationEffect.BLOCKS_EXACT_FABRIC}})
        a = _artifact(semantic_bindings=coarsened)
        b = _artifact(semantic_bindings=blocked)
        assert a.backend_config_hash() != b.backend_config_hash()

    def test_roundtrip_preserves_hash(self):
        a = _artifact()
        assert BackendConfigArtifact.from_dict(a.to_dict()) \
            .backend_config_hash() == a.backend_config_hash()

    def test_persisted_shape(self):
        d = _artifact().to_dict()
        assert d["backend_config_hash"] == _artifact().backend_config_hash()
        assert set(d) == {
            "type", "schema_version", "backend_target", "backend_profile",
            "backend_semantics_version", "lowerer_version",
            "resolved_fabric_hash", "fabric_hash", "normalized_parameters",
            "semantic_bindings", "backend_config_hash"}


class TestConfigStrictness:
    def test_tampered_body_refused(self):
        d = _artifact().to_dict()
        d["normalized_parameters"]["num_vcs"] = 9
        with pytest.raises(BackendConfigError, match="does not match"):
            BackendConfigArtifact.from_dict(d)

    def test_unknown_schema_refused(self):
        d = _artifact().to_dict()
        d["schema_version"] = 2
        with pytest.raises(BackendConfigError, match="schema_version"):
            BackendConfigArtifact.from_dict(d)

    def test_unknown_field_refused(self):
        d = _artifact().to_dict()
        d["extra"] = 1
        with pytest.raises(BackendConfigError, match="unknown fields"):
            BackendConfigArtifact.from_dict(d)

    def test_unknown_enum_refused(self):
        d = _artifact().to_dict()
        d["backend_target"] = "ASTRA"
        with pytest.raises(BackendConfigError, match="unknown backend_target"):
            BackendConfigArtifact.from_dict(d)

    def test_unknown_binding_status_refused(self):
        d = _artifact().to_dict()
        d["semantic_bindings"][0]["representation_status"] = "PROBABLY_EXACT"
        with pytest.raises(BackendConfigError, match="unknown "
                                                     "representation_status"):
            BackendConfigArtifact.from_dict(d)

    def test_wrong_primitive_refused(self):
        with pytest.raises(BackendConfigError):
            _artifact(fabric_hash=123)

    def test_bool_hash_refused(self):
        with pytest.raises(BackendConfigError, match="sha256"):
            _artifact(fabric_hash=True)

    def test_missing_dimension_refused(self):
        binds = tuple(b for b in _bindings()
                      if b.dimension is not SemanticDimension.ADDRESS_DECODE)
        with pytest.raises(BackendConfigError, match="missing dimensions"):
            _artifact(semantic_bindings=binds)

    def test_duplicate_dimension_refused(self):
        binds = _bindings()
        dup = binds + (binds[0],)
        with pytest.raises(BackendConfigError, match="exactly once"):
            _artifact(semantic_bindings=dup)

    def test_out_of_order_dimensions_refused(self):
        binds = tuple(reversed(_bindings()))
        with pytest.raises(BackendConfigError, match="canonical dimension "
                                                     "order"):
            _artifact(semantic_bindings=binds)

    def test_exact_with_effect_refused(self):
        with pytest.raises(BackendConfigError, match="exact representation"):
            _binding(SemanticDimension.VC_COUNT,
                     status=RepresentationStatus.EXACT,
                     effect=CertificationEffect.FIDELITY_DOWNGRADE)

    def test_nonexact_without_reason_refused(self):
        with pytest.raises(BackendConfigError, match="requires a reason"):
            SemanticBinding(
                dimension=SemanticDimension.VC_COUNT,
                source_identity=H64,
                representation_status=RepresentationStatus.COARSENED,
                backend_fields=(),
                reason="",
                certification_effect=CertificationEffect.FIDELITY_DOWNGRADE)

    def test_irrelevant_with_effect_refused(self):
        with pytest.raises(BackendConfigError, match="BACKEND_IRRELEVANT"):
            _binding(SemanticDimension.FLIT_WIDTH,
                     status=RepresentationStatus.BACKEND_IRRELEVANT,
                     effect=CertificationEffect.FIDELITY_DOWNGRADE,
                     reason="no width model")

    def test_unrepresentable_without_effect_refused(self):
        with pytest.raises(BackendConfigError, match="must carry a "
                                                     "certification effect"):
            _binding(SemanticDimension.ESCAPE_VCS,
                     status=RepresentationStatus.UNREPRESENTABLE,
                     effect=CertificationEffect.NONE,
                     reason="no escape VC knob")

    def test_duplicate_backend_field_refused(self):
        with pytest.raises(BackendConfigError, match="declared twice"):
            _binding(SemanticDimension.VC_COUNT,
                     fields=(("num_vcs", 4), ("num_vcs", 8)))


class TestConfigImmutability:
    def test_caller_list_mutation_does_not_change_artifact(self):
        params = [("num_vcs", 4)]
        binds = list(_bindings())
        a = _artifact(normalized_parameters=tuple(params),
                      semantic_bindings=tuple(binds))
        before = a.backend_config_hash()
        params.append(("vc_buf_size", 8))
        binds.clear()
        assert a.backend_config_hash() == before

    def test_nested_dict_mutation_does_not_change_artifact(self):
        value = {"inner": [1, 2]}
        a = _artifact(normalized_parameters=(("profile", value),))
        before = a.backend_config_hash()
        value["inner"].append(3)
        assert a.backend_config_hash() == before

    def test_list_of_pairs_roundtrips_as_list(self):
        pairs = [["a", 1], ["b", 2]]
        a = _artifact(normalized_parameters=(("rows", pairs),))
        d = a.to_dict()
        assert d["normalized_parameters"]["rows"] == pairs
        b = BackendConfigArtifact.from_dict(d)
        assert b.backend_config_hash() == a.backend_config_hash()

    def test_nested_dict_roundtrips_as_object(self):
        a = _artifact(normalized_parameters=(("profile", {"x": 1}),))
        d = a.to_dict()
        assert d["normalized_parameters"]["profile"] == {"x": 1}
        b = BackendConfigArtifact.from_dict(d)
        assert b.backend_config_hash() == a.backend_config_hash()

    def test_derived_views_come_from_bindings(self):
        binds = _bindings(**{
            "ESCAPE_VCS": {
                "status": RepresentationStatus.UNREPRESENTABLE,
                "effect": CertificationEffect.BLOCKS_EXACT_FABRIC,
                "reason": "no escape VC knob"},
            "FLIT_WIDTH": {
                "status": RepresentationStatus.BACKEND_IRRELEVANT,
                "effect": CertificationEffect.NONE,
                "reason": "BookSim counts flits, no width model"},
        })
        a = _artifact(semantic_bindings=binds)
        loss = a.semantic_loss_summary()
        assert {row["dimension"] for row in loss} == {"ESCAPE_VCS", "FLIT_WIDTH"}
        assert not a.exact_fabric_eligible()
        assert a.binding(SemanticDimension.VC_COUNT).representation_status \
            is RepresentationStatus.EXACT


# ── input manifest algebra ──────────────────────────────────────────────

class TestInputManifest:
    def test_hash_is_domain_separated(self):
        import hashlib
        from veritx_dse.core.spec import canonical_json
        m = _manifest()
        body = ("srota/BackendInputManifest/v1\0"
                + canonical_json(m.identity_dict()))
        assert m.backend_input_hash() == hashlib.sha256(
            body.encode()).hexdigest()
        assert m.schema_version == BACKEND_INPUT_SCHEMA_VERSION == 1

    def test_workload_change_changes_input_hash(self):
        a = _manifest(workload_hash=H64C)
        b = _manifest(workload_hash="e" * 64)
        assert a.backend_input_hash() != b.backend_input_hash()

    def test_same_inputs_other_path_same_hash(self):
        a = _manifest()
        b = _manifest()
        assert a.backend_input_hash() == b.backend_input_hash()

    def test_rendered_input_change_changes_hash(self):
        a = _manifest()
        b = _manifest(rendered_inputs=(RenderedInput(
            role="topology", logical_name="topology.anynet",
            sha256="f" * 64, size=123),))
        assert a.backend_input_hash() != b.backend_input_hash()

    def test_workload_change_does_not_touch_config(self):
        # Config artifact is workload-independent by construction.
        a = _artifact()
        assert a.backend_config_hash() == _artifact().backend_config_hash()
        assert BackendInputManifest.__dataclass_fields__.get(
            "workload_hash") is not None

    def test_seed_change_changes_hash(self):
        assert _manifest(seed=8).backend_input_hash() != \
            _manifest(seed=7).backend_input_hash()

    def test_invocation_change_changes_hash(self):
        b = _manifest(invocation_args=(("config", "other.cfg"),))
        assert _manifest().backend_input_hash() != b.backend_input_hash()

    def test_roundtrip_preserves_hash(self):
        m = _manifest()
        loaded = BackendInputManifest.from_dict(m.to_dict())
        assert loaded.backend_input_hash() == m.backend_input_hash()

    def test_tampered_body_refused(self):
        d = _manifest().to_dict()
        d["seed"] = 99
        with pytest.raises(BackendInputError, match="does not match"):
            BackendInputManifest.from_dict(d)

    def test_unknown_schema_refused(self):
        d = _manifest().to_dict()
        d["schema_version"] = 2
        with pytest.raises(BackendInputError, match="schema_version"):
            BackendInputManifest.from_dict(d)

    def test_unknown_field_refused(self):
        d = _manifest().to_dict()
        d["binary_path"] = "/usr/bin/booksim"
        with pytest.raises(BackendInputError, match="unknown fields"):
            BackendInputManifest.from_dict(d)

    def test_absolute_logical_name_refused(self):
        with pytest.raises(BackendInputError, match="relative logical name"):
            RenderedInput(role="x", logical_name="/tmp/workload.trace",
                          sha256="d" * 64, size=1)

    def test_parent_traversal_logical_name_refused(self):
        with pytest.raises(BackendInputError, match="relative logical name"):
            RenderedInput(role="x", logical_name="../workload.trace",
                          sha256="d" * 64, size=1)

    def test_absolute_invocation_arg_refused(self):
        with pytest.raises(BackendInputError, match="absolute path"):
            _manifest(invocation_args=(("config", "/tmp/config.cfg"),))

    def test_duplicate_rendered_name_refused(self):
        with pytest.raises(BackendInputError, match="unique"):
            _manifest(rendered_inputs=(
                RenderedInput(role="a", logical_name="x.cfg",
                              sha256="d" * 64, size=1),
                RenderedInput(role="b", logical_name="x.cfg",
                              sha256="e" * 64, size=1),))

    def test_unsorted_rendered_inputs_refused(self):
        with pytest.raises(BackendInputError, match="sorted"):
            _manifest(rendered_inputs=(
                RenderedInput(role="b", logical_name="z.cfg",
                              sha256="d" * 64, size=1),
                RenderedInput(role="a", logical_name="a.cfg",
                              sha256="e" * 64, size=1),))

    def test_bad_size_refused(self):
        with pytest.raises(BackendInputError, match="non-negative int"):
            RenderedInput(role="x", logical_name="x.cfg",
                          sha256="d" * 64, size=-1)

    def test_manifest_is_deeply_immutable(self):
        m = _manifest()
        before = m.backend_input_hash()
        snapshot = copy.deepcopy(m.to_dict())
        # Dataclass is frozen; the nested tuples cannot be mutated at all.
        with pytest.raises(Exception):
            m.seed = 5  # type: ignore[misc]
        assert m.backend_input_hash() == before
        assert m.to_dict() == snapshot
