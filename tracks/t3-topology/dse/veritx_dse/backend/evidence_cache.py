"""Evidence-reuse cache orchestration — explicit hits, typed transplant refusal.

Thin orchestration over backend/evidence.py verify_reusable_record +
read_reusable_record (the safe verification primitives). This module adds
the missing layer only: key→record lookup keyed SOLELY by the scientific
parents required for reuse. No trial/study-id-only keys, no TTL tricks,
no synthetic measurements.

- put(ref, parents): re-passes the full reuse gate, then indexes.
- lookup(key, parents): re-reads via the verified reader, checks every
  bound field, recomputes evidence_id (inside the reader). Unknown key →
  CacheMiss. Known key with divergent bytes/fields → BackendEvidenceError
  (transplant refusal, never a quiet miss). Hit returns stored evidence
  unchanged with CacheHit(reused_evidence_id, hits).
- Clock discipline is strict exact-match; cycles-vs-ns re-derivation
  stays with callers. Question is the EvaluationQuestion name string;
  callers must pass it (never inferred).

In-memory only in this slice (no persisted index/TTL); wiring into the
federated evaluator + Studio run UI (explicit 'cache hit · reused id')
is the parent-owned next step.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from veritx_dse.backend.evidence import (
    BackendEvidenceError,
    EvidenceRef,
    read_reusable_record,
)
from veritx_dse.core.artifact import content_id

#: Every field bound into the reuse key. All must match exactly on lookup.
#: prepared/config/trace/binary pin the execution; profile/projection/
#: parser/build-manifest/recipe/schema pin the semantics; producer pins
#: the binary provenance; seed/topology/fabric/traffic/message/route pins
#: the design; question + network clock pin the asked quantity.
KEY_FIELDS = (
    "prepared_id",
    "config_sha256",
    "trace_sha256",
    "binary_sha256",
    "binary_size",
    "profile_id",
    "projection_semantics_version",
    "parser_version",
    "build_manifest",
    "build_recipe_version",
    "schema_version",
    "producer_revision",
    "producer_dirty",
    "producer_transport",
    "producer_fidelity",
    "seed",
    "topology_id",
    "fabric_id",
    "traffic_id",
    "message_id",
    "route_observation",
    "route_dump_sha256",
    "question",
    "network_clock_hz",
)


class CacheMiss(KeyError):
    """No entry for this reuse key."""


@dataclass(frozen=True)
class CacheHit:
    reused_evidence_id: str
    hits: int


@dataclass
class EvidenceCache:
    _entries: dict[str, tuple[EvidenceRef, dict[str, object], str]] = field(
        default_factory=dict
    )
    _hits: dict[str, int] = field(default_factory=dict)
    _read: object = None

    def __post_init__(self):
        object.__setattr__(
            self, "_read", self._read or read_reusable_record
        )

    @staticmethod
    def derive_key(parents: dict[str, object]) -> str:
        missing = [k for k in KEY_FIELDS if k not in parents]
        if missing:
            raise BackendEvidenceError(
                f"reuse key missing parent fields {missing} — refusing "
                "to key reuse on a partial parent set"
            )
        return content_id(
            "veritx/evidence-reuse-key/v1",
            {k: parents[k] for k in KEY_FIELDS},
        )

    def put(self, ref: EvidenceRef, parents: dict[str, object]) -> str:
        key = self.derive_key(parents)
        evidence = self._read(ref, **{  # noqa: SLF — verified reader
            k: parents[k]
            for k in ("prepared_id", "config_sha256", "trace_sha256",
                      "binary_sha256")
            if k in parents
        })
        evidence_id = getattr(evidence, "evidence_id", None) or str(
            getattr(evidence, "evidence", {})
        )
        self._entries[key] = (ref, dict(parents), str(evidence_id))
        self._hits[key] = 0
        return key

    def lookup(self, key: str, parents: dict[str, object]):
        entry = self._entries.get(key)
        if entry is None:
            raise CacheMiss(key)
        ref, bound, evidence_id = entry
        for k in KEY_FIELDS:
            if parents.get(k) != bound.get(k):
                raise BackendEvidenceError(
                    f"cache transplant refused: parent field {k!r} differs "
                    f"(stored {bound.get(k)!r} vs requested "
                    f"{parents.get(k)!r})"
                )
        evidence = self._read(ref, **{
            k: parents[k]
            for k in ("prepared_id", "config_sha256", "trace_sha256",
                      "binary_sha256")
            if k in parents
        })
        current_id = getattr(evidence, "evidence_id", None) or str(
            getattr(evidence, "evidence", {})
        )
        if str(current_id) != str(evidence_id):
            raise BackendEvidenceError(
                "cache transplant refused: evidence_id recomputation "
                "differs from the indexed record"
            )
        self._hits[key] = self._hits.get(key, 0) + 1
        return evidence, CacheHit(
            reused_evidence_id=str(evidence_id), hits=self._hits[key]
        )


__all__ = [
    "KEY_FIELDS",
    "CacheMiss",
    "CacheHit",
    "EvidenceCache",
]
