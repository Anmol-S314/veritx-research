"""results.py — Canonical synthesis result schema (Phase 2a).

Single source of truth for what a synthesis evaluation produces, so the
four result schemas (BO, iterative, MILP, pareto) can be merged additively
without renaming existing keys.

No other dependencies (stdlib only) so every producer — including
script-mode (``python3 bo_synthesizer.py``) — can import it safely.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SynthResult:
    """Canonical synthesis evaluation record.

    Fields:
        name: display name (e.g. topo name, ``bo_N64_winner``).
        topology: backend string (``anynet``, ``mesh``, ``torus``, ...).
            ``backend`` is accepted as an alias and always emitted too,
            because pareto calls this key ``topology`` while other code
            says backend.
        backend: alias for topology; kept in sync in to_dict/from_dict.
        nodes: node count.
        edges: undirected edge count.
        latency: measured latency in cycles, or None on failure.
        status: "ok" | "error".
        error: human-readable failure reason, or None on success.
        seed: BookSim seed used, or None if not applicable.
        provenance: which tool+preset produced this
            (e.g. ``bo_synthesizer+BO_PRESET``).
        extra: tool-specific fields (trace, routing, solver, ...).
    """

    name: str = ""
    topology: str = ""
    backend: str = ""
    nodes: int = 0
    edges: int = 0
    latency: float | None = None
    status: str = "ok"
    error: str | None = None
    seed: int | None = None
    provenance: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        # Keep the topology/backend aliases in sync: whichever was given
        # wins; when both are given they must agree (caller bug otherwise,
        # but we keep topology as canonical rather than crashing loops).
        if self.backend and not self.topology:
            self.topology = self.backend
        elif self.topology and not self.backend:
            self.backend = self.topology
        if self.status not in ("ok", "error"):
            raise ValueError(f"status must be 'ok'|'error', got {self.status!r}")

    def to_dict(self) -> dict:
        """Serialize to plain JSON-ready dict (round-trips via from_dict)."""
        # Canonicalize aliases on the way out so readers see both keys.
        topo = self.topology or self.backend
        d: dict[str, Any] = {
            "name": self.name,
            "topology": topo,
            "backend": self.backend or topo,
            "nodes": int(self.nodes),
            "edges": int(self.edges),
            "latency": None if self.latency is None else float(self.latency),
            "status": self.status,
            "error": self.error,
            "seed": self.seed,
            "provenance": self.provenance,
            "extra": dict(self.extra),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SynthResult":
        """Inverse of to_dict; accepts either ``topology`` or ``backend``."""
        topo = d.get("topology", "") or d.get("backend", "")
        be = d.get("backend", "") or topo
        return cls(
            name=d.get("name", ""),
            topology=topo,
            backend=be,
            nodes=int(d.get("nodes", 0) or 0),
            edges=int(d.get("edges", 0) or 0),
            latency=d.get("latency", None),
            status=d.get("status", "ok"),
            error=d.get("error", None),
            seed=d.get("seed", None),
            provenance=d.get("provenance", ""),
            extra=dict(d.get("extra", {}) or {}),
        )

    @classmethod
    def ok(
        cls,
        name: str,
        topology: str,
        nodes: int,
        edges: int,
        latency: float,
        seed: int | None = None,
        provenance: str = "",
        extra: dict | None = None,
        backend: str = "",
    ) -> "SynthResult":
        """Success constructor (status="ok", error=None)."""
        return cls(
            name=name,
            topology=topology,
            backend=backend or topology,
            nodes=nodes,
            edges=edges,
            latency=float(latency),
            status="ok",
            error=None,
            seed=seed,
            provenance=provenance,
            extra=dict(extra or {}),
        )

    @classmethod
    def fail(
        cls,
        name: str,
        topology: str,
        nodes: int,
        edges: int,
        error: str,
        seed: int | None = None,
        provenance: str = "",
        extra: dict | None = None,
        backend: str = "",
    ) -> "SynthResult":
        """Failure constructor (status="error", latency=None)."""
        return cls(
            name=name,
            topology=topology,
            backend=backend or topology,
            nodes=nodes,
            edges=edges,
            latency=None,
            status="error",
            error=error,
            seed=seed,
            provenance=provenance,
            extra=dict(extra or {}),
        )
