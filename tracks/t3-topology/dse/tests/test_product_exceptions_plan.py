"""evaluation_plan() must never launder software faults as semantics.

b1d693cc narrowed the context-build catch to the explicit semantic
tuple; this pins it: AttributeError/NameError injected into
build_evaluation_context surface as INTERNAL_ERROR (never
UNSUPPORTED_SEMANTICS), other typed ControlPlaneErrors keep their own
code, and genuine semantic refusals still read UNSUPPORTED_SEMANTICS.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.errors import (  # noqa: E402
    ControlPlaneError,
    ErrorCode,
)
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig,
    ProductService,
    ProductServiceError,
)


def _service(tmp_path: Path) -> ProductService:
    return ProductService(ProductConfig(projects_root=tmp_path / "projects"))


def _compiled_revision(svc: ProductService) -> dict:
    pid = svc.create_project(name="exc-plan")["project"]["project_id"]
    compiled = svc.compile_draft(pid)
    assert compiled["compilation"]["status"] == "COMPILED"
    return compiled


def test_attribute_error_is_internal_never_unsupported(tmp_path, monkeypatch):
    # service.py imports build_evaluation_context inside the method, so
    # the patch target is the defining module.
    import veritx_dse.application.evaluation_context as _ctx_mod

    svc = _service(tmp_path)
    revision = _compiled_revision(svc)

    def _boom(_compilation):
        raise AttributeError("synthetic attribute defect")

    monkeypatch.setattr(_ctx_mod, "build_evaluation_context", _boom)
    with pytest.raises(ProductServiceError) as exc:
        svc.evaluation_plan(revision["revision_id"])
    assert exc.value.code == ErrorCode.INTERNAL_ERROR, exc.value.code
    assert exc.value.code != ErrorCode.UNSUPPORTED_SEMANTICS


def test_name_error_is_internal_never_unsupported(tmp_path, monkeypatch):
    import veritx_dse.application.evaluation_context as _ctx_mod

    svc = _service(tmp_path)
    revision = _compiled_revision(svc)

    def _boom(_compilation):
        raise NameError("synthetic name defect")

    monkeypatch.setattr(_ctx_mod, "build_evaluation_context", _boom)
    with pytest.raises(ProductServiceError) as exc:
        svc.evaluation_plan(revision["revision_id"])
    assert exc.value.code == ErrorCode.INTERNAL_ERROR, exc.value.code


def test_typed_control_plane_error_keeps_its_code(tmp_path, monkeypatch):
    import veritx_dse.application.evaluation_context as _ctx_mod

    svc = _service(tmp_path)
    revision = _compiled_revision(svc)

    def _boom(_compilation):
        raise ControlPlaneError(ErrorCode.NOT_FOUND, "synthetic typed",
                                operation="evaluation_plan")

    monkeypatch.setattr(_ctx_mod, "build_evaluation_context", _boom)
    with pytest.raises(ControlPlaneError) as exc:
        svc.evaluation_plan(revision["revision_id"])
    assert exc.value.code == ErrorCode.NOT_FOUND, exc.value.code
    assert exc.value.code != ErrorCode.UNSUPPORTED_SEMANTICS


def test_genuine_semantic_refusal_stays_unsupported(tmp_path, monkeypatch):
    from veritx_dse.application.evaluation_context import (  # noqa: E402
        EvaluationContextError,
    )
    import veritx_dse.application.evaluation_context as _ctx_mod

    svc = _service(tmp_path)
    revision = _compiled_revision(svc)

    def _boom(_compilation):
        raise EvaluationContextError("synthetic semantic refusal")

    monkeypatch.setattr(_ctx_mod, "build_evaluation_context", _boom)
    with pytest.raises(ProductServiceError) as exc:
        svc.evaluation_plan(revision["revision_id"])
    assert exc.value.code == ErrorCode.UNSUPPORTED_SEMANTICS, exc.value.code
