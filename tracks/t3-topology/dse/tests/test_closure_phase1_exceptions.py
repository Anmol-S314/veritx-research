"""Phase-1 closure: programming errors are internal failures, never verdicts.

A bug (AttributeError/TypeError/AssertionError/...) raised inside a
narrowed boundary must escape — it must never be laundered into a
capability/refusal verdict (NOT_QUALIFIED, PROJECTABLE=NO, FAILS,
EVIDENCE_INVALID, corrupt-resource, ...). Each test injects a
programming error at a narrowed boundary and asserts it propagates; a
companion positive control asserts the documented refusal vocabulary
still maps to its verdict.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from veritx_dse.application import booksim_qualification_registry as reg
from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.application.store import (
    ResourceCorruptionError, ResourceStore,
)
from veritx_dse.backend.booksim_projection import SemanticLoss


def _stub_qualification(monkeypatch, qualifier_fn):
    record = SimpleNamespace(
        is_qualified=True,
        projection_semantics_version="SEM",
        lowerer_version="LOW",
        unresolved_evidence=lambda: (),
        qualifier="stub:qualifier",
    )
    profile = SimpleNamespace(
        profile_id="STUB", semantics_version="SEM", lowerer_version="LOW")
    monkeypatch.setattr(reg, "qualification_of", lambda _pid: record)
    monkeypatch.setattr(reg, "resolve_handler", lambda _dotted: qualifier_fn)
    return profile


def test_qualifier_attribute_error_propagates(monkeypatch):
    """A buggy qualifier is an internal failure, not a NO verdict."""

    def buggy(_parents):
        raise AttributeError("qualifier bug")

    profile = _stub_qualification(monkeypatch, buggy)
    with pytest.raises(AttributeError):
        reg.evaluate_qualification(profile, object())


def test_qualifier_semantic_loss_is_still_a_refusal(monkeypatch):
    """Positive control: documented refusal vocabulary still maps."""

    def refusing(_parents):
        raise SemanticLoss("these parents are not mesh-DOR")

    profile = _stub_qualification(monkeypatch, refusing)
    qualified, reason = reg.evaluate_qualification(profile, object())
    assert qualified is False
    assert "refused these parents" in reason


def test_routing_class_ids_type_error_propagates():
    from veritx_dse.application import preset_certification as pc

    class Exploding:
        @property
        def router_route(self):
            raise TypeError("bundle bug")

    compilation = SimpleNamespace(status="COMPILED", bundle=Exploding())
    with pytest.raises(TypeError):
        pc._routing_class_ids(compilation)


def test_routing_class_ids_absent_is_empty():
    from veritx_dse.application import preset_certification as pc

    compilation = SimpleNamespace(status="COMPILED",
                                  bundle=SimpleNamespace())
    assert pc._routing_class_ids(compilation) == ()


def test_identity_vc_transitions_absent_is_fails_not_crash():
    from veritx_dse.application import preset_certification as pc

    compilation = SimpleNamespace(status="COMPILED",
                                  bundle=SimpleNamespace())
    assert pc._cond_identity_vc_transitions({}, compilation) == pc.FAILS


def test_lowered_traffic_classes_type_error_propagates():
    from veritx_dse.application import design_view_v2 as dv2

    class Exploding:
        @property
        def vc_assignment(self):
            raise TypeError("bundle bug")

    compilation = SimpleNamespace(status="COMPILED", bundle=Exploding())
    with pytest.raises(TypeError):
        dv2._lowered_traffic_classes(compilation)


def test_lowered_traffic_classes_absent_is_empty():
    from veritx_dse.application import design_view_v2 as dv2

    compilation = SimpleNamespace(status="COMPILED",
                                  bundle=SimpleNamespace())
    assert dv2._lowered_traffic_classes(compilation) == set()


def _store_with_doc(tmp_path, payload: dict) -> tuple[ResourceStore, str]:
    store = ResourceStore(tmp_path / "store")
    key = "ab" * 32
    path = tmp_path / "store" / "designs" / f"{key}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return store, key


def test_store_parser_attribute_error_propagates(tmp_path):
    store, key = _store_with_doc(tmp_path, {"a": 1})

    def buggy(_doc, _key):
        raise AttributeError("parser bug")

    with pytest.raises(AttributeError):
        store._load_resource("design", key, buggy)


def test_store_parser_value_error_is_corruption(tmp_path):
    store, key = _store_with_doc(tmp_path, {"a": 1})

    def refusing(_doc, _key):
        raise ValueError("malformed document")

    with pytest.raises(ResourceCorruptionError):
        store._load_resource("design", key, refusing)


def test_waved_parse_programming_error_propagates():
    from veritx_dse.application.waved_resources import _parse

    with pytest.raises(ZeroDivisionError):
        _parse("workloadgraph", "r1", lambda: 1 // 0)


def test_waved_parse_value_error_is_evidence_invalid():
    from veritx_dse.application.waved_resources import _parse

    def refusing():
        raise ValueError("malformed artifact")

    with pytest.raises(ControlPlaneError) as excinfo:
        _parse("workloadgraph", "r1", refusing)
    assert excinfo.value.code == ErrorCode.EVIDENCE_INVALID


def test_meshdor_attribute_error_propagates(monkeypatch):
    from veritx_dse.backend import meshdor

    monkeypatch.setattr(meshdor, "assert_canonical_meshdor_projection",
                        lambda _b, _c: None)

    class ExplodingRendered:
        def file(self, _name):
            raise AttributeError("render bug")

    prepared = SimpleNamespace(bundle=object(), config=object(),
                               rendered=ExplodingRendered(),
                               manifest=object())
    with pytest.raises(AttributeError):
        meshdor.assert_canonical_prepared_meshdor(prepared)


def test_meshdor_missing_input_is_lowering_refusal(monkeypatch):
    from veritx_dse.backend import meshdor
    from veritx_dse.backend.booksim import BackendMaterializationError

    monkeypatch.setattr(meshdor, "assert_canonical_meshdor_projection",
                        lambda _b, _c: None)

    class MissingRendered:
        def file(self, _name):
            raise BackendMaterializationError("no such file")

    prepared = SimpleNamespace(bundle=object(), config=object(),
                               rendered=MissingRendered(),
                               manifest=object())
    with pytest.raises(meshdor.BookSimLoweringError):
        meshdor.assert_canonical_prepared_meshdor(prepared)
