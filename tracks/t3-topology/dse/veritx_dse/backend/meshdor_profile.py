"""veritx_dse.backend.meshdor_profile — CERTIFIED_BOOKSIM_MESH_DOR_XY_V1 audit.

The second certified BookSim projection, for native-mesh DOR_XY fabrics.
CERTIFIED_BOOKSIM_ANYNET_V1 is sealed and untouched; this profile has its
own identity, backend semantics version, parameter ownership table and
site-gate table.

Why a separate profile (not a flag): the native mesh path reads a
different config surface than AnyNet (`k`, `n`, `use_noc_latency` become
live; `network_file` goes dead; the `pin:topology=anynet` disabling
argument inverts). Sharing one audit would let one profile's pins vouch
for the other's reads.

Narrow certified domain (deliberate; widened only with new proofs):
  * TopologyArtifact.family == MESH, square k x k, seat_capacity 1;
  * router route materializes DOR_XY; every VC maps to DOR_XY;
  * attachment is identity-prefix (endpoint i -> router i; E <= N);
  * uniform channel latency 1, unit route weights, no parallel channels.

Native-mesh facts the domain rests on (all read from the vendored fork
at third_party/booksim2/src, pinned by tests in
tests/test_p1b_meshdor_profile.py):
  * mesh == KNCube(native): k-ary 2-cube, `_nodes == _size`, node n <->
    router n 1:1, coordinates x = id % k (x fastest) — the same row-major
    numbering the Srota mesh materializes, and the same decomposition
    `dor_next_mesh` routes on;
  * native links are latency 1 under `use_noc_latency=1` (pinned; the =0
    branch also yields 1 for mesh, but no compiled default is consumed);
  * trace-only addressing: the trace event list drives injection and
    BookSim skips self-loop injections for non-participating nodes, so
    native nodes beyond the attached endpoint prefix inject nothing;
  * the P1B mesh dump hook (KNCube::DumpDorRoutes) calls the CONFIGURED
    routing function (same `routing_function + "_" + topology` key rule
    both consumers use) with a probe flit per (router, node) pair, so the
    dumped first-hop table IS the executed realization, not a second
    Python DOR implementation.

Config selector pinned by construction-rule evidence (not function names):
`routing_function=dim_order` + `topology=mesh` -> key `dim_order_mesh` ->
`&dim_order_mesh`. (`dor` would resolve to the same pointer; `dim_order`
is pinned because key, function and class name coincide.)
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from .booksim_profile import (
    BOOKSIM_CERTIFIED_CONFIG_AUDIT, BookSimCertifiedProfile, ConfigRead,
)
from .contracts import ParameterOwner
from .source_audit import GATED_READ_SITES, GatedReadSite

MESH_DOR_PROFILE_ID = "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
MESH_DOR_BACKEND_SEMANTICS_VERSION = "booksim2-fork+P1B-meshdor-dump"
MESH_DOR_LOWERER_VERSION = "DORXY/1"

# The rendered config value (the lookup KEY is value + "_mesh").
MESH_DOR_ROUTING_FUNCTION_VALUE = "dim_order"
MESH_DOR_ROUTING_KEY = "dim_order_mesh"

A = ParameterOwner


def _mesh_audit() -> tuple[ConfigRead, ...]:
    """The standalone audit, re-pathed for the native mesh surface.

    - `network_file` is dead under native mesh (no AnyNet file exists);
      it leaves the active set (its read site stays declared below).
    - `topology` pins `mesh`.
    - `k`, `n`, `use_noc_latency` become live reads with explicit owners
      (fabric-derived shape; pinned backend constant).
    Every other row is shared unchanged (same Router/VC/flow/traffic-
    manager code runs under both topologies).
    """
    rows: list[ConfigRead] = []
    for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT:
        if row.name == "network_file":
            continue
        if row.name == "topology":
            rows.append(ConfigRead(
                "topology", A.BACKEND_PROFILE,
                "networks/network.cpp:89", "mesh",
                note="certified mesh-DOR projector renders native mesh"))
            continue
        rows.append(row)
    rows.append(ConfigRead(
        "k", A.FABRIC_DERIVED, "networks/kncube.cpp (KNCube::_ComputeSize)",
        note="mesh radix, re-derived from the topology artifact (isqrt of "
             "the router count) and re-checked at spawn"))
    rows.append(ConfigRead(
        "n", A.FABRIC_DERIVED, "networks/kncube.cpp (KNCube::_ComputeSize)",
        note="mesh dimensionality, always 2 in the certified domain"))
    rows.append(ConfigRead(
        "use_noc_latency", A.BACKEND_PROFILE,
        "networks/kncube.cpp (KNCube::_BuildNet)", 1,
        note="native mesh links are latency 1 under this pin; pinned "
             "explicit so no compiled default is consumed"))
    return tuple(rows)


MESH_DOR_AUDIT = _mesh_audit()


def _mesh_sites() -> dict[str, tuple[GatedReadSite, ...]]:
    """Site gates for the mesh-DOR render.

    Transformation of GATED_READ_SITES, stated explicitly:
    - every `pin:topology=anynet` disabling argument becomes
      `pin:topology=mesh` (other topologies' constructors never run);
    - `k`/`n`/`use_noc_latency` @ kncube become ACTIVE reads (dropped
      from the site table — active fields need no sites);
    - `fail_seed` @ kncube stays gated but on its true guard,
      `pin:link_failures=0` (read only inside `if (_size && num_fails)`);
    - `network_file` @ anynet gains a site (unregistered in this
      profile; unreachable under mesh).
    """
    out: dict[str, list[GatedReadSite]] = {}
    for field, sites in GATED_READ_SITES.items():
        kept: list[GatedReadSite] = []
        for site in sites:
            if site.path == "networks/kncube.cpp" and field in (
                    "k", "n", "use_noc_latency"):
                continue  # ACTIVE in the mesh profile
            if field == "fail_seed" and \
                    site.path == "networks/kncube.cpp":
                kept.append(replace(site, gates=("pin:link_failures=0",)))
                continue
            gates = tuple(
                "pin:topology=mesh" if g == "pin:topology=anynet" else g
                for g in site.gates)
            kept.append(replace(site, gates=gates))
        if kept:
            out[field] = kept
    out["network_file"] = (GatedReadSite(
        "networks/anynet.cpp", 1, ("AnyNet::_ComputeSize",),
        ("pin:topology=mesh",)),)
    return {field: tuple(sites) for field, sites in out.items()}


MESH_DOR_SITES = _mesh_sites()


def _check_mesh_tables() -> None:
    """Construction-time closure over the transform (fail fast)."""
    for field, sites in MESH_DOR_SITES.items():
        for site in sites:
            for gate in site.gates:
                if gate == "pin:topology=anynet":
                    raise ValueError(
                        f"mesh site {field}@{site.path} still carries the "
                        f"anynet disabling argument")
    for field in ("k", "n", "use_noc_latency"):
        for site in MESH_DOR_SITES.get(field, ()):
            if site.path == "networks/kncube.cpp":
                raise ValueError(
                    f"mesh-active read {field}@kncube must not keep a site")
    fail_sites = MESH_DOR_SITES.get("fail_seed", ())
    if len(fail_sites) != 1 or \
            fail_sites[0].gates != ("pin:link_failures=0",):
        raise ValueError("fail_seed@kncube must gate on link_failures=0")
    names = [r.name for r in MESH_DOR_AUDIT]
    if "network_file" in names:
        raise ValueError("network_file must leave the mesh active set")
    for required in ("topology", "k", "n", "use_noc_latency",
                     "routing_function", "routing_dump_file"):
        if required not in names:
            raise ValueError(
                f"mesh audit is missing required field {required!r}")


_check_mesh_tables()


MESH_DOR_PROFILE = BookSimCertifiedProfile(
    profile_id=MESH_DOR_PROFILE_ID,
    semantics_version=MESH_DOR_BACKEND_SEMANTICS_VERSION,
    audit=MESH_DOR_AUDIT,
)

MESH_DOR_OWNERSHIP = MESH_DOR_PROFILE.ownership()


__all__ = [
    "MESH_DOR_AUDIT",
    "MESH_DOR_BACKEND_SEMANTICS_VERSION",
    "MESH_DOR_LOWERER_VERSION",
    "MESH_DOR_OWNERSHIP",
    "MESH_DOR_PROFILE",
    "MESH_DOR_PROFILE_ID",
    "MESH_DOR_ROUTING_FUNCTION_VALUE",
    "MESH_DOR_ROUTING_KEY",
    "MESH_DOR_SITES",
]
