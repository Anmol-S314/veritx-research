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

# Workload provenance vocabulary: a packet trace is NOT a semantic
# workload. Wave D workloads declare operations explicitly and derive
# their trace; legacy traces stay explicitly classified as such.
WORKLOAD_KIND_LEGACY_TRACE = "LEGACY_TRACE"
WORKLOAD_KIND_WAVE_D = "WAVE_D_SEMANTIC"

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
    """Workload reference with resolved content identity.

    Provenance kinds:

    * legacy packet trace (``trace``/``trace_file``): the bytes are the
      ground truth and ``trace_sha256`` is the content digest; no Wave-D
      semantics can be reconstructed from a trace, ever;
    * explicit Wave-D semantic workload (``wave_d``): the declared
      operations are the ground truth and ``wave_d.workload_id()`` is
      the content digest. The BookSim trace is DERIVED from it.
    * optional Wave-E temporal overlay (``wave_e``): an explicit
      TemporalWorkload layered OVER a Wave-D workload — it adds
      WHEN (events/resources/requests) but owns no communication
      semantics (§8: never retrofit compute into Wave D).

    The filesystem path (for ``trace_file``) is transport metadata and
    never enters identity; the bytes always do. An intent without a
    resolved digest has no identity (``intent_id`` refuses).
    """

    trace: str | None = None
    trace_file: str | None = None
    trace_sha256: str | None = None
    wave_d: Any = None          # WaveDWorkload | None
    wave_e: Any = None          # TemporalWorkload | None

    @property
    def workload_kind(self) -> str:
        return WORKLOAD_KIND_WAVE_D if self.wave_d is not None \
            else WORKLOAD_KIND_LEGACY_TRACE

    def identity_dict(self) -> dict[str, Any]:
        if self.wave_d is not None:
            body = {"wave_d": self.wave_d.workload_id()}
            if self.wave_e is not None:
                body["wave_e"] = self.wave_e.temporal_workload_id()
            return body
        return {"trace": self.trace, "trace_sha256": self.trace_sha256}


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
        if self.workload.trace_sha256 is None \
                and self.workload.wave_d is None:
            raise ValueError(
                "intent has no resolved workload digest; resolve the "
                "trace bytes first (resolve_intent)")
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
        d = {k: v for k, v in self.identity_dict().items()
             if k != "type"}
        d["name"] = self.name
        d["timeout_s"] = self.timeout_s
        workload: dict[str, Any] = {}
        if self.workload.trace is not None:
            workload["trace"] = self.workload.trace
        if self.workload.trace_file is not None:
            workload["trace_file"] = self.workload.trace_file
        if self.workload.trace_sha256 is not None:
            workload["trace_sha256"] = self.workload.trace_sha256
        if self.workload.wave_d is not None:
            from veritx_dse.workload.graph import WaveDWorkload
            w = self.workload.wave_d
            if not isinstance(w, WaveDWorkload):
                raise ValueError("workload.wave_d must be a WaveDWorkload")
            workload["wave_d"] = {
                "parallelism": w.parallelism.to_dict(),
                "semantics": w.semantics.to_dict(),
                "operations": [op.to_dict() for op in w.operations],
            }
        if self.workload.wave_e is not None:
            from veritx_dse.performance.workload import TemporalWorkload
            we = self.workload.wave_e
            if not isinstance(we, TemporalWorkload):
                raise ValueError(
                    "workload.wave_e must be a TemporalWorkload")
            workload["wave_e"] = we.to_dict()
        d["workload"] = workload
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
            _strict_keys(workload_raw, frozenset(
                {"trace", "trace_file", "trace_sha256", "wave_d",
                 "wave_e"}))
            trace = workload_raw.get("trace")
            trace_file = workload_raw.get("trace_file")
            digest = workload_raw.get("trace_sha256")
            wave_d_doc = workload_raw.get("wave_d")
            wave_e_doc = workload_raw.get("wave_e")
            if wave_e_doc is not None:
                if wave_d_doc is None:
                    raise ValueError(
                        "intent.workload.wave_e requires workload.wave_d: "
                        "a temporal overlay extends Wave-D semantics, it "
                        "never replaces them (§8)")
                from veritx_dse.performance.workload import TemporalWorkload
                try:
                    wave_e = TemporalWorkload.from_dict(wave_e_doc)
                except Exception as exc:
                    raise ValueError(
                        f"intent.workload.wave_e does not parse: {exc}") \
                        from exc
            else:
                wave_e = None
            if wave_d_doc is not None:
                if trace is not None or trace_file is not None \
                        or digest is not None:
                    raise ValueError(
                        "intent.workload.wave_d is mutually exclusive "
                        "with trace/trace_file/trace_sha256: a semantic "
                        "workload derives its own trace")
                from veritx_dse.workload.graph import WaveDWorkload
                try:
                    wave_d = WaveDWorkload.from_dict(wave_d_doc)
                except Exception as exc:
                    raise ValueError(
                        f"intent.workload.wave_d does not parse: {exc}") \
                        from exc
            else:
                wave_d = None
                if digest is not None and not _is_sha256(digest):
                    raise ValueError(
                        f"intent.workload.trace_sha256 must be a 64-char "
                        f"hex digest, got {digest!r}")
                if (trace is None) == (trace_file is None):
                    raise ValueError(
                        "intent.workload needs exactly one of "
                        "'trace', 'trace_file' or 'wave_d'")
                if trace is not None:
                    if trace not in trace_names():
                        raise ValueError(
                            f"unknown trace {trace!r} "
                            f"(known: {list(trace_names())})")
                else:
                    if not isinstance(trace_file, str) or not Path(
                            trace_file).is_absolute():
                        raise ValueError(
                            "intent.workload.trace_file must be an "
                            "absolute path string")
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
                workload=WorkloadRef(trace=trace, trace_file=trace_file,
                                     trace_sha256=digest, wave_d=wave_d,
                                     wave_e=wave_e),
                backend_target=backend, seed=seed,
                metrics=tuple(raw_metrics), timeout_s=timeout)
        except (ValueError, KeyError) as exc:
            raise intent_error(str(exc), operation="parse_intent",
                               cause_type=type(exc).__name__) from exc


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value)


def parse_intent(doc: Any) -> Intent:
    """Parse a canonical intent document (all surfaces use this)."""
    return Intent.from_dict(doc)


def resolve_intent(doc: Any) -> tuple[Intent, bytes | None, dict[str, Any]]:
    """Parse AND resolve workload content in one step.

    Returns (intent with workload identity filled, exact trace bytes or
    ``None`` for a Wave-D semantic workload, transport source metadata).
    Every downstream stage must use these bytes — never reread the file.
    A document digest that disagrees with the resolved bytes refuses (a
    file changed after intent resolution never executes under a stale
    identity). Registry traces resolve without I/O; external files are
    read here, once.

    A Wave-D semantic workload has no trace bytes yet: its trace is
    DERIVED from the verified Wave-D traffic inside the control plane,
    after the fabric is compiled. ``None`` here is therefore a kind
    signal, never an empty workload.
    """
    from veritx_dse.backend.contracts import sha256_bytes
    intent = parse_intent(doc)
    if intent.workload.wave_d is not None:
        return intent, None, {"source": "wave_d",
                              "workload_id":
                                  intent.workload.wave_d.workload_id()}
    trace_bytes, source = resolve_workload_bytes(intent)
    digest = sha256_bytes(trace_bytes)
    if intent.workload.trace_sha256 is not None and \
            intent.workload.trace_sha256 != digest:
        raise intent_error(
            f"workload digest mismatch: document claims "
            f"{intent.workload.trace_sha256} but the resolved trace "
            f"bytes hash to {digest}; refusing stale execution",
            operation="resolve_intent")
    resolved = Intent(
        schema_version=intent.schema_version, name=intent.name,
        fabric_preset=intent.fabric_preset,
        fabric_overrides=intent.fabric_overrides,
        workload=WorkloadRef(trace=intent.workload.trace,
                             trace_file=intent.workload.trace_file,
                             trace_sha256=digest),
        backend_target=intent.backend_target, seed=intent.seed,
        metrics=intent.metrics, timeout_s=intent.timeout_s)
    return resolved, trace_bytes, source


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
    "WORKLOAD_KIND_LEGACY_TRACE",
    "WORKLOAD_KIND_WAVE_D",
    "Intent",
    "WorkloadRef",
    "parse_intent",
    "resolve_intent",
    "resolve_workload_bytes",
]
