"""veritx_dse.backend.evidence — authenticated backend evidence.

One artifact per executed backend run. Every digest in it is computed from
bytes that actually crossed the backend boundary, never from a claim:

    backend input bytes      -> backend_input_sha256
    raw evidence bytes       -> raw_evidence_sha256
    parsed counters          -> stats_sha256
    EvidenceArtifact         -> evidence_id (self-authenticating)

A backend that emits no bytes refuses here: counters with nothing to
authenticate them are a fabrication risk, not a measurement. A result
refuses evidence that names a different backend input (see
``application.results.EvaluationResult``), so a valid evidence artifact
cannot be transplanted onto another traffic.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import (
    canonical_json,
    content_id,
    require_embedded_id,
    require_exact_fields,
)
from veritx_dse.core.errors import BackendFailure, EvidenceInvalid, InvalidInput

DOMAIN = "veritx/evidence/v2"
PARSER_VERSION = "veritx/evidence-parser/v1"
SCHEMA_VERSION = 2

_HEX = frozenset("0123456789abcdef")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_digest(value: Any, where: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in _HEX for c in value):
        raise EvidenceInvalid(
            f"{where} must be a 64-char lowercase hex digest, got {value!r}")


@dataclass(frozen=True)
class EvidenceArtifact:
    backend: str
    backend_input_id: str
    backend_input_sha256: str
    raw_evidence_sha256: str
    parser_version: str
    counters: tuple[tuple[str, int], ...]
    stats_sha256: str

    def __post_init__(self):
        for name in ("backend", "backend_input_id", "parser_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise InvalidInput(f"{name} must be a non-empty string")
        _require_digest(self.backend_input_sha256, "backend_input_sha256")
        _require_digest(self.raw_evidence_sha256, "raw_evidence_sha256")
        _require_digest(self.stats_sha256, "stats_sha256")
        if not self.counters:
            raise EvidenceInvalid("evidence without counters is not a measurement")
        seen, previous = set(), None
        for item in self.counters:
            if not isinstance(item, tuple) or len(item) != 2:
                raise InvalidInput("counters must be (name, value) pairs")
            name, value = item
            if not isinstance(name, str) or not name:
                raise InvalidInput("counter names must be non-empty strings")
            if type(value) is not int or value < 0:
                raise InvalidInput(f"counter {name!r} must be a non-negative int")
            if name in seen:
                raise InvalidInput(f"duplicate counter {name!r}")
            if previous is not None and name <= previous:
                raise InvalidInput("counters must be canonically ordered by name")
            seen.add(name)
            previous = name
        if _sha256(canonical_json(dict(self.counters)).encode()) != self.stats_sha256:
            raise EvidenceInvalid("stats_sha256 does not authenticate the counters")

    @classmethod
    def build(cls, *, backend, backend_input_id, input_bytes, raw_evidence,
              counters, parser_version=PARSER_VERSION):
        """Authenticate one backend run's input bytes, output bytes, counters."""
        if not isinstance(raw_evidence, (bytes, bytearray)) or not raw_evidence:
            raise BackendFailure(
                f"{backend}: backend emitted no evidence bytes; counters "
                "without raw evidence cannot be authenticated")
        if not isinstance(input_bytes, (bytes, bytearray)):
            raise InvalidInput("backend input must be bytes")
        items = tuple(counters.items()) if isinstance(counters, Mapping) else tuple(counters)
        try:
            ordered = tuple(sorted(items))
        except TypeError as exc:
            raise InvalidInput(f"counters must be (name, int) pairs: {exc}") from exc
        for item in ordered:
            if not isinstance(item, tuple) or len(item) != 2:
                raise InvalidInput("counters must be (name, value) pairs")
        return cls(
            backend=backend,
            backend_input_id=backend_input_id,
            backend_input_sha256=_sha256(bytes(input_bytes)),
            raw_evidence_sha256=_sha256(bytes(raw_evidence)),
            parser_version=parser_version,
            counters=ordered,
            stats_sha256=_sha256(canonical_json(dict(ordered)).encode()),
        )

    def counter(self, name):
        return dict(self.counters)[name]

    def authenticates(self, *, input_bytes, raw_evidence) -> bool:
        """True only if these exact bytes are the ones this artifact names."""
        return (_sha256(bytes(input_bytes)) == self.backend_input_sha256
                and _sha256(bytes(raw_evidence)) == self.raw_evidence_sha256)

    def identity_dict(self):
        return {
            "backend": self.backend,
            "backend_input_id": self.backend_input_id,
            "backend_input_sha256": self.backend_input_sha256,
            "raw_evidence_sha256": self.raw_evidence_sha256,
            "parser_version": self.parser_version,
            "counters": dict(self.counters),
            "stats_sha256": self.stats_sha256,
        }

    def evidence_id(self):
        return content_id(DOMAIN, self.identity_dict())

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            **self.identity_dict(),
            "evidence_id": self.evidence_id(),
        }

    @classmethod
    def from_dict(cls, doc: Any):
        require_exact_fields(
            doc,
            {"schema_version", "backend", "backend_input_id", "backend_input_sha256",
             "raw_evidence_sha256", "parser_version", "counters", "stats_sha256",
             "evidence_id"},
            "evidence",
        )
        if doc["schema_version"] != SCHEMA_VERSION:
            raise InvalidInput("unsupported evidence schema")
        counters = doc["counters"]
        if not isinstance(counters, dict):
            raise InvalidInput("evidence counters must be an object")
        obj = cls(
            backend=doc["backend"],
            backend_input_id=doc["backend_input_id"],
            backend_input_sha256=doc["backend_input_sha256"],
            raw_evidence_sha256=doc["raw_evidence_sha256"],
            parser_version=doc["parser_version"],
            counters=tuple(sorted(counters.items())),
            stats_sha256=doc["stats_sha256"],
        )
        require_embedded_id(doc, "evidence_id", obj.evidence_id(), "evidence")
        return obj


__all__ = ["DOMAIN", "PARSER_VERSION", "SCHEMA_VERSION", "EvidenceArtifact"]
