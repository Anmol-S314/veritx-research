"""veritx_dse.application.design_view_v2 — DesignViewV2 (Gate 5 D1 / Gate 6 /
Gate 7 §51.1).

One projection serves authoring and Review. Review is
``presentation="review"`` on the same object — there is no
``DesignReviewView`` (Gate 7 §2).

The backend owns (Gate 7 §51):

    canonical field values · readiness · validation · capability
    consequences · scientific diff · snapshot identity · grouping semantics

The frontend owns rendering and interaction. It never reconstructs
canonical semantics, never infers blocking from message text, never
recomputes readiness, and never maintains its own field classification —
sections, exposure classes, labels and source-of-value all come from
``exposure-registry.yaml`` via :mod:`veritx_dse.application.product_registry`.

Two laws shape the output:

* **Completeness** (Gate 7 §5). Review must not hide active science:

      canonical active draft fields − metadata-only fields
        = scientific fields represented by Review

  Every registry field that is not metadata-only is either represented or
  proved non-active in this draft. ``completeness`` makes that mechanically
  checkable instead of a promise.

* **No later-stage claims** (Gate 7 §39/§40). Review describes the draft.
  It must never present DEADLOCK_FREE, ROUTE_LEGAL, QUALIFIED, SATISFIED,
  a measured latency or any backend evidence as a current fact — none of
  those exist before compile/evaluation.

Design readiness is its own result and is NOT evaluation preflight
(REV-D5): no backend, backend_profile, network_clock_hz or
expected_evidence_tier appears here.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from veritx_dse.application import product_registry as registry

CONTRACT_VERSION = 2

#: Gate 7 §51.1 — edit is authoring, review is the pre-compile boundary.
PRESENTATIONS = ("edit", "review")

#: Gate 7 §26 / Gate 6 §106 — one backend-owned result, never a boolean.
READINESS = (
    "READY",
    "INCOMPLETE",
    "INVALID",
    "PREFLIGHT_BLOCKED",
    "CAPABILITY_LIMITED_BUT_COMPILABLE",
)

#: Gate 7 §29 — a red banner is not semantic authority; the class is.
FINDING_CLASSES = (
    "BLOCKING_ERROR",
    "DOWNSTREAM_LIMITATION",
    "INFORMATION",
    "LEGACY_MIGRATION_NOTICE",
)

#: Gate 7 §52 — no naked values without a semantic class.
SEMANTIC_CLASSES = (
    "DECLARED",
    "DERIVED_PREVIEW",
    "METADATA",
    "CAPABILITY_CONSEQUENCE",
)

#: Review freshness (Gate 7 §33). Presentation-only state never makes a
#: Review stale; a canonical scientific field change always does.
FRESHNESS = ("CURRENT", "STALE")

#: Gate 7 §9 — nine sections, in order. Router Behavior is split out of
#: Fabric and Memory Addressing out of System for comprehension; Physical
#: Context is its own small section. These are the only documented
#: deviations from ontology ownership.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("system", "System"),
    ("memory_addressing", "Memory Addressing"),
    ("workload", "Workload"),
    ("parallelism", "Parallelism"),
    ("communication", "Communication"),
    ("fabric", "Fabric"),
    ("router_behavior", "Router Behavior"),
    ("physical_context", "Physical Context"),
    ("requirements", "Requirements"),
)

#: Registry owner -> Review section. A field with no owner (metadata,
#: removed-v4, legacy) is not sectioned.
OWNER_SECTION = {
    "SYSTEM": "system",
    "MEMORY": "memory_addressing",
    "WORKLOAD": "workload",
    "PARALLELISM": "parallelism",
    "COMMUNICATION": "communication",
    "FABRIC": "fabric",
    "ROUTER_RESOURCE": "router_behavior",
    "PHYSICAL": "physical_context",
    "REQUIREMENTS": "requirements",
}

#: How a registry leaf is read out of the canonical draft document.
_LEAF_PATHS: dict[str, tuple[str, ...]] = {
    "WorkloadV3.model_family": ("workload", "model_family"),
    "WorkloadV3.model_name": ("workload", "model_name"),
    "WorkloadV3.tp": ("workload", "tp"),
    "WorkloadV3.pp": ("workload", "pp"),
    "WorkloadV3.ep": ("workload", "ep"),
    "WorkloadV3.dp": ("workload", "dp"),
    "WorkloadV3.serving_mode": ("workload", "serving_mode"),
    "WorkloadV3.collectives": ("workload", "collectives"),
    "WorkloadV3.source_ref": ("workload", "workload_source_ref"),
    "NocConfig.topology_family": ("noc_config", "topology_family"),
    "NocConfig.radix": ("noc_config", "radix"),
    "NocConfig.concentration": ("noc_config", "concentration"),
    "NocConfig.arbitration": ("noc_config", "arbitration"),
    "NocConfig.rcu_enabled": ("noc_config", "rcu_enabled"),
    "NocConfig.link_width": ("noc_config", "link_width"),
    "NocConfig.output_formats": ("noc_config", "output_formats"),
    "NocConfig.obfuscation_level": ("noc_config", "obfuscation_level"),
    "NocConfig.mcast_groups": ("noc_config", "mcast_groups"),
    "NocConfig.mcast_setup_cycles": ("noc_config", "mcast_setup_cycles"),
    "AddressMap.ranges": ("address_map", "ranges"),
    "PhysicalContext.default_clock_freq_mhz": ("physical", "clock_freq_mhz"),
    "PhysicalContext.default_data_width": ("physical", "data_width"),
    "PhysicalContext.num_power_domains": ("physical", "num_power_domains"),
    "PhysicalContext.process_node_nm": ("physical", "process_node_nm"),
    "CompileRequestV3.schema_version": ("schema_version",),
    "CompileRequestV3.compiler_semantics_version":
        ("compiler_semantics_version",),
}

#: Repeated groups: registry class -> (container path, candidate row-list
#: paths). A candidate list is tried in order because v2 nests dependencies
#: under ``dependencies.dependencies`` while v3 declares them directly.
_GROUPS: dict[str, tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]] = {
    "RequirementV3": (("requirements",), (("requirements",),)),
    "Agent": (("agents",), (("agents",),)),
    "Dependency": (("dependencies",),
                   (("dependencies",), ("dependencies", "dependencies"))),
    "CollectiveIntent": (("workload", "collectives"),
                         (("workload", "collectives"),)),
    "AddressRange": (("address_map", "ranges"),
                     (("address_map", "ranges"),)),
}

#: Which capability a draft choice makes material (Gate 7 §30). These come
#: from the registry; the mapping from a *choice* to the capability it
#: exercises is product grouping, and it is deliberately explicit rather
#: than inferred.
_BASE_CAPABILITIES = ("FAB-001", "FAB-002", "FAB-006", "SYS-001", "MEM-001",
                      "WORK-001", "PAR-001", "REQ-001", "ROUTE-007")


def _dig(doc: Any, path: tuple[str, ...]) -> Any:
    node = doc
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _dig_first(doc: Any, paths: tuple[tuple[str, ...], ...]) -> Any:
    """First candidate path that yields a list — v2/v3 shape tolerance."""
    for path in paths:
        value = _dig(doc, path)
        if isinstance(value, list):
            return value
    return None


def _is_metadata_only(path: str) -> bool:
    row = registry.exposure_row(path) or {}
    return row.get("class") == "METADATA" or row.get("src") == "METADATA"


def _is_hidden(path: str) -> bool:
    row = registry.exposure_row(path) or {}
    if row.get("class") in registry.HIDDEN_CLASSES:
        return True
    return row.get("behaviour") == "DO_NOT_RENDER"


def _is_container(path: str) -> bool:
    row = registry.exposure_row(path) or {}
    return row.get("class") == registry.CONTAINER_CLASS


def _section_of(path: str) -> str | None:
    row = registry.exposure_row(path) or {}
    return OWNER_SECTION.get(row.get("owner"))


def _leaf_value(doc: dict[str, Any], path: str) -> Any:
    """Read one registry leaf out of the canonical draft document.

    A repeated child yields the list of that leaf's values across rows —
    uniform, complete, and never a dumped row set (Gate 7 §10).
    """
    if path in _LEAF_PATHS:
        return _dig(doc, _LEAF_PATHS[path])
    cls, _, field = path.partition(".")
    group = _GROUPS.get(cls)
    if group is None:
        return None
    _container_path, rows_paths = group
    rows = _dig_first(doc, rows_paths)
    if not isinstance(rows, list):
        return None
    if field in ("", cls):
        return rows
    return [row.get(field) if isinstance(row, dict) else None for row in rows]


def _is_active(path: str, value: Any) -> bool:
    """Is this field carrying science in THIS draft?

    Gate 7 §5/§22: an active canonical value cannot be invisible. An
    AddressMap is active when it has ranges, even though authoring does not
    render it. A repeated child whose every row leaves the field unset
    carries nothing — ``[None]`` is not an active value.
    """
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return False
        return any(item is not None for item in value)
    if isinstance(value, dict):
        return len(value) > 0
    return True


# ── findings ───────────────────────────────────────────────────────────


def _finding(*, cls: str, owner: str, code: str, message: str,
             affected: str | None = None, blocking: bool = False,
             remediation_owners: tuple[str, ...] = ()) -> dict[str, Any]:
    if cls not in FINDING_CLASSES:
        raise ValueError(f"unknown finding class {cls!r}")
    return {
        "class": cls,
        "owner_domain": owner,
        "code": code,
        "message": message,
        "affected": affected,
        "blocking": blocking,
        "remediation_owners": list(remediation_owners),
    }


def _compilation_for(doc: dict[str, Any]):
    """Compile once; the projection reuses it everywhere.

    ``None`` when the document does not canonicalize — the callers treat
    that as "not decidable", never as "passes".
    """
    request, error = _canonicalize(doc)
    if request is None:
        return None
    from veritx_dse.application.fabric_compiler import FabricCompiler
    return FabricCompiler().compile(request)


def _lowered_traffic_classes(compilation) -> set[str]:
    """The traffic classes the canonical lowering actually produced.

    This is the authoritative multi-class signal: a fabric can be
    multi-class through its dependency graph without declaring a single
    collective (the ``mesh4`` family is exactly that case), so reading
    declared collective classes alone under-reports.
    """
    if compilation is None or compilation.status != "COMPILED":
        return set()
    try:
        pairs = compilation.bundle.vc_assignment.traffic_class_to_vcs
    except Exception:  # noqa: BLE001
        return set()
    # `traffic_class_to_vcs` is a tuple of (traffic_class, vc_ids) pairs.
    return {str(pair[0]) for pair in (pairs or ())
            if isinstance(pair, (tuple, list)) and pair}


def _capability_consequences(doc: dict[str, Any],
                             compilation=None) -> list[dict[str, Any]]:
    """Consequences materially caused by the current choices (Gate 7 §30).

    Not the 73-row matrix, and never hand-coded conditionals: each entry is
    a registry row plus the product statement of what the choice means.
    """
    chosen: list[tuple[str, str]] = []

    family = (doc.get("noc_config") or {}).get("topology_family")
    if family in ("torus", "gec", "fat_tree"):
        chosen.append((family.upper(), _torus_capability(family)))
    concentration = (doc.get("noc_config") or {}).get("concentration")
    if isinstance(concentration, int) and concentration > 1:
        chosen.append(("concentration > 1", "FAB-002"))

    classes = _lowered_traffic_classes(compilation)
    if not classes:
        collectives = (doc.get("workload") or {}).get("collectives") or []
        classes = {c.get("traffic_class") for c in collectives
                   if isinstance(c, dict) and c.get("traffic_class")}
    if len(classes) > 1:
        chosen.append((f"multiple communication classes "
                       f"({', '.join(sorted(classes))})", "COMM-006"))

    clock_domains = {a.get("clock_domain") for a in doc.get("agents") or []
                     if isinstance(a, dict)}
    if len({c for c in clock_domains if c}) > 1:
        chosen.append(("multiple clock domains", "SYS-003"))

    if _declares_moe_structure(doc):
        chosen.append(("static MoE", "WORK-002"))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label, capability_id in chosen:
        if capability_id in seen:
            continue
        seen.add(capability_id)
        consequence = registry.capability_consequence(capability_id)
        if consequence is None:
            continue
        out.append({
            "capability_id": capability_id,
            "choice": label,
            "name": consequence["name"],
            "wiring": consequence["wiring"],
            "reason": consequence["reason"],
            "limiting": consequence["limiting"],
            "claim_scope": consequence["claim_scope"],
            "stages": consequence["stages"],
            "registry_version": consequence["capability_semantics_version"],
        })
    return out


def _declares_moe_structure(doc: dict[str, Any]) -> bool:
    """Does this design actually exercise MoE structure?

    WORK-002's limitation is "no full static dispatch/combine lowering" — it
    is about expert routing, not about a model-family label. A design only
    reaches that limitation when it has expert parallelism or declares
    dispatch/combine traffic. Firing on the label alone would report a
    limitation for a single-NPU trace carrier that has no MoE structure to
    lower — a false capability claim in the opposite direction.
    """
    workload = doc.get("workload") or {}
    if workload.get("model_family") != "mixture_of_experts":
        return False
    try:
        if int(workload.get("ep") or 1) > 1:
            return True
    except (TypeError, ValueError):
        return True
    for collective in workload.get("collectives") or []:
        if not isinstance(collective, dict):
            continue
        dimension = str(collective.get("dimension") or "").upper()
        kind = str(collective.get("kind") or "").lower()
        if dimension == "EP" or kind in ("alltoall", "dispatch", "combine"):
            return True
    return False


def _torus_capability(family: str) -> str:
    """The capability row for a non-mesh topology family."""
    for row in registry.capability_rows():
        if row.get("owner") != "FABRIC":
            continue
        if family.lower() in (row.get("name") or "").lower():
            return row["id"]
    return "FAB-001"


def _downstream_findings(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-blocking consequences of an otherwise valid design (Gate 7 §28).

    Torus routing unavailability must not prevent topology compilation.
    """
    findings: list[dict[str, Any]] = []
    family = (doc.get("noc_config") or {}).get("topology_family")
    if family in ("torus", "gec", "fat_tree"):
        capability_id = _torus_capability(family)
        consequence = registry.capability_consequence(capability_id)
        scope = (consequence or {}).get("claim_scope") \
            or "routed execution is unavailable in the current pipeline"
        findings.append(_finding(
            cls="DOWNSTREAM_LIMITATION",
            owner="FABRIC",
            code="NO_BACKEND_PROJECTION",
            message=f"{family}: {scope}",
            affected="noc_config.topology_family",
            blocking=False,
            remediation_owners=("fabric",),
        ))
    return findings


def _legacy_findings(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Removed-v4 values still present in the document (Gate 7 §29).

    A legacy value is not silently dropped and is not a blocking error —
    it is a decision the user must make.
    """
    findings: list[dict[str, Any]] = []
    noc = doc.get("noc_config") or {}
    if noc.get("rcu_enabled"):
        findings.append(_finding(
            cls="LEGACY_MIGRATION_NOTICE",
            owner="ROUTER_RESOURCE",
            code="REMOVED_V4",
            message=("rcu_enabled is removed from v4: no RCU realization "
                     "exists. It does not affect this design; remove it or "
                     "accept that it is ignored."),
            affected="noc_config.rcu_enabled",
            blocking=False,
            remediation_owners=("fabric",),
        ))
    for key in ("mcast_groups", "mcast_setup_cycles"):
        if noc.get(key) is not None:
            findings.append(_finding(
                cls="LEGACY_MIGRATION_NOTICE",
                owner="COMMUNICATION",
                code="REMOVED_V4",
                message=(f"{key} is removed from v4: hardware multicast is "
                         "not modeled. Semantic multicast lowers to "
                         "unicasts."),
                affected=f"noc_config.{key}",
                blocking=False,
                remediation_owners=("communication",),
            ))
    for index, req in enumerate(doc.get("requirements") or []):
        if isinstance(req, dict) and req.get("bandwidth_floor_gbps") is not None:
            findings.append(_finding(
                cls="LEGACY_MIGRATION_NOTICE",
                owner="REQUIREMENTS",
                code="REMOVED_V4",
                message=("bandwidth_floor_gbps is removed from v4: it is not "
                         "evaluated. Latency ceilings and QoS class remain."),
                affected=f"requirements[{index}].bandwidth_floor_gbps",
                blocking=False,
                remediation_owners=("requirements",),
            ))
    return findings


def _canonicalize(doc: dict[str, Any]):
    """Canonicalize the draft document through the compiler's own reader.

    Gate 7 §7: canonicalization happens before Review. The frontend never
    reconstructs values.
    """
    from veritx_dse.model.compile_model import (
        CompileRequest, CompileRequestSchemaError, CompileRequestV3,
        CompileRequestV3SchemaError,
    )

    schema_version = doc.get("schema_version")
    try:
        if schema_version == 3:
            return CompileRequestV3.from_dict(doc), None
        if schema_version == 2:
            return CompileRequest.from_dict(doc), None
    except (CompileRequestSchemaError, CompileRequestV3SchemaError) as exc:
        return None, str(exc)
    except ValueError as exc:
        return None, str(exc)
    return None, (f"unsupported request schema_version {schema_version!r} "
                  "(expected 2 or 3)")


def _validation_findings(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Local/canonical validation findings (Gate 7 §27, class 1).

    Derived from the compiler's own reader — never a parallel validator.
    """
    request, error = _canonicalize(doc)
    if error is None:
        return []
    return [_finding(
        cls="BLOCKING_ERROR",
        owner="SYSTEM",
        code="INVALID_INTENT",
        message=error,
        affected=None,
        blocking=True,
    )]


def _preflight_findings(doc: dict[str, Any],
                        compilation=None) -> list[dict[str, Any]]:
    """Cross-domain preflight (Gate 7 §27, class 2).

    Provable before compile, using the canonical compiler as the authority
    rather than a parallel join implementation.
    """
    if compilation is None:
        return []
    if compilation.status == "COMPILED":
        return []
    cls = "PREFLIGHT_BLOCKED" if compilation.status == "INVALID" \
        else "UNSUPPORTED"
    owner = "FABRIC" if "route" in (compilation.error or "").lower() \
        else "SYSTEM"
    return [_finding(
        cls="BLOCKING_ERROR",
        owner=owner,
        code=cls,
        message=compilation.error or "the design cannot be compiled",
        affected=None,
        blocking=True,
        remediation_owners=("fabric", "system"),
    )]


def _derived_summaries(doc: dict[str, Any],
                       compilation=None) -> list[dict[str, Any]]:
    """PRE-COMPILE DERIVED SUMMARY (Gate 7 §19 / Gate 8 §42).

    Computed by the canonical compiler, never by the frontend. Absent when
    the design does not derive.
    """
    if compilation is None or compilation.status != "COMPILED":
        return []
    bundle = compilation.bundle
    topology = getattr(bundle, "topology", None)
    summary: list[dict[str, Any]] = []

    def add(identifier: str, label: str, value: Any) -> None:
        summary.append({
            "id": identifier,
            "label": label,
            "value": value,
            "kind": "PRE_COMPILE_DERIVED_SUMMARY",
            "semantic_class": "DERIVED_PREVIEW",
        })

    if topology is not None:
        routers = getattr(topology, "routers", None)
        channels = getattr(topology, "channels", None)
        if routers is not None:
            add("routers", "routers", len(routers))
        if channels is not None:
            add("channels", "directed channels", len(channels))
        seats = sum(getattr(r, "seat_capacity", 0) or 0
                    for r in (routers or ()))
        if routers:
            add("seats", "router seats", seats)
    required = sum(int(a.get("count") or 0)
                   for a in doc.get("agents") or []
                   if isinstance(a, dict))
    add("required_endpoints", "required endpoints", required)
    return summary


# ── readiness ──────────────────────────────────────────────────────────


def _readiness(findings: list[dict[str, Any]],
               consequences: list[dict[str, Any]],
               doc: dict[str, Any]) -> str:
    if any(f["blocking"] for f in findings):
        request, _ = _canonicalize(doc)
        if request is None:
            return "INVALID"
        return "PREFLIGHT_BLOCKED"
    if _incomplete(doc):
        return "INCOMPLETE"
    if consequences:
        return "CAPABILITY_LIMITED_BUT_COMPILABLE"
    return "READY"


def _incomplete(doc: dict[str, Any]) -> bool:
    """A mandatory field has no value (Gate 6 §106/§107).

    Mandatory is decided by the canonical contract, never a frontend list.
    The compiler's own reader already enforces everything it requires — a
    document that fails it is INVALID, not INCOMPLETE. What remains is the
    scalar *user decision* the schema permits to be absent: a rendered,
    non-metadata field the registry marks ``default: NONE``.

    Repeated children (requirements, agents, collectives, dependencies,
    address ranges) are excluded: their per-row required fields are
    enforced by the reader, and an empty list is a legitimate design.
    """
    for path in _mandatory_fields():
        if _leaf_value(doc, path) is None:
            return True
    return False


@lru_cache(maxsize=1)
def _mandatory_fields() -> tuple[str, ...]:
    out: list[str] = []
    for path, row in registry.exposure_fields().items():
        if row.get("default") != "NONE":
            continue
        if _is_metadata_only(path) or _is_hidden(path) or _is_container(path):
            continue
        if path.partition(".")[0] in _GROUPS:
            continue
        out.append(path)
    return tuple(sorted(out))


# ── sections and entries ───────────────────────────────────────────────


def _entry(path: str, doc: dict[str, Any]) -> dict[str, Any] | None:
    row = registry.exposure_row(path) or {}
    value = _leaf_value(doc, path)
    depth = registry.disclosure_depth(path) or "GUIDED"
    entry = {
        "field": path,
        "label": registry.product_label(path, depth) or path,
        "value": value,
        "semantic_class": "DECLARED",
        "exposure_class": row.get("class"),
        "disclosure_depth": depth,
        "source": registry.source_of_value(path),
        "active": _is_active(path, value),
        "capability_ref": row.get("capability"),
        "ownership": {
            "domain": row.get("owner"),
            "canonical_field": path,
            "scientific_name": registry.scientific_name(path),
        },
    }
    return entry


def _sections(doc: dict[str, Any], presentation: str) -> list[dict[str, Any]]:
    """Nine sections, from the registry — never a hand-kept React list."""
    fields = registry.exposure_fields()
    grouped: dict[str, list[str]] = {sid: [] for sid, _ in SECTIONS}
    for path in fields:
        if _is_metadata_only(path) or _is_container(path):
            continue
        if _is_hidden(path):
            # Authoring never shows it; Review shows an active AddressMap
            # read-only (Gate 7 §22). Everything else stays out of both.
            if not (presentation == "review"
                    and _section_of(path) == "memory_addressing"):
                continue
        section = _section_of(path)
        if section is None:
            continue
        grouped[section].append(path)

    out: list[dict[str, Any]] = []
    for section_id, title in SECTIONS:
        entries: list[dict[str, Any]] = []
        for path in sorted(grouped[section_id]):
            entry = _entry(path, doc)
            if entry is None:
                continue
            if presentation == "edit" and not _is_active(path, entry["value"]):
                # Authoring shows empty accepted intent; Review must not
                # omit active science, so only edit filters on activity.
                pass
            entries.append(entry)
        blocking = sum(1 for e in entries if e["field"] in _BLOCKING_FIELDS)
        limitation = sum(1 for e in entries if e["field"] in _LIMITED_FIELDS)
        advanced_active = sum(
            1 for e in entries
            if e["disclosure_depth"] == "EXPERT" and e["active"])
        out.append({
            "id": section_id,
            "title": title,
            "entries": entries,
            "advanced_active_count": advanced_active,
            "blocking_count": blocking,
            "limitation_count": limitation,
        })
    return out


#: Filled from findings at build time; kept as module state only to let the
#: section counters be computed in one pass.
_BLOCKING_FIELDS: set[str] = set()
_LIMITED_FIELDS: set[str] = set()


# ── completeness ───────────────────────────────────────────────────────


def _completeness(doc: dict[str, Any], sections: list[dict[str, Any]],
                  presentation: str) -> dict[str, Any]:
    """Gate 7 §5 — mechanically checkable, not a promise."""
    represented: set[str] = set()
    for section in sections:
        for entry in section["entries"]:
            represented.add(entry["field"])

    active: list[str] = []
    non_active: list[dict[str, Any]] = []
    for path in registry.exposure_fields():
        if _is_metadata_only(path) or _is_container(path):
            continue
        value = _leaf_value(doc, path)
        if _is_active(path, value):
            active.append(path)
        else:
            non_active.append({"field": path, "reason": "NO_ACTIVE_VALUE"})

    missing = sorted(set(active) - represented)
    return {
        "active_scientific_fields": sorted(active),
        "represented_fields": sorted(represented),
        "non_active_fields": sorted(non_active, key=lambda r: r["field"]),
        "unrepresented_active_fields": missing,
        "invariant_holds": not missing,
        "law": ("canonical active draft fields − metadata-only fields = "
                "scientific fields represented by Review"),
    }


# ── scientific diff ────────────────────────────────────────────────────


#: Field-level normalizers applied before a scientific comparison. A diff
#: is over *normalized* science (Gate 8 §24): field order, formatting and
#: aliases are not differences. Arbitration is the one field whose raw
#: spelling is not semantic identity, so it is normalized through the
#: domain owner before comparison.
_NORMALIZERS = {
    "NocConfig.arbitration": lambda value: _normalize_arbitration(value),
}


def _normalize_arbitration(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    from veritx_dse.model.router_behavior import (  # noqa: PLC0415
        canonical_arbitration_token,
    )
    return canonical_arbitration_token(value)


def _normalized(path: str, value: Any) -> Any:
    normalizer = _NORMALIZERS.get(path)
    return normalizer(value) if normalizer else value


def _scientific_diff(doc: dict[str, Any],
                     parent_doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Canonical scientific diff (Gate 7 §34, Gate 8 §24).

    Normalized fields only: field order, formatting and aliases are not
    differences (arbitration is canonicalized before comparison, so
    re-spelling "islip" as " iSLIP " is not a scientific change).
    """
    if parent_doc is None:
        return []
    diff: list[dict[str, Any]] = []
    for path in sorted(registry.exposure_fields()):
        if _is_metadata_only(path) or _is_container(path):
            continue
        before = _normalized(path, _leaf_value(parent_doc, path))
        after = _normalized(path, _leaf_value(doc, path))
        if before == after:
            continue
        diff.append({
            "field": path,
            "before": before,
            "after": after,
            "kind": ("added" if before is None and after is not None
                     else "removed" if before is not None and after is None
                     else "changed"),
        })
    return diff


# ── the projection ─────────────────────────────────────────────────────


def build_design_view_v2(
        draft_doc: dict[str, Any],
        *,
        project_id: str,
        presentation: str = "edit",
        draft_design_hash: str | None = None,
        parent_revision: dict[str, Any] | None = None,
        parent_doc: dict[str, Any] | None = None,
        review_snapshot_hash: str | None = None,
        expected_capability_semantics_version: str | None = None,
) -> dict[str, Any]:
    """Build the DesignViewV2 projection.

    ``presentation="review"`` is the same object in Review mode: complete,
    canonical, read-only, and free of any later-stage claim.
    """
    if presentation not in PRESENTATIONS:
        raise ValueError(f"presentation must be one of {PRESENTATIONS}, "
                         f"got {presentation!r}")

    semantics_version = registry.capability_semantics_version()
    if (expected_capability_semantics_version is not None
            and expected_capability_semantics_version != semantics_version):
        # Gate 7 §31: never generate potentially false claims.
        return _registry_mismatch_view(
            project_id=project_id, presentation=presentation,
            expected=expected_capability_semantics_version,
            actual=semantics_version)

    # Compile once. Every consumer below reads the same canonical
    # compilation, so the projection can never disagree with itself about
    # what the design derives.
    compilation = _compilation_for(draft_doc)

    findings = [
        *_validation_findings(draft_doc),
        *_preflight_findings(draft_doc, compilation),
        *_legacy_findings(draft_doc),
        *_downstream_findings(draft_doc),
    ]

    _BLOCKING_FIELDS.clear()
    _LIMITED_FIELDS.clear()
    for finding in findings:
        if not finding.get("affected"):
            continue
        if finding["blocking"]:
            _BLOCKING_FIELDS.add(finding["affected"])
        elif finding["class"] == "DOWNSTREAM_LIMITATION":
            _LIMITED_FIELDS.add(finding["affected"])

    consequences = _capability_consequences(draft_doc, compilation)
    sections = _sections(draft_doc, presentation)
    readiness = _readiness(findings, consequences, draft_doc)

    view: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "presentation": presentation,
        "draft_identity": {
            "project_id": project_id,
            "draft_design_hash": draft_design_hash,
        },
        "parent_revision_ref": (
            {"revision_id": parent_revision.get("revision_id"),
             "label": parent_revision.get("display_name")}
            if parent_revision else None),
        "readiness": readiness,
        "sections": sections,
        "derived_summaries": _derived_summaries(draft_doc, compilation),
        "validation_findings": findings,
        "capability_consequences": consequences,
        "completeness": _completeness(draft_doc, sections, presentation),
        "capability_semantics_version": semantics_version,
        "registry_versions": registry.registry_versions(),
    }

    if presentation == "review":
        view["scientific_diff"] = _scientific_diff(draft_doc, parent_doc)
        view["review_freshness"] = (
            "CURRENT"
            if review_snapshot_hash is None
            or review_snapshot_hash == draft_design_hash
            else "STALE")
        view["review_snapshot"] = {
            "reviewed_draft_design_hash": review_snapshot_hash,
            "current_draft_design_hash": draft_design_hash,
            "bound_by": ["project_id", "draft_design_hash",
                         "capability_semantics_version"],
        }
        # Gate 7 §39/§40: Review describes the draft and claims nothing that
        # does not exist before compile/evaluation.
        view["later_stage_claims"] = {
            "certificate": None,
            "qualification": None,
            "measurements": None,
            "requirement_verdicts": None,
            "note": ("these do not exist before compile/evaluation and are "
                     "never presented as current facts by Review"),
        }
    return view


def _registry_mismatch_view(*, project_id: str, presentation: str,
                            expected: str, actual: str) -> dict[str, Any]:
    """Fail safely rather than emit claims bound to a stale registry."""
    return {
        "contract_version": CONTRACT_VERSION,
        "presentation": presentation,
        "draft_identity": {"project_id": project_id,
                           "draft_design_hash": None},
        "parent_revision_ref": None,
        "readiness": "PREFLIGHT_BLOCKED",
        "sections": [],
        "derived_summaries": [],
        "validation_findings": [_finding(
            cls="BLOCKING_ERROR",
            owner="PRODUCT",
            code="CAPABILITY_REGISTRY_MISMATCH",
            message=(f"capability semantics version {expected!r} is not the "
                     f"registry version {actual!r}; claims are withheld "
                     "until the registry is refreshed"),
            affected=None,
            blocking=True,
        )],
        "capability_consequences": [],
        "completeness": {
            "active_scientific_fields": [],
            "represented_fields": [],
            "non_active_fields": [],
            "unrepresented_active_fields": [],
            "invariant_holds": False,
            "law": "withheld: registry mismatch",
        },
        "capability_semantics_version": actual,
        "registry_versions": registry.registry_versions(),
    }


__all__ = [
    "CONTRACT_VERSION",
    "FINDING_CLASSES",
    "FRESHNESS",
    "OWNER_SECTION",
    "PRESENTATIONS",
    "READINESS",
    "SECTIONS",
    "SEMANTIC_CLASSES",
    "build_design_view_v2",
]
