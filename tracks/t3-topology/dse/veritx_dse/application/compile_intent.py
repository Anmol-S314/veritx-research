"""veritx_dse.application.compile_intent — compile-only product boundary.

The smallest product-facing input boundary that can reach the canonical
architecture:

    CompileIntent
        ├── fabric_preset
        ├── strict overrides
        └── candidate_policy
                 |
                 v
           CompileRequest
                 |
                 v
       Slice-24 candidate policy
                 |
                 v
       Slice-23 canonical compiler
                 |
                 v
           ResolvedFabric

This module owns exactly:

1. named product ``CompileRequest`` presets (the authoritative canonical
   product preset registry: ``mesh4``, ``mesh4_hbm``, ``mesh4_wide128``);
2. strict, type-safe dotted-path preset overrides;
3. an immutable compile-only product intent with its own content id;
4. derivation of the exact canonical ``CompileRequest``;
5. explicit selection of the candidate-generation policy.

It does NOT own workload-trace transport, backend targets, seeds,
metrics, timeouts, execution, verification, persistence, or service
orchestration. ``CompileRequest.workload`` below is ordinary design
semantics, not a product trace-transport concern.

INTENT IDENTITY

    intent_id = content_id(
        "srota/CompileIntent/v2",
        {type, schema_version, compiler_semantics_version, fabric_preset,
         preset_design_hash, fabric_overrides, candidate_policy})

``name`` is presentation: it round-trips and never enters the id.
The id represents the DECLARED product request, not the resulting
hardware — a changed override changes intent identity even if a compiler
later produced equivalent hardware.

The intent is CLOSED over every semantics needed to reproduce its derived
design: it pins the compiler semantics version and the exact semantic
revision of the named preset (``preset_design_hash`` is the
``design_hash()`` of the un-overridden base preset under that compiler
semantics version — the existing canonical design hash, not an invented
preset fingerprint). A schema-v1 CompileIntent predates this pinning and
is refused explicitly; it is never silently reinterpreted.

OVERRIDE MODEL

``fabric_overrides`` is a canonical, sorted, duplicate-free tuple of
``(dotted_path, JSON scalar)`` pairs; transport form is a JSON object.
Paths address existing dictionary fields only (no array indices), may not
create fields, and may not touch the computed identity fields
(``design_hash``/``guardrail_hash``) or the envelope/version fields. When
the current leaf is non-null the override must preserve the exact JSON
semantic type — ``bool`` is not ``int`` — while a null leaf defers final
type authority to the canonical ``CompileRequest`` parser.

Nothing in the lower architecture imports this module.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from veritx_dse.compiler.candidate_policy import CandidatePolicy
from veritx_dse.core.artifact import content_id
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, AddressMap, AddressRange, Agent, AgentKind,
    CompileRequest, DepKind, Dependency, DependencyGraph, ModelFamily,
    NocConfig, TopologyFamily, Workload,
)

COMPILE_INTENT_SCHEMA_VERSION = 2
_HASH_TYPE_TAG = "srota/CompileIntent"

# Exactly the computed identity fields CompileRequest.to_dict() serializes.
# These are stripped before reparse so from_dict() recomputes them under the
# overridden semantics. Explicit set only — no "endswith _hash" catch-all.
COMPUTED_IDENTITY_FIELDS = frozenset({"design_hash", "guardrail_hash"})

# Product callers may never select the schema/compiler-semantics envelope or
# the computed identity fields through an override.
RESERVED_OVERRIDE_PATHS = frozenset({
    "schema_version", "compiler_semantics_version", "type",
    "design_hash", "guardrail_hash",
})


class CompileIntentError(ValueError):
    """The product intent/preset/override boundary rejected the input."""


# ── product preset registry ───────────────────────────────────────────────

@dataclass(frozen=True)
class CompilePreset:
    """Named product preset descriptor (presentation-level metadata only)."""

    name: str
    description: str


_COMPUTE_KIND = AgentKind.COMPUTE_TILE
_BLOCKING_KIND = DepKind.BLOCKING


def _mesh4_agents() -> tuple[Agent, ...]:
    return (Agent(kind=_COMPUTE_KIND, count=4, protocol="AXI",
                  data_width=256, addr_width=64),)


def _mesh4_dependencies() -> DependencyGraph:
    return DependencyGraph((Dependency("A", "B", _BLOCKING_KIND),
                            Dependency("B", "A", _BLOCKING_KIND)))


def _mesh4_workload() -> Workload:
    """The carrier workload for the mesh4 FABRIC presets.

    DENSE_TRANSFORMER, not MOE: these presets exist to certify a 4-tile
    mesh, they carry a minimal synthetic trace, and ``tp=ep=dp=1`` means
    they exercise no parallelism structure. Declaring MOE made the preset
    fail COND-DENSE-STATIC-WORKLOAD, a condition of the very envelope
    GUIDED-EXPERT.md certifies it under. See application/presets.py for
    the inertness proof.
    """
    return Workload(model_family=ModelFamily.DENSE_TRANSFORMER,
                    tp=1, pp=1, ep=1, dp=1)


def _mesh4_request() -> CompileRequest:
    """4-tile mesh, multi-class baseline derivation (no address map)."""
    return CompileRequest(
        workload=_mesh4_workload(),
        requirements=[],
        agents=_mesh4_agents(),
        dependencies=_mesh4_dependencies(),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        address_map=AddressMap())


def _mesh4_hbm_request() -> CompileRequest:
    """mesh4 plus one HBM controller and its single address range."""
    return CompileRequest(
        workload=_mesh4_workload(),
        requirements=[],
        agents=_mesh4_agents() + (
            Agent(kind=AgentKind.HBM_CONTROLLER, count=1, protocol="AXI",
                  data_width=256, addr_width=64),),
        dependencies=_mesh4_dependencies(),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=1),)))


def _mesh4_wide128_request() -> CompileRequest:
    """mesh4 with 128-bit links as explicit design intent."""
    return CompileRequest(
        workload=_mesh4_workload(),
        requirements=[],
        agents=_mesh4_agents(),
        dependencies=_mesh4_dependencies(),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH,
                             link_width=128),
        address_map=AddressMap())


# Structurally immutable module-level registries: no runtime caller can
# mutate preset descriptors or the preset->builder association. Builders
# always construct fresh CompileRequest objects (see test_preset_requests_are_fresh_and_frozen).
_PRESETS: Mapping[str, CompilePreset] = MappingProxyType({
    "mesh4": CompilePreset(
        name="mesh4",
        description="4-tile mesh fabric (multi-class baseline derivation)"),
    "mesh4_hbm": CompilePreset(
        name="mesh4_hbm",
        description="4-tile mesh with one HBM controller and address map"),
    "mesh4_wide128": CompilePreset(
        name="mesh4_wide128",
        description="4-tile mesh with 128-bit links"),
})
_PRESET_BUILDERS: Mapping[str, Any] = MappingProxyType({
    "mesh4": _mesh4_request,
    "mesh4_hbm": _mesh4_hbm_request,
    "mesh4_wide128": _mesh4_wide128_request,
})


def preset_names() -> tuple[str, ...]:
    """The complete current product preset registry (no fallback preset)."""
    return tuple(_PRESETS)


def get_preset(name: str) -> CompilePreset:
    if not isinstance(name, str):
        raise CompileIntentError(
            f"preset name must be a string, got {type(name).__name__}")
    preset = _PRESETS.get(name)
    if preset is None:
        raise CompileIntentError(
            f"unknown product preset {name!r}; known presets: "
            f"{list(preset_names())}")
    return preset


def build_preset_request(name: str) -> CompileRequest:
    """Fresh canonical CompileRequest for a named product preset."""
    get_preset(name)  # raises CompileIntentError for unknown names
    return _PRESET_BUILDERS[name]()


# ── strict override model ─────────────────────────────────────────────────

def _is_json_scalar(value: Any) -> bool:
    if value is None or type(value) is bool or type(value) is int \
            or isinstance(value, str):
        return True
    if type(value) is float:
        return math.isfinite(value)
    return False


def _check_override_value(path: str, value: Any) -> None:
    if not _is_json_scalar(value):
        raise CompileIntentError(
            f"override {path!r} must be a JSON scalar (null, bool, int, "
            f"finite float or string), got {type(value).__name__}")


def _check_override_path(path: Any) -> str:
    if not isinstance(path, str) or not path:
        raise CompileIntentError(
            f"override path must be a non-empty string, got {path!r}")
    if path in RESERVED_OVERRIDE_PATHS:
        raise CompileIntentError(
            f"override path {path!r} is reserved: schema/compiler-semantics "
            "envelope and computed identity fields come from the running "
            "canonical compiler, never from product overrides")
    if any(not segment for segment in path.split(".")):
        raise CompileIntentError(
            f"override path {path!r} has an empty segment")
    return path


def _normalize_overrides(value: Any) -> tuple[tuple[str, Any], ...]:
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, (tuple, list)):
        items = []
        for item in value:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise CompileIntentError(
                    "fabric_overrides sequence entries must be "
                    "(path, value) pairs")
            items.append((item[0], item[1]))
    else:
        raise CompileIntentError(
            "fabric_overrides must be a mapping or a sequence of "
            "(path, value) pairs")
    seen: set[str] = set()
    rows: list[tuple[str, Any]] = []
    for raw_path, raw_value in items:
        path = _check_override_path(raw_path)
        if path in seen:
            raise CompileIntentError(
                f"duplicate override for {path!r}; duplicate declarations "
                "are refused (no last-write-wins)")
        seen.add(path)
        _check_override_value(path, raw_value)
        rows.append((path, raw_value))
    return tuple(sorted(rows))


def _apply_overrides(d: dict[str, Any],
                     overrides: tuple[tuple[str, Any], ...]) -> None:
    for path, value in overrides:
        _check_override_path(path)
        segments = path.split(".")
        node: Any = d
        for segment in segments[:-1]:
            if not isinstance(node, dict):
                raise CompileIntentError(
                    f"override path {path!r} descends through a "
                    "non-dictionary value (array/list-index overrides are "
                    "not supported)")
            if segment not in node:
                raise CompileIntentError(
                    f"override path {path!r} names unknown field "
                    f"{segment!r}; overrides may not create fields")
            node = node[segment]
        leaf = segments[-1]
        if not isinstance(node, dict) or leaf not in node:
            raise CompileIntentError(
                f"override path {path!r} names unknown field {leaf!r}; "
                "overrides may not create fields")
        current = node[leaf]
        if current is not None and type(current) is not type(value):
            raise CompileIntentError(
                f"override for {path!r} changes JSON semantic type: "
                f"existing leaf is {type(current).__name__}, override is "
                f"{type(value).__name__} (bool is not int; no coercion)")
        node[leaf] = value


def _require_intent(intent: Any) -> "CompileIntent":
    if not isinstance(intent, CompileIntent):
        raise CompileIntentError(
            f"intent must be a CompileIntent, got {type(intent).__name__}")
    return intent


def derive_compile_request(intent: CompileIntent) -> CompileRequest:
    """Build the exact canonical CompileRequest declared by an intent.

    Fresh preset -> canonical to_dict() -> strict overrides -> strip the
    computed identity fields -> canonical CompileRequest.from_dict().
    The preset object itself is never mutated; the canonical parser is the
    final type authority for null leaves. Every user/product declaration
    failure surfaces as CompileIntentError with the canonical underlying
    exception preserved through ``__cause__`` — canonical semantic
    authority is never flattened into this boundary.
    """
    _require_intent(intent)
    d = build_preset_request(intent.fabric_preset).to_dict()
    for field in COMPUTED_IDENTITY_FIELDS:
        d.pop(field, None)
    _apply_overrides(d, intent.fabric_overrides)
    try:
        return CompileRequest.from_dict(d)
    except ValueError as exc:
        raise CompileIntentError(
            f"preset {intent.fabric_preset!r} with the declared overrides "
            f"does not form a valid CompileRequest: {exc}") from exc


# ── compile-only product intent ───────────────────────────────────────────

@dataclass(frozen=True)
class CompileIntent:
    """Immutable compile-only declaration of a product compile request.

    ``compiler_semantics_version`` and ``preset_design_hash`` are bound on
    construction (callers do not supply them): they pin the compiler
    semantics and the exact semantic revision of the named preset. If
    explicitly present (deserialization), they must equal the current
    expected values — a stale pin is refused, never accepted silently.
    """

    name: str
    fabric_preset: str
    fabric_overrides: tuple[tuple[str, Any], ...]
    candidate_policy: CandidatePolicy
    schema_version: int = COMPILE_INTENT_SCHEMA_VERSION
    compiler_semantics_version: int | None = None
    preset_design_hash: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise CompileIntentError(
                "name must be a non-empty string (presentation only)")
        get_preset(self.fabric_preset)
        object.__setattr__(
            self, "fabric_overrides",
            _normalize_overrides(self.fabric_overrides))
        if not isinstance(self.candidate_policy, CandidatePolicy):
            raise CompileIntentError(
                "candidate_policy must be a CandidatePolicy, got "
                f"{type(self.candidate_policy).__name__}; it is required "
                "and may not be defaulted")
        if type(self.schema_version) is not int or \
                self.schema_version != COMPILE_INTENT_SCHEMA_VERSION:
            raise CompileIntentError(
                f"unsupported CompileIntent schema_version "
                f"{self.schema_version!r} (expected "
                f"{COMPILE_INTENT_SCHEMA_VERSION})")
        expected_semantics = COMPILER_SEMANTICS_VERSION
        expected_preset_hash = build_preset_request(
            self.fabric_preset).design_hash()
        if self.compiler_semantics_version is None:
            object.__setattr__(self, "compiler_semantics_version",
                               expected_semantics)
        elif type(self.compiler_semantics_version) is not int \
                or self.compiler_semantics_version != expected_semantics:
            raise CompileIntentError(
                f"compiler_semantics_version "
                f"{self.compiler_semantics_version!r} does not match the "
                f"current compiler semantics {expected_semantics}; a stale "
                "pin is refused — rebuild the intent")
        if self.preset_design_hash is None:
            object.__setattr__(self, "preset_design_hash",
                               expected_preset_hash)
        elif not isinstance(self.preset_design_hash, str) \
                or self.preset_design_hash != expected_preset_hash:
            raise CompileIntentError(
                f"preset_design_hash {self.preset_design_hash!r} does not "
                f"match the current revision of preset "
                f"{self.fabric_preset!r} ({expected_preset_hash}); a stale "
                "pin is refused — rebuild the intent")

    def identity_dict(self) -> dict[str, Any]:
        """Declared-request identity: no display name, no derived state."""
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            "fabric_preset": self.fabric_preset,
            "preset_design_hash": self.preset_design_hash,
            "fabric_overrides": [[path, value]
                                 for path, value in self.fabric_overrides],
            "candidate_policy": self.candidate_policy.value,
        }

    def intent_id(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "compiler_semantics_version": self.compiler_semantics_version,
            "fabric_preset": self.fabric_preset,
            "preset_design_hash": self.preset_design_hash,
            "fabric_overrides": {path: value
                                 for path, value in self.fabric_overrides},
            "candidate_policy": self.candidate_policy.value,
            "intent_id": self.intent_id(),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "CompileIntent":
        allowed = frozenset({"schema_version", "name", "fabric_preset",
                             "fabric_overrides", "candidate_policy",
                             "intent_id", "compiler_semantics_version",
                             "preset_design_hash"})
        if not isinstance(d, dict):
            raise CompileIntentError(
                f"compile intent must be an object, got "
                f"{type(d).__name__}")
        # A schema-v1 document predates the compiler-semantics and
        # preset-revision pins; it is refused explicitly and never
        # silently reinterpreted or auto-migrated here.
        if type(d.get("schema_version")) is int and d["schema_version"] == 1:
            raise CompileIntentError(
                "CompileIntent v1 predates compiler-semantics and "
                "preset-revision pinning; rebuild the intent under schema "
                "v2.")
        unknown = set(d) - allowed
        if unknown:
            raise CompileIntentError(
                f"compile intent has unknown fields: {sorted(unknown)}")
        missing = allowed - set(d)
        if missing:
            raise CompileIntentError(
                f"compile intent is missing required fields: "
                f"{sorted(missing)}")
        if not isinstance(d["name"], str) or not d["name"]:
            raise CompileIntentError("name must be a non-empty string")
        if not isinstance(d["fabric_preset"], str):
            raise CompileIntentError("fabric_preset must be a string")
        if not isinstance(d["fabric_overrides"], dict):
            raise CompileIntentError(
                "fabric_overrides must be a JSON object in transport form")
        if not isinstance(d["candidate_policy"], str):
            raise CompileIntentError(
                "candidate_policy must be a string policy value")
        try:
            policy = CandidatePolicy(d["candidate_policy"])
        except ValueError:
            raise CompileIntentError(
                f"unknown candidate_policy {d['candidate_policy']!r}; known: "
                f"{[member.value for member in CandidatePolicy]}") from None
        if not isinstance(d["intent_id"], str) or not d["intent_id"]:
            raise CompileIntentError("intent_id must be a non-empty string")
        intent = cls(
            name=d["name"],
            fabric_preset=d["fabric_preset"],
            fabric_overrides=_normalize_overrides(d["fabric_overrides"]),
            candidate_policy=policy,
            schema_version=d["schema_version"],
            compiler_semantics_version=d["compiler_semantics_version"],
            preset_design_hash=d["preset_design_hash"],
        )
        if d["intent_id"] != intent.intent_id():
            raise CompileIntentError(
                "intent_id does not match the declared intent content")
        return intent
