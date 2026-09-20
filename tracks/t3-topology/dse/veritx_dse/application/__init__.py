"""veritx_dse.application — Wave-C unified control plane.

One authoritative service (``SrotaControlPlane``) through which every
product-facing request is compiled, evaluated, inspected and compared.
Adapters (CLI/API/T3) translate transport only; Wave-B layers own all
semantics.
"""
from .service import SrotaControlPlane

__all__ = ["SrotaControlPlane"]
