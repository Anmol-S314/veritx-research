"""veritx_dse.application.revision_diff — stable revision-diff projection.

Compares two FROZEN CompileResultView payloads field-by-field and reports
what changed between them. This is a presentation projection, not science:
it never recompiles, never re-derives a route, never re-runs the CDG
analysis. Every row names frozen values from payloads materialized at
certification time, so the diff cannot drift from the proofs it describes.

Three sections, in product order:

    DESIGN CHANGES      declared intent (what the user asked for)
    DERIVED CHANGES     compiler-derived structure (what was built)
    CAPABILITY CHANGES  executability / qualification (what it can do)

A missing predecessor is not an error: the first revision of a project has
nothing to diff against, and the view says so explicitly.
"""
from __future__ import annotations

from typing import Any

CONTRACT_VERSION = 1


def _h(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.startswith("sha256:") else f"sha256:{text}"


def _row(field: str, before: Any, after: Any) -> dict[str, Any] | None:
    """One diff row, or None when the field is identical.

    Lists compare by value; dicts compare by value. ``None`` vs a value is
    a change (added/removed), never silently dropped.
    """
    if before == after:
        return None
    if isinstance(before, list) and isinstance(after, list):
        kind = "changed"
    elif before is None:
        kind = "added"
    elif after is None:
        kind = "removed"
    else:
        kind = "changed"
    return {"field": field, "before": before, "after": after, "kind": kind}


def _declared_diff(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """DESIGN CHANGES — declared intent fields from the frozen summary."""
    da = ((a.get("groups") or {}).get("summary") or {}).get("declared") or {}
    db = ((b.get("groups") or {}).get("summary") or {}).get("declared") or {}
    rows: list[dict[str, Any]] = []
    for field in ("topology_family", "side_length", "concentration",
                  "link_width", "arbitration", "requirements"):
        row = _row(field, da.get(field), db.get(field))
        if row is not None:
            rows.append(row)
    pa = da.get("parallelism") or {}
    pb = db.get("parallelism") or {}
    for dim in ("tp", "pp", "ep", "dp"):
        row = _row(f"parallelism.{dim}", pa.get(dim), pb.get(dim))
        if row is not None:
            rows.append(row)
    aa = {e.get("kind"): e.get("count")
          for e in (da.get("agents") or []) if isinstance(e, dict)}
    ab = {e.get("kind"): e.get("count")
          for e in (db.get("agents") or []) if isinstance(e, dict)}
    for kind in sorted(set(aa) | set(ab)):
        row = _row(f"agents.{kind}", aa.get(kind), ab.get(kind))
        if row is not None:
            rows.append(row)
    return rows


def _derived_diff(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """DERIVED CHANGES — compiler-derived structure from frozen payloads."""
    sa = ((a.get("groups") or {}).get("summary") or {}).get("derived") or {}
    sb = ((b.get("groups") or {}).get("summary") or {}).get("derived") or {}
    rows: list[dict[str, Any]] = []
    for field in ("routers", "channels", "seats", "endpoints", "vc_count"):
        row = _row(field, sa.get(field), sb.get(field))
        if row is not None:
            rows.append(row)
    row = _row("routing_classes", sa.get("routing_classes"),
               sb.get("routing_classes"))
    if row is not None:
        rows.append(row)
    # Identity rows: a changed hash IS the derived-identity change. The
    # mapping identity is the rank→endpoint row set; comparing the full row
    # list would ship megabytes, so the row count plus the fabric hash
    # carries the signal and the inspector owns the detail.
    ma = ((a.get("groups") or {}).get("mapping") or {})
    mb = ((b.get("groups") or {}).get("mapping") or {})
    row = _row("mapping.rank_count", ma.get("rank_count"), mb.get("rank_count"))
    if row is not None:
        rows.append(row)
    for field, key in (("design_hash", "design_hash"),
                       ("fabric_identity", "topology_hash")):
        row = _row(field, a.get(key), b.get(key))
        if row is not None:
            rows.append(row)
    return rows


def _capability_diff(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """CAPABILITY CHANGES — executability / qualification deltas.

    Compares the frozen ``capability_consequences`` (registry authority,
    stable across reads) and the certificate overall. Preflight readiness
    is deliberately EXCLUDED: it depends on the live backend binary in
    this environment, so diffing it would report environment drift as a
    design change.
    """
    rows: list[dict[str, Any]] = []
    oa = ((a.get("certificate") or {}).get("overall")
          if isinstance(a.get("certificate"), dict) else None)
    ob = ((b.get("certificate") or {}).get("overall")
          if isinstance(b.get("certificate"), dict) else None)
    row = _row("certificate_overall", oa, ob)
    if row is not None:
        rows.append(row)
    ca = {c.get("capability_id"): c for c in
          (a.get("capability_consequences") or []) if isinstance(c, dict)}
    cb = {c.get("capability_id"): c for c in
          (b.get("capability_consequences") or []) if isinstance(c, dict)}
    for cap in sorted(set(ca) | set(cb)):
        xa, xb = ca.get(cap), cb.get(cap)
        if xa == xb:
            continue
        if xa is None:
            rows.append({"field": f"capability.{cap}", "before": None,
                         "after": (xb or {}).get("choice"),
                         "kind": "added",
                         "detail": (xb or {}).get("reason")})
        elif xb is None:
            rows.append({"field": f"capability.{cap}",
                         "before": xa.get("choice"), "after": None,
                         "kind": "removed",
                         "detail": xa.get("reason")})
        else:
            rows.append({"field": f"capability.{cap}",
                         "before": xa.get("choice"), "after": xb.get("choice"),
                         "kind": "changed",
                         "detail": xb.get("reason") or xa.get("reason")})
    return rows


def build_revision_diff(*, revision_id: str, against_revision_id: str | None,
                        revision_payload: dict[str, Any],
                        against_payload: dict[str, Any] | None,
                        revision_meta: dict[str, Any],
                        against_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Assemble the RevisionDiffView from two frozen compile results."""
    if against_payload is None or against_meta is None:
        return {
            "contract_version": CONTRACT_VERSION,
            "revision_id": revision_id,
            "display_name": revision_meta.get("display_name"),
            "against_revision_id": None,
            "against_display_name": None,
            "has_basis": False,
            "reason": ("this is the first compiled revision of its project; "
                       "there is no predecessor to compare against"),
            "design_changes": [],
            "derived_changes": [],
            "capability_changes": [],
        }
    design = _declared_diff(against_payload, revision_payload)
    derived = _derived_diff(against_payload, revision_payload)
    capability = _capability_diff(against_payload, revision_payload)
    return {
        "contract_version": CONTRACT_VERSION,
        "revision_id": revision_id,
        "display_name": revision_meta.get("display_name"),
        "against_revision_id": against_revision_id,
        "against_display_name": (against_meta or {}).get("display_name"),
        "has_basis": True,
        "reason": None,
        "design_changes": design,
        "derived_changes": derived,
        "capability_changes": capability,
    }


__all__ = ["CONTRACT_VERSION", "build_revision_diff"]
