"""veritx_dse.product — the VERITX Studio product resource layer.

Filesystem-backed Project / Draft / DesignRevision / Run / Job /
OptimizationStudy resources that link the canonical scientific views
(DesignView, CompilationView, EvaluationView, RequirementReport,
OptimizationStudyView) into one coherent product state machine.

No science lives here: every scientific fact is projected from an
application service. See ``docs/product/STUDIO-FLOW-AUDIT.md``.
"""
from __future__ import annotations

from veritx_dse.product.service import (
    ProductService, ProductServiceError, BackendUnavailable,
)
from veritx_dse.product.store import ProductStore, ProductStoreError

__all__ = [
    "BackendUnavailable",
    "ProductService",
    "ProductServiceError",
    "ProductStore",
    "ProductStoreError",
]
