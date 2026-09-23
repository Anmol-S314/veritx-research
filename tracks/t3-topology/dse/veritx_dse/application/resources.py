"""veritx_dse.application.resources — durable application resource envelopes.

The first durable persistence boundary for canonical compilation defines
exactly four resource kinds:

    CompileIntentRecord    key = intent_id              (this module)
    CompileRequest         key = design_hash            (model, verbatim)
    ResolvedFabric         key = resolved_fabric_hash   (model, verbatim)
    CompileResolution      key = intent_id              (this module)

Relationship:

    CompileIntent declaration
            |
            v
    CompileIntentRecord
     key = intent_id
            |
            v
    CompileResolution
     key = intent_id
     |-- design_hash ----------> CompileRequest
     `-- resolved_fabric_hash -> ResolvedFabric

There is NO CompiledDesign hash, NO resolution hash, NO store-generated
UUID, NO timestamp identity, and NO duplicate hash over
``{design_hash,mapping_hash,fabric_hash}``. ``ResolvedFabric`` already owns
precisely that semantic identity.

WHY CompileIntent IS NOT STORED VERBATIM

``intent_id`` deliberately excludes ``CompileIntent.name`` (presentation
metadata). Two intents named ``"alpha"`` and ``"beta"`` can therefore share
one ``intent_id`` while having different ``to_dict()`` bytes. An
identity-addressed store keyed by ``intent_id`` must not persist
``CompileIntent.to_dict()``; it persists :class:`CompileIntentRecord`, the
exact *semantic* declaration. Human labels belong to a future
project/UI metadata layer. ``CompileIntent`` identity is not redefined to
solve a storage problem.

These envelopes are persistence projections, NOT new semantic identities:
neither type has a hash method. ``CompileIntentRecord`` validation
recomputes the EXISTING CompileIntent identity equation and requires it to
equal the stored ``intent_id``; the projection is pinned structurally
against ``CompileIntent.identity_dict()`` so it cannot drift.

CURRENT-ONLY WRITE POLICY

The first persistent store begins after the v2 semantics migration, so
both parsers accept only current CompileIntent schema v2, current compiler
semantics v2, and a currently recognized candidate policy. Pre-25B v1
application intents are refused explicitly; no silent reinterpretation and
no migration is performed here.

This module imports neither candidate generation nor the canonical
compiler: it only validates and links already-produced resources.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.application.compile_intent import (
    COMPILE_INTENT_SCHEMA_VERSION, CompileIntent, CompileIntentError,
    derive_compile_request,
)
from veritx_dse.core.artifact import content_id
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, CompileRequest, CompileRequestSchemaError,
)
from veritx_dse.model.resolved_fabric import ResolvedFabric

COMPILE_INTENT_RECORD_SCHEMA_VERSION = 1
COMPILE_RESOLUTION_SCHEMA_VERSION = 1

_INTENT_TYPE_TAG = "srota/CompileIntent"
_RECORD_TYPE_TAG = "srota/CompileIntentRecord"
_RESOLUTION_TYPE_TAG = "srota/CompileResolution"

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")

# Synthetic presentation name used only to reconstruct a current
# CompileIntent for semantic validation. Never serialized, never returned.
_VALIDATION_NAME = "validation-only"


class ResourceValidationError(ValueError):
    """A resource envelope failed strict validation."""


def _require_key_id(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _HEX64.match(value):
        raise ResourceValidationError(
            f"{name} must be a canonical 64-character lowercase hex id, "
            f"got {value!r}")
    return value


def _require_int(name: str, value: Any, expected: int) -> int:
    if type(value) is not int:
        raise ResourceValidationError(
            f"{name} must be an exact int, got {type(value).__name__}")
    if value != expected:
        raise ResourceValidationError(
            f"unsupported {name} {value!r} (expected {expected})")
    return value


def _is_json_scalar(value: Any) -> bool:
    if value is None or type(value) is bool or type(value) is int \
            or isinstance(value, str):
        return True
    if type(value) is float:
        return math.isfinite(value)
    return False


def _normalize_overrides(value: Any) -> tuple[tuple[str, Any], ...]:
    """Canonical sorted immutable ``((path, scalar), ...)``.

    Uses the exact representation CompileIntent identity requires: JSON
    scalars only, non-empty dotted paths, duplicate-free, sorted by path.
    """
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, (tuple, list)):
        items = []
        for item in value:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ResourceValidationError(
                    "fabric_overrides entries must be (path, value) pairs")
            items.append((item[0], item[1]))
    else:
        raise ResourceValidationError(
            "fabric_overrides must be a mapping or a sequence of "
            "(path, value) pairs")
    seen: set[str] = set()
    rows: list[tuple[str, Any]] = []
    for path, scalar in items:
        if not isinstance(path, str) or not path:
            raise ResourceValidationError(
                "override path must be a non-empty string")
        if any(not segment for segment in path.split(".")):
            raise ResourceValidationError(
                f"override path {path!r} has an empty segment")
        if path in seen:
            raise ResourceValidationError(
                f"duplicate override for {path!r}; duplicate declarations "
                "are refused (no last-write-wins)")
        seen.add(path)
        if not _is_json_scalar(scalar):
            raise ResourceValidationError(
                f"override {path!r} must be a JSON scalar (null, bool, "
                f"int, finite float or string), got {type(scalar).__name__}")
        rows.append((path, scalar))
    rows.sort(key=lambda row: row[0])
    return tuple(rows)


# ── CompileIntentRecord ───────────────────────────────────────────────────

@dataclass(frozen=True)
class CompileIntentRecord:
    """Persistence envelope for the semantic CompileIntent declaration.

    Exactly the identity-bearing declaration; no presentation name, no
    derived design/mapping/fabric/resolved hash, no timestamp, no user, no
    git SHA. The resource key is ``intent_id``.
    """

    intent_schema_version: int
    compiler_semantics_version: int
    fabric_preset: str
    preset_design_hash: str
    fabric_overrides: Any
    candidate_policy: str
    intent_id: str
    schema_version: int = COMPILE_INTENT_RECORD_SCHEMA_VERSION

    def __post_init__(self):
        _require_int("schema_version", self.schema_version,
                     COMPILE_INTENT_RECORD_SCHEMA_VERSION)
        _require_int("intent_schema_version", self.intent_schema_version,
                     COMPILE_INTENT_SCHEMA_VERSION)
        _require_int("compiler_semantics_version",
                     self.compiler_semantics_version,
                     COMPILER_SEMANTICS_VERSION)
        if not isinstance(self.fabric_preset, str) or not self.fabric_preset:
            raise ResourceValidationError(
                "fabric_preset must be a non-empty string")
        if not isinstance(self.candidate_policy, str) \
                or not self.candidate_policy:
            raise ResourceValidationError(
                "candidate_policy must be a non-empty string")
        _require_key_id("preset_design_hash", self.preset_design_hash)
        _require_key_id("intent_id", self.intent_id)
        object.__setattr__(self, "fabric_overrides",
                           _normalize_overrides(self.fabric_overrides))
        expected = content_id(
            f"{_INTENT_TYPE_TAG}/v{self.intent_schema_version}",
            self.identity_payload())
        if expected != self.intent_id:
            raise ResourceValidationError(
                "intent_id does not match the recomputed CompileIntent "
                "identity — record tampered with or drifted")
        # Current-only: the declaration must still be accepted by the
        # running application semantics (preset revision, policy
        # vocabulary, compiler semantics).
        self.to_current_intent(name=_VALIDATION_NAME)

    # -- projections ------------------------------------------------------

    def identity_payload(self) -> dict[str, Any]:
        """The exact payload of the CompileIntent identity equation."""
        return {
            "type": _INTENT_TYPE_TAG,
            "schema_version": self.intent_schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            "fabric_preset": self.fabric_preset,
            "preset_design_hash": self.preset_design_hash,
            "fabric_overrides": [[path, value]
                                 for path, value in self.fabric_overrides],
            "candidate_policy": self.candidate_policy,
        }

    def to_current_intent(self, *, name: str) -> CompileIntent:
        """Reconstruct a current CompileIntent for semantic operations.

        ``name`` is supplied by the caller; the record never stores a
        presentation name. Fails explicitly if current semantics no longer
        accept the stored declaration.
        """
        if not isinstance(name, str) or not name:
            raise ResourceValidationError(
                "name must be a non-empty string (presentation only)")
        document = {
            "schema_version": self.intent_schema_version,
            "name": name,
            "compiler_semantics_version": self.compiler_semantics_version,
            "fabric_preset": self.fabric_preset,
            "preset_design_hash": self.preset_design_hash,
            "fabric_overrides": {path: value
                                 for path, value in self.fabric_overrides},
            "candidate_policy": self.candidate_policy,
            "intent_id": self.intent_id,
        }
        try:
            intent = CompileIntent.from_dict(document)
        except CompileIntentError as exc:
            raise ResourceValidationError(
                "stored intent declaration is not accepted by current "
                f"semantics: {exc}") from exc
        if not isinstance(intent, CompileIntent) \
                or intent.intent_id() != self.intent_id:
            raise ResourceValidationError(
                "reconstructed CompileIntent does not reproduce intent_id")
        return intent

    # -- serialization ----------------------------------------------------

    @classmethod
    def from_intent(cls, intent: Any) -> "CompileIntentRecord":
        """Semantic projection of a current CompileIntent.

        Copies only identity-bearing fields; ``name`` is copied nowhere.
        """
        if not isinstance(intent, CompileIntent):
            raise ResourceValidationError(
                f"intent must be a CompileIntent, got {type(intent).__name__}")
        record = cls(
            intent_schema_version=intent.schema_version,
            compiler_semantics_version=intent.compiler_semantics_version,
            fabric_preset=intent.fabric_preset,
            preset_design_hash=intent.preset_design_hash,
            fabric_overrides=intent.fabric_overrides,
            candidate_policy=intent.candidate_policy.value,
            intent_id=intent.intent_id(),
        )
        if record.identity_payload() != intent.identity_dict():
            raise ResourceValidationError(
                "intent record payload does not match CompileIntent identity")
        if record.intent_id != intent.intent_id():
            raise ResourceValidationError(
                "intent record intent_id does not match the intent")
        return record

    def to_dict(self) -> dict[str, Any]:
        """Fresh serialization each call; lossless for semantic fields."""
        return {
            "type": _RECORD_TYPE_TAG,
            "schema_version": self.schema_version,
            "intent_schema_version": self.intent_schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            "fabric_preset": self.fabric_preset,
            "preset_design_hash": self.preset_design_hash,
            "fabric_overrides": [[path, value]
                                 for path, value in self.fabric_overrides],
            "candidate_policy": self.candidate_policy,
            "intent_id": self.intent_id,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "CompileIntentRecord":
        allowed = frozenset({
            "type", "schema_version", "intent_schema_version",
            "compiler_semantics_version", "fabric_preset",
            "preset_design_hash", "fabric_overrides", "candidate_policy",
            "intent_id"})
        if not isinstance(d, dict):
            raise ResourceValidationError(
                f"intent record must be a JSON object, got "
                f"{type(d).__name__}")
        unknown = set(d) - allowed
        if unknown:
            raise ResourceValidationError(
                f"intent record has unknown fields: {sorted(unknown)}")
        missing = allowed - set(d)
        if missing:
            raise ResourceValidationError(
                f"intent record is missing required fields: "
                f"{sorted(missing)}")
        if d["type"] != _RECORD_TYPE_TAG:
            raise ResourceValidationError(
                f"intent record type must be {_RECORD_TYPE_TAG!r}, got "
                f"{d['type']!r}")
        return cls(
            intent_schema_version=d["intent_schema_version"],
            compiler_semantics_version=d["compiler_semantics_version"],
            fabric_preset=d["fabric_preset"],
            preset_design_hash=d["preset_design_hash"],
            fabric_overrides=d["fabric_overrides"],
            candidate_policy=d["candidate_policy"],
            intent_id=d["intent_id"],
            schema_version=d["schema_version"],
        )


# ── CompileResolution ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompileResolution:
    """This exact product declaration resolved to this exact design/hardware.

    No hash field, no name, no candidate-policy duplicate, no mapping hash,
    no fabric hash, no backend, no verification, no timestamp. The storage
    key is ``intent_id``, and there is deliberately no independent content
    hash: a second hash domain would give one compiled design two competing
    canonical ids, since ``ResolvedFabric`` already owns that identity.
    """

    intent_id: str
    design_hash: str
    resolved_fabric_hash: str
    schema_version: int = COMPILE_RESOLUTION_SCHEMA_VERSION

    def __post_init__(self):
        _require_int("schema_version", self.schema_version,
                     COMPILE_RESOLUTION_SCHEMA_VERSION)
        _require_key_id("intent_id", self.intent_id)
        _require_key_id("design_hash", self.design_hash)
        _require_key_id("resolved_fabric_hash", self.resolved_fabric_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": _RESOLUTION_TYPE_TAG,
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "design_hash": self.design_hash,
            "resolved_fabric_hash": self.resolved_fabric_hash,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "CompileResolution":
        allowed = frozenset({"type", "schema_version", "intent_id",
                             "design_hash", "resolved_fabric_hash"})
        if not isinstance(d, dict):
            raise ResourceValidationError(
                f"compile resolution must be a JSON object, got "
                f"{type(d).__name__}")
        unknown = set(d) - allowed
        if unknown:
            raise ResourceValidationError(
                f"compile resolution has unknown fields: {sorted(unknown)}")
        missing = allowed - set(d)
        if missing:
            raise ResourceValidationError(
                f"compile resolution is missing required fields: "
                f"{sorted(missing)}")
        if d["type"] != _RESOLUTION_TYPE_TAG:
            raise ResourceValidationError(
                f"compile resolution type must be {_RESOLUTION_TYPE_TAG!r}, "
                f"got {d['type']!r}")
        return cls(
            intent_id=d["intent_id"],
            design_hash=d["design_hash"],
            resolved_fabric_hash=d["resolved_fabric_hash"],
            schema_version=d["schema_version"],
        )

    def validate_against(self, intent_record: "CompileIntentRecord",
                         design: CompileRequest,
                         resolved_fabric: ResolvedFabric) -> None:
        """Prove every link of a committed resolution.

        All three referenced resources must pass their own strict parsers,
        and the reconstructed current CompileIntent must derive exactly the
        supplied design. Fails explicitly rather than weakening validation.
        """
        if not isinstance(intent_record, CompileIntentRecord):
            raise ResourceValidationError(
                f"intent_record must be a CompileIntentRecord, got "
                f"{type(intent_record).__name__}")
        if not isinstance(design, CompileRequest):
            raise ResourceValidationError(
                f"design must be a CompileRequest, got "
                f"{type(design).__name__}")
        if not isinstance(resolved_fabric, ResolvedFabric):
            raise ResourceValidationError(
                f"resolved_fabric must be a ResolvedFabric, got "
                f"{type(resolved_fabric).__name__}")
        # strict self-validation through the canonical parsers
        record = CompileIntentRecord.from_dict(intent_record.to_dict())
        try:
            reparsed_design = CompileRequest.from_dict(design.to_dict())
        except (CompileRequestSchemaError, ValueError) as exc:
            raise ResourceValidationError(
                f"supplied design is not a valid CompileRequest: {exc}",
            ) from exc
        if reparsed_design.compiler_semantics_version \
                != COMPILER_SEMANTICS_VERSION:
            raise ResourceValidationError(
                "supplied design does not use current compiler semantics "
                f"v{COMPILER_SEMANTICS_VERSION}")
        try:
            reparsed_resolved = ResolvedFabric.from_dict(
                resolved_fabric.to_dict())
        except ValueError as exc:
            raise ResourceValidationError(
                f"supplied resolved fabric is not valid: {exc}") from exc
        if self.intent_id != record.intent_id:
            raise ResourceValidationError(
                "resolution intent_id does not match the intent record")
        if self.design_hash != reparsed_design.design_hash():
            raise ResourceValidationError(
                "resolution design_hash does not match the design")
        if self.resolved_fabric_hash \
                != reparsed_resolved.resolved_fabric_hash:
            raise ResourceValidationError(
                "resolution resolved_fabric_hash does not match the "
                "resolved fabric")
        if reparsed_resolved.design_hash != reparsed_design.design_hash():
            raise ResourceValidationError(
                "resolved fabric design_hash does not match the design")
        current_intent = record.to_current_intent(name=_VALIDATION_NAME)
        derived = derive_compile_request(current_intent)
        if derived.to_dict() != reparsed_design.to_dict():
            raise ResourceValidationError(
                "supplied design is not exactly the request declared by "
                "the intent record")


def make_compile_resolution(*, intent: CompileIntent,
                            design: CompileRequest,
                            resolved_fabric: ResolvedFabric
                            ) -> CompileResolution:
    """Linkage-validate and build the resolution commit record.

    Validates only; it does NOT invoke candidate generation, the canonical
    compiler, verification, or any backend.
    """
    if not isinstance(intent, CompileIntent):
        raise ResourceValidationError(
            f"intent must be a CompileIntent, got {type(intent).__name__}")
    if intent.schema_version != COMPILE_INTENT_SCHEMA_VERSION \
            or intent.compiler_semantics_version != COMPILER_SEMANTICS_VERSION:
        raise ResourceValidationError(
            "intent is not a current-semantics CompileIntent")
    if not isinstance(design, CompileRequest):
        raise ResourceValidationError(
            f"design must be a CompileRequest, got {type(design).__name__}")
    if design.compiler_semantics_version != COMPILER_SEMANTICS_VERSION:
        raise ResourceValidationError(
            "design does not use current compiler semantics "
            f"v{COMPILER_SEMANTICS_VERSION}")
    if not isinstance(resolved_fabric, ResolvedFabric):
        raise ResourceValidationError(
            f"resolved_fabric must be a ResolvedFabric, got "
            f"{type(resolved_fabric).__name__}")
    derived = derive_compile_request(intent)
    if derived.to_dict() != design.to_dict():
        raise ResourceValidationError(
            "supplied design is not exactly the request declared by the "
            "intent (canonical to_dict mismatch)")
    if resolved_fabric.design_hash != design.design_hash():
        raise ResourceValidationError(
            "resolved fabric design_hash does not match the design")
    return CompileResolution(
        intent_id=intent.intent_id(),
        design_hash=design.design_hash(),
        resolved_fabric_hash=resolved_fabric.resolved_fabric_hash,
    )
