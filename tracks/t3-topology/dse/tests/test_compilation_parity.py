"""Compilation parity: non-semantic certificate drift must not freeze a revision.

A revision freezes the compiler's derived identities. When compiler code
changes only the *description* of a certificate obligation — for example the
ROUTE_COMPLETE pair-domain label — every classic certificate and every
``compiled_system_hash`` changes without touching the fabric, routes or VC
scheme. Those revisions must stay runnable, but the run must record which
system root it actually executed. Any semantic drift still refuses.
"""
from __future__ import annotations

import hashlib

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.artifact import content_id
from veritx_dse.core.spec import canonical_json
from veritx_dse.product.service import (
    ProductService, ProductServiceError, parse_request_doc,
)
from veritx_dse.verification.certificate import _HASH_TYPE_TAG

from test_product_workflow import _client, _make_project


def _certificate_id(certificate: dict, base: dict) -> str:
    identity = {**base, "overall": certificate["overall"],
                "obligations": certificate["obligations"]}
    body = (f"{_HASH_TYPE_TAG}/v{identity['schema_version']}\0"
            + canonical_json(identity))
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def _with_old_certificate_label(stored: dict, base: dict) -> dict:
    """Give the stored certificate the pre-change descriptive label.

    Only ``evidence['domain']`` changes. Every verdict, count, fabric hash and
    obligation stays identical, so this is exactly the drift a label change
    produces.
    """
    certificate = dict(stored["certificate"])
    obligations = [dict(row) for row in certificate["obligations"]]
    route = next(row for row in obligations
                 if row["obligation"] == "ROUTE_COMPLETE")
    route["evidence"] = {**route["evidence"], "domain": "router x terminal"}
    certificate["obligations"] = obligations
    certificate["certificate_id"] = _certificate_id(certificate, base)

    system = stored["compilation"]["compiled_system"]
    children = dict(system["children"])
    children["network_certificate"] = certificate["certificate_id"]
    system = {**system, "children": children}
    identity = {key: system[key] for key in (
        "type", "schema_version", "system_semantics_version",
        "design_identity", "children", "scopes")}
    system_hash = content_id("veritx/CompiledSystemArtifact/v1", identity)
    system["system_hash"] = system_hash

    compilation = dict(stored["compilation"])
    compilation["compiled_system"] = system
    compilation["system_hash"] = system_hash
    hashes = dict(compilation["artifact_hashes"])
    hashes["compiled_system_hash"] = system_hash
    compilation["artifact_hashes"] = hashes
    return {**stored, "certificate": certificate, "compilation": compilation}


def _compiled_revision(tmp_path):
    client = _client(tmp_path, with_backend=False)
    project = _make_project(client)
    pid = project["project"]["project_id"]
    compiled = client.post(f"/api/v1/projects/{pid}/compile")
    assert compiled.status_code == 200, compiled.text
    revision_id = compiled.json()["revision_id"]
    stored = client.app.state.product.store.load_revision(pid, revision_id)
    request = parse_request_doc(stored["request"])
    identity = FabricCompiler().compile(request).certificate.identity_dict()
    return client, stored, request, identity


def test_matching_compilation_records_both_system_hashes(tmp_path):
    _client_instance, stored, request, _identity = _compiled_revision(tmp_path)
    service = ProductService.__new__(ProductService)

    compilation, parity = service._check_compilation_parity(stored, request)

    expected = stored["compilation"]["artifact_hashes"]["compiled_system_hash"]
    assert parity["parity"] == "MATCHED"
    assert parity["stored_compiled_system_hash"] == expected
    assert parity["executed_compiled_system_hash"] == \
        compilation.compiled_system.system_hash()


def test_label_only_certificate_drift_is_allowed_and_reported(tmp_path):
    _client_instance, stored, request, identity = _compiled_revision(tmp_path)
    drifted = _with_old_certificate_label(stored, identity)
    service = ProductService.__new__(ProductService)

    compilation, parity = service._check_compilation_parity(drifted, request)

    assert compilation.status == "COMPILED"
    assert parity["parity"] == "RECOMPILED_CERTIFICATE_IDENTITY"
    assert parity["stored_compiled_system_hash"] == \
        drifted["compilation"]["artifact_hashes"]["compiled_system_hash"]
    assert parity["executed_compiled_system_hash"] == \
        compilation.compiled_system.system_hash()
    assert parity["stored_compiled_system_hash"] != \
        parity["executed_compiled_system_hash"]
    assert "fabric, routes, VC scheme" in parity["note"]


def test_semantic_artifact_drift_still_refuses(tmp_path):
    _client_instance, stored, request, _identity = _compiled_revision(tmp_path)
    tampered = {**stored, "compilation": {**stored["compilation"]}}
    hashes = dict(tampered["compilation"]["artifact_hashes"])
    hashes["mapping_hash"] = "0" * 64
    tampered["compilation"]["artifact_hashes"] = hashes
    service = ProductService.__new__(ProductService)

    with pytest.raises(ProductServiceError) as refused:
        service._check_compilation_parity(tampered, request)

    assert "different artifacts" in str(refused.value)
    assert "mapping_hash" in str(refused.value)
    assert "Recompile the unchanged draft" in str(refused.value)
