"""veritx_dse.application.requests — typed product intent (Wave C).

``Intent`` is the single typed boundary every surface (Python, CLI, API,
T3) constructs. Strict parsing (unknown fields refuse, no coercion),
explicit schema version, and canonical identity over SEMANTIC fields
only: display labels (``name``) and transport metadata (external trace
paths, output locations) never enter the identity.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import intent_error
from .presets import (
    get_metric_definition, get_preset, metric_ids, preset_names,
    resolve_trace_bytes, trace_names,
)

INTENT_SCHEMA_VERSION = 1
INTENT_HASH_TAG = "srota-intent/v1"

EXECUTABLE_BACKEND_TARGETS = ("BOOKSIM_STANDALONE",)
KNOWN_BACKEND_TARGETS = (
    "BOOKSIM_STANDALONE",
    "SERVING_BOOKSIM2",
    "SERVING_ANALYTICAL_AWARE",
    "SERVING_ANALYTICAL_UNAWARE",
)

_DEFAULT_TIMEOUT_S = 120


def _need(d: dict[str, Any], key: str) -> Any:
    if not isinstance(d, dict) or key not in d:
        raise ValueError(f"intent: missing required field {key!r}")
    return d[key]


def _strict_keys(d: dict[str, Any], allowed: frozenset[str]) -> None:
    if not isinstance(d, dict):
        raise ValueError("intent: request must be a JSON object")
    extra = sorted(set(d) - allowed)
    if extra:
        raise ValueError(f"intent: unknown fields {extra}")


@dataclass(frozen=True)
class WorkloadRef:
    """Workload reference: registered trace or external trace file."""

    trace: str | None = None
    trace_file: str | None = None

    def identity_dict(self) -> dict[str, Any]:
        # Only one arm is ever set; the external path itself is transport
        # metadata and never enters identity (bytes do).
        return {"trace": self.trace}


@dataclass(frozen=True)
class Intent:
    """One typed product request (immutable)."""

    schema_version: int
    name: str
    fabric_preset: str
    fabric_overrides: tuple[tuple[str, Any], ...]
    workload: WorkloadRef
    backend_target: str
    seed: int | None
    metrics: tuple[str, ...]
    timeout_s: int

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": INTENT_HASH_TAG,
            "schema_version": self.schema_version,
            "fabric_preset": self.fabric_preset,
            "fabric_overrides": {k: v for k, v in self.fabric_overrides},
            "workload": self.workload.identity_dict(),
            "backend_target": self.backend_target,
            "seed": self.seed,
            "metrics": list(self.metrics),
        }

    def intent_id(self) -> str:
        from veritx_dse.core.spec import canonical_json
        body = INTENT_HASH_TAG + "\0" + canonical_json(self.identity_dict())
        return hashlib.sha256(body.encode()).hexdigest()

    def seed_policy(self) -> str:
        from veritx_dse.backend.booksim import (
            SEED_POLICY_EXPLICIT, SEED_POLICY_PINNED_DEFAULT,
        )
        return SEED_POLICY_EXPLICIT if self.seed is not None \
            else SEED_POLICY_PINNED_DEFAULT

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["name"] = self.name
        d["timeout_s"] = self.timeout_s
        if self.workload.trace_file is not None:
            d["workload"] = {"trace_file": self.workload.trace_file}
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "Intent":
        allowed = frozenset({
            "schema_version", "name", "fabric_preset", "fabric_overrides",
            "workload", "backend_target", "seed", "metrics", "timeout_s"})
        try:
            _strict_keys(d, allowed)
            version = _need(d, "schema_version")
            if version != INTENT_SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported intent schema_version {version!r} "
                    f"(this build speaks v{INTENT_SCHEMA_VERSION})")
            name = _need(d, "name")
            if not isinstance(name, str) or not name:
                raise ValueError("intent.name must be a non-empty string")
            preset = _need(d, "fabric_preset")
            if preset not in preset_names():
                raise ValueError(
                    f"unknown fabric_preset {preset!r} "
                    f"(known: {list(preset_names())})")
            raw_overrides = d.get("fabric_overrides", {})
            if not isinstance(raw_overrides, dict):
                raise ValueError("intent.fabric_overrides must be an object")
            for key, value in raw_overrides.items():
                if not isinstance(key, str) or not key:
                    raise ValueError(
                        f"override paths must be non-empty strings, got "
                        f"{key!r}")
                if value is not None and not isinstance(
                        value, (int, float, str, bool)):
                    raise ValueError(
                        f"override {key!r} must be a JSON scalar, got "
                        f"{type(value).__name__}")
            workload_raw = _need(d, "workload")
            if not isinstance(workload_raw, dict):
                raise ValueError("intent.workload must be an object")
            _strict_keys(workload_raw, frozenset({"trace", "trace_file"}))
            trace = workload_raw.get("trace")
            trace_file = workload_raw.get("trace_file")
            if (trace is None) == (trace_file is None):
                raise ValueError(
                    "intent.workload needs exactly one of "
                    "'trace' or 'trace_file'")
            if trace is not None:
                if trace not in trace_names():
                    raise ValueError(
                        f"unknown trace {trace!r} "
                        f"(known: {list(trace_names())})")
            else:
                if not isinstance(trace_file, str) or not Path(
                        trace_file).is_absolute():
                    raise ValueError(
                        "intent.workload.trace_file must be an absolute "
                        "path string")
            backend = _need(d, "backend_target")
            if backend not in KNOWN_BACKEND_TARGETS:
                raise ValueError(
                    f"unknown backend_target {backend!r} "
                    f"(known: {list(KNOWN_BACKEND_TARGETS)})")
            seed = d.get("seed")
            if seed is not None and (type(seed) is not int or seed < 0):
                raise ValueError(
                    f"intent.seed must be a non-negative int or null, got "
                    f"{seed!r}")
            raw_metrics = d.get("metrics", [])
            if not isinstance(raw_metrics, list) or not raw_metrics:
                raise ValueError(
                    "intent.metrics must be a non-empty list of metric ids")
            for metric_id in raw_metrics:
                get_metric_definition(metric_id)
            timeout = d.get("timeout_s", _DEFAULT_TIMEOUT_S)
            if type(timeout) is not int or timeout < 1:
                raise ValueError(
                    f"intent.timeout_s must be a positive int, got "
                    f"{timeout!r}")
            return cls(
                schema_version=version, name=name, fabric_preset=preset,
                fabric_overrides=tuple(sorted(raw_overrides.items())),
                workload=WorkloadRef(trace=trace, trace_file=trace_file),
                backend_target=backend, seed=seed,
                metrics=tuple(raw_metrics), timeout_s=timeout)
        except (ValueError, KeyError) as exc:
            raise intent_error(str(exc), operation="parse_intent",
                               cause_type=type(exc).__name__) from exc


def parse_intent(doc: Any) -> Intent:
    """Parse a canonical intent document (all surfaces use this)."""
    return Intent.from_dict(doc)


def resolve_workload_bytes(intent: Intent) -> tuple[bytes, dict[str, Any]]:
    """Trace bytes + transport metadata (path excluded from identity)."""
    if intent.workload.trace is not None:
        data = resolve_trace_bytes(intent.workload.trace)
        return data, {"source": "registry",
                      "trace": intent.workload.trace}
    path = Path(intent.workload.trace_file or "")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise intent_error(
            f"cannot read trace_file {path}: {exc}", operation="intent",
            cause_type=type(exc).__name__) from exc
    if not data:
        raise intent_error(
            f"trace_file {path} is empty", operation="intent")
    return data, {"source": "file", "trace_file": str(path)}


__all__ = [
    "EXECUTABLE_BACKEND_TARGETS",
    "INTENT_HASH_TAG",
    "INTENT_SCHEMA_VERSION",
    "KNOWN_BACKEND_TARGETS",
    "Intent",
    "WorkloadRef",
    "parse_intent",
    "resolve_workload_bytes",
]
