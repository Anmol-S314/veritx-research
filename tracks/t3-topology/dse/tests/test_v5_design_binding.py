"""P6: exact V5-root/record/certificate preservation across JSON exports.

Structural clock records are not multi-clock/CDC execution qualification.
"""
from dataclasses import replace
import json

import pytest

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import _typed_request
from veritx_dse.application.views import (
    artifact_chain_view, compilation_view, design_view, topology_view,
)
from veritx_dse.model.access_policy import AccessPolicyArtifact
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.domain_intent import (
    AssertionMode, ClockDomain, ClockSource, ClockSourceKind, DeassertionMode,
    PowerDomain, PowerPolicy, ResetChannel, materialize_clock_domains,
)
from veritx_dse.model.sideband import Direction, SidebandInterface, SidebandKind
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.verification.certificate import (
    VerificationCertificate, verify_v5_compilation,
)


def _request(frequency=500_000_000, *, records=False):
    return CompileRequestV5(
        base_v4=_typed_request(MeshIntent(side_length=2), endpoints=4, tp=4,
                               payload_bytes=512),
        clock_sources=(ClockSource("pll", ClockSourceKind.PLL, 1_000_000_000),),
        clock_domains=(ClockDomain("core", "pll", frequency,
                                   divider_num=1_000_000_000 // frequency),),
        sideband_interfaces=(SidebandInterface(
            "irq", SidebandKind.INTERRUPT, Direction.OUTPUT, 1),) if records else (),
        access_policy=AccessPolicyArtifact(rules=()) if records else None)


def _compiled(request=None):
    request = request if request is not None else _request()
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    return compilation


def test_clocks_bind_the_original_root_and_explicit_hardware_base():
    request = _request()
    compilation = _compiled(request)
    assert compilation.request is request
    binding = compilation.certificate.design_binding
    assert binding["design_hash"] == request.design_hash()
    assert binding["base_design_hash"] == compilation.bundle.design.design_hash()
    assert binding["base_design_hash"] == request.base_v4.design_hash()
    assert binding["resolved_fabric_hash"] == compilation.bundle.resolved_fabric.resolved_fabric_hash
    assert binding["extensions"]["clock_domains"] == compilation.clock_domains.content_hash
    assert binding["scope"] == "DECLARED_V5_EXTENSION_STRUCTURE_ONLY"
    assert binding["execution_semantics"] == "NOT_MODELED"
    assert compilation.certificate.compiler_semantics_version == request.compiler_semantics_version


def test_divider_changes_design_and_certificate_but_not_hardware_identity():
    first = _compiled(_request(500_000_000))
    second = _compiled(_request(250_000_000))
    assert first.request.design_hash() != second.request.design_hash()
    assert first.certificate.certificate_id() != second.certificate.certificate_id()
    assert first.clock_domains.content_hash != second.clock_domains.content_hash
    assert first.bundle.root_hashes() == second.bundle.root_hashes()


@pytest.mark.parametrize("field", ["clock_domains", "sideband_set", "access_policy"])
def test_dropped_record_fails_structural_certification(field):
    compilation = _compiled(_request(records=True))
    records = {name: getattr(compilation, name) for name in
               ("clock_domains", "sideband_set", "access_policy")}
    records[field] = None
    certificate = verify_v5_compilation(compilation.request, compilation.bundle, **records)
    assert certificate.overall == "FAIL"
    dag = next(o for o in certificate.obligations if o.obligation == "FABRIC_DAG_VALID")
    assert dag.status == "FAIL" and field in dag.evidence["failure_reason"]
    with pytest.raises(ControlPlaneError) as caught:
        replace(compilation, **{field: None})
    assert caught.value.code == ErrorCode.EVIDENCE_INVALID


def test_undeclared_clock_output_is_not_admitted():
    source = _request()
    neutral = _compiled(CompileRequestV5(base_v4=source.base_v4))
    with pytest.raises(ControlPlaneError, match="declared design binding"):
        replace(neutral, clock_domains=materialize_clock_domains(
            source.clock_sources, source.clock_domains))


def test_verifier_internal_fault_aborts_instead_of_becoming_a_design_verdict(monkeypatch):
    from veritx_dse.model import domain_intent
    compilation = _compiled()
    def broken_materializer(*_args, **_kwargs):
        raise ValueError("internal clock materializer fault")
    monkeypatch.setattr(domain_intent, "materialize_clock_domains", broken_materializer)
    with pytest.raises(ValueError, match="internal clock materializer fault"):
        verify_v5_compilation(compilation.request, compilation.bundle,
                              clock_domains=compilation.clock_domains)


def test_wrong_clock_record_or_foreign_root_is_not_admitted():
    compilation = _compiled()
    other = _request(250_000_000)
    wrong_clocks = materialize_clock_domains(other.clock_sources, other.clock_domains)
    for changes in ({"clock_domains": wrong_clocks}, {"request": other}):
        with pytest.raises(ControlPlaneError, match="declared design binding"):
            replace(compilation, **changes)


def test_base_only_certificate_cannot_certify_v5_intent():
    compilation = _compiled()
    base_certificate = FabricCompiler().compile(compilation.request.base_v4).certificate
    with pytest.raises(ControlPlaneError, match="declared design binding"):
        replace(compilation, certificate=base_certificate)


def test_same_topology_from_a_different_base_design_refuses():
    compilation = _compiled()
    other_base = replace(compilation.request.base_v4,
                         workload=replace(compilation.request.base_v4.workload, model_name="other"))
    other_bundle = FabricCompiler().compile(other_base).bundle
    certificate = verify_v5_compilation(compilation.request, other_bundle,
                                        clock_domains=compilation.clock_domains)
    assert certificate.overall == "FAIL"


def test_compilation_export_roundtrips_source_records_and_certificate():
    compilation = _compiled(_request(records=True))
    exported = json.loads(json.dumps(compilation_view(compilation)))
    assert exported["design_hash"] == "sha256:" + compilation.request.design_hash()
    assert exported["request"] == compilation.request.to_dict()
    assert exported["design_extensions"]["clock_domains"] == compilation.clock_domains.to_dict()
    assert exported["design_extensions"]["sideband_set"] == compilation.sideband_set.to_dict()
    assert exported["design_extensions"]["access_policy"] == compilation.access_policy.to_dict()
    certificate = VerificationCertificate.from_dict(exported["certificate"])
    assert certificate.design_binding == exported["design_binding"]
    replayed = _compiled(CompileRequestV5.from_dict(exported["request"]))
    assert replayed.certificate.certificate_id() == certificate.certificate_id()
    assert json.loads(json.dumps(replayed.certificate.to_dict())) == certificate.to_dict()
    reloaded = replace(compilation, certificate=certificate)
    reloaded.validate_design_binding()
    assert compilation_view(replayed)["design_extensions"] == exported["design_extensions"]


def test_design_and_chain_exports_distinguish_v5_root_from_base():
    compilation = _compiled()
    view = design_view(compilation.request, compilation)
    assert view["schema_version"] == 5
    assert view["base_design_hash"] == "sha256:" + compilation.request.base_v4.design_hash()
    assert view["v5_intent"] == compilation.request.to_dict()
    chain = artifact_chain_view(compilation)
    nodes = {node["artifact"]: node for node in chain["nodes"]}
    assert nodes["v5_design"]["hash"] == view["design_hash"]
    assert nodes["design"]["hash"] == view["base_design_hash"]
    assert nodes["design"]["parents"] == ["v5_design"]
    assert nodes["clock_domains"]["parents"] == ["v5_design"]
    assert nodes["clock_domains"]["hash"] == "sha256:" + compilation.clock_domains.content_hash


def test_compile_result_exports_records_without_losing_base_inspection():
    from veritx_dse.application.compile_result_view import build_compile_result
    compilation = _compiled()
    result = build_compile_result(
        {"design_hash": compilation.request.design_hash()}, compilation,
        topology_view(compilation), artifact_chain_view(compilation))
    assert result["design_binding"] == compilation.certificate.design_binding
    assert result["design_extensions"]["clock_domains"] == compilation.clock_domains.to_dict()
    assert result["groups"]["summary"]["declared"]["agents"][0]["count"] == 4
    assert result["groups"]["mapping"]["parallelism"]["tp"] == 4
    assert result["certificate"]["obligation_count"] == 10


def test_exports_are_detached_from_the_live_certificate():
    compilation = _compiled()
    identity = compilation.certificate.certificate_id()
    exported = compilation_view(compilation)
    dag = next(o for o in exported["certificate"]["obligations"] if o["obligation"] == "FABRIC_DAG_VALID")
    dag["evidence"]["v5_design_binding"]["extensions"]["clock_domains"] = "0" * 64
    assert compilation.certificate.certificate_id() == identity
    compilation.validate_design_binding()


def test_tampered_live_certificate_is_refused_at_export():
    compilation = _compiled()
    dag = next(o for o in compilation.certificate.obligations if o.obligation == "FABRIC_DAG_VALID")
    dag.evidence["v5_design_binding"]["extensions"]["clock_domains"] = "0" * 64
    for export in (compilation_view, artifact_chain_view, topology_view):
        with pytest.raises(ControlPlaneError, match="declared design binding"):
            export(compilation)


def test_no_silent_v4_execution_of_structural_v5(monkeypatch):
    from veritx_dse.application.evaluation_context import build_evaluation_context
    from veritx_dse.application.fabric_evaluator import FabricEvaluator
    from veritx_dse.core.errors import UnsupportedSemantics
    from veritx_dse.workload import intent_lowering
    compilation = _compiled()
    graph = intent_lowering.lower_compile_workload(compilation.request.base_v4).graph
    def unexpected_lowering(*_args, **_kwargs):
        pytest.fail("V5 execution refusal must precede workload lowering")
    monkeypatch.setattr(intent_lowering, "lower_compile_workload", unexpected_lowering)
    with pytest.raises(UnsupportedSemantics) as refusal:
        build_evaluation_context(compilation)
    assert "ABSTRACT_DATA_MOVEMENT_V1" in refusal.value.message
    assert "data_movement" in refusal.value.message
    with pytest.raises(ControlPlaneError) as caught:
        FabricEvaluator().evaluate(compilation, graph)
    assert caught.value.code == ErrorCode.UNSUPPORTED_SEMANTICS


def test_unsupported_extension_preserves_root_in_refusal_export():
    request = replace(_request(), power_domains=(PowerDomain("power", PowerPolicy.ALWAYS_ON),))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "UNSUPPORTED"
    assert compilation.stopped_at_stage == "COMPOSE"
    exported = compilation_view(compilation)
    assert exported["request"] == request.to_dict()
    assert "design_extensions" not in exported


def test_transactions_extension_owner_is_recorded():
    from veritx_dse.application.fabric_compiler import _V5_EXTENSION_OWNERS
    owners = {name: (stage, why) for name, stage, why in _V5_EXTENSION_OWNERS}
    assert "transactions" in owners
    stage, why = owners["transactions"]
    assert stage == "EVALUATE"
    assert "ABSTRACT_DATA_MOVEMENT_V1" in why
    assert "unqualified" in why


@pytest.mark.parametrize("name, value", [
    ("power_domains", (PowerDomain("power", PowerPolicy.ALWAYS_ON),)),
    ("reset_channels", (ResetChannel(
        "rst", "por", "core", AssertionMode.SYNC,
        DeassertionMode.SYNC),)),
])
def test_declared_extension_refuses_at_its_recorded_owner_stage(name, value):
    from veritx_dse.application.fabric_compiler import _V5_EXTENSION_OWNERS
    owners = {n: (stage, why) for n, stage, why in _V5_EXTENSION_OWNERS}
    stage, why = owners[name]
    compilation = FabricCompiler().compile(replace(_request(), **{name: value}))
    assert compilation.status == "UNSUPPORTED"
    assert compilation.stopped_at_stage == stage == "COMPOSE"
    assert name in compilation.error
    assert why in compilation.error
