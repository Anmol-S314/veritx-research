"""veritx_dse.core.spec — experiment spec boundary (redesign PR 2).

The strict boundary between scientific intent and everything else
(ADR 0005). An experiment spec:

  * names simulators/topologies by REGISTERED ID, never by path,
  * rejects unknown fields at the boundary (no silent normalization),
  * materializes into a fully-resolved, deterministic dict whose canonical
    JSON hash is the experiment identity (ADR 0002).

Pydantic is used here only at the parsing boundary; the rest of the system
consumes plain dicts/dataclasses from resolve().
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# One line per persisted format (ADR: versioned formats). Bump on any
# resolution-rule change — it deliberately changes every experiment_hash.
SCHEMA_VERSION = 1

# Fields that describe the *display* of an experiment, not its science.
# Excluded from the canonical hash — changing a note must not fork identity.
NON_SCIENTIFIC_FIELDS = frozenset({"name", "notes"})


class SpecError(ValueError):
    """Rejected experiment spec (unknown field, bad type, bad value)."""


# ── Boundary models ─────────────────────────────────────────────────────────
# extra="forbid" IS the boundary: unknown fields raise, they are never
# normalized away (redesign §32). strict=True forbids silent coercion
# ("64" -> 64) — scientific parameters must arrive as the declared type.

_STRICT = ConfigDict(extra="forbid", strict=True)

class WorkloadSpec(BaseModel):
    model_config = _STRICT
    id: str = Field(min_length=1)
    trace: str = Field(min_length=1)  # path relative to dse archive, or abs


class SystemSpec(BaseModel):
    model_config = _STRICT
    nodes: int = Field(ge=1)
    tp_size: int = Field(default=1, ge=1)
    instances_per_node: int = Field(default=1, ge=1)


class NetworkSpec(BaseModel):
    model_config = _STRICT
    topology: str = Field(min_length=1)  # registered ID (model/presets.py)
    # Study-integrity P0 (#10): a named preset OWNS its routing. ``None``
    # means "no opinion — the preset is the authority"; an explicit value
    # must EQUAL the preset's native routing or the spec is rejected at
    # the boundary. The old default ("dim_order") silently mutated any
    # preset whose native routing differed — the same defect class as the
    # Dragonfly k=8 disaster. None never reaches `resolved`: resolution
    # always materializes the preset's concrete routing.
    routing: str | None = Field(default=None)


class SimulationSpec(BaseModel):
    model_config = _STRICT
    mode: str = Field(default="latency")  # latency | serving (PR 4+)
    network_simulator: str = Field(default="booksim")  # registered ID
    timeout_s: int = Field(default=60, ge=1)


class ReplicationSpec(BaseModel):
    model_config = _STRICT
    # Explicit randomness policy (ADR/redesign §20): either deterministic,
    # or stochastic with an explicit seed list. No universal seeds=5.
    mode: str = Field(default="deterministic")  # deterministic | stochastic
    seeds: list[int] = Field(default_factory=lambda: [42])


class ComparisonSpec(BaseModel):
    """Explicit comparison intent (redesign §19). Optional for single runs;
    required (and validated) by compare flows once they move onto runs."""
    model_config = _STRICT
    variable: list[str] = Field(default_factory=list)
    controlled: dict[str, str] = Field(default_factory=dict)
    acknowledged_differences: list[str] = Field(default_factory=list)


class ServingSpec(BaseModel):
    """Serving intent (PR6 slice B). Cluster/dataset are REGISTERED IDs
    (ADR 0005) resolved via the trusted serving registry in core.paths —
    never filesystem paths in the spec."""
    model_config = _STRICT
    cluster: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    num_reqs: int = Field(ge=1)
    network_backend: Literal["booksim", "analytical", "ns3"] = "booksim"
    cycle_accurate: bool = Field(default=True)
    request_routing_policy: Literal["LOAD", "RR", "RAND", "CUSTOM"] = "LOAD"


class ExperimentSpec(BaseModel):
    model_config = _STRICT
    schema_version: int = SCHEMA_VERSION
    name: str = Field(min_length=1)
    workload: WorkloadSpec
    system: SystemSpec
    # Study-integrity P0 (#2): the serving CLUSTER is the authoritative
    # fabric intent until Wave B lands FabricArtifact. A serving spec must
    # NOT carry a standalone network preset — that was false intent (the
    # cluster's parallelism generates the executed fabric, not the spec).
    network: NetworkSpec | None = None
    simulation: SimulationSpec = Field(default_factory=SimulationSpec)
    replication: ReplicationSpec = Field(default_factory=ReplicationSpec)
    comparison: ComparisonSpec | None = None
    serving: ServingSpec | None = None
    notes: str = ""


# ── Parsing / resolution / hashing ──────────────────────────────────────────

def parse(data: dict[str, Any]) -> ExperimentSpec:
    """Strictly parse an experiment spec dict. Raises SpecError with a
    precise message on any unknown field or bad value."""
    try:
        return ExperimentSpec.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "<root>"
        raise SpecError(f"invalid spec at '{loc}': {first['msg']}") from e


def _resolve_named_network(network: NetworkSpec) -> dict[str, str]:
    """One topology resolver: named preset -> concrete (topology, routing).

    The preset is immutable fabric intent (study-integrity P0 #10):
      * ``routing is None``  -> the preset's native routing is materialized;
      * ``routing == native`` -> same resolved intent (hash-identical);
      * anything else        -> SpecError BEFORE anything is created.
    There is no alias guessing (exact registered IDs only) and no
    ``replace(topo, routing=...)`` anywhere downstream — run_experiment
    consumes this concrete routing and re-asserts it.
    """
    from ..model.presets import lookup_topo

    topo = lookup_topo(network.topology)
    if topo is None:
        raise SpecError(
            f"unknown topology id {network.topology!r} — not in the "
            "registered presets; specs reference topologies by exact "
            "registered ID (no aliases)")
    if network.routing is not None and network.routing != topo.routing:
        raise SpecError(
            f"named preset {topo.name!r} owns routing {topo.routing!r}; "
            f"requested {network.routing!r}. Use an explicit custom-fabric "
            "path when custom routing is supported.")
    return {"topology": topo.name, "routing": topo.routing}


def resolve(spec: ExperimentSpec) -> dict[str, Any]:
    """Materialize the fully-resolved experiment: every default explicit,
    references expanded, deterministic key order.

    The resolved dict is the unit of identity — what gets hashed (ADR 0002)
    and what gets frozen into the run directory (ADR 0001).
    """
    if spec.schema_version != SCHEMA_VERSION:
        raise SpecError(
            f"spec schema_version {spec.schema_version} != supported {SCHEMA_VERSION}"
        )
    repl = spec.replication
    if repl.mode not in ("deterministic", "stochastic"):
        raise SpecError("replication.mode must be deterministic or stochastic")
    if not repl.seeds or any(seed < 0 for seed in repl.seeds):
        raise SpecError("replication.seeds must contain non-negative seeds")
    seeds = sorted(set(repl.seeds))
    if repl.mode == "deterministic" and len(seeds) != 1:
        raise SpecError("deterministic replication.seeds must contain one distinct seed")
    if repl.mode == "stochastic" and len(seeds) < 2:
        raise SpecError(
            "stochastic replication with <2 distinct seeds is a one-seed "
            "comparison (redesign §20) — pass explicit seeds or use "
            "mode=deterministic"
        )
    if spec.simulation.mode == "serving" and spec.serving is None:
        raise SpecError("simulation.mode is serving but no serving block "
                        "was provided")
    if spec.simulation.mode != "serving" and spec.serving is not None:
        raise SpecError("serving block provided but simulation.mode is "
                        f"{spec.simulation.mode!r}, not serving")
    if spec.simulation.mode == "serving":
        if spec.network is not None:
            # Serving fabric authority is the CLUSTER (study-integrity P0
            # #2, Wave-A rule): its parallelism generates the executed
            # BookSim fabric. A standalone preset here is false scientific
            # intent — the old shape let spec.network.topology ride the
            # fingerprint while the cluster's fabric executed.
            raise SpecError(
                "serving fabric is cluster-derived in the current schema; "
                "do not provide network.topology — the serving cluster "
                "owns fabric intent (FabricArtifact lands in Wave B)")
    elif spec.network is None:
        raise SpecError("network is required for standalone experiments")
    network = (_resolve_named_network(spec.network)
               if spec.network is not None else None)
    return {
        "schema_version": SCHEMA_VERSION,
        "workload": {"id": spec.workload.id, "trace": spec.workload.trace},
        "system": {
            "nodes": spec.system.nodes,
            "tp_size": spec.system.tp_size,
            "instances_per_node": spec.system.instances_per_node,
        },
        "network": network,
        "simulation": {
            "mode": spec.simulation.mode,
            "network_simulator": spec.simulation.network_simulator,
            "timeout_s": spec.simulation.timeout_s,
        },
        "replication": {"mode": repl.mode, "seeds": seeds},
        "comparison": (
            {
                "variable": spec.comparison.variable,
                "controlled": spec.comparison.controlled,
                "acknowledged_differences": spec.comparison.acknowledged_differences,
            }
            if spec.comparison is not None
            else None
        ),
        "serving": (
            {
                "cluster": spec.serving.cluster,
                "dataset": spec.serving.dataset,
                "num_reqs": spec.serving.num_reqs,
                "network_backend": spec.serving.network_backend,
                "cycle_accurate": spec.serving.cycle_accurate,
                "request_routing_policy":
                    spec.serving.request_routing_policy,
                # intent→execution join (study-integrity P0): the concrete
                # cluster-derived fabric identity is injected into this
                # block by the serving slice BEFORE Run.create() (see
                # core.serving.resolve_serving_fabric_identity), so the
                # experiment hash binds the expected fabric and the run
                # slice can prove expected == executed. ``network`` is
                # deliberately absent for serving — the cluster, not a
                # standalone preset, owns fabric intent.
            }
            if spec.serving is not None
            else None
        ),
    }


def canonical_json(resolved: dict[str, Any]) -> str:
    """Deterministic serialization: sorted keys, tight separators."""
    return json.dumps(resolved, sort_keys=True, separators=(",", ":"))


def experiment_hash(resolved: dict[str, Any]) -> str:
    """SHA-256 over the canonical resolved spec = scientific identity.

    Non-scientific fields never reach `resolved` (resolve() omits them), so
    the hash is stable under notes/name edits by construction.
    """
    return hashlib.sha256(canonical_json(resolved).encode()).hexdigest()


def spec_from_file(path) -> ExperimentSpec:
    """Load + parse a spec from a JSON file (strict; SpecError on garbage)."""
    import json as _json
    from pathlib import Path as _Path

    p = _Path(path)
    try:
        data = _json.loads(p.read_text())
    except FileNotFoundError as e:
        raise SpecError(f"spec file not found: {p}") from e
    except _json.JSONDecodeError as e:
        raise SpecError(f"spec file is not valid JSON: {p}: {e}") from e
    return parse(data)


# ── Plan (validate -> plan -> execute seam; redesign §24) ───────────────────
# A plan is the executable expansion of one resolved experiment: one task per
# (topology?, seed) combination. Slice A has a single task per seed.

def plan(resolved: dict[str, Any]) -> dict[str, Any]:
    """Deterministic plan for a resolved spec. Stable identity: the plan hash
    is derived from the resolved spec hash + plan schema version, so
    execute(plan_id) can never drift from what was validated."""
    seeds = resolved["replication"]["seeds"]
    tasks = [
        {
            "task_id": f"eval-seed{s}",
            "topology": resolved["network"]["topology"],
            "trace": resolved["workload"]["trace"],
            "seed": s,
            "timeout_s": resolved["simulation"]["timeout_s"],
        }
        for s in seeds
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_hash": experiment_hash(resolved),
        "tasks": tasks,
    }
