"""veritx_dse.synthesis.definition — the canonical synthesis problem.

Rationale: docs/decisions/modules/synthesis.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.spec import canonical_json

DOMAIN = "veritx/synthesis-definition/v1"
SCHEMA_VERSION = 1

LAYOUTS = ("grid", "interposer")

#: Generator objectives. BOTH are ANALYTICAL generator objectives and are
#: never measured performance (see candidate.py).
OBJECTIVES = ("geodesic", "priced_geodesic")

#: Engine families this definition can drive. Tranche 3 wires exactly one.
ENGINES = ("milp_tmcf", "rho_iterative", "grpo_group", "bo_gp")

DEFAULT_MAX_NODES = 20


class SynthesisDefinitionError(ValueError):
    """Invalid synthesis definition (typed, fail-closed)."""


@dataclass(frozen=True)
class SynthesisDefinition:
    """What to synthesise. Identity binds only graph-changing inputs."""

    # ── scientific identity ──────────────────────────────────────────
    #: Router count. Must equal k*k for grid, rows*cols for interposer.
    nodes: int
    layout: str
    radix: int
    #: Maximum link length in layout pitches (the `max_len` admissibility
    #: radius). SCIENTIFIC: it decides which links are candidates.
    max_len: float
    bandwidth_GBs: float
    latency_ns: float
    objective: str = "geodesic"
    #: Layout shape. k for grid; rows/cols for interposer.
    k: int | None = None
    rows: int | None = None
    cols: int | None = None
    layout_seed: int = 7
    jitter: float = 0.08
    #: Physical price model. Only consumed when objective is priced_geodesic.
    #: ANALYTICAL / UNCALIBRATED — see candidate.py.
    pipe_cost: float = 3.0
    wire_cost: float = 1.0
    engine: str = "milp_tmcf"

    # ── execution policy (NOT identity) ──────────────────────────────
    timeout_s: int = 120
    max_nodes: int = DEFAULT_MAX_NODES
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION:
            raise SynthesisDefinitionError(
                f"schema_version {self.schema_version} != {SCHEMA_VERSION}")
        if type(self.nodes) is not int or self.nodes < 2:
            raise SynthesisDefinitionError(
                f"nodes must be an int >= 2, got {self.nodes!r}")
        if self.layout not in LAYOUTS:
            raise SynthesisDefinitionError(
                f"unknown layout {self.layout!r}; supported: {list(LAYOUTS)}")
        if self.objective not in OBJECTIVES:
            raise SynthesisDefinitionError(
                f"unknown objective {self.objective!r}; "
                f"supported: {list(OBJECTIVES)}")
        if self.engine not in ENGINES:
            raise SynthesisDefinitionError(
                f"unknown engine {self.engine!r}; supported: {list(ENGINES)}")
        for name in ("radix",):
            v = getattr(self, name)
            if type(v) is not int or v < 2:
                raise SynthesisDefinitionError(
                    f"{name} must be an int >= 2, got {v!r}")
        for name in ("max_len", "bandwidth_GBs", "latency_ns", "jitter",
                     "pipe_cost", "wire_cost"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or v != v or v in (
                    float("inf"), float("-inf")):
                raise SynthesisDefinitionError(
                    f"{name} must be a finite number, got {v!r}")
            if v <= 0:
                raise SynthesisDefinitionError(
                    f"{name} must be positive, got {v!r}")
        if self.layout == "grid":
            if self.k is None:
                raise SynthesisDefinitionError("grid layout requires k")
            if self.k * self.k != self.nodes:
                raise SynthesisDefinitionError(
                    f"grid requires nodes == k*k; k={self.k} gives "
                    f"{self.k * self.k} but nodes={self.nodes}")
        else:
            if self.rows is None or self.cols is None:
                raise SynthesisDefinitionError(
                    "interposer layout requires rows and cols")
            if self.rows * self.cols != self.nodes:
                raise SynthesisDefinitionError(
                    f"interposer requires nodes == rows*cols; "
                    f"{self.rows}x{self.cols} gives {self.rows * self.cols} "
                    f"but nodes={self.nodes}")
        if type(self.timeout_s) is not int or self.timeout_s < 1:
            raise SynthesisDefinitionError(
                f"timeout_s must be a positive int, got {self.timeout_s!r}")
        if type(self.max_nodes) is not int or self.max_nodes < 2:
            raise SynthesisDefinitionError(
                f"max_nodes must be an int >= 2, got {self.max_nodes!r}")

    # ── identity ─────────────────────────────────────────────────────

    def _scientific(self) -> dict[str, Any]:
        """ONLY graph-changing inputs. Execution policy is excluded."""
        return {
            "nodes": self.nodes,
            "layout": self.layout,
            "k": self.k,
            "rows": self.rows,
            "cols": self.cols,
            "layout_seed": self.layout_seed,
            "jitter": self.jitter,
            "radix": self.radix,
            "max_len": self.max_len,
            "objective": self.objective,
            "pipe_cost": self.pipe_cost,
            "wire_cost": self.wire_cost,
            "bandwidth_GBs": self.bandwidth_GBs,
            "latency_ns": self.latency_ns,
            "engine": self.engine,
        }

    def definition_id(self) -> str:
        return content_id(DOMAIN, self._scientific())

    def scientific_dict(self) -> dict[str, Any]:
        return dict(self._scientific())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "definition_id": self.definition_id(),
            **self._scientific(),
            "execution_policy": {
                "timeout_s": self.timeout_s,
                "max_nodes": self.max_nodes,
            },
        }

    @classmethod
    def from_dict(cls, d: Any) -> "SynthesisDefinition":
        if not isinstance(d, dict):
            raise SynthesisDefinitionError(
                f"definition must be an object, got {type(d).__name__}")
        allowed = {
            "schema_version", "definition_id", "nodes", "layout", "k",
            "rows", "cols", "layout_seed", "jitter", "radix", "max_len",
            "objective", "pipe_cost", "wire_cost",
            "bandwidth_GBs", "latency_ns", "engine", "execution_policy",
        }
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise SynthesisDefinitionError(
                f"unknown definition fields {unknown} (schema close)")
        policy = d.get("execution_policy") or {}
        if not isinstance(policy, dict):
            raise SynthesisDefinitionError("execution_policy must be an object")
        known_policy = {"timeout_s", "max_nodes"}
        bad_policy = sorted(set(policy) - known_policy)
        if bad_policy:
            raise SynthesisDefinitionError(
                f"unknown execution_policy fields {bad_policy}")
        obj = cls(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            nodes=d["nodes"], layout=d["layout"], radix=d["radix"],
            max_len=d["max_len"], bandwidth_GBs=d["bandwidth_GBs"],
            latency_ns=d["latency_ns"],
            objective=d.get("objective", "geodesic"),
            k=d.get("k"), rows=d.get("rows"), cols=d.get("cols"),
            layout_seed=d.get("layout_seed", 7),
            jitter=d.get("jitter", 0.08),
            pipe_cost=d.get("pipe_cost", 3.0),
            wire_cost=d.get("wire_cost", 1.0),
            engine=d.get("engine", "milp_tmcf"),
            timeout_s=policy.get("timeout_s", 120),
            max_nodes=policy.get("max_nodes", DEFAULT_MAX_NODES),
        )
        supplied = d.get("definition_id")
        if supplied is not None and supplied != obj.definition_id():
            raise SynthesisDefinitionError(
                "definition_id does not match content — the payload was "
                "edited after it was addressed")
        return obj

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())


__all__ = [
    "DOMAIN", "SCHEMA_VERSION", "LAYOUTS", "OBJECTIVES", "ENGINES",
    "DEFAULT_MAX_NODES", "SynthesisDefinitionError", "SynthesisDefinition",
]
