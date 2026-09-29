"""veritx_dse.product — the VERITX Studio product resource layer.

Rationale: docs/decisions/modules/product.md
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
