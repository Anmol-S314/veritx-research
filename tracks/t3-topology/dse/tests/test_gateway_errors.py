"""Gateway HTTP error taxonomy (R3.14).

The gateway must map ONLY typed failures to 4xx/503. A programmer fault
(``ValueError``/``TypeError``/``RuntimeError``/``AttributeError``) must
become a logged 500, never an INVALID/UNSUPPORTED user error. This is a stop
condition, so it is tested by injection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.application.errors import (  # noqa: E402
    ControlPlaneError, ErrorCode,
)
from veritx_dse.application.service import SrotaControlPlane  # noqa: E402
from veritx_dse.core.errors import (  # noqa: E402
    BackendFailure, BackendTimeout, InvalidInput, UnsupportedSemantics,
)
from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402
from veritx_dse.optimization.real_evaluator import (  # noqa: E402
    RealCandidateEvaluator,
)
from veritx_dse.model.compile_model import CompileRequestV3  # noqa: E402


def _client(tmp_path, *, with_binary: bool):
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    binary = None
    if with_binary:
        binary = tmp_path / "booksim"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
    cfg = GatewayConfig(store_root=tmp_path / "store", runs_root=runs,
                        booksim_bin=binary)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def _raise(exc):
    def _boom(*args, **kwargs):
        raise exc
    return _boom


@pytest.mark.parametrize("exc,status,code", [
    (UnsupportedSemantics("no such lowering"), 422, "UNSUPPORTED_SEMANTICS"),
    (InvalidInput("malformed intent"), 400, "INVALID_INPUT"),
    (BackendTimeout("backend timed out"), 503, "TIMEOUT"),
    (BackendFailure("backend exited 1"), 503, "BACKEND_FAILURE"),
    (ControlPlaneError(ErrorCode.CONFLICT, "state changed"), 409, "CONFLICT"),
    (ControlPlaneError(ErrorCode.NOT_FOUND, "gone"), 404, "NOT_FOUND"),
])
def test_typed_refusals_map_to_their_status(tmp_path, monkeypatch, exc,
                                            status, code):
    monkeypatch.setattr(SrotaControlPlane, "compile", _raise(exc))
    response = _client(tmp_path, with_binary=False).post(
        "/compile", json={"preset": "mesh4"})
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


@pytest.mark.parametrize("fault", [
    ValueError("a programmer invariant exploded"),
    TypeError("a programmer type mismatch"),
    RuntimeError("a programmer runtime bug"),
    AttributeError("a programmer attribute bug"),
])
def test_internal_programmer_errors_are_500_never_user_errors(
        tmp_path, monkeypatch, fault):
    monkeypatch.setattr(SrotaControlPlane, "compile", _raise(fault))
    response = _client(tmp_path, with_binary=False).post(
        "/compile", json={"preset": "mesh4"})
    assert response.status_code == 500, response.text
    assert response.status_code not in (400, 422)
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    # internals are not leaked to the client
    assert "programmer" not in body["detail"]


def test_evaluate_without_a_backend_is_503(tmp_path):
    response = _client(tmp_path, with_binary=False).post(
        "/evaluate", json={"request": {}})
    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"


@pytest.mark.parametrize("fault", [ValueError("boom"), RuntimeError("boom")])
def test_evaluate_internal_fault_is_500(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(CompileRequestV3, "from_dict",
                        staticmethod(lambda _d: object()))
    monkeypatch.setattr(RealCandidateEvaluator, "evaluate", _raise(fault))
    response = _client(tmp_path, with_binary=True).post(
        "/evaluate", json={"request": {"anything": True}})
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_optimize_internal_fault_is_500(tmp_path, monkeypatch):
    from veritx_dse.optimization.result import Optimizer

    monkeypatch.setattr(CompileRequestV3, "from_dict",
                        staticmethod(lambda _d: object()))
    monkeypatch.setattr(Optimizer, "optimize_certified",
                        _raise(TypeError("boom")))
    response = _client(tmp_path, with_binary=True).post(
        "/optimize", json={"request": {"anything": True},
                           "domain": [{"name": "link_width",
                                       "values": [64, 128]}]})
    assert response.status_code == 500, response.text
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_unknown_run_is_404_and_traversal_is_rejected(tmp_path):
    client = _client(tmp_path, with_binary=False)
    missing = client.get("/runs/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    # a traversal attempt is never a 200; the router or the id guard refuses it
    traversal = client.get("/runs/..%2Fsecret")
    assert traversal.status_code in (400, 404), traversal.text
