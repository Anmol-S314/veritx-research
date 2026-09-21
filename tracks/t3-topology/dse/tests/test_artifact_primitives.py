"""tests/test_artifact_primitives.py — the one artifact primitive.

Identity oracle. Every constant below was computed from the PRE-merge
implementation (``waved/identity.py`` + ``waved/immutable.py`` +
``wavee/result.py::_content_id``) and is pinned here, so the merge cannot
silently move a sealed artifact identity. A refactor that changes a hash is
a refactor that invalidated every persisted resource and golden.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.core.artifact import (  # noqa: E402
    EvidenceInvalid, FrozenMap, ImmutableError, InvalidInput,
    canonical_bytes, content_hash, content_id, freeze, require_embedded_id,
    require_fields, require_schema_version, require_type_tag, thaw,
)

# ── pinned identity oracle (values captured before the merge) ────────────
_PLAIN = {"b": 1, "a": [1, 2, {"z": None}]}
_UNICODE = {"k": "café\u00e9", "n": 1}

PINNED = [
    # (label, canonical bytes, content_hash("srota/Test", 3, payload))
    ("plain",
     b'{"a":[1,2,{"z":null}],"b":1}',
     "sha256:6e0a96206dfa2a0f5b085053d66f22519fc9e63ab3af562d2fca08147fdd3fde"),
    ("unicode",
     b'{"k":"caf\\u00e9\\u00e9","n":1}',
     "sha256:d55d3856e9939b8821baa5032008f942dac9310c57237284a00825a219dbca03"),
]

# A frozen carrier must hash EXACTLY like its plain form.
_FROZEN_BYTES = b'{"a":{"b":[1,2]},"c":[{"d":"x"}]}'
_FROZEN_HASH = ("sha256:4fe7b672106c498b782d3716dfc2e049cf6c66bd7ffa1908d125"
                "d01fc4080b99")

# The Wave-E convention (bare digest, tag as the whole domain).
_WAVEE_ID = "645139502956b2d43abdedd1e3ac9b321887ef4dcb369985e05832386d4df60c"

# A real sealed artifact identity.
_PARALLELISM_ID = ("sha256:f4d64bf6d851ab997a54a1219179fe9088aac1419dab2b27e"
                   "285815c5480806a")


class TestCanonicalIdentity:
    @pytest.mark.parametrize("label,expected_bytes,expected_hash", PINNED,
                             ids=[p[0] for p in PINNED])
    def test_pinned_bytes_and_hash(self, label, expected_bytes,
                                   expected_hash):
        payload = _PLAIN if label == "plain" else _UNICODE
        assert canonical_bytes(payload) == expected_bytes
        assert content_hash("srota/Test", 3, payload) == expected_hash

    def test_frozen_carrier_hashes_like_plain(self):
        payload = freeze({"a": {"b": (1, 2)}, "c": [{"d": "x"}]})
        assert canonical_bytes(payload) == _FROZEN_BYTES
        assert content_hash("srota/Test", 3, payload) == _FROZEN_HASH
        # and the plain form is byte-identical
        assert canonical_bytes(thaw(payload)) == _FROZEN_BYTES

    def test_wavee_convention_is_the_same_primitive(self):
        assert content_id("srota/wavee/performance-result/v1",
                          {"x": 1}) == _WAVEE_ID

    def test_domain_separation(self):
        """Same payload, different domain -> different identity."""
        a = content_id("srota/A", {"x": 1})
        b = content_id("srota/B", {"x": 1})
        assert a != b

    def test_version_is_part_of_the_domain(self):
        assert content_hash("srota/Test", 1, {"x": 1}) != \
            content_hash("srota/Test", 2, {"x": 1})

    def test_sealed_artifact_identity_survives(self):
        from veritx_dse.waved.parallelism import ParallelismArtifact
        assert ParallelismArtifact(tp=2, pp=1, ep=1,
                                   dp=2).parallelism_id() == _PARALLELISM_ID


class TestImmutability:
    def test_deep_freeze_and_thaw_roundtrip(self):
        src = {"b": [1, {"c": 2}], "a": "x"}
        frozen = freeze(src)
        assert isinstance(frozen, FrozenMap)
        assert isinstance(frozen["b"], tuple)
        assert isinstance(frozen["b"][1], FrozenMap)
        assert thaw(frozen) == src

    def test_caller_mutation_cannot_reach_the_artifact(self):
        src = {"k": {"n": [1]}}
        frozen = freeze(src)
        before = canonical_bytes(frozen)
        src["k"]["n"].append(2)
        src["new"] = True
        assert canonical_bytes(frozen) == before
        assert thaw(frozen) == {"k": {"n": [1]}}

    def test_mapping_is_canonically_ordered_and_hashable(self):
        a = FrozenMap({"b": 1, "a": 2})
        b = FrozenMap({"a": 2, "b": 1})
        assert list(a) == ["a", "b"]
        assert a == b
        assert hash(a) == hash(b)
        assert {a: "ok"}[b] == "ok"

    def test_mutation_attempts_raise(self):
        m = FrozenMap({"a": 1})
        with pytest.raises(TypeError):
            m["b"] = 2  # type: ignore[index]
        with pytest.raises(TypeError):
            del m["a"]  # type: ignore[attr-defined]

    def test_non_canonical_values_refuse(self):
        class Opaque:
            pass

        with pytest.raises(ImmutableError):
            freeze({"x": Opaque()})
        with pytest.raises(ImmutableError):
            freeze({"x": float("nan")})
        with pytest.raises(ImmutableError):
            FrozenMap({1: "int key"})  # type: ignore[dict-item]

    def test_frozen_map_pickles(self):
        import pickle
        m = FrozenMap({"a": [1, 2]})
        assert pickle.loads(pickle.dumps(m)) == m


class TestStrictParsing:
    def test_unknown_fields_refuse(self):
        with pytest.raises(InvalidInput, match="unknown fields"):
            require_fields({"a": 1, "b": 2}, ("a",), "doc")

    def test_wrong_type_tag_refuses(self):
        with pytest.raises(InvalidInput, match="type tag"):
            require_type_tag({"type": "wrong"}, "right", "doc")

    def test_wrong_schema_version_refuses(self):
        with pytest.raises(InvalidInput, match="schema_version"):
            require_schema_version({"schema_version": 1}, 2, "doc")

    def test_missing_embedded_id_refuses(self):
        with pytest.raises(EvidenceInvalid, match="no embedded"):
            require_embedded_id({}, "artifact_id", "sha256:x", "doc")

    def test_forged_embedded_id_refuses(self):
        with pytest.raises(EvidenceInvalid, match="content forged"):
            require_embedded_id({"artifact_id": "sha256:other"}, "artifact_id",
                                "sha256:x", "doc")

    def test_correct_embedded_id_passes(self):
        require_embedded_id({"artifact_id": "sha256:x"}, "artifact_id",
                            "sha256:x", "doc")


class TestOneErrorTaxonomy:
    """The Wave-D error names are now aliases of the core classes.

    Not a copy: ``is`` identity, so ``except``/``pytest.raises`` sites in
    the Wave-D suites are unchanged and there is exactly one class object
    per refusal.
    """

    def test_waved_errors_are_the_core_classes(self):
        from veritx_dse.waved import errors as waved_errors
        assert waved_errors.InvalidInput is InvalidInput
        assert waved_errors.EvidenceInvalid is EvidenceInvalid

    def test_codes_are_preserved(self):
        assert InvalidInput("x").code == "INVALID_INPUT"
        assert EvidenceInvalid("x").code == "EVIDENCE_INVALID"
        assert InvalidInput("x").message == "x"

    def test_wave_semantic_errors_still_have_their_base(self):
        from veritx_dse.waved.errors import (
            ConservationFailed, MappingInvalid, UnsupportedSemantics,
            WaveDError,
        )
        for cls in (ConservationFailed, MappingInvalid,
                    UnsupportedSemantics):
            assert issubclass(cls, WaveDError)


class TestOneDimensionLaw:
    """Parallelism legality has one definition (the sealed Wave-B algebra)."""

    @pytest.mark.parametrize("kw", [
        dict(tp=0, pp=1, ep=1, dp=1),
        dict(tp=1, pp=-1, ep=1, dp=1),
        dict(tp=True, pp=1, ep=1, dp=1),
        dict(tp=1.0, pp=1, ep=1, dp=1),
        dict(tp="2", pp=1, ep=1, dp=1),
        dict(tp=None, pp=1, ep=1, dp=1),
    ])
    def test_artifact_and_algebra_agree(self, kw):
        from veritx_dse.model.placement import ParallelismShape
        from veritx_dse.waved.parallelism import ParallelismArtifact
        with pytest.raises(ValueError):
            ParallelismShape(**kw)
        with pytest.raises(InvalidInput):
            ParallelismArtifact(**kw)

    def test_legal_shapes_agree(self):
        from veritx_dse.model.placement import ParallelismShape
        from veritx_dse.waved.parallelism import ParallelismArtifact
        for dims in ((1, 1, 1, 1), (2, 1, 1, 2), (4, 2, 1, 1)):
            shape = ParallelismShape(*dims)
            art = ParallelismArtifact(*dims)
            assert art.world_size == shape.world_size


class TestNoSecondImplementation:
    """The deleted modules must not come back as aliases of nothing."""

    def test_primitive_modules_are_gone(self):
        import importlib
        for name in ("veritx_dse.waved.identity",
                     "veritx_dse.waved.immutable",
                     "veritx_dse.waved.strict"):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(name)

    def test_source_tree_has_one_canonical_bytes(self):
        """No module outside core/artifact.py may define its own."""
        import subprocess
        root = DSE / "veritx_dse"
        hits = subprocess.run(
            ["grep", "-rn", "def canonical_bytes", str(root)],
            capture_output=True, text=True).stdout.strip().splitlines()
        assert len(hits) == 1, hits
        assert hits[0].startswith(str(root / "core" / "artifact.py")), hits

    def test_wavee_content_id_is_delegation_not_duplication(self):
        import inspect
        from veritx_dse.wavee import result as wavee_result
        src = inspect.getsource(wavee_result._content_id)
        assert "core.artifact" in src or "content_id" in src
        assert "json.dumps" not in src
