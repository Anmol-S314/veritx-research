"""veritx_dse.waved.semantics — WaveDWorkloadSemantics (D1/D2, §12/§14).

A separate immutable versioned Wave-D semantic envelope, orthogonal to
the frozen CompileRequest ``design_hash`` (§23.4): it carries ONLY the
fields the implemented Wave-D semantics actually consume.

Model shape metadata is admitted only as content: either the caller
passes the descriptor dict itself (hashed by value here) or a
descriptor content hash. A bare model name is never identity (§14) —
``model_descriptor_name`` may ride along as provenance but is excluded
from the identity payload unless a descriptor hash binds it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import InvalidInput
from .identity import content_hash

SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/WaveDWorkloadSemantics"

PHASE_PREFILL = "PREFILL"
PHASE_DECODE = "DECODE"
PHASES = (PHASE_PREFILL, PHASE_DECODE)

ROUTING_EXPLICIT_TRACE = "EXPLICIT_TRACE"
SUPPORTED_ROUTING = (ROUTING_EXPLICIT_TRACE,)


def _check_phase(phase: str) -> str:
    if phase not in PHASES:
        raise InvalidInput(
            f"phase must be one of {PHASES}, got {phase!r} "
            "(serving-mode labels are not phases, §11)")
    return phase


def _check_shape(shape: dict[str, Any] | None) -> dict[str, Any] | None:
    if shape is None:
        return None
    if not isinstance(shape, dict):
        raise InvalidInput("shape_metadata must be a dict or None")
    allowed = {"num_layers", "hidden_size", "bytes_per_elem",
               "decode_steps", "num_experts", "top_k"}
    unknown = set(shape) - allowed
    if unknown:
        raise InvalidInput(
            f"shape_metadata has unsupported fields {sorted(unknown)}; "
            f"supported: {sorted(allowed)}")
    for k, v in shape.items():
        if type(v) is not int or isinstance(v, bool) or v < 0:
            raise InvalidInput(
                f"shape_metadata {k!r} must be a non-negative int, got {v!r}")
    return dict(shape)


@dataclass(frozen=True)
class WaveDWorkloadSemantics:
    """The versioned Wave-D semantic envelope (§23.5).

    Identity payload: schema version, phase, routing policy, declared
    shape metadata (sorted canonical dict), model descriptor content
    hash. ``model_descriptor_name`` rides as provenance only.
    """

    phase: str
    routing_policy: str = ROUTING_EXPLICIT_TRACE
    shape_metadata: dict[str, int] = field(default_factory=dict)
    model_descriptor_hash: str | None = None
    model_descriptor_name: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _check_phase(self.phase)
        if self.routing_policy not in SUPPORTED_ROUTING:
            raise InvalidInput(
                f"routing_policy {self.routing_policy!r} is unsupported "
                f"(supported: {SUPPORTED_ROUTING}); do not approximate")
        _check_shape(self.shape_metadata)
        if self.model_descriptor_hash is not None and \
                (not isinstance(self.model_descriptor_hash, str)
                 or not self.model_descriptor_hash):
            raise InvalidInput(
                "model_descriptor_hash must be a non-empty string or None")
        if self.model_descriptor_name is not None and \
                (not isinstance(self.model_descriptor_name, str)
                 or not self.model_descriptor_name):
            raise InvalidInput(
                "model_descriptor_name must be a non-empty string or None")
        if type(self.schema_version) is not int \
                or self.schema_version != SCHEMA_VERSION:
            raise InvalidInput(
                f"unsupported semantics schema_version "
                f"{self.schema_version!r} (expected {SCHEMA_VERSION})")

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "phase": self.phase,
            "routing_policy": self.routing_policy,
            "shape_metadata": dict(sorted(
                (self.shape_metadata or {}).items())),
            "model_descriptor_hash": self.model_descriptor_hash,
        }

    def semantics_id(self) -> str:
        return content_hash(_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(),
                "model_descriptor_name": self.model_descriptor_name,
                "wave_d_semantics_id": self.semantics_id()}

    @classmethod
    def from_dict(cls, d: Any) -> "WaveDWorkloadSemantics":
        if not isinstance(d, dict):
            raise InvalidInput("semantics must be an object")
        unknown = set(d) - {"type", "schema_version", "phase",
                            "routing_policy", "shape_metadata",
                            "model_descriptor_hash",
                            "model_descriptor_name",
                            "wave_d_semantics_id"}
        if unknown:
            raise InvalidInput(
                f"semantics has unknown fields: {sorted(unknown)}")
        art = cls(
            phase=d["phase"],
            routing_policy=d.get("routing_policy", ROUTING_EXPLICIT_TRACE),
            shape_metadata=dict(d.get("shape_metadata") or {}),
            model_descriptor_hash=d.get("model_descriptor_hash"),
            model_descriptor_name=d.get("model_descriptor_name"),
            schema_version=d.get("schema_version", SCHEMA_VERSION))
        if d.get("wave_d_semantics_id") not in (None, art.semantics_id()):
            raise InvalidInput("wave_d_semantics_id does not match content")
        return art

    @staticmethod
    def descriptor_hash(descriptor: dict[str, Any]) -> str:
        """Content hash for an immutable model descriptor document."""
        return content_hash("srota/ModelDescriptor", 1, descriptor)


__all__ = [
    "PHASES", "PHASE_DECODE", "PHASE_PREFILL", "ROUTING_EXPLICIT_TRACE",
    "SCHEMA_VERSION", "SUPPORTED_ROUTING", "WaveDWorkloadSemantics",
]
