"""Wave-C control-plane tests: intent, presets, store, errors, metrics.

Table-driven identity and immutability invariants for the typed
request/resource layer. No backend execution here except through the
service tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from veritx_dse.application.errors import (  # noqa: E402
    ControlPlaneError, ErrorCode,
)
from veritx_dse.application.presets import (  # noqa: E402
    METRIC_SCHEMA_VERSION, TRACE_REGISTRY, build_preset_request,
    derive_request, get_metric_definition, metric_ids, preset_names,
)
from veritx_dse.application.requests import (  # noqa: E402
    INTENT_SCHEMA_VERSION, Intent, parse_intent,
)
from veritx_dse.application.store import ResourceStore  # noqa: E402


def _doc(**over):
    doc = {
        "schema_version": 1, "name": "fixture",
        "fabric_preset": "mesh4", "fabric_overrides": {},
        "workload": {"trace": "tiny2"},
        "backend_target": "BOOKSIM_STANDALONE", "seed": None,
        "metrics": ["sim.latency.avg_cycles", "sim.delivered.packets"],
    }
    doc.update(over)
    return doc


def _resolved(doc):
    from veritx_dse.application.requests import resolve_intent  # noqa: PLC0415
    intent, _, _ = resolve_intent(doc)
    return intent


class TestIntentParsing:
    def test_valid_intent_parses(self):
        intent = _resolved(_doc())
        assert intent.intent_id()
        assert intent.seed_policy() == "pinned_default"

    def test_explicit_seed_policy(self):
        intent = parse_intent(_doc(seed=7))
        assert intent.seed_policy() == "explicit"

    @pytest.mark.parametrize("mutator", [
        lambda d: d.update({"bogus": 1}),
        lambda d: d.update({"schema_version": 999}),
        lambda d: d.update({"fabric_preset": "nope"}),
        lambda d: d.update({"backend_target": "nope"}),
        lambda d: d.update({"seed": -1}),
        lambda d: d.update({"seed": "7"}),
        lambda d: d.update({"metrics": []}),
        lambda d: d.update({"metrics": ["nope"]}),
        lambda d: d.update({"workload": {"trace": "nope"}}),
        lambda d: d.update({"workload": {}}),
        lambda d: d.update(
            {"workload": {"trace": "tiny2", "trace_file": "/x"}}),
        lambda d: d.update(
            {"workload": {"trace_file": "relative/path"}}),
        lambda d: d.pop("name"),
    ])
    def test_invalid_intents_refuse(self, mutator):
        doc = _doc()
        mutator(doc)
        with pytest.raises(ControlPlaneError) as excinfo:
            parse_intent(doc)
        assert excinfo.value.code == ErrorCode.INVALID_INTENT

    def test_error_envelope_shape(self):
        try:
            parse_intent(_doc(fabric_preset="nope"))
        except ControlPlaneError as exc:
            body = exc.to_dict()
            assert body["code"] == "INVALID_INTENT"
            assert body["error"] is True
            assert "operation" in body and "message" in body
        else:
            raise AssertionError("expected INVALID_INTENT")


class TestIntentIdentity:
    def test_display_label_excluded(self):
        assert _resolved(_doc(name="a")).intent_id() == \
            _resolved(_doc(name="b")).intent_id()

    def test_json_key_order_excluded(self):
        import json
        doc = _doc()
        reordered = json.loads(
            json.dumps(doc, sort_keys=True))
        assert _resolved(doc).intent_id() == \
            _resolved(reordered).intent_id()

    def test_round_trip_preserves_identity(self):
        intent = _resolved(_doc())
        assert _resolved(intent.to_dict()).intent_id() == \
            intent.intent_id()

    @pytest.mark.parametrize("field,value", [
        ("fabric_preset", "mesh4_hbm"),
        ("fabric_overrides", {"noc_config.link_width": 64}),
        ("seed", 7),
        ("metrics", ["sim.latency.avg_cycles"]),
        ("backend_target", "SERVING_BOOKSIM2"),
    ])
    def test_semantic_mutation_moves_identity(self, field, value):
        assert _resolved(_doc()).intent_id() != \
            _resolved(_doc(**{field: value})).intent_id()

    def test_override_mutation_moves_identity(self):
        base = _resolved(_doc()).intent_id()
        altered = _resolved(_doc(fabric_overrides={
            "noc_config.link_width": 64})).intent_id()
        assert base != altered

    def test_timeout_excluded_from_identity(self):
        assert _resolved(_doc(timeout_s=60)).intent_id() == \
            _resolved(_doc(timeout_s=600)).intent_id()


class TestPresetImmutability:
    def test_registry_lists_known_presets(self):
        assert set(preset_names()) == {"mesh4", "mesh4_hbm",
                                       "mesh4_wide128"}
        assert "tiny2" in TRACE_REGISTRY

    def test_builders_return_fresh_objects(self):
        first_dict = build_preset_request("mesh4").to_dict()
        first_dict["agents"] = "MUTATED"
        second = build_preset_request("mesh4")
        assert second.to_dict()["agents"] != "MUTATED"

    def test_derive_customize_then_reload_unchanged(self):
        derived = derive_request(
            "mesh4", {"noc_config.link_width": 64})
        assert build_preset_request("mesh4").to_dict() != derived
        assert build_preset_request("mesh4").to_dict() == \
            build_preset_request("mesh4").to_dict()

    def test_derive_order_independent(self):
        first = derive_request("mesh4", {
            "noc_config.link_width": 64,
            "workload.tp": 1,
        })
        second = derive_request("mesh4", {
            "workload.tp": 1,
            "noc_config.link_width": 64,
        })
        assert first == second

    def test_unknown_override_path_refuses(self):
        with pytest.raises((KeyError, TypeError)):
            derive_request("mesh4", {"no.such.path": 1})

    def test_override_type_change_refuses(self):
        with pytest.raises((KeyError, TypeError)):
            derive_request("mesh4", {"workload.tp": "many"})

    def test_unknown_preset_refuses(self):
        with pytest.raises(KeyError):
            build_preset_request("nope")

    def test_metric_schema_lists_only_real_metrics(self):
        assert "sim.latency.avg_cycles" in metric_ids()
        assert "sim.delivered.packets" in metric_ids()
        with pytest.raises(KeyError):
            get_metric_definition("sim.power.watts")
        assert METRIC_SCHEMA_VERSION == "booksim-parse/v1"


class TestStore:
    def test_put_get_roundtrip(self, tmp_path):
        store = ResourceStore(tmp_path)
        payload = {"resource_type": "intent", "a": [1, 2]}
        path = store.put("intent", "abc123", payload)
        assert path.is_file()
        assert store.get("intent", "abc123")["a"] == [1, 2]

    def test_idempotent_rewrite(self, tmp_path):
        store = ResourceStore(tmp_path)
        payload = {"x": 1}
        first = store.put("design", "d1", payload)
        second = store.put("design", "d1", dict(payload))
        assert first == second

    def test_overwrite_different_refuses(self, tmp_path):
        from veritx_dse.application.errors import ErrorCode  # noqa: PLC0415
        store = ResourceStore(tmp_path)
        store.put("design", "d1", {"x": 1})
        with pytest.raises(ControlPlaneError) as excinfo:
            store.put("design", "d1", {"x": 2})
        assert excinfo.value.code == ErrorCode.CONFLICT

    def test_unknown_id_refuses(self, tmp_path):
        store = ResourceStore(tmp_path)
        with pytest.raises(ControlPlaneError) as excinfo:
            store.get("result", "missing")
        assert excinfo.value.code == ErrorCode.NOT_FOUND

    def test_unknown_kind_refuses(self, tmp_path):
        store = ResourceStore(tmp_path)
        with pytest.raises(ControlPlaneError):
            store.put("nope", "x", {})
