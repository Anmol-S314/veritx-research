"""compile_request_v4 — the v4 fabric intent root.

WHY A NEW GENERATION
====================

Schema 3 / compiler semantics 3 are RELEASED semantic authorities. PHASE B
originally added typed topology intent to `CompileRequestV3` directly, which
expanded schema 3 IN PLACE: schema-3 readers that used to refuse a typed
intent would accept one. Two binaries reading the same "v3" document would
then disagree about what v3 means.

So the new fabric semantics get a new generation:

    V2 IS FROZEN.  V3 IS FROZEN.  NEW FABRIC SEMANTICS REQUIRE V4.

WHAT CHANGES IN V4
==================

ONE topology authority. v3 had `noc_config.topology_family` XOR
`explicit_topology`, and `topology_family=None` IMPLICITLY meant mesh. v4 has
a single `topology: TopologyIntent` field that is REQUIRED and always
explicit:

  * there is no "None means mesh" in the v4 persisted schema — implicit mesh
    is a LEGACY meaning and is handled only in migration;
  * an explicit graph is an `ExplicitTopologyIntent(graph=TopologyIR)`, so
    two topology authorities cannot even be expressed;
  * `NocConfig` is replaced by `NocControls`, which may not describe topology
    shape at all.

NEW HASH DOMAIN. `_HASH_TYPE_TAG_V4` plus `schema_version=4` /
`compiler_semantics_version=4` domain-separate the envelope, so a v3 and a
v4 document can never share an identity by construction — including the
migrated pair, which is the point: the same science expressed in two
generations is deliberately NOT the same design identity.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.model.compile_model import (
    AddressMap, Agent, CompileRequestV3, CompileRequestV3SchemaError,
    DependencyGraph, PhysicalContext, RequirementV3, TopologyFamily,
    WorkloadV3, _strict_keys, _as_tuple,
)
from veritx_dse.model.noc_controls import (
    NocControls, NocControlsError, noc_controls_from_dict,
    noc_controls_from_noc_config,
)
from veritx_dse.model.topology_intent import (
    ExplicitTopologyIntent, TopologyIntent, TopologyIntentError,
    topology_intent_from_dict, topology_intent_from_noc_config,
)

COMPILE_REQUEST_SCHEMA_VERSION_V4 = 4
COMPILER_SEMANTICS_VERSION_V4 = 4

_HASH_TYPE_TAG_V4 = "srota/CompileRequest/v4"


class CompileRequestV4SchemaError(ValueError, SemanticError):
    """v4 fail-closed boundary: unknown keys/kinds refuse as v4 errors."""


class CompileRequestV4MigrationError(ValueError, SemanticError):
    """A legacy document does not determine a v4 design. Migration REFUSES
    rather than defaulting to a plausible-looking guess."""


_TOP_V4_KEYS = frozenset({
    "schema_version", "compiler_semantics_version", "workload",
    "requirements", "agents", "dependencies", "topology", "noc_controls",
    "address_map", "physical", "synthesis_provenance",
    "migration_provenance", "design_hash", "guardrail_hash",
    #: Documentation-only keys, carried for parity with the v2/v3 readers.
    #: They are never read as science.
    "_comment", "_docs",
})


def _strict_keys_v4(d: Any, allowed: frozenset, where: str) -> None:
    try:
        _strict_keys(d, allowed, where)
    except Exception as e:                                   # noqa: BLE001
        raise CompileRequestV4SchemaError(str(e)) from e


@dataclass(frozen=True)
class CompileRequestV4:
    """The v4 design root. `topology` is REQUIRED and is the ONLY topology
    authority; `noc_controls` carries only topology-independent controls."""

    workload: WorkloadV3
    requirements: tuple[RequirementV3, ...] = ()
    agents: tuple[Agent, ...] = ()
    dependencies: DependencyGraph = field(default_factory=DependencyGraph)
    #: THE one topology authority. Required: a v4 document always declares
    #: its topology explicitly (see module docstring).
    topology: TopologyIntent = None                # type: ignore[assignment]
    noc_controls: NocControls = field(default_factory=NocControls)
    address_map: AddressMap = field(default_factory=AddressMap)
    physical: PhysicalContext = field(default_factory=PhysicalContext)
    #: Linkage to the synthesis candidate this design came from. NOT design
    #: semantics: excluded from canonical_dict(), so origin cannot enter
    #: design identity.
    synthesis_provenance: Any = None
    #: NON-SEMANTIC migration record (what legacy spelling was read). Linkage
    #: only; excluded from canonical_dict() for the same reason.
    migration_provenance: Any = None
    schema_version: int = COMPILE_REQUEST_SCHEMA_VERSION_V4
    compiler_semantics_version: int = COMPILER_SEMANTICS_VERSION_V4

    def __post_init__(self):
        if not isinstance(self.workload, WorkloadV3):
            raise ValueError("workload must be a WorkloadV3")
        object.__setattr__(self, "requirements",
                           _as_tuple("requirements", self.requirements))
        object.__setattr__(self, "agents", _as_tuple("agents", self.agents))
        if self.topology is None:
            raise ValueError(
                "a v4 request MUST declare its topology explicitly: there is "
                "no implicit 'None means mesh' in schema 4. Migrate a legacy "
                "document with migrate_v3_to_v4() if it relied on the "
                "implicit default.")
        if not isinstance(self.topology, TopologyIntent):
            raise ValueError(
                "topology must be a TopologyIntent, got "
                f"{type(self.topology).__name__}")
        if not isinstance(self.noc_controls, NocControls):
            raise ValueError(
                "noc_controls must be a NocControls, got "
                f"{type(self.noc_controls).__name__}")
        if not isinstance(self.dependencies, DependencyGraph):
            raise ValueError("dependencies must be a DependencyGraph")
        if not isinstance(self.address_map, AddressMap):
            raise ValueError("address_map must be an AddressMap")
        if not isinstance(self.physical, PhysicalContext):
            raise ValueError("physical must be a PhysicalContext")
        if self.schema_version != COMPILE_REQUEST_SCHEMA_VERSION_V4:
            raise ValueError(
                f"unsupported v4 schema_version {self.schema_version}")
        if self.compiler_semantics_version != COMPILER_SEMANTICS_VERSION_V4:
            raise ValueError(
                "unsupported v4 compiler_semantics_version "
                f"{self.compiler_semantics_version}")

    # ── derived ─────────────────────────────────────────────────────────

    @property
    def total_nodes(self) -> int:
        return sum(a.count for a in self.agents)

    @property
    def noc_config(self) -> Any:
        """LEGACY CONTROL VIEW — for consumers that read NoC CONTROLS.

        It carries NO topology shape: `topology_family`, `radix` and
        `concentration` are all None, because in v4 topology shape belongs
        exclusively to `self.topology` and a second copy could disagree.

        This exists so control reads (`link_width`, `arbitration`, ...) do not
        have to be rewritten in one step. It is NOT a second authority for
        anything: the shape fields are structurally absent, so a consumer
        that reads shape here gets None and must fail loudly rather than
        silently use a stale copy.
        """
        from veritx_dse.model.compile_model import NocConfig
        c = self.noc_controls
        return NocConfig(
            topology_family=None, radix=None, concentration=None,
            arbitration=c.arbitration, rcu_enabled=c.rcu_enabled,
            link_width=c.link_width, mcast_groups=c.mcast_groups,
            mcast_setup_cycles=c.mcast_setup_cycles,
            output_formats=c.output_formats,
            obfuscation_level=c.obfuscation_level,
        )

    # ── envelope rendering (delegates to the frozen v3 helpers) ─────────
    # These parts of the envelope are IDENTICAL to v3 by construction, so
    # they are rendered by the v3 code rather than re-implemented: a
    # duplicate would be free to drift.

    def _workload_dict(self) -> dict:
        return CompileRequestV3._workload_dict(self)      # type: ignore[arg-type]

    def _physical_dict(self) -> dict:
        return CompileRequestV3._physical_dict(self)      # type: ignore[arg-type]

    def _semantic_dict(self) -> dict:
        return {
            "workload": self._workload_dict(),
            "requirements": [CompileRequestV3._requirement_dict(r)
                             for r in self.requirements],
            "agents": [CompileRequestV3._agent_dict(a) for a in self.agents],
            "dependencies": [CompileRequestV3._dependency_dict(dep)
                             for dep in self.dependencies.dependencies],
            "topology": self.topology.to_dict(),
            "noc_controls": self.noc_controls.to_dict(),
            "address_map": {"ranges": [CompileRequestV3._address_dict(r)
                                       for r in self.address_map.ranges]},
            "physical": self._physical_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "compiler_semantics_version": self.compiler_semantics_version,
            **self._semantic_dict(),
        }
        if self.synthesis_provenance is not None:
            d["synthesis_provenance"] = dict(self.synthesis_provenance)
        if self.migration_provenance is not None:
            d["migration_provenance"] = dict(self.migration_provenance)
        return d

    def canonical_dict(self) -> dict:
        """Identity envelope — sole input to design_hash().

        Topology SCIENCE enters (the topology variant's scientific_dict), so
        two different physical designs can never collide. Origin
        (synthesis_provenance) and the migration record do NOT.
        """
        d = self._semantic_dict()
        d["topology"] = self.topology.scientific_dict()
        d["noc_controls"] = self.noc_controls.canonical_dict()
        if self.workload.source_ref is not None:
            d["workload"]["workload_source_ref"] = \
                self.workload.source_ref.identity_dict()
        return d

    def design_hash(self) -> str:
        """AUTHORITATIVE v4 design-intent identity (SHA-256).

        Domain-separated by the v4 tag AND the v4/c4 envelope, so a v2, a v3
        and a v4 document can never share an identity by construction.
        """
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG_V4}/v{self.schema_version}/"
                f"c{self.compiler_semantics_version}\0"
                + canonical_json(self.canonical_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def guardrail_hash(self) -> str:
        return self.design_hash()

    # ── parsing ─────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: Any) -> "CompileRequestV4":
        if not isinstance(d, dict):
            raise CompileRequestV4SchemaError("request must be an object")
        # Check the GENERATION first: a v2/v3 document should be told to
        # MIGRATE, not handed a confusing "unknown field noc_config".
        if d.get("schema_version") != COMPILE_REQUEST_SCHEMA_VERSION_V4:
            raise CompileRequestV4SchemaError(
                f"this v4 reader speaks schema "
                f"v{COMPILE_REQUEST_SCHEMA_VERSION_V4}, got "
                f"{d.get('schema_version')!r}. A v2/v3 document must be "
                "MIGRATED (migrate_v2_to_v4/migrate_v3_to_v4); it is never "
                "upgraded implicitly during parsing.")
        _strict_keys_v4(d, _TOP_V4_KEYS, "CompileRequestV4")
        if d.get("compiler_semantics_version") \
                != COMPILER_SEMANTICS_VERSION_V4:
            raise CompileRequestV4SchemaError(
                "unsupported v4 compiler_semantics_version "
                f"{d.get('compiler_semantics_version')!r}")

        # Reuse the frozen v3 readers for the UNCHANGED parts of the
        # envelope. They are invoked on a v3-shaped projection of this
        # document, so the shared sub-objects cannot drift between
        # generations.
        shared = {k: v for k, v in d.items() if k not in (
            "topology", "noc_controls", "schema_version",
            "compiler_semantics_version", "synthesis_provenance",
            "migration_provenance")}
        shared["schema_version"] = 3
        shared["compiler_semantics_version"] = 3
        shared["noc_config"] = {"topology_family": "mesh"}
        # Documentation keys are not science; the frozen v3 reader accepts
        # them, and the v4 reader accepts them too (see _TOP_V4_KEYS).
        try:
            v3 = CompileRequestV3.from_dict(shared)
        except CompileRequestV3SchemaError as e:
            raise CompileRequestV4SchemaError(
                f"invalid v4 request body: {e}") from e

        if "topology" not in d or d["topology"] is None:
            raise CompileRequestV4SchemaError(
                "a v4 request MUST carry 'topology': schema 4 has no "
                "implicit default")
        try:
            topology = topology_intent_from_dict(d["topology"])
        except TopologyIntentError as e:
            raise CompileRequestV4SchemaError(
                f"invalid topology: {e}") from e
        try:
            controls = noc_controls_from_dict(d.get("noc_controls", {}))
        except NocControlsError as e:
            raise CompileRequestV4SchemaError(
                f"invalid noc_controls: {e}") from e

        try:
            obj = cls(
                workload=v3.workload,
                requirements=v3.requirements,
                agents=v3.agents,
                dependencies=v3.dependencies,
                topology=topology,
                noc_controls=controls,
                address_map=v3.address_map,
                physical=v3.physical,
                synthesis_provenance=(dict(d["synthesis_provenance"])
                                      if d.get("synthesis_provenance")
                                      else None),
                migration_provenance=(dict(d["migration_provenance"])
                                      if d.get("migration_provenance")
                                      else None),
                schema_version=d["schema_version"],
                compiler_semantics_version=d["compiler_semantics_version"],
            )
        except ValueError as e:
            raise CompileRequestV4SchemaError(
                f"invalid v4 request: {e}") from e
        for key in ("design_hash", "guardrail_hash"):
            if key in d and d[key] != obj.design_hash():
                raise CompileRequestV4SchemaError(
                    f"{key} mismatch: document says {d[key]!r}, this "
                    f"document's science hashes to {obj.design_hash()!r}")
        return obj


# ══════════════════════════════════════════════════════════════════════════
# MIGRATION
# ══════════════════════════════════════════════════════════════════════════

def _frozen_v3_radix(endpoint_count: int, concentration: int) -> int:
    """The FROZEN v3 auto-sizing law for mesh/torus/concentrated mesh.

    v3 `radix=None` meant "size the grid for me". That law is a literal here
    rather than a call into current code: a migration's meaning must not
    depend on what the sizing code does later. (Source: the v3 materializer
    computed ``max(1, ceil(sqrt(ceil(endpoint_count / concentration))))``.)
    """
    routers_needed = math.ceil(endpoint_count / concentration)
    return max(1, math.ceil(math.sqrt(routers_needed)))


def migrate_v3_to_v4(
        request: CompileRequestV3, *,
        topology_intent: TopologyIntent | None = None,
) -> CompileRequestV4:
    """v3 -> v4. NEVER implicit: callers migrate deliberately.

    MIGRATION MATRIX
    ----------------
    mesh (+ radix=None)      -> MeshIntent, radix RESOLVED from the request's
                                endpoint count via the FROZEN v3 sizing law
    mesh (+ radix=k)         -> MeshIntent(side_length=k)
    concentrated_mesh        -> ConcentratedMeshIntent; a missing
                                concentration resolves to the FROZEN v3
                                default 4 (a literal, not a live default)
    torus                    -> TorusIntent (wrap topology only; no routing
                                is invented)
    explicit_topology        -> ExplicitTopologyIntent(graph=...) preserving
                                the graph's scientific identity
    topology_family=None     -> the legacy IMPLICIT mesh becomes an EXPLICIT
      (and no explicit graph)   MeshIntent
    flatfly / gec / fat_tree -> REFUSED unless `topology_intent` is supplied.
                                The v3 spelling does not determine a physical
                                design for these families.

    `topology_intent` may be supplied to resolve a family v3 could not
    express. It must AGREE with any family v3 DID express.
    """
    if not isinstance(request, CompileRequestV3):
        raise CompileRequestV4MigrationError(
            f"migrate_v3_to_v4 needs a CompileRequestV3, got "
            f"{type(request).__name__}")

    noc = request.noc_config
    explicit = request.explicit_topology
    family = noc.topology_family

    provenance: dict[str, Any] = {
        "migrated_from": "CompileRequestV3",
        "source_design_hash": request.design_hash(),
    }

    if explicit is not None:
        if topology_intent is not None:
            raise CompileRequestV4MigrationError(
                "the v3 request already carries an explicit graph; supplying "
                "a topology_intent as well would be two authorities for one "
                "fact")
        topology = ExplicitTopologyIntent(graph=explicit)
        provenance["read"] = {"source": "explicit_topology",
                              "graph_kind": explicit.kind}
    elif topology_intent is not None:
        # A caller-supplied intent resolves a family v3 could not express.
        # It must not CONTRADICT what v3 did express.
        if family is not None and not _intent_agrees_with_legacy(
                topology_intent, family):
            raise CompileRequestV4MigrationError(
                f"supplied topology intent kind {topology_intent.kind!r} "
                f"contradicts the v3 topology_family {family.value!r}")
        topology = topology_intent
        provenance["read"] = {"source": "supplied_topology_intent",
                              "intent_kind": topology_intent.kind}
    else:
        endpoint_count = request.total_nodes
        concentration = noc.concentration
        try:
            if family in (None, TopologyFamily.MESH):
                conc = concentration or 1
                if noc.radix is not None:
                    topology = topology_intent_from_noc_config(
                        TopologyFamily.MESH, radix=noc.radix,
                        concentration=conc)
                    provenance["radix_resolution"] = "explicit"
                else:
                    k = _frozen_v3_radix(endpoint_count, conc)
                    topology = topology_intent_from_noc_config(
                        TopologyFamily.MESH, radix=k, concentration=conc)
                    provenance["radix_resolution"] = (
                        "frozen_v3_autosize"
                        f"(endpoints={endpoint_count},"
                        f"concentration={conc})->side_length={k}")
            elif family is TopologyFamily.CONCENTRATED_MESH:
                conc = concentration \
                    or topology_intent_from_noc_config(
                        family, radix=noc.radix,
                        concentration=None).concentration
                k = noc.radix if noc.radix is not None else \
                    _frozen_v3_radix(endpoint_count, conc)
                topology = topology_intent_from_noc_config(
                    family, radix=k, concentration=conc)
                provenance["radix_resolution"] = (
                    "explicit" if noc.radix is not None
                    else f"frozen_v3_autosize->side_length={k}")
                if concentration is None:
                    provenance["concentration_resolution"] = (
                        "frozen_v3_default_4")
            elif family is TopologyFamily.TORUS:
                conc = concentration or 1
                k = noc.radix if noc.radix is not None else \
                    _frozen_v3_radix(endpoint_count, conc)
                topology = topology_intent_from_noc_config(
                    family, radix=k, concentration=conc)
                provenance["radix_resolution"] = (
                    "explicit" if noc.radix is not None
                    else f"frozen_v3_autosize->side_length={k}")
            else:
                raise CompileRequestV4MigrationError(
                    f"the v3 topology_family {family.value!r} does not "
                    "determine a physical v4 design: its legacy spelling "
                    "carries no mode/structure. Supply `topology_intent` "
                    "explicitly. Migration REFUSES rather than defaulting to "
                    "the backend's internal fallback.")
        except TopologyIntentError as e:
            raise CompileRequestV4MigrationError(str(e)) from e
        provenance["read"] = {"source": "noc_config.topology_family",
                              "topology_family": family and family.value,
                              "radix": noc.radix,
                              "concentration": concentration}

    provenance["intent_kind"] = topology.kind
    provenance["intent_id"] = topology.intent_id()

    return CompileRequestV4(
        workload=request.workload,
        requirements=request.requirements,
        agents=request.agents,
        dependencies=request.dependencies,
        topology=topology,
        noc_controls=noc_controls_from_noc_config(noc),
        address_map=request.address_map,
        physical=request.physical,
        synthesis_provenance=request.synthesis_provenance,
        migration_provenance=provenance,
    )


def _intent_agrees_with_legacy(intent: TopologyIntent,
                               family: TopologyFamily) -> bool:
    """A supplied intent may resolve a family v3 could not express, but it may
    not CONTRADICT a family v3 DID express."""
    from veritx_dse.model.topology_intent import (
        ConcentratedMeshIntent, MeshIntent, TorusIntent,
    )
    if family is TopologyFamily.MESH:
        return isinstance(intent, MeshIntent)
    if family is TopologyFamily.CONCENTRATED_MESH:
        return isinstance(intent, ConcentratedMeshIntent)
    if family is TopologyFamily.TORUS:
        return isinstance(intent, TorusIntent)
    if family is TopologyFamily.CUSTOM:
        return isinstance(intent, ExplicitTopologyIntent)
    # GEC / FAT_TREE: the legacy spelling carried no structure, so any intent
    # of that family resolves it.
    return intent.kind in ("gec", "fattree")


def migrate_v2_to_v4(
        request: Any, *, collective_specs: Any,
        source_ref: Any = None,
        topology_intent: TopologyIntent | None = None,
) -> CompileRequestV4:
    """v2 -> v4, COMPOSED: the existing v2 -> v3 workload migration followed
    by v3 -> v4. No migration logic is duplicated here, so the two steps can
    never disagree about what a v2 document meant.

    Every explicit supplemental fact demanded by either step must be
    supplied; nothing is defaulted. v2 cannot express a topology shape at
    all, so in practice `topology_intent` is required for anything but the
    legacy implicit mesh.
    """
    from veritx_dse.model.compile_model import migrate_v2_to_v3
    v3 = migrate_v2_to_v3(request, collective_specs=collective_specs,
                          source_ref=source_ref)
    return migrate_v3_to_v4(v3, topology_intent=topology_intent)


__all__ = [
    "CompileRequestV4", "CompileRequestV4SchemaError",
    "CompileRequestV4MigrationError",
    "COMPILE_REQUEST_SCHEMA_VERSION_V4", "COMPILER_SEMANTICS_VERSION_V4",
    "migrate_v3_to_v4", "migrate_v2_to_v4",
]
