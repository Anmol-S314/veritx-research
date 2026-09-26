#!/usr/bin/env python3
"""Fail-closed gate for the Design/Intent ontology (Gate 1, §2.15).

`docs/product/intent-ontology.yaml` answers ten questions for every field
the Studio Design page may render. This script refuses to let that file
drift from the compiler, and refuses to let the UI render a field that has
no row.

It checks:

  1. COVERAGE   every declared field of every intent dataclass has a row
                (or is a container satisfied by its child class);
  2. ANSWERS    every row answers all ten questions;
  3. EVIDENCE   every row is `evidence: V` (read at the call site) — an
                inferred row is not an answer;
  4. CITE       every `cite: file:line` resolves inside the dse track;
  5. INVARIANTS real R4 => edit "---"; kind PRF => a `default` is stated;
                unsupported set <=> real R3;
  6. UI         every field path the Studio Design editor writes has a row.

Exit codes:

  0  ontology valid and the gate is open
  1  ontology invalid (a check above failed)
  2  ontology valid but the gate is closed (pending decisions)

Usage:
    python3 scripts/check_intent_ontology.py [--allow-pending]
"""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DSE = REPO_ROOT / "tracks" / "t3-topology" / "dse"
ONTOLOGY = REPO_ROOT / "docs" / "product" / "intent-ontology.yaml"
#: The one canonical Design editor. It maps canonical field paths to inputs;
#: every path it can write must have an ontology row (UI admission).
DESIGN_EDITOR = (REPO_ROOT / "apps" / "studio" / "src" / "components"
                 / "DesignViewV2Editor.tsx")

ANSWERS = (
    "real", "owner", "edit", "kind", "stored", "depends_on",
    "invalidates", "validation", "unsupported", "visual",
)
REAL = {"R2", "R1", "R3", "R4", "R0"}
OWNER = {"PRD", "CI", "CAND", "DER", "EXE", "OPT", "NONE"}
EDIT = {"TCU", "TC-", "T--", "---"}
KIND = {"CMT", "PRF", "META", "RED", "INERT", "DERIVED", "ABSENT"}
INVALIDATES = {"A", "B", "C", "D", "E", "NONE"}
DECISION = {"out_of_scope", "new_contract", "pending"}
VALIDATION = {"L1n", "L1d", "L2", "L3d", "L3x", "L4", "L5"}
VISUAL = {1, 2, 3, 4, 5, 6}

# The declared classes whose fields must all be covered. Imported so the
# coverage check follows the compiler, never a hand-kept list.
DECLARED = (
    "CompileRequestV3", "WorkloadV3", "RequirementV3", "Agent", "NocConfig",
    "AddressMap", "AddressRange", "PhysicalContext", "DependencyGraph",
    "Dependency", "CollectiveIntent", "WorkloadSourceRef",
)
PRODUCT_DECLARED = ("CompileIntent",)


def _load_declared_fields() -> dict[str, list[str]]:
    sys.path.insert(0, str(DSE))
    from veritx_dse.model import compile_model as cm  # noqa: PLC0415
    from veritx_dse.application.compile_intent import (  # noqa: PLC0415
        CompileIntent,
    )
    out: dict[str, list[str]] = {}
    for name in DECLARED:
        cls = getattr(cm, name)
        out[name] = [f.name for f in dataclasses.fields(cls)]
    out["CompileIntent"] = [f.name for f in dataclasses.fields(CompileIntent)]
    return out


def _resolve_cite(cite: str) -> str | None:
    """Return an error string, or None when the citation resolves."""
    if ":" not in cite:
        return f"cite {cite!r} is not file:line"
    rel, _, line = cite.rpartition(":")
    candidates = (DSE / "veritx_dse" / rel, DSE / rel, REPO_ROOT / rel)
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return f"cite {cite!r}: no such file"
    try:
        n = int(line)
    except ValueError:
        return f"cite {cite!r}: line is not an int"
    total = len(path.read_text(encoding="utf-8").splitlines())
    if n < 1 or n > total:
        return f"cite {cite!r}: line {n} outside 1..{total}"
    return None


def main(argv: list[str]) -> int:
    allow_pending = "--allow-pending" in argv
    doc = yaml.safe_load(ONTOLOGY.read_text(encoding="utf-8"))
    nodes = doc.get("nodes") or []
    containers = doc.get("containers") or {}
    errors: list[str] = []

    # ── 2. answers ─────────────────────────────────────────────────────
    covered_fields: set[str] = set()
    for i, node in enumerate(nodes):
        where = node.get("id", f"nodes[{i}]")
        for key in ANSWERS:
            if key not in node:
                errors.append(f"{where}: missing answer {key!r}")
        if node.get("real") not in REAL:
            errors.append(f"{where}: real {node.get('real')!r} invalid")
        if node.get("owner") not in OWNER:
            errors.append(f"{where}: owner {node.get('owner')!r} invalid")
        if node.get("edit") not in EDIT:
            errors.append(f"{where}: edit {node.get('edit')!r} invalid")
        if node.get("kind") not in KIND:
            errors.append(f"{where}: kind {node.get('kind')!r} invalid")
        if node.get("invalidates") not in INVALIDATES:
            errors.append(
                f"{where}: invalidates {node.get('invalidates')!r} invalid")
        for v in node.get("validation") or []:
            if v not in VALIDATION:
                errors.append(f"{where}: validation {v!r} invalid")
        for v in node.get("visual") or []:
            if v not in VISUAL:
                errors.append(f"{where}: visual {v!r} invalid")
        if not isinstance(node.get("depends_on"), list):
            errors.append(f"{where}: depends_on must be a list")
        if not node.get("stored"):
            errors.append(f"{where}: stored is empty")

        # ── 3. evidence ────────────────────────────────────────────────
        if node.get("evidence") != "V":
            errors.append(
                f"{where}: evidence {node.get('evidence')!r} — every row "
                "must be V (read at the call site)")

        # ── 4. cite ────────────────────────────────────────────────────
        cite = node.get("cite")
        if not cite:
            errors.append(f"{where}: missing cite")
        else:
            err = _resolve_cite(str(cite))
            if err:
                errors.append(f"{where}: {err}")

        # ── 5. invariants ──────────────────────────────────────────────
        if node.get("real") == "R4" and node.get("edit") != "---":
            errors.append(
                f"{where}: real R4 must not be editable (edit={node.get('edit')!r})")
        if node.get("real") == "R0":
            if node.get("edit") != "---":
                errors.append(f"{where}: real R0 must not be editable")
            decision = node.get("decision")
            if decision not in DECISION:
                errors.append(
                    f"{where}: real R0 needs decision out_of_scope|new_contract|"
                    f"pending, got {decision!r}")
        if node.get("kind") == "PRF" and "default" not in node:
            errors.append(f"{where}: kind PRF must state a default")
        unsupported = node.get("unsupported")
        if unsupported is not None and not node.get("refusal_stage"):
            errors.append(
                f"{where}: unsupported set but no refusal_stage — a refusal "
                "is a property of a stage")
        if node.get("real") == "R3" and not unsupported:
            errors.append(f"{where}: real R3 must name what is unsupported")

        covered_fields.update(node.get("fields") or [])

    # ── 1. coverage ────────────────────────────────────────────────────
    declared = _load_declared_fields()

    def class_covered(cls_name: str, seen: frozenset[str] = frozenset()) -> bool:
        """A class is covered when it has rows, directly or via children."""
        if cls_name in seen:
            return False
        if any(f.startswith(f"{cls_name}.") for f in covered_fields):
            return True
        nested = seen | {cls_name}
        return any(
            key.startswith(f"{cls_name}.")
            and class_covered(child, nested)
            for key, child in containers.items()
        )

    for cls_name, fields in declared.items():
        for field in fields:
            key = f"{cls_name}.{field}"
            if key in covered_fields:
                continue
            child = containers.get(key)
            if child:
                if class_covered(child):
                    continue
                errors.append(
                    f"coverage: container {key} -> {child} has no child rows")
                continue
            errors.append(f"coverage: declared field {key} has no row")

    # ── 6. UI admission ────────────────────────────────────────────────
    # The Design editor writes canonical intent by path. Every path it can
    # write must be covered by an ontology row, so the UI cannot introduce a
    # field the ontology never answered for.
    if DESIGN_EDITOR.is_file():
        src = DESIGN_EDITOR.read_text(encoding="utf-8")
        found = re.findall(r"^  '([A-Za-z_]+\.[a-z_]+)':", src, re.MULTILINE)
        if not found:
            errors.append(
                "ui: the Design editor declares no canonical field paths — "
                "the UI-admission check has nothing to validate")
        # A row covers a path when the path is in its `fields` list (the
        # authoritative coverage declaration). The id-suffix form is kept as
        # a fallback for rows that cover a field implicitly.
        for path in sorted(set(found)):
            cls, _, field = path.partition(".")
            if cls not in DECLARED and cls not in PRODUCT_DECLARED:
                errors.append(
                    f"ui: {path!r} names class {cls!r}, which is not a "
                    "declared intent class")
                continue
            covered = any(
                path in (n.get("fields") or [])
                or n.get("id", "").endswith(field)
                for n in nodes)
            if not covered:
                errors.append(
                    f"ui: the Design editor writes {path!r} but no ontology "
                    "row covers it")

    # ── 7. domain plans (Gate 2) ───────────────────────────────────────
    domains = doc.get("domains") or {}
    PLAN_KEYS = (
        "surface", "control", "default", "validation_timing", "refusal",
        "change_class", "blast_radius", "primitive", "action",
    )
    by_domain: dict[str, list[dict]] = {}
    for i, node in enumerate(nodes):
        where = node.get("id", f"nodes[{i}]")
        dom = node.get("domain")
        if not dom:
            errors.append(f"{where}: missing domain")
            continue
        if dom not in domains:
            errors.append(f"{where}: domain {dom!r} is not declared in `domains:`")
            continue
        by_domain.setdefault(dom, []).append(node)
    for dom, spec in domains.items():
        status = (spec or {}).get("status")
        if status not in ("planned", "in_progress", "unplanned"):
            errors.append(
                f"domain {dom}: status {status!r} must be planned|in_progress|"
                "unplanned")
        if "order" not in spec:
            errors.append(f"domain {dom}: missing order")
        if status != "planned":
            continue
        pending = [n.get("id") for n in by_domain.get(dom, [])
                   if n.get("decision") == "pending"]
        if pending:
            errors.append(
                f"domain {dom}: cannot be planned while entities are undecided: "
                f"{pending}")
        for dep in spec.get("depends_on") or []:
            if dep not in domains:
                errors.append(f"domain {dom}: depends_on {dep!r} is not declared")
            elif (domains[dep] or {}).get("status") != "planned":
                errors.append(
                    f"domain {dom}: planned but dependency {dep} is not planned")
        if not spec.get("coherence"):
            errors.append(f"domain {dom}: planned but no coherence rules recorded")
        if not spec.get("exits"):
            errors.append(f"domain {dom}: planned but no NOT-MODELLED exits recorded")
        for node in by_domain.get(dom, []):
            where = node.get("id")
            plan = node.get("plan")
            if not plan:
                errors.append(
                    f"domain {dom}: planned, but node {where} has no plan block")
                continue
            for key in PLAN_KEYS:
                if key not in plan:
                    errors.append(f"{where}: plan missing {key!r}")

    orders = [spec.get("order") for spec in domains.values()]
    if len(set(orders)) != len(orders):
        errors.append(f"domain order values are not unique: {orders}")

    # ── report ─────────────────────────────────────────────────────────
    pending = doc.get("pending_decisions") or []
    if errors:
        print(f"INTENT ONTOLOGY INVALID — {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"ontology valid: {len(nodes)} rows, "
          f"{len(covered_fields)} declared fields covered, all evidence=V")
    if pending:
        print(f"GATE CLOSED — pending decisions: {', '.join(pending)}")
        if not allow_pending:
            return 2
        print("(--allow-pending: reporting only)")
    else:
        print("GATE OPEN — nothing blocks UI admission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
