"""Federation Commit 03 — the canonical evaluation context.

Tests the boundary laws: PASS-gating, lower-exactly-once binding,
transplanted-lowering refusal, and context identity accessors. The
context is constructed only through ``build_evaluation_context``.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_context import (  # noqa: E402
    CanonicalEvaluationContext, EvaluationContextError,
    build_evaluation_context,
)
from veritx_dse.application.errors import ControlPlaneError  # noqa: E402
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    LoweredWorkload, lower_compile_workload,
)

DENSE = REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json"


def _dense_request():
    return parse_request_doc(json.loads(DENSE.read_text(encoding="utf-8")))


def _compiled():
    compilation = FabricCompiler().compile(_dense_request())
    assert compilation.status == "COMPILED", compilation.status
    return compilation


def test_context_binds_all_canonical_parents():
    compilation = _compiled()
    ctx = build_evaluation_context(compilation)
    assert isinstance(ctx, CanonicalEvaluationContext)
    assert ctx.request is compilation.request
    assert ctx.compilation is compilation
    assert ctx.bundle is compilation.bundle
    assert isinstance(ctx.lowered_workload, LoweredWorkload)
    assert ctx.workload is ctx.lowered_workload.graph


def test_context_identity_accessors_agree_with_their_artifacts():
    compilation = _compiled()
    ctx = build_evaluation_context(compilation)
    assert ctx.design_hash == compilation.request.design_hash()
    assert ctx.workload_id == ctx.workload.workload_id()
    assert ctx.unified_traffic_class == \
        ctx.lowered_workload.unified_traffic_class
    assert ctx.unified_traffic_class == "tp_collective"


def test_non_compilation_refused():
    with pytest.raises(EvaluationContextError, match="Compilation"):
        build_evaluation_context(object())


def test_uncompiled_compilation_refused():
    request = _dense_request()
    request_doc = json.loads(DENSE.read_text(encoding="utf-8"))
    request_doc["noc_config"]["topology_family"] = "torus"
    unsupported = FabricCompiler().compile(parse_request_doc(request_doc))
    assert unsupported.status == "UNSUPPORTED"
    with pytest.raises(EvaluationContextError, match="UNSUPPORTED"):
        build_evaluation_context(unsupported)


def test_non_pass_certificate_refused():
    compilation = _compiled()
    broken = dataclasses.replace(
        compilation, certificate=dataclasses.replace(
            compilation.certificate, overall="FAIL"))
    with pytest.raises(EvaluationContextError, match="certificate"):
        build_evaluation_context(broken)


def test_compilation_type_refuses_missing_certificate_and_bundle():
    """The upstream invariant: a COMPILED result cannot even exist without
    bundle + certificate — Compilation.__post_init__ refuses it, so the
    context builder's own bundle/certificate checks defend only against
    object() stand-ins and mutated certificates."""
    compilation = _compiled()
    with pytest.raises(ControlPlaneError, match="bundle \+ certificate"):
        dataclasses.replace(compilation, certificate=None)
    with pytest.raises(ControlPlaneError, match="bundle \+ certificate"):
        dataclasses.replace(compilation, bundle=None)


def test_lowering_binds_back_to_the_design():
    """The context's lowering must be a lowering OF THIS REQUEST: its
    design_hash equals the request identity. A foreign lowering would be
    refused at construction."""
    compilation = _compiled()
    ctx = build_evaluation_context(compilation)
    assert ctx.lowered_workload.design_hash == compilation.request.design_hash()


def test_lowering_is_deterministic_over_the_request():
    """Two contexts over the same compilation bind the same workload
    identity — the lowering is a function of the request, so adapters
    can never disagree about which graph they evaluated."""
    compilation = _compiled()
    first = build_evaluation_context(compilation)
    second = build_evaluation_context(compilation)
    assert first.workload_id == second.workload_id
    assert first.design_hash == second.design_hash


def test_context_is_frozen():
    ctx = build_evaluation_context(_compiled())
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.workload = object()
