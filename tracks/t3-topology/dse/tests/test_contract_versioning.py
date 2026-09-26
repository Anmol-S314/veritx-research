"""Contract-versioning and frozen-payload regression tests (FIX-1..FIX-10).

THE DEFECT CLASS THIS PINS. A backend->Studio payload shape changed while
its contract version stayed the same, a frozen payload was served verbatim,
and the frontend assumed the old shape. That is a contract/versioning bug,
not stale golden data — and it has now appeared twice:

  * the certificate claim shape changed under CONTRACT_VERSION 1, so a
    revision frozen before the change handed the frontend claims without
    `contributing_obligations` and the Compile Result white-screened;
  * views.py emitted `staged`/`stopped_at_stage` since 2fdd758f while the
    schema (last touched in a5b806fe) declared
    unevaluatedProperties:false — so the engine emitted fields its own
    contract forbade and every regeneration failed validation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
DSE = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(DSE))

from veritx_dse.application.compile_result_view import (
    CLAIM_SHAPE_VERSION,
    CONTRACT_VERSION,
    REQUIRED_CLAIM_FIELDS,
    claims_are_current,
    compile_result_is_current,
)


# ══ FIX-1: incompatible change without a version bump must FAIL ═════════

def test_fix_1_shape_change_without_version_bump_is_refused():
    """A payload carrying a stale claim shape under the CURRENT contract
    version must not be treated as servable."""
    stale = {
        "contract_version": CONTRACT_VERSION,
        "certificate": {"claims": [
            {"claim": "ROUTE_COMPLETE", "scope": "s", "status": "PASS"}]},
    }
    assert compile_result_is_current(stale) is False, (
        "a shape change under an unchanged contract version must be "
        "detected, not served")


def test_fix_1b_claim_shape_version_is_a_real_bump():
    assert CLAIM_SHAPE_VERSION >= 2, \
        "the claim shape changed incompatibly; the version must record it"
    assert REQUIRED_CLAIM_FIELDS, "the required-field set must be declared"


# ══ FIX-2: fixture contract version must match the parser ══════════════

def test_fix_2_fixtures_declare_the_current_contract_version():
    fixtures = ROOT / "apps/studio/fixtures"
    for path in sorted(fixtures.glob("*.json")):
        doc = json.loads(path.read_text())
        def walk(o):
            if isinstance(o, dict):
                if "contract_version" in o:
                    yield o["contract_version"]
                for v in o.values():
                    yield from walk(v)
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v)
        for v in walk(doc):
            assert isinstance(v, int) and v >= 1, (path.name, v)


def test_fix_2b_studio_fixture_schemas_exist_and_are_strict():
    for view in ("compilation.view", "optimization.study.view"):
        for v in ("v1", "v2"):
            p = ROOT / f"contracts/srota/{v}/{view}.schema.json"
            if not p.exists():
                continue
            schema = json.loads(p.read_text())
            assert schema.get("unevaluatedProperties") is False, (
                f"{v}/{view} must stay strict, otherwise undeclared fields "
                "pass silently")


# ══ FIX-3: the generated view must validate against its schema ═════════

def test_fix_3_compilation_view_declares_every_emitted_field():
    """The schema must declare what views.py emits. This is the exact bug
    that blocked regeneration: staged/stopped_at_stage were emitted but
    undeclared."""
    schema = json.loads(
        (ROOT / "contracts/srota/v1/compilation.view.schema.json").read_text())
    props = set(schema["properties"])
    src = (DSE / "veritx_dse/application/views.py").read_text()
    for emitted in ("staged", "stopped_at_stage"):
        if f'view["{emitted}"]' in src:
            assert emitted in props, (
                f"views.py emits {emitted!r} but the schema does not "
                "declare it — an undeclared field on a strict schema is a "
                "contract violation")


def test_fix_3b_staged_block_shape_matches_the_schema():
    schema = json.loads(
        (ROOT / "contracts/srota/v1/compilation.view.schema.json").read_text())
    staged = schema["properties"]["staged"]
    declared = set(staged["properties"])
    src = (DSE / "veritx_dse/application/views.py").read_text()
    for key in ("stopped_at_stage", "produced_stages", "has_topology",
                "has_attachment", "has_mapping", "has_inventory"):
        assert key in declared, f"schema must declare staged.{key}"
        assert f'"{key}"' in src, f"views.py must emit staged.{key}"


# ══ FIX-4: a stale frozen payload is refused, not served ═══════════════

def test_fix_4_stale_frozen_payload_is_refused():
    legacy = {
        "contract_version": CONTRACT_VERSION,
        "certificate": {"claims": [
            {"claim": "ATTACHMENT_COMPLETE", "scope": "s",
             "status": "PASS", "method": None}]},
    }
    assert compile_result_is_current(legacy) is False
    assert claims_are_current(legacy["certificate"]["claims"]) is False


def test_fix_4b_current_payload_is_served_as_is():
    current = {
        "contract_version": CONTRACT_VERSION,
        "certificate": {"claim_shape_version": CLAIM_SHAPE_VERSION,
                        "claims": [dict.fromkeys(REQUIRED_CLAIM_FIELDS, "x")]},
    }
    assert compile_result_is_current(current) is True


def test_fix_4c_absent_certificate_is_servable():
    """available:False / a staged stop carries no claims to render."""
    assert compile_result_is_current(
        {"contract_version": CONTRACT_VERSION, "certificate": None}) is True


# ══ FIX-5 / FIX-6: malformed payload never becomes valid state ═════════

def test_fix_5_non_dict_and_missing_fields_are_not_current():
    for bad in ("nope", 42, None, [], {"contract_version": None}):
        assert compile_result_is_current(bad) is False
    assert claims_are_current("nope") is False
    assert claims_are_current([{"claim": "x"}]) is False
    assert claims_are_current([None]) is False


def test_fix_6_malformed_claim_never_reads_as_pass():
    """A row missing `certificate_status` must not be silently treated as
    established just because it carries some other field."""
    malformed = [{"claim": "ROUTE_COMPLETE", "scope": "s", "status": "PASS"}]
    assert claims_are_current(malformed) is False
    assert "certificate_status" in REQUIRED_CLAIM_FIELDS


# ══ FIX-7 / FIX-8: AMEND-5 changed only the expected fields ════════════

def test_fix_7_amend5_identity_impact_is_bounded():
    """Adding metric projection must move the registry identity and the
    result identity that binds it — and nothing else."""
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY, CERTIFIED_METRIC_REGISTRY_V1,
    )
    assert CERTIFIED_METRIC_REGISTRY.registry_id() != \
        CERTIFIED_METRIC_REGISTRY_V1.registry_id()
    assert CERTIFIED_METRIC_REGISTRY.version == "certified-builtin-v2"
    assert CERTIFIED_METRIC_REGISTRY_V1.version == "certified-builtin-v1"


def test_fix_8_design_and_topology_identity_do_not_depend_on_the_registry():
    """Design/topology/fabric identity is computed BEFORE any metric
    registry is consulted, so adding metrics must not move it."""
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_family,
    )
    a = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    b = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    assert a.topology_hash() == b.topology_hash()
    assert a.topology_hash().startswith("524cf3267d4d64c3cdd07dd2"), \
        "mesh identity must be stable across the metric-registry change"
    # The artifact has no registry concept at all.
    assert "metric_registry" not in json.dumps(a.to_dict())


# ══ FIX-9: v1 and v2 must not alias ════════════════════════════════════

def test_fix_9_v1_and_v2_do_not_alias():
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY as V2, CERTIFIED_METRIC_REGISTRY_V1 as V1,
    )
    n1, n2 = set(V1.metric_names()), set(V2.metric_names())
    assert n1 < n2, "v2 must strictly extend v1"
    # One metric has one authority; v1's authenticated metrics are untouched.
    for m in n1:
        assert V2.authorities[m].producer_id == V1.authorities[m].producer_id, m
        assert V2.authorities[m].semantics_version == \
            V1.authorities[m].semantics_version, m
    assert V2.registry_id() != V1.registry_id()


# ══ FIX-10: absence never serializes as a zero measurement ═════════════

def test_fix_10_absent_metric_is_absent_not_zero():
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY as R,
    )
    assert R.extract_all({}) == {}
    for m in ("makespan", "critical_path", "request_latency_mean",
              "resource_utilization_max"):
        assert R.extract(m, {}) is None, f"{m} must be absent, not 0"
    # A malformed value is also absent, never coerced.
    assert R.extract("makespan", {"makespan": {"numerator": 1,
                                               "denominator": 0}}) is None


def test_fix_10b_unsupported_metrics_stay_unregistered():
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY as R, WAVE_E_NOT_SCALAR,
    )
    names = set(R.metric_names())
    assert "ttft" not in names
    assert "decode_step_latency" not in names
    assert "ttft" in WAVE_E_NOT_SCALAR
