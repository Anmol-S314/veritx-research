"""veritx_dse.model.family_registry — the ONE topology authority.

The bug this prevents: every consumer switched on the family name
independently, each covering a different subset. Mesh worked because it was
first; cmesh/flatfly compiled and certified then refused at the system leg
because the AstraSim namespace derivation knew only mesh/torus/anynet.

Per family, once, with provenance:
  * ``backend`` — the name BookSim's ``Network::New`` dispatches on;
  * ``nodes``   — terminal-node count, transcribed from BookSim's OWN
    constructor for that network, so a count is never a guess.

BookSim's ``_nodes`` counts TERMINALS, and BookSim builds a network at least
as large as what is attached to it — so the formula and the attachment plan
must be CONSISTENT, not equal (a 5x5 mesh offers 25 seats; a design may fill
17). A network smaller than what is attached refuses.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

@dataclass(frozen=True)
class BookSimTopology:
    """One topology BookSim can build, and how it counts its terminals."""

    backend: str
    nodes: Callable[[dict[str, int]], int | None]
    source: str

def _int(values: dict[str, Any], key: str) -> int | None:
    """A positive int from a config value (config values are STRINGS)."""
    v = values.get(key)
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = int(v.strip())
        except ValueError:
            return None
    if not isinstance(v, int) or v < 1:
        return None
    return v

def _k_n(values: dict[str, int]) -> int | None:
    """kncube.cpp: `_nodes = _size`, `_size = powi(k, n)` — mesh / torus."""
    k, n = _int(values, "k"), _int(values, "n")
    return None if k is None or n is None else k ** n

def _c_kn(values: dict[str, int]) -> int | None:
    """cmesh.cpp:95 `_nodes = _c * powi(_k, _n)`; flatfly_onchip.cpp:98
    `_nodes = powi(_k, _n) * _c` — the same product, different order."""
    c, base = _int(values, "c"), _k_n(values)
    return None if c is None or base is None else c * base

def _size_c(values: dict[str, int]) -> int | None:
    """gec.cpp:205 `_nodes = _size * _c` (terminals)."""
    size, c = _int(values, "size"), _int(values, "c")
    return None if size is None or c is None else size * c

def _dragonfly(values: dict[str, int]) -> int | None:
    """dragonfly.cpp:199 `_nodes = _a * _p * _g`, where `_p = k`,
    `_a = 2p if n == 1 else p^n` (dragonfly.cpp:194,196) and
    `_g = _a * _p + 1` (dragonfly.cpp:198)."""
    p, n = _int(values, "k"), _int(values, "n")
    if p is None or n is None:
        return None
    a = 2 * p if n == 1 else p ** n
    return a * p * (a * p + 1)

BOOKSIM_TOPOLOGIES: dict[str, BookSimTopology] = {
    "torus": BookSimTopology("torus", _k_n, "kncube.cpp:64"),
    "mesh": BookSimTopology("mesh", _k_n, "kncube.cpp:64"),
    "cmesh": BookSimTopology("cmesh", _c_kn, "cmesh.cpp:95"),
    "fly": BookSimTopology("fly", _k_n, "fly.cpp:52"),
    "qtree": BookSimTopology("qtree", _k_n, "qtree.cpp:67"),
    "tree4": BookSimTopology("tree4", _k_n, "tree4.cpp:74"),
    "fattree": BookSimTopology("fattree", _k_n, "fattree.cpp:77"),
    "flatfly": BookSimTopology("flatfly", _c_kn, "flatfly_onchip.cpp:98"),
    "anynet": BookSimTopology("anynet", lambda v: None, "anynet.cpp (file)"),
    "dragonflynew": BookSimTopology("dragonflynew", _dragonfly,
                                    "dragonfly.cpp:199"),
    "gec": BookSimTopology("gec", _size_c, "gec.cpp:205"),
}

EXPRESSIBLE_FAMILIES = frozenset({
    "mesh", "torus", "cmesh", "flatfly", "fattree", "anynet", "gec",
})

class FamilyRegistryError(ValueError):
    """A topology count could not be established without guessing."""

def terminal_node_count(topology: str, values: dict[str, Any]) -> int | None:
    """BookSim's terminal-node count for `topology`, or None if unknown.

    None means "this table cannot derive it" — NEVER a guess. Callers fall
    back to the attachment plan and cross-check.
    """
    entry = BOOKSIM_TOPOLOGIES.get(topology)
    if entry is None:
        return None
    return entry.nodes(values)

def resolve_node_count(*, topology: str, values: dict[str, Any],
                       endpoint_count: int) -> tuple[int, str]:
    """The ASTRA Sys namespace size, with the witness that established it.

    The relation is `nodes >= endpoints`, NOT equality: a 5x5 mesh provides
    25 terminal positions and a design may attach 17 agents to them. The
    config formula and the attachment plan are independent witnesses of the
    same machine, so they must be CONSISTENT (a network smaller than what is
    attached is a contradiction) — but a partially-filled network is normal.
    """
    if endpoint_count < 1:
        raise FamilyRegistryError(
            f"the attachment plan attaches {endpoint_count} endpoints; a "
            "Sys namespace cannot be that small")
    derived = terminal_node_count(topology, values)
    if derived is None:
        if topology not in BOOKSIM_TOPOLOGIES:
            raise FamilyRegistryError(
                f"topology {topology!r} is not in the family registry "
                f"({sorted(BOOKSIM_TOPOLOGIES)}) and its config carries no "
                "node-count formula — register it in "
                "model/family_registry.py with the BookSim constructor it "
                "was transcribed from; refusing to guess a node count")
        return endpoint_count, "attachment plan (config omits the formula inputs)"
    if derived < endpoint_count:
        raise FamilyRegistryError(
            f"node-count contradiction for topology {topology!r}: "
            f"BookSim's own formula "
            f"({BOOKSIM_TOPOLOGIES[topology].source}) yields {derived} "
            f"nodes, but the attachment plan attaches {endpoint_count} "
            "endpoints — the network cannot be smaller than what is "
            "attached to it")
    return derived, f"BookSim formula ({BOOKSIM_TOPOLOGIES[topology].source})"

def _mesh_edges(v: dict[str, Any]) -> int | None:
    k, n = _int(v, "k"), _int(v, "n")
    return None if k is None or n is None else n * (k - 1) * k ** (n - 1)


def _torus_edges(v: dict[str, Any]) -> int | None:
    k, n = _int(v, "k"), _int(v, "n")
    return None if k is None or n is None else n * k ** n


def _flatfly_edges(v: dict[str, Any]) -> int | None:
    k, n, c = _int(v, "k"), _int(v, "n"), _int(v, "c")
    if k is None or n is None or c is None:
        return None
    nodes = (k ** n) * c
    radix = c + (k - 1) * n
    return nodes // c * (radix - c) // 2


def _gec_edges(v: dict[str, Any]) -> int | None:
    k, o, d = _int(v, "k"), _int(v, "o"), _int(v, "d")
    if k is None:
        return None
    if v.get("mesh"):
        return 2 * k * (k - 1)
    if (d or 0) == 1 and (o or 0) >= k - 1:
        return k * k * (k - 1)
    return 2 * k * (k - 1) + (o or 0) * k * k


def _fly_edges(v: dict[str, Any]) -> int | None:
    k, n = _int(v, "k"), _int(v, "n")
    return None if k is None or n is None else (n - 1) * k ** n


def _cmesh_edges(v: dict[str, Any]) -> int | None:
    k, n = _int(v, "k"), _int(v, "n")
    return None if k is None or n is None else 2 * n * k ** n


def _tree_edges(v: dict[str, Any]) -> int | None:
    k, n = _int(v, "k"), _int(v, "n")
    return None if k is None or n is None else n * k ** n


def _dragonfly_edges(v: dict[str, Any]) -> int | None:
    p = _int(v, "k")
    if p is None:
        return None
    a, g = 2 * p, 2 * p * p + 1
    return g * a * p // 2 + g * a * (2 * p - 1) // 2


#: Canonical families. NAMES come from the declared authority —
#: `docs/product/topology-family-registry.yaml` (registry_version
#: topo-fam-v1) — so this module adds computable facts and never invents a
#: vocabulary. `backend` is BookSim's dispatch name, `ir_kinds` the
#: `topology_ir.KINDS` that lower here. `None` for nodes/edges means the
#: shape is arbitrary (a rendered graph), not that the fact is unknown.
#:
#: Note the two many-to-one edges, which are exactly the renames that were
#: never written down before:
#:   ring            -> BookSim `torus` (a 1-D torus IS a ring)
#:   gec_express     -> BookSim `gec`    (gec and gec_express share it)
#:   flattened_butterfly -> BookSim `fly`; dragonfly -> `dragonflynew`
TOPOLOGY_FAMILIES: dict[str, dict[str, Any]] = {
    "mesh": {"backend": "mesh", "ir_kinds": ("mesh",),
             "routing": "dim_order", "analytical": "Ring",
             "nodes": _k_n, "edges": _mesh_edges},
    "torus": {"backend": "torus", "ir_kinds": ("torus",),
              "routing": "dim_order", "analytical": "Ring",
              "nodes": _k_n, "edges": _torus_edges},
    "ring": {"backend": "torus", "ir_kinds": ("ring",),
             "routing": "dim_order", "analytical": "Ring",
             "nodes": _k_n, "edges": _torus_edges},
    "concentrated_mesh": {"backend": "cmesh", "ir_kinds": (),
                          "routing": "dim_order", "analytical": "Ring",
                          "nodes": _c_kn, "edges": _cmesh_edges},
    "flatfly": {"backend": "flatfly", "ir_kinds": (),
                "routing": "min", "analytical": "Ring",
                "nodes": _c_kn, "edges": _flatfly_edges},
    "gec": {"backend": "gec", "ir_kinds": (), "routing": "min",
            "analytical": None, "nodes": _size_c, "edges": _gec_edges,
            "noc_latency_zero": True,
            # MUST equal GecMode values; test_family_registry asserts it.
            "modes": ("mesh", "express", "multidrop", "hybrid"),
            "vcs_from_multidrop": True},
    "gec_express": {"backend": "gec", "ir_kinds": (), "routing": "min",
                    "analytical": None, "nodes": _size_c,
                    "edges": _gec_edges, "noc_latency_zero": True,
                    "modes": ("mesh", "express", "multidrop", "hybrid"),
            "vcs_from_multidrop": True},
    "fat_tree": {"backend": "fattree", "ir_kinds": (), "routing": "min",
                 "analytical": None, "nodes": _k_n, "edges": _tree_edges},
    "flattened_butterfly": {"backend": "fly", "ir_kinds": (),
                            "routing": "min", "analytical": None,
                            "nodes": _k_n, "edges": _fly_edges},
    "dragonfly": {"backend": "dragonflynew", "ir_kinds": (),
                  "routing": "min", "analytical": None,
                  "nodes": _dragonfly, "edges": _dragonfly_edges},
    "qtree": {"backend": "qtree", "ir_kinds": (), "routing": "min",
              "analytical": None, "nodes": _k_n, "edges": _tree_edges},
    "custom": {"backend": "anynet", "ir_kinds": ("anynet", "custom"),
               "routing": "min", "analytical": None,
               "nodes": None, "edges": None, "rendered_graph": True},
    # Not in the declared registry. Recorded so the gaps are measured.
    "tree4": {"backend": "tree4", "ir_kinds": (), "routing": "min",
              "analytical": None, "nodes": _k_n, "edges": _tree_edges},
    "star": {"backend": "anynet", "ir_kinds": ("star",),
             "routing": "min", "analytical": "Switch",
             "nodes": None, "edges": None, "rendered_graph": True},
    "switch": {"backend": "anynet", "ir_kinds": ("switch",),
               "routing": "min", "analytical": "Switch",
               "nodes": None, "edges": None, "rendered_graph": True},
}

#: Fields every family carries; `spec_for` fills these in so a consumer
#: never has to guess or re-declare a default.
_SPEC_DEFAULTS: dict[str, Any] = {
    "backend": None, "ir_kinds": (), "routing": "min", "analytical": None,
    "nodes": None, "edges": None, "noc_latency_zero": False,
    "rendered_graph": False, "modes": None,
    #: A multidrop degree (`d`) needs one VC per destination, so the VC count
    #: is derived from `d`. Family knowledge, kept here instead of as a
    #: `backend == "gec"` test in every caller.
    "vcs_from_multidrop": False,
}


def spec_for(name: str) -> dict[str, Any]:
    """Every fact about a family or backend name, with defaults filled in.

    Unknown names yield the all-defaults spec rather than raising, so a
    caller migrating a `== "something"` test keeps its old behaviour.
    """
    family = resolve_family(name)
    spec = dict(_SPEC_DEFAULTS)
    if family is not None:
        spec.update(TOPOLOGY_FAMILIES[family])
    spec["family"] = family
    return spec

#: Families with a `MaterializedFamily` member (they can reach an artifact).
MATERIALIZED_FAMILIES = frozenset({
    "mesh", "torus", "ring", "concentrated_mesh", "flatfly", "gec_express",
    "custom",
})


#: Per-family default config, the values BookSim assumes when a design
#: omits them. Part of the family fact: `presets._default_edge_count` used
#: its own copy of these, which is how two tables drifted apart.
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "mesh": {"k": 8, "n": 2},
    "torus": {"k": 8, "n": 2},
    "ring": {"k": 8, "n": 1},
    "concentrated_mesh": {"k": 4, "n": 2},
    "flatfly": {"k": 4, "n": 2, "c": 4},
    "gec": {"k": 8, "o": 0, "d": 1},
    "gec_express": {"k": 8, "o": 0, "d": 1},
    "fat_tree": {"k": 4, "n": 3},
    "flattened_butterfly": {"k": 4, "n": 3},
    "dragonfly": {"k": 2},
    "qtree": {"k": 4, "n": 3},
    "tree4": {"k": 4, "n": 3},
    "custom": {},
    "star": {},
    "switch": {},
}


def resolve_family(name: str) -> str | None:
    """Accept a canonical family OR a BookSim backend spelling."""
    if name in TOPOLOGY_FAMILIES:
        return name
    return family_for_backend(name)


def resolved_params(family: str, params: dict[str, Any] | None = None) -> dict:
    """Family defaults overlaid with the design's own params."""
    merged = dict(DEFAULT_PARAMS.get(family, {}))
    merged.update(params or {})
    return merged


def edge_count(name: str, params: dict[str, Any] | None = None) -> int:
    """Undirected edge count for a family or backend name; 0 if unknown.

    Accepts either spelling and applies the family defaults, so a caller
    migrating off its own table needs no defaults of its own.
    """
    family = resolve_family(name)
    if family is None:
        return 0
    fn = TOPOLOGY_FAMILIES[family]["edges"]
    if fn is None:
        return 0
    return fn(resolved_params(family, params)) or 0


def node_count(name: str, params: dict[str, Any] | None = None) -> int | None:
    """Terminal-node count for a family or backend name, or None."""
    family = resolve_family(name)
    if family is None:
        return None
    fn = TOPOLOGY_FAMILIES[family]["nodes"]
    if fn is None:
        return None
    return fn(resolved_params(family, params))


def families_for_backend(backend: str) -> tuple[str, ...]:
    """Every canonical family BookSim renders for `backend`.

    Many-to-one by design: `gec` serves both `gec` and `gec_express`, and
    `torus` serves both `torus` and `ring`.
    """
    return tuple(n for n, s in TOPOLOGY_FAMILIES.items()
                 if s["backend"] == backend)


def family_for_backend(backend: str) -> str | None:
    """First canonical family for a BookSim backend, or None."""
    found = families_for_backend(backend)
    return found[0] if found else None


def family_for_ir_kind(kind: str) -> str | None:
    """Canonical family a `topology_ir` kind lowers to, or None."""
    for name, spec in TOPOLOGY_FAMILIES.items():
        if kind in spec["ir_kinds"]:
            return name
    return None


def declared_family_names(registry: Path | None = None) -> tuple[str, ...]:
    """The family names from the declared authority, in registry order."""
    import yaml

    path = registry or (Path(__file__).resolve().parents[5]
                        / "docs/product/topology-family-registry.yaml")
    return tuple(yaml.safe_load(path.read_text())["families"])


def migration_gaps() -> dict[str, list[str]]:
    """Every name in any vocabulary that has no canonical family."""
    from veritx_dse.model.topology_ir import KINDS

    in_ir = {k for spec in TOPOLOGY_FAMILIES.values()
             for k in spec["ir_kinds"]}
    in_backend = {spec["backend"] for spec in TOPOLOGY_FAMILIES.values()}
    return {
        "ir_kinds_without_a_family": sorted(set(KINDS) - in_ir),
        "booksim_backends_without_a_family": sorted(
            set(BOOKSIM_TOPOLOGIES) - in_backend),
        "booksim_backends_not_claimed_by_the_registry": sorted(
            set(BOOKSIM_TOPOLOGIES)
            - {TOPOLOGY_FAMILIES[n]["backend"]
               for n in TOPOLOGY_FAMILIES if n in declared_family_names()}),
    }


__all__ = [
    "BOOKSIM_TOPOLOGIES",
    "EXPRESSIBLE_FAMILIES",
    "MATERIALIZED_FAMILIES",
    "TOPOLOGY_FAMILIES",
    "BookSimTopology",
    "FamilyRegistryError",
    "declared_family_names",
    "DEFAULT_PARAMS",
    "edge_count",
    "families_for_backend",
    "family_for_backend",
    "family_for_ir_kind",
    "migration_gaps",
    "node_count",
    "resolve_family",
    "resolved_params",
    "spec_for",
    "resolve_node_count",
    "terminal_node_count",
]
