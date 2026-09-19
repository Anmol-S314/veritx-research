"""veritx_dse.backend.contracts — backend projection/input identity (B3.7a).

Two identity domains, deliberately separate:

    BackendConfigArtifact
        the PATH-INDEPENDENT backend projection of one semantic fabric:
        backend target/profile, lowerer version, normalized parameters,
        and one SemanticBinding per fabric dimension with its
        representation status and certification effect.

    BackendInputManifest
        the exact per-execution scientific inputs: workload content hash,
        seed/policy, rendered file hashes, normalized invocation. It binds
        to a BackendConfigArtifact but never contaminates fabric identity.

The binary/source-tree identity is NOT part of either hash; B4 composes
producer identity later.

Strictness rules (same discipline as the B3 semantic artifacts):
  * frozen dataclasses, tuple-valued collections;
  * canonical JSON + domain-separated SHA-256;
  * unknown fields, unknown enum values and wrong primitive types refused;
  * hashes recomputed on load; old schemas refused unless an explicit
    migration exists (v1 is the first schema, so nothing to migrate);
  * no absolute filesystem path may enter scientific identity — a
    path-only change must not change any hash;
  * `semantic_loss` is a DERIVED view of the bindings, never an
    independently editable list that could disagree with them.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

BACKEND_CONFIG_SCHEMA_VERSION = 1
BACKEND_INPUT_SCHEMA_VERSION = 1
_CONFIG_HASH_TAG = "srota/BackendConfig"
_INPUT_HASH_TAG = "srota/BackendInputManifest"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BackendConfigError(ValueError):
    """The backend projection is invalid or unproven — fail closed."""


class BackendInputError(ValueError):
    """The exact execution inputs are invalid or unproven — fail closed."""


# ── closed vocabularies ─────────────────────────────────────────────────

class BackendTarget(Enum):
    """Distinct execution identities. Never collapse these into 'ASTRA',
    'BOOKSIM' or 'ANALYTICAL': each name hides materially different
    execution behavior (different binaries, protocols, capabilities)."""

    BOOKSIM_STANDALONE = "BOOKSIM_STANDALONE"
    SERVING_BOOKSIM2 = "SERVING_BOOKSIM2"
    SERVING_ANALYTICAL_AWARE = "SERVING_ANALYTICAL_AWARE"
    SERVING_ANALYTICAL_UNAWARE = "SERVING_ANALYTICAL_UNAWARE"


class SemanticDimension(Enum):
    """The closed fabric-semantic vocabulary every lowerer must account for.

    Extend only when source inspection proves a new identity-bearing
    fabric semantic exists; never silently drop one.
    """

    TOPOLOGY_GRAPH = "TOPOLOGY_GRAPH"
    ENDPOINT_ATTACHMENT = "ENDPOINT_ATTACHMENT"

    CHANNEL_WIDTH = "CHANNEL_WIDTH"
    CHANNEL_LATENCY = "CHANNEL_LATENCY"
    ROUTE_WEIGHT = "ROUTE_WEIGHT"

    ROUTE_REALIZATION = "ROUTE_REALIZATION"

    VC_COUNT = "VC_COUNT"
    VC_CLASS_ASSIGNMENT = "VC_CLASS_ASSIGNMENT"
    VC_ROUTING_CLASS = "VC_ROUTING_CLASS"
    VC_TRANSITIONS = "VC_TRANSITIONS"
    ESCAPE_VCS = "ESCAPE_VCS"

    FLIT_WIDTH = "FLIT_WIDTH"
    PACKET_DELIMITATION = "PACKET_DELIMITATION"
    PACKET_MAX_FLITS = "PACKET_MAX_FLITS"
    HEADER_LAYOUT = "HEADER_LAYOUT"
    HEADER_REPLICATION = "HEADER_REPLICATION"

    BUFFER_ORGANIZATION = "BUFFER_ORGANIZATION"
    INPUT_BUFFER_DEPTH = "INPUT_BUFFER_DEPTH"
    OUTPUT_STAGE_DEPTH = "OUTPUT_STAGE_DEPTH"
    FLOW_CONTROL = "FLOW_CONTROL"
    CREDIT_RETURN_LATENCY = "CREDIT_RETURN_LATENCY"
    VC_REUSE_POLICY = "VC_REUSE_POLICY"

    VC_ALLOCATOR = "VC_ALLOCATOR"
    SWITCH_ALLOCATOR = "SWITCH_ALLOCATOR"
    ALLOCATOR_ITERATIONS = "ALLOCATOR_ITERATIONS"
    HOLD_SWITCH_FOR_PACKET = "HOLD_SWITCH_FOR_PACKET"

    INPUT_SPEEDUP = "INPUT_SPEEDUP"
    OUTPUT_SPEEDUP = "OUTPUT_SPEEDUP"
    INTERNAL_SPEEDUP = "INTERNAL_SPEEDUP"

    ROUTE_COMPUTE_CYCLES = "ROUTE_COMPUTE_CYCLES"
    VC_ALLOC_CYCLES = "VC_ALLOC_CYCLES"
    SWITCH_ALLOC_CYCLES = "SWITCH_ALLOC_CYCLES"
    SWITCH_TRAVERSAL_CYCLES = "SWITCH_TRAVERSAL_CYCLES"
    OUTPUT_DELAY_CYCLES = "OUTPUT_DELAY_CYCLES"

    ADDRESS_DECODE = "ADDRESS_DECODE"
    PLANE_COMPOSITION = "PLANE_COMPOSITION"


class RepresentationStatus(Enum):
    """How (and whether) one fabric dimension is represented by a backend.

    Non-exact statuses must state the reason; the certification effect is
    stored explicitly (and consistency-checked), never silently inferred.
    """

    EXACT = "EXACT"
    DERIVED_EXACT = "DERIVED_EXACT"
    COARSENED = "COARSENED"
    BACKEND_IRRELEVANT = "BACKEND_IRRELEVANT"
    ASSUMED_FIXED = "ASSUMED_FIXED"
    UNREPRESENTABLE = "UNREPRESENTABLE"


class CertificationEffect(Enum):
    """What a non-exact representation does to certification."""

    NONE = "NONE"
    FIDELITY_DOWNGRADE = "FIDELITY_DOWNGRADE"
    BLOCKS_EXACT_FABRIC = "BLOCKS_EXACT_FABRIC"
    UNSUPPORTED_EXECUTION = "UNSUPPORTED_EXECUTION"


_EXACT_STATUSES = frozenset({RepresentationStatus.EXACT,
                             RepresentationStatus.DERIVED_EXACT})
_NON_EXACT_EFFECTS = frozenset({CertificationEffect.FIDELITY_DOWNGRADE,
                                CertificationEffect.BLOCKS_EXACT_FABRIC,
                                CertificationEffect.UNSUPPORTED_EXECUTION})


# ── strict primitive helpers ────────────────────────────────────────────

def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise BackendConfigError(f"{name} must be a non-empty string")
    return value


def _as_sha256(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise BackendConfigError(
            f"{name} must be a lowercase 64-hex sha256, got {value!r}")
    return value


def _as_enum(name: str, enum_cls: type[Enum], value: Any,
             error: type[Exception] = BackendConfigError) -> Enum:
    if not isinstance(value, enum_cls):
        raise error(f"{name} must be a {enum_cls.__name__}, got "
                    f"{type(value).__name__}")
    return value


def _enum_from_value(name: str, enum_cls: type[Enum], value: Any,
                     error: type[Exception] = BackendConfigError) -> Enum:
    if not isinstance(value, str):
        raise error(f"{name} must be a string enum value, got "
                    f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise error(
            f"unknown {name} {value!r}; known: "
            f"{[m.value for m in enum_cls]}") from None


def _strict_keys(d: Any, allowed: frozenset[str], where: str,
                 error: type[Exception] = BackendConfigError) -> None:
    if not isinstance(d, dict):
        raise error(f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise error(f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str,
          error: type[Exception] = BackendConfigError) -> Any:
    if key not in d:
        raise error(f"{where} is missing required field {key!r}")
    return d[key]


def _no_absolute_paths(value: Any, where: str,
                       error: type[Exception] = BackendConfigError) -> None:
    """Scientific identity must be path-independent.

    Refuse absolute POSIX paths and Windows drive paths anywhere in a
    value tree. Logical relative names (``topology.anynet``) are fine.
    """
    if isinstance(value, str):
        if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
            raise error(
                f"{where} contains an absolute path {value!r}; backend "
                "scientific identity must be path-independent")
    elif isinstance(value, (list, tuple)):
        for item in value:
            _no_absolute_paths(item, where, error)
    elif isinstance(value, dict):
        for key, item in value.items():
            _no_absolute_paths(item, f"{where}.{key}", error)


class _FrozenMap(tuple):
    """Deep-frozen JSON object: an ordered tuple of (key, value) pairs.

    A distinct type keeps ``{"a": 1}`` unambiguous from ``[["a", 1]]``
    when converting back to JSON; plain tuples are lists.
    """

    __slots__ = ()


def _freeze_json(value: Any, where: str) -> Any:
    """JSON-shaped value -> deep-immutable canonical value.

    Lists become tuples and objects become _FrozenMap so a caller
    mutating its own list/dict after construction cannot change the
    artifact.
    """
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str):
            _no_absolute_paths(value, where)
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise BackendConfigError(f"{where} must not be NaN/inf")
        return value
    if isinstance(value, _FrozenMap):
        return _FrozenMap((k, _freeze_json(v, where)) for k, v in value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(v, where) for v in value)
    if isinstance(value, dict):
        out = []
        for key in sorted(value):
            if not isinstance(key, str) or not key:
                raise BackendConfigError(
                    f"{where} keys must be non-empty strings")
            out.append((key, _freeze_json(value[key], f"{where}.{key}")))
        return _FrozenMap(out)
    raise BackendConfigError(
        f"{where} must be JSON-shaped, got {type(value).__name__}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, _FrozenMap):
        return {k: _jsonable(v) for k, v in value}
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


# ── SemanticBinding ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class SemanticBinding:
    """One fabric dimension's backend representation declaration."""

    dimension: SemanticDimension
    source_identity: str
    representation_status: RepresentationStatus
    backend_fields: tuple[tuple[str, Any], ...]
    reason: str
    certification_effect: CertificationEffect

    def __post_init__(self):
        _as_enum("dimension", SemanticDimension, self.dimension)
        _as_str("source_identity", self.source_identity)
        _as_enum("representation_status", RepresentationStatus,
                 self.representation_status)
        _as_enum("certification_effect", CertificationEffect,
                 self.certification_effect)
        if not isinstance(self.reason, str):
            raise BackendConfigError("reason must be a string")
        if not isinstance(self.backend_fields, tuple):
            raise BackendConfigError(
                "backend_fields must be a tuple of (name, value) pairs")
        seen: set[str] = set()
        frozen = []
        for item in self.backend_fields:
            if not isinstance(item, tuple) or len(item) != 2:
                raise BackendConfigError(
                    "backend_fields entries must be (name, value) pairs")
            name, value = item
            if not isinstance(name, str) or not name:
                raise BackendConfigError(
                    "backend_fields names must be non-empty strings")
            if name in seen:
                raise BackendConfigError(
                    f"backend field {name!r} declared twice")
            seen.add(name)
            frozen.append((name, _freeze_json(
                value, f"binding[{self.dimension.value}].{name}")))
        if frozen != sorted(frozen, key=lambda kv: kv[0]):
            raise BackendConfigError(
                "backend_fields must be sorted by field name")
        object.__setattr__(self, "backend_fields", tuple(frozen))

        status = self.representation_status
        effect = self.certification_effect
        if status in _EXACT_STATUSES and effect is not CertificationEffect.NONE:
            raise BackendConfigError(
                f"{self.dimension.value}: exact representation cannot carry "
                f"certification effect {effect.value}")
        if status is not RepresentationStatus.EXACT and not self.reason:
            raise BackendConfigError(
                f"{self.dimension.value}: non-exact representation "
                f"{status.value} requires a reason")
        if status is RepresentationStatus.BACKEND_IRRELEVANT \
                and effect is not CertificationEffect.NONE:
            raise BackendConfigError(
                f"{self.dimension.value}: BACKEND_IRRELEVANT carries no "
                "certification effect (state the irrelevance reason)")
        if status is RepresentationStatus.UNREPRESENTABLE \
                and effect is CertificationEffect.NONE:
            raise BackendConfigError(
                f"{self.dimension.value}: UNREPRESENTABLE must carry a "
                "certification effect")
        if status in (RepresentationStatus.COARSENED,
                      RepresentationStatus.ASSUMED_FIXED) \
                and effect is CertificationEffect.NONE:
            raise BackendConfigError(
                f"{self.dimension.value}: {status.value} must carry a "
                "certification effect")

    def identity_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "source_identity": self.source_identity,
            "representation_status": self.representation_status.value,
            "backend_fields": {k: _jsonable(v)
                               for k, v in self.backend_fields},
            "reason": self.reason,
            "certification_effect": self.certification_effect.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_dict()

    @classmethod
    def from_dict(cls, d: Any) -> "SemanticBinding":
        allowed = frozenset({
            "dimension", "source_identity", "representation_status",
            "backend_fields", "reason", "certification_effect"})
        _strict_keys(d, allowed, "semantic_binding")
        raw_fields = _need(d, "backend_fields", "semantic_binding")
        if not isinstance(raw_fields, dict):
            raise BackendConfigError(
                "semantic_binding.backend_fields must be an object")
        return cls(
            dimension=_enum_from_value("dimension", SemanticDimension,
                                       _need(d, "dimension",
                                             "semantic_binding")),
            source_identity=_need(d, "source_identity", "semantic_binding"),
            representation_status=_enum_from_value(
                "representation_status", RepresentationStatus,
                _need(d, "representation_status", "semantic_binding")),
            backend_fields=tuple(sorted(
                (k, _freeze_json(v, f"semantic_binding.{k}"))
                for k, v in raw_fields.items())),
            reason=_need(d, "reason", "semantic_binding"),
            certification_effect=_enum_from_value(
                "certification_effect", CertificationEffect,
                _need(d, "certification_effect", "semantic_binding")),
        )


# ── BackendConfigArtifact ───────────────────────────────────────────────

@dataclass(frozen=True)
class BackendConfigArtifact:
    """Path-independent backend projection of one resolved semantic fabric.

    Every SemanticDimension appears exactly once. Identity contains no
    design/mapping/workload/run/backend-binary bytes: the projection is a
    pure function of the fabric hash, the declared target/profile and the
    lowered parameters/bindings.
    """

    backend_target: BackendTarget
    backend_profile: str
    backend_semantics_version: str
    lowerer_version: str
    resolved_fabric_hash: str
    fabric_hash: str
    normalized_parameters: tuple[tuple[str, Any], ...]
    semantic_bindings: tuple[SemanticBinding, ...]

    schema_version: int = BACKEND_CONFIG_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        _as_enum("backend_target", BackendTarget, self.backend_target)
        for name in ("backend_profile", "backend_semantics_version",
                     "lowerer_version"):
            _as_str(name, getattr(self, name))
        _as_sha256("resolved_fabric_hash", self.resolved_fabric_hash)
        _as_sha256("fabric_hash", self.fabric_hash)
        if not isinstance(self.normalized_parameters, tuple):
            raise BackendConfigError(
                "normalized_parameters must be a tuple of (key, value) "
                "pairs")
        seen: set[str] = set()
        frozen = []
        for item in self.normalized_parameters:
            if not isinstance(item, tuple) or len(item) != 2:
                raise BackendConfigError(
                    "normalized_parameters entries must be (key, value) "
                    "pairs")
            key, value = item
            if not isinstance(key, str) or not key:
                raise BackendConfigError(
                    "normalized_parameters keys must be non-empty strings")
            if key in seen:
                raise BackendConfigError(
                    f"normalized parameter {key!r} declared twice")
            seen.add(key)
            frozen.append((key, _freeze_json(
                value, f"normalized_parameters.{key}")))
        if frozen != sorted(frozen, key=lambda kv: kv[0]):
            raise BackendConfigError(
                "normalized_parameters must be sorted by key")
        object.__setattr__(self, "normalized_parameters", tuple(frozen))

        if not isinstance(self.semantic_bindings, tuple) \
                or not self.semantic_bindings:
            raise BackendConfigError(
                "semantic_bindings must be a non-empty tuple")
        dims = [b.dimension for b in self.semantic_bindings]
        if len(set(dims)) != len(dims):
            raise BackendConfigError(
                "each semantic dimension may appear exactly once")
        expected = set(SemanticDimension)
        missing = expected - set(dims)
        if missing:
            raise BackendConfigError(
                f"semantic_bindings missing dimensions: "
                f"{sorted(d.value for d in missing)}")
        if dims != sorted(dims, key=lambda d: list(SemanticDimension).index(d)):
            raise BackendConfigError(
                "semantic_bindings must follow the canonical dimension "
                "order")
        if type(self.schema_version) is not int or \
                self.schema_version != BACKEND_CONFIG_SCHEMA_VERSION:
            raise BackendConfigError(
                f"unsupported backend-config schema_version "
                f"{self.schema_version!r} (expected "
                f"{BACKEND_CONFIG_SCHEMA_VERSION})")
        expected_hash = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected_hash:
            raise BackendConfigError(
                "backend_config_hash does not match content")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash", expected_hash)

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _CONFIG_HASH_TAG,
            "schema_version": self.schema_version,
            "backend_target": self.backend_target.value,
            "backend_profile": self.backend_profile,
            "backend_semantics_version": self.backend_semantics_version,
            "lowerer_version": self.lowerer_version,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "fabric_hash": self.fabric_hash,
            "normalized_parameters": {k: _jsonable(v)
                                      for k, v in self.normalized_parameters},
            "semantic_bindings": [b.identity_dict()
                                  for b in self.semantic_bindings],
        }

    def _compute_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_CONFIG_HASH_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def backend_config_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["backend_config_hash"] = self.backend_config_hash()
        return d

    # ── derived views (never independently editable) ───────────────────
    def binding(self, dimension: SemanticDimension) -> SemanticBinding:
        for b in self.semantic_bindings:
            if b.dimension is dimension:
                return b
        raise BackendConfigError(
            f"no binding for dimension {dimension.value}")

    def non_exact_bindings(self) -> tuple[SemanticBinding, ...]:
        return tuple(b for b in self.semantic_bindings
                     if b.representation_status not in _EXACT_STATUSES)

    def semantic_loss_summary(self) -> tuple[dict[str, Any], ...]:
        return tuple({
            "dimension": b.dimension.value,
            "status": b.representation_status.value,
            "effect": b.certification_effect.value,
            "reason": b.reason,
        } for b in self.non_exact_bindings())

    def exact_fabric_eligible(self) -> bool:
        """True only when no binding blocks or refuses exact execution."""
        for b in self.semantic_bindings:
            if b.certification_effect in (
                    CertificationEffect.BLOCKS_EXACT_FABRIC,
                    CertificationEffect.UNSUPPORTED_EXECUTION):
                return False
        return True

    # ── persisted parsing ──────────────────────────────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "BackendConfigArtifact":
        allowed = frozenset({
            "type", "schema_version", "backend_target", "backend_profile",
            "backend_semantics_version", "lowerer_version",
            "resolved_fabric_hash", "fabric_hash", "normalized_parameters",
            "semantic_bindings", "backend_config_hash"})
        _strict_keys(d, allowed, "backend_config")
        if _need(d, "type", "backend_config") != _CONFIG_HASH_TAG:
            raise BackendConfigError(
                f"unexpected artifact type {d.get('type')!r}")
        if _need(d, "schema_version", "backend_config") != \
                BACKEND_CONFIG_SCHEMA_VERSION:
            raise BackendConfigError(
                f"unsupported backend-config schema_version "
                f"{d.get('schema_version')!r}")
        raw_params = _need(d, "normalized_parameters", "backend_config")
        if not isinstance(raw_params, dict):
            raise BackendConfigError(
                "normalized_parameters must be an object")
        raw_bindings = _need(d, "semantic_bindings", "backend_config")
        if not isinstance(raw_bindings, list):
            raise BackendConfigError(
                "semantic_bindings must be a list")
        return cls(
            backend_target=_enum_from_value(
                "backend_target", BackendTarget,
                _need(d, "backend_target", "backend_config")),
            backend_profile=_need(d, "backend_profile", "backend_config"),
            backend_semantics_version=_need(
                d, "backend_semantics_version", "backend_config"),
            lowerer_version=_need(d, "lowerer_version", "backend_config"),
            resolved_fabric_hash=_need(
                d, "resolved_fabric_hash", "backend_config"),
            fabric_hash=_need(d, "fabric_hash", "backend_config"),
            normalized_parameters=tuple(sorted(
                (k, _freeze_json(v, f"normalized_parameters.{k}"))
                for k, v in raw_params.items())),
            semantic_bindings=tuple(
                SemanticBinding.from_dict(b) for b in raw_bindings),
            schema_version=d["schema_version"],
            artifact_hash=_need(d, "backend_config_hash", "backend_config"),
        )


# ── BackendInputManifest ────────────────────────────────────────────────

@dataclass(frozen=True)
class RenderedInput:
    """One materialized backend input file (logical, content-addressed)."""

    role: str
    logical_name: str
    sha256: str
    size: int

    def __post_init__(self):
        _as_str("role", self.role)
        _as_str("logical_name", self.logical_name)
        if self.logical_name.startswith("/") or ".." in \
                self.logical_name.split("/"):
            raise BackendInputError(
                f"logical_name must be a relative logical name, got "
                f"{self.logical_name!r}")
        _as_sha256("sha256", self.sha256)
        if type(self.size) is not int or self.size < 0:
            raise BackendInputError(
                f"size must be a non-negative int, got {self.size!r}")

    def identity_dict(self) -> dict[str, Any]:
        return {"role": self.role, "logical_name": self.logical_name,
                "sha256": self.sha256, "size": self.size}

    def to_dict(self) -> dict[str, Any]:
        return self.identity_dict()

    @classmethod
    def from_dict(cls, d: Any) -> "RenderedInput":
        allowed = frozenset({"role", "logical_name", "sha256", "size"})
        _strict_keys(d, allowed, "rendered_input", BackendInputError)
        return cls(
            role=_need(d, "role", "rendered_input", BackendInputError),
            logical_name=_need(d, "logical_name", "rendered_input",
                               BackendInputError),
            sha256=_need(d, "sha256", "rendered_input", BackendInputError),
            size=_need(d, "size", "rendered_input", BackendInputError),
        )


@dataclass(frozen=True)
class BackendInputManifest:
    """Exact per-execution scientific inputs for one backend invocation.

    ``backend_input_hash`` changes when a true backend input changes
    (workload content, seed, rendered bytes, invocation) and does NOT
    change when only a filesystem path changes. The executable/source
    identity is deliberately absent; B4 composes that later.
    """

    backend_config_hash: str
    workload_hash: str | None
    execution_mode: str
    seed: int | None
    seed_policy: str
    rendered_inputs: tuple[RenderedInput, ...]
    invocation_args: tuple[tuple[str, str], ...]

    schema_version: int = BACKEND_INPUT_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        _as_sha256("backend_config_hash", self.backend_config_hash)
        if self.workload_hash is not None:
            _as_sha256("workload_hash", self.workload_hash)
        _as_str("execution_mode", self.execution_mode)
        if self.seed is not None and (type(self.seed) is not int
                                      or self.seed < 0):
            raise BackendInputError(
                f"seed must be a non-negative int or None, got "
                f"{self.seed!r}")
        _as_str("seed_policy", self.seed_policy)
        if not isinstance(self.rendered_inputs, tuple) \
                or not self.rendered_inputs:
            raise BackendInputError(
                "rendered_inputs must be a non-empty tuple")
        names = [r.logical_name for r in self.rendered_inputs]
        if len(set(names)) != len(names):
            raise BackendInputError(
                "rendered_inputs logical names must be unique")
        if names != sorted(names):
            raise BackendInputError(
                "rendered_inputs must be sorted by logical name")
        if not isinstance(self.invocation_args, tuple):
            raise BackendInputError(
                "invocation_args must be a tuple of (name, value) pairs")
        seen: set[str] = set()
        for item in self.invocation_args:
            if not isinstance(item, tuple) or len(item) != 2 \
                    or not isinstance(item[0], str) or not item[0] \
                    or not isinstance(item[1], str):
                raise BackendInputError(
                    "invocation_args entries must be (name, value) string "
                    "pairs")
            if item[0] in seen:
                raise BackendInputError(
                    f"invocation arg {item[0]!r} declared twice")
            seen.add(item[0])
            _no_absolute_paths(item[1], f"invocation_args.{item[0]}",
                               BackendInputError)
        if self.invocation_args != tuple(
                sorted(self.invocation_args, key=lambda kv: kv[0])):
            raise BackendInputError(
                "invocation_args must be sorted by name")
        if type(self.schema_version) is not int or \
                self.schema_version != BACKEND_INPUT_SCHEMA_VERSION:
            raise BackendInputError(
                f"unsupported backend-input schema_version "
                f"{self.schema_version!r} (expected "
                f"{BACKEND_INPUT_SCHEMA_VERSION})")
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise BackendInputError(
                "backend_input_hash does not match content")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash", expected)

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _INPUT_HASH_TAG,
            "schema_version": self.schema_version,
            "backend_config_hash": self.backend_config_hash,
            "workload_hash": self.workload_hash,
            "execution_mode": self.execution_mode,
            "seed": self.seed,
            "seed_policy": self.seed_policy,
            "rendered_inputs": [r.identity_dict()
                                for r in self.rendered_inputs],
            "invocation_args": {k: v for k, v in self.invocation_args},
        }

    def _compute_hash(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = (f"{_INPUT_HASH_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def backend_input_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["backend_input_hash"] = self.backend_input_hash()
        return d

    def input(self, logical_name: str) -> RenderedInput:
        for r in self.rendered_inputs:
            if r.logical_name == logical_name:
                return r
        raise BackendInputError(
            f"no rendered input named {logical_name!r}")

    # ── persisted parsing ──────────────────────────────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "BackendInputManifest":
        allowed = frozenset({
            "type", "schema_version", "backend_config_hash", "workload_hash",
            "execution_mode", "seed", "seed_policy", "rendered_inputs",
            "invocation_args", "backend_input_hash"})
        _strict_keys(d, allowed, "backend_input", BackendInputError)
        if _need(d, "type", "backend_input", BackendInputError) != \
                _INPUT_HASH_TAG:
            raise BackendInputError(
                f"unexpected artifact type {d.get('type')!r}")
        if _need(d, "schema_version", "backend_input", BackendInputError) != \
                BACKEND_INPUT_SCHEMA_VERSION:
            raise BackendInputError(
                f"unsupported backend-input schema_version "
                f"{d.get('schema_version')!r}")
        raw_inputs = _need(d, "rendered_inputs", "backend_input",
                           BackendInputError)
        if not isinstance(raw_inputs, list):
            raise BackendInputError("rendered_inputs must be a list")
        raw_args = _need(d, "invocation_args", "backend_input",
                         BackendInputError)
        if not isinstance(raw_args, dict):
            raise BackendInputError("invocation_args must be an object")
        return cls(
            backend_config_hash=_need(d, "backend_config_hash",
                                      "backend_input", BackendInputError),
            workload_hash=d.get("workload_hash"),
            execution_mode=_need(d, "execution_mode", "backend_input",
                                 BackendInputError),
            seed=d.get("seed"),
            seed_policy=_need(d, "seed_policy", "backend_input",
                              BackendInputError),
            rendered_inputs=tuple(
                RenderedInput.from_dict(r) for r in raw_inputs),
            invocation_args=tuple(sorted(
                (k, v) for k, v in raw_args.items())),
            schema_version=d["schema_version"],
            artifact_hash=_need(d, "backend_input_hash", "backend_input",
                                BackendInputError),
        )


def sha256_bytes(data: bytes) -> str:
    """Content hash used by both manifests and rendered inputs."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Any) -> str:
    """Streaming file hash (large traces must not be slurped twice)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "BACKEND_CONFIG_SCHEMA_VERSION",
    "BACKEND_INPUT_SCHEMA_VERSION",
    "BackendConfigArtifact",
    "BackendConfigError",
    "BackendInputError",
    "BackendInputManifest",
    "BackendTarget",
    "CertificationEffect",
    "RenderedInput",
    "RepresentationStatus",
    "SemanticBinding",
    "SemanticDimension",
    "sha256_bytes",
    "sha256_file",
]
