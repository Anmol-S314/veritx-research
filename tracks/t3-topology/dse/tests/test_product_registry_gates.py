"""Product registry gates (Gate 4 / Gate 6).

Three machine-readable planning authorities must be validated
automatically, and each validator must be provably able to fail. A
checker that always passes is worse than no checker, so every invariant
here has a mutation test that breaks the registry and asserts the
validator refuses it.

The authorities:

  * ``docs/product/intent-ontology.yaml``     (Gate 1)
  * ``docs/product/capability-registry.yaml`` (Gate 4)
  * ``docs/product/exposure-registry.yaml``   (Gate 6)

The validators live in ``scripts/`` as standalone fail-closed commands so
they can also run outside pytest; this module imports them and drives
them over mutated copies.
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = REPO_ROOT / "scripts"
DOCS = REPO_ROOT / "docs" / "product"

CAPABILITY = DOCS / "capability-registry.yaml"
EXPOSURE = DOCS / "exposure-registry.yaml"
ONTOLOGY = DOCS / "intent-ontology.yaml"


def _load(name: str):
    """Import a ``scripts/check_*.py`` module without a package."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cap_check = _load("check_capability_registry")
exp_check = _load("check_exposure_registry")


@pytest.fixture(scope="module")
def capability_doc() -> dict:
    return yaml.safe_load(CAPABILITY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def exposure_doc() -> dict:
    return yaml.safe_load(EXPOSURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def declared_fields() -> dict[str, list[str]]:
    return exp_check._load_declared_fields()


def _cap(capability_doc: dict) -> dict:
    return copy.deepcopy(capability_doc)


def _exp(exposure_doc: dict) -> dict:
    return copy.deepcopy(exposure_doc)


def _first(caps: list[dict], predicate) -> dict:
    return next(c for c in caps if predicate(c))


# ── the frozen registries are valid ────────────────────────────────────


def test_capability_registry_is_valid(capability_doc):
    assert cap_check.check(capability_doc) == []


def test_exposure_registry_is_valid(exposure_doc, capability_doc, declared_fields):
    assert exp_check.check(exposure_doc, capability_doc, declared_fields) == []


def test_registries_share_one_capability_semantics_version(
        exposure_doc, capability_doc):
    """One authority for the version every claim surface binds to."""
    assert (exposure_doc["capability_semantics_version"]
            == capability_doc["capability_semantics_version"])


# ── capability registry: the validator can fail ────────────────────────


def test_capability_duplicate_id_is_refused(capability_doc):
    doc = _cap(capability_doc)
    doc["capabilities"].append(copy.deepcopy(doc["capabilities"][0]))
    assert any("duplicate capability id" in e for e in cap_check.check(doc))


def test_capability_unknown_stage_value_is_refused(capability_doc):
    doc = _cap(capability_doc)
    doc["capabilities"][0]["stages"]["DERIVABLE"] = "PROBABLY"
    assert any("not in results" in e for e in cap_check.check(doc))


def test_capability_missing_stage_is_refused(capability_doc):
    doc = _cap(capability_doc)
    del doc["capabilities"][0]["stages"]["QUALIFIED"]
    assert any("!= declared stages" in e for e in cap_check.check(doc))


def test_capability_unknown_owner_is_refused(capability_doc):
    doc = _cap(capability_doc)
    doc["capabilities"][0]["owner"] = "NOT_A_DOMAIN"
    assert any("is not a declared domain" in e for e in cap_check.check(doc))


def test_capability_unknown_reason_is_refused(capability_doc):
    doc = _cap(capability_doc)
    target = _first(doc["capabilities"], lambda c: c["wiring"] != "WIRED")
    target["reason"] = "BECAUSE"
    assert any("not in reasons" in e for e in cap_check.check(doc))


def test_capability_wired_without_product_wired_is_refused(capability_doc):
    doc = _cap(capability_doc)
    target = _first(doc["capabilities"], lambda c: c["wiring"] == "WIRED")
    target["stages"]["PRODUCT_WIRED"] = "NO"
    assert any("wiring WIRED but PRODUCT_WIRED" in e
               for e in cap_check.check(doc))


def test_capability_wired_with_reason_is_refused(capability_doc):
    doc = _cap(capability_doc)
    target = _first(doc["capabilities"], lambda c: c["wiring"] == "WIRED")
    target["reason"] = "PRODUCT_NOT_WIRED"
    assert any("must not carry a reason" in e for e in cap_check.check(doc))


def test_capability_product_wired_on_unavailable_wiring_is_refused(capability_doc):
    doc = _cap(capability_doc)
    target = _first(doc["capabilities"], lambda c: c["wiring"] == "NOT_AVAILABLE")
    target["stages"]["PRODUCT_WIRED"] = "YES"
    errors = cap_check.check(doc)
    assert any("PRODUCT_WIRED YES requires wiring" in e for e in errors)
    assert any("must have PRODUCT_WIRED NO" in e for e in errors)


def test_capability_future_contract_with_later_stage_is_refused(capability_doc):
    """A future contract is not partly available."""
    doc = _cap(capability_doc)
    target = _first(doc["capabilities"],
                    lambda c: c["stages"]["DECLARABLE"] == "FUTURE_CONTRACT")
    target["stages"]["EXECUTABLE"] = "YES"
    assert any("later stage EXECUTABLE" in e for e in cap_check.check(doc))


def test_capability_legacy_only_with_later_stage_is_refused(capability_doc):
    doc = _cap(capability_doc)
    target = _first(doc["capabilities"],
                    lambda c: c["stages"]["DECLARABLE"] == "LEGACY_ONLY")
    target["stages"]["PRODUCT_WIRED"] = "YES"
    assert any("later stage PRODUCT_WIRED" in e for e in cap_check.check(doc))


def test_capability_dangling_condition_ref_is_refused(capability_doc):
    doc = _cap(capability_doc)
    target = _first(doc["capabilities"], lambda c: c.get("conditions"))
    target["conditions"] = ["COND-DOES-NOT-EXIST"]
    assert any("is not declared" in e for e in cap_check.check(doc))


def test_capability_envelope_with_unknown_condition_is_refused(capability_doc):
    doc = _cap(capability_doc)
    name = next(iter(doc["envelopes"]))
    doc["envelopes"][name]["required_conditions"] = ["COND-NOPE"]
    assert any("is not declared" in e for e in cap_check.check(doc))


def test_capability_dead_condition_is_refused(capability_doc):
    doc = _cap(capability_doc)
    doc["conditions"]["COND-UNUSED"] = "nothing references this"
    assert any("dead vocabulary" in e for e in cap_check.check(doc))


def test_capability_envelope_missing_claim_scope_is_refused(capability_doc):
    doc = _cap(capability_doc)
    name = next(iter(doc["envelopes"]))
    del doc["envelopes"][name]["claim_scope"]
    assert any("missing 'claim_scope'" in e for e in cap_check.check(doc))


def test_capability_schema_drift_is_refused(capability_doc):
    doc = _cap(capability_doc)
    doc["schema"] = "srota/capability-registry/v2"
    assert any("schema" in e for e in cap_check.check(doc))


# ── exposure registry: the validator can fail ──────────────────────────


def test_exposure_removed_v4_rendered_is_refused(exposure_doc, capability_doc,
                                                 declared_fields):
    """No removed-v4 field is rendered."""
    doc = _exp(exposure_doc)
    doc["fields"]["NocConfig.rcu_enabled"] = {
        "owner": "ROUTER_RESOURCE", "src": "REMOVED_V4", "class": "G1",
        "default": "NONE",
    }
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("REMOVED_V4 must be DO_NOT_RENDER" in e for e in errors)


def test_exposure_not_rendered_class_without_behaviour_is_refused(
        exposure_doc, capability_doc, declared_fields):
    doc = _exp(exposure_doc)
    doc["fields"]["NocConfig.rcu_enabled"]["behaviour"] = "RENDER_WITH_LIMIT"
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("must be DO_NOT_RENDER" in e for e in errors)


def test_exposure_rendered_field_without_default_is_refused(
        exposure_doc, capability_doc, declared_fields):
    doc = _exp(exposure_doc)
    del doc["fields"]["NocConfig.radix"]["default"]
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("must state a default" in e for e in errors)


def test_exposure_unknown_class_is_refused(exposure_doc, capability_doc,
                                           declared_fields):
    doc = _exp(exposure_doc)
    doc["fields"]["NocConfig.radix"]["class"] = "G9"
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("class 'G9' is not declared" in e for e in errors)


def test_exposure_unknown_behaviour_is_refused(exposure_doc, capability_doc,
                                               declared_fields):
    doc = _exp(exposure_doc)
    doc["fields"]["NocConfig.rcu_enabled"]["behaviour"] = "MAYBE"
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("behaviour 'MAYBE' is not declared" in e for e in errors)


def test_exposure_dangling_capability_ref_is_refused(exposure_doc,
                                                     capability_doc,
                                                     declared_fields):
    doc = _exp(exposure_doc)
    doc["fields"]["NocConfig.radix"]["capability"] = "FAB-999"
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("capability 'FAB-999' is not declared" in e for e in errors)


def test_exposure_phantom_field_is_refused(exposure_doc, capability_doc,
                                           declared_fields):
    """No row may name a field the intent model does not have."""
    doc = _exp(exposure_doc)
    doc["fields"]["NocConfig.not_a_real_field"] = {
        "owner": "FABRIC", "src": "UI", "class": "G1", "default": "NONE",
    }
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("the intent model has no such field" in e for e in errors)


def test_exposure_coverage_hole_is_refused(exposure_doc, capability_doc,
                                           declared_fields):
    """No unclassified active field: every declared intent field has a row."""
    doc = _exp(exposure_doc)
    del doc["fields"]["NocConfig.radix"]
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("has no row" in e for e in errors)


def test_exposure_undeclared_class_prefix_is_refused(exposure_doc,
                                                     capability_doc,
                                                     declared_fields):
    doc = _exp(exposure_doc)
    doc["fields"]["Mystery.field"] = {
        "owner": "SYSTEM", "src": "UI", "class": "G1", "default": "NONE",
    }
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("is not a declared intent class" in e for e in errors)


def test_exposure_duplicate_field_authority_is_refused(exposure_doc,
                                                       capability_doc,
                                                       declared_fields):
    """A field is either Design intent or Evaluation policy, never both."""
    doc = _exp(exposure_doc)
    doc["evaluation_only"].append(
        {"field": "link_width", "owner": "EVALUATION", "note": "collision"})
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("duplicate field authority" in e for e in errors)


def test_exposure_future_contract_rendered_is_refused(exposure_doc,
                                                      capability_doc,
                                                      declared_fields):
    """A FUTURE_CONTRACT capability is never exposed as editable intent."""
    doc = _exp(exposure_doc)
    row = doc["fields"]["NocConfig.rcu_enabled"]
    row["class"] = "G2"
    row["behaviour"] = "RENDER_WITH_LIMIT"
    row["default"] = "NONE"
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("future contract is never editable intent" in e for e in errors)


def test_exposure_guided_preset_without_envelope_is_refused(
        exposure_doc, capability_doc, declared_fields):
    doc = _exp(exposure_doc)
    doc["presets"]["mesh4"]["envelope"] = None
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("Guided-eligible but names no envelope" in e for e in errors)


def test_exposure_unknown_preset_envelope_is_refused(exposure_doc,
                                                     capability_doc,
                                                     declared_fields):
    doc = _exp(exposure_doc)
    doc["presets"]["mesh4"]["envelope"] = "CAP-ENV-NOPE-V1"
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("is not declared" in e for e in errors)


def test_exposure_capability_semantics_version_drift_is_refused(
        exposure_doc, capability_doc, declared_fields):
    doc = _exp(exposure_doc)
    doc["capability_semantics_version"] = "cap-v2"
    errors = exp_check.check(doc, capability_doc, declared_fields)
    assert any("one authority" in e for e in errors)


# ── ontology: the existing gate still refuses an unanswered row ────────


def test_ontology_rows_answer_all_ten_questions():
    doc = yaml.safe_load(ONTOLOGY.read_text(encoding="utf-8"))
    answers = ("real", "owner", "edit", "kind", "stored", "depends_on",
               "invalidates", "validation", "unsupported", "visual")
    for node in doc["nodes"]:
        for key in answers:
            assert key in node, f"{node.get('id')} missing {key}"
        assert node.get("evidence") == "V", f"{node.get('id')} not evidence=V"


def test_ontology_has_no_pending_decisions():
    """The gate is open: nothing blocks UI admission."""
    doc = yaml.safe_load(ONTOLOGY.read_text(encoding="utf-8"))
    assert doc.get("pending_decisions") == []
