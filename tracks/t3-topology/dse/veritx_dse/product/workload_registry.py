"""veritx_dse.product.workload_registry — workloads as data, not code.

The product catalog used to be a hardcoded 4-tuple in ``product/service.py``,
so onboarding a customer workload meant editing source. This module makes the
catalog a registry:

  * ``BUILTIN_WORKLOADS`` — the shipped real-model workloads (unchanged
    identity; re-exported as ``_WORKLOAD_TEMPLATES`` for existing importers);
  * an optional on-disk registry at ``tracks/t3-topology/workloads/
    registry.json`` (schema ``veritx.workload-registry/1``) adding customer
    workloads WITHOUT a code change.

A registry entry may name a ``profile`` document (see
``performance/profile_ingest.py``). When it does, the request's ``compute``
block is DERIVED from that measured profile — the customer path: measured
per-layer durations in, a v4 workload out.

Fail-closed: unknown keys refuse, a duplicate ``workload_id`` refuses (never
a silent shadow of a shipped workload), and a profile can only attach to a
v4 request (compute is a v4 field — silently dropping it would lose the
customer's numbers).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.core.errors import SemanticError

REGISTRY_SCHEMA = "veritx.workload-registry/1"
REGISTRY_REL = "tracks/t3-topology/workloads/registry.json"

class WorkloadRegistryError(ValueError, SemanticError):
    """The registry document (or an entry) is not well-formed."""

BUILTIN_WORKLOADS: tuple[tuple[str, str, str, str], ...] = (
    (
        "llama-dense-8b-64tiles",
        "tracks/t3-topology/examples/llama_dense_64tiles-v3.json",
        "Llama-3.1-8B \u00b7 TP8 \u00b7 64 tiles",
        "dense transformer, TP8 allreduce over a 64-tile mesh "
        "(hidden 4096, bf16)",
    ),
    (
        "qwen3-32b-tp2-16tiles",
        "tracks/t3-topology/examples/qwen3_32b_tp2_16tiles-v3.json",
        "Qwen3-32B \u00b7 TP2 \u00b7 16 tiles",
        "Qwen3-32B decode intent over a 16-tile mesh "
        "(TP allreduce payload 10240 B = hidden 5120 x bf16)",
    ),
    (
        "qwen3-moe-tp2-ep4-16tiles",
        "tracks/t3-topology/examples/qwen3_moe_tp2_ep4_16tiles-v3.json",
        "Qwen3-30B-A3B \u00b7 TP2+EP4 \u00b7 8 ranks",
        "TP allreduce + EP dispatch/combine over a 16-tile mesh "
        "(canonical full-stack acceptance workload)",
    ),
    (
        "qwen3-moe-tp2-ep4-8ranks-declared-compute",
        "tracks/t3-topology/examples/qwen3_moe_tp2_ep4_16tiles-v4.json",
        "Qwen3-30B-A3B \u00b7 TP2+EP4 \u00b7 8 ranks \u00b7 declared compute",
        "canonical full-stack acceptance workload (v4): TP allreduce + EP "
        "dispatch/combine + DECLARED compute/memory operands (Qwen geometry), "
        "so DRAM timing has real demand",
    ),
)

_ENTRY_KEYS = frozenset({
    "workload_id", "path", "display_name", "description", "profile",
    "owners",
})
_DOC_KEYS = frozenset({"schema", "workloads"})

@dataclass(frozen=True)
class WorkloadEntry:
    workload_id: str
    path: str
    display_name: str
    description: str
    profile: str | None = None
    owners: int | None = None
    origin: str = "builtin"

def _text(doc: dict[str, Any], key: str, where: str, *,
          required: bool = True) -> str | None:
    v = doc.get(key)
    if v is None:
        if required:
            raise WorkloadRegistryError(f"{where}.{key} is required")
        return None
    if not isinstance(v, str) or not v.strip():
        raise WorkloadRegistryError(
            f"{where}.{key} must be a non-empty string, got {v!r}")
    return v

def _entry_from_doc(doc: Any, where: str) -> WorkloadEntry:
    if not isinstance(doc, dict):
        raise WorkloadRegistryError(f"{where} must be an object")
    extra = set(doc) - _ENTRY_KEYS
    if extra:
        raise WorkloadRegistryError(
            f"{where} has unknown fields {sorted(extra)}; allowed "
            f"{sorted(_ENTRY_KEYS)}")
    owners = doc.get("owners")
    if owners is not None and (isinstance(owners, bool)
                               or not isinstance(owners, int) or owners < 1):
        raise WorkloadRegistryError(
            f"{where}.owners must be an integer >= 1, got {owners!r}")
    return WorkloadEntry(
        workload_id=_text(doc, "workload_id", where),
        path=_text(doc, "path", where),
        display_name=_text(doc, "display_name", where),
        description=_text(doc, "description", where),
        profile=_text(doc, "profile", where, required=False),
        owners=owners,
        origin="registry",
    )

def registry_path(repo_root: Path) -> Path:
    return Path(repo_root) / REGISTRY_REL

def load_registry(repo_root: Path) -> tuple[WorkloadEntry, ...]:
    """Builtins plus the on-disk registry (if present), refusing collisions."""
    entries = [WorkloadEntry(*t, origin="builtin") for t in BUILTIN_WORKLOADS]
    path = registry_path(repo_root)
    if not path.is_file():
        return tuple(entries)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkloadRegistryError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise WorkloadRegistryError(f"{path} must be a JSON object")
    extra = set(doc) - _DOC_KEYS
    if extra:
        raise WorkloadRegistryError(
            f"{path} has unknown fields {sorted(extra)}; allowed "
            f"{sorted(_DOC_KEYS)}")
    if doc.get("schema") != REGISTRY_SCHEMA:
        raise WorkloadRegistryError(
            f"{path}.schema must be {REGISTRY_SCHEMA!r}, "
            f"got {doc.get('schema')!r}")
    raw = doc.get("workloads")
    if not isinstance(raw, list):
        raise WorkloadRegistryError(f"{path}.workloads must be an array")

    seen = {e.workload_id for e in entries}
    for i, item in enumerate(raw):
        entry = _entry_from_doc(item, f"{path}.workloads[{i}]")
        if entry.workload_id in seen:
            raise WorkloadRegistryError(
                f"{path}.workloads[{i}]: duplicate workload_id "
                f"{entry.workload_id!r} (a registry entry must never shadow "
                "a shipped workload)")
        seen.add(entry.workload_id)
        entries.append(entry)
    return tuple(entries)

def resolve(repo_root: Path, workload_id: str) -> WorkloadEntry | None:
    for entry in load_registry(repo_root):
        if entry.workload_id == workload_id:
            return entry
    return None

def materialize(entry: WorkloadEntry, repo_root: Path) -> dict[str, Any]:
    """The request document for an entry, with profile-derived compute.

    A plain entry returns the file verbatim. An entry that names a
    ``profile`` gets its ``compute`` block replaced by the stages derived
    from that measured profile — the request must be v4 (compute is a v4
    field; attaching nothing would silently discard the customer's numbers).
    """
    path = Path(repo_root) / entry.path
    if not path.is_file():
        raise WorkloadRegistryError(f"workload document is missing: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if entry.profile is None:
        return document

    if not isinstance(document, dict) or \
            document.get("schema_version") != 4:
        raise WorkloadRegistryError(
            f"{entry.workload_id}: a profile-backed workload must be a v4 "
            f"request (compute is a v4 field); {entry.path} declares "
            f"schema_version={document.get('schema_version')!r}")

    from veritx_dse.performance.profile_ingest import load_profile
    profile_path = Path(repo_root) / entry.profile
    profile = load_profile(profile_path)
    document = dict(document)
    document["compute"] = profile.to_compute_intent(
        participants=entry.owners or 1,
        stage_prefix=entry.workload_id.replace("-", "_") + "_")
    return document

__all__ = [
    "BUILTIN_WORKLOADS",
    "REGISTRY_REL",
    "REGISTRY_SCHEMA",
    "WorkloadEntry",
    "WorkloadRegistryError",
    "load_registry",
    "materialize",
    "registry_path",
    "resolve",
]
