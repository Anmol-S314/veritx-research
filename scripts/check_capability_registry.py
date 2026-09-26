#!/usr/bin/env python3
"""Fail-closed gate for the capability registry (Gate 4).

`docs/product/capability-registry.yaml` is the single authority for what
SROTA can represent, derive, verify, project, execute, qualify, evidence
and wire. Every product claim surface binds to it. This script refuses to
let it drift into a shape the product cannot honour.

It checks:

  1. HEADER     schema id, version, and a non-empty capability semantics
                version (the value claim surfaces bind to);
  2. UNIQUE     no duplicate capability id;
  3. SHAPE      every capability answers all eight stages with a value
                from the declared result vocabulary;
  4. VOCAB      `wiring`, `reason` and `owner` come from declared sets;
  5. WIRING     product-wiring and the PRODUCT_WIRED stage agree:
                  WIRED            => PRODUCT_WIRED YES
                  PRODUCT_WIRED YES => wiring in {WIRED, INSPECT_ONLY}
                  NOT_AVAILABLE / ENGINE_ONLY => PRODUCT_WIRED NO
                  WIRED            => no `reason` (a wired capability
                                      needs no excuse)
  6. TERMINAL   a FUTURE_CONTRACT or LEGACY_ONLY stage means every later
                stage is NO — a future contract is not partly available;
  7. REFS       every `conditions` reference resolves to a declared
                envelope or condition; every envelope's
                `required_conditions` resolves to a declared condition;
                and no declared condition is dead vocabulary;
  8. ENVELOPES  every envelope states profile_id, claim_scope,
                failure_meaning and required_conditions.

Deliberately NOT asserted (they do not hold in the frozen planning data,
so asserting them would be inventing semantics):

  * stage monotonicity. `DECLARABLE: NO` with `DERIVABLE: YES` is correct
    for a compiler-derived concept (ROUTE-001 routes, MAP-001 placement):
    it is real, and it is never user intent.
  * `NOT_APPLICABLE` as a stop marker. SYS-001 has EXECUTABLE
    NOT_APPLICABLE and PRODUCT_WIRED YES: there is no execution concept,
    yet the product does expose the declared inventory.
  * `claim_scope` on every row (13 rows omit it) and `reason` on every
    non-WIRED row (6 rows omit it).
  * `limiting` only on non-WIRED rows: FAB-002 is WIRED and carries the
    concentration>1 envelope limitation.

Exit codes:

  0  registry valid
  1  registry invalid

Usage:
    python3 scripts/check_capability_registry.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "docs" / "product" / "capability-registry.yaml"

SCHEMA = "srota/capability-registry/v1"

#: The eleven scientific domains (Gate 2 / Gate 4). A closed vocabulary:
#: a new owner means a new domain, which is a planning change, not a
#: registry edit.
OWNERS = frozenset({
    "SYSTEM", "WORKLOAD", "PARALLELISM", "COMMUNICATION", "PLACEMENT",
    "FABRIC", "ROUTER_RESOURCE", "MEMORY", "EVALUATION", "REQUIREMENTS",
    "DESIGN_SPACE",
})

#: Stages after which nothing may be available.
TERMINAL_STAGES = frozenset({"FUTURE_CONTRACT", "LEGACY_ONLY"})


def load(path: Path = REGISTRY) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check(doc: dict) -> list[str]:
    errors: list[str] = []

    # ── 1. header ──────────────────────────────────────────────────────
    if doc.get("schema") != SCHEMA:
        errors.append(f"schema {doc.get('schema')!r} != {SCHEMA!r}")
    if not isinstance(doc.get("version"), int):
        errors.append("version must be an integer")
    csv = doc.get("capability_semantics_version")
    if not csv or not isinstance(csv, str):
        errors.append("capability_semantics_version must be a non-empty string")

    stages = [s.get("id") for s in doc.get("stages") or []]
    if len(stages) != 8 or len(set(stages)) != 8:
        errors.append(f"expected 8 unique stages, got {stages}")
    results = set(doc.get("results") or [])
    wiring = set(doc.get("product_wiring") or [])
    reasons = set(doc.get("reasons") or [])
    envelopes = doc.get("envelopes") or {}
    conditions = doc.get("conditions") or {}
    capabilities = doc.get("capabilities") or []

    # ── 2. unique ids ──────────────────────────────────────────────────
    seen: set[str] = set()
    for cap in capabilities:
        cid = cap.get("id")
        if not cid:
            errors.append(f"capability {cap.get('name')!r} has no id")
            continue
        if cid in seen:
            errors.append(f"duplicate capability id {cid!r}")
        seen.add(cid)

    # ── 3–6. per capability ────────────────────────────────────────────
    for cap in capabilities:
        cid = cap.get("id", "<no-id>")
        for key in ("id", "name", "owner"):
            if not cap.get(key):
                errors.append(f"{cid}: missing {key!r}")
        if cap.get("owner") and cap["owner"] not in OWNERS:
            errors.append(f"{cid}: owner {cap['owner']!r} is not a declared domain")

        cap_stages = cap.get("stages") or {}
        if set(cap_stages) != set(stages):
            errors.append(f"{cid}: stages {sorted(cap_stages)} != declared stages")
            continue
        for stage, value in cap_stages.items():
            if value not in results:
                errors.append(f"{cid}: stage {stage} value {value!r} not in results")

        cap_wiring = cap.get("wiring")
        if cap_wiring not in wiring:
            errors.append(f"{cid}: wiring {cap_wiring!r} not in product_wiring")
        reason = cap.get("reason")
        if reason is not None and reason not in reasons:
            errors.append(f"{cid}: reason {reason!r} not in reasons")

        product_wired = cap_stages.get("PRODUCT_WIRED")
        if cap_wiring == "WIRED":
            if product_wired != "YES":
                errors.append(f"{cid}: wiring WIRED but PRODUCT_WIRED {product_wired!r}")
            if reason is not None:
                errors.append(f"{cid}: wiring WIRED must not carry a reason")
        if product_wired == "YES" and cap_wiring not in ("WIRED", "INSPECT_ONLY"):
            errors.append(
                f"{cid}: PRODUCT_WIRED YES requires wiring WIRED or "
                f"INSPECT_ONLY, got {cap_wiring!r}")
        if cap_wiring in ("NOT_AVAILABLE", "ENGINE_ONLY") and product_wired != "NO":
            errors.append(
                f"{cid}: wiring {cap_wiring} must have PRODUCT_WIRED NO, "
                f"got {product_wired!r}")

        for i, stage in enumerate(stages):
            if cap_stages.get(stage) in TERMINAL_STAGES:
                for later in stages[i + 1:]:
                    if cap_stages.get(later) != "NO":
                        errors.append(
                            f"{cid}: {stage} is {cap_stages[stage]} but later "
                            f"stage {later} is {cap_stages[later]!r}")

        # ── 7. references ──────────────────────────────────────────────
        for ref in cap.get("conditions") or []:
            if ref not in envelopes and ref not in conditions:
                errors.append(f"{cid}: condition ref {ref!r} is not declared")

    # ── 7/8. envelopes and conditions ──────────────────────────────────
    for name, env in envelopes.items():
        for key in ("profile_id", "claim_scope", "failure_meaning",
                    "required_conditions"):
            if not env.get(key):
                errors.append(f"envelope {name}: missing {key!r}")
        for ref in env.get("required_conditions") or []:
            if ref not in conditions:
                errors.append(f"envelope {name}: condition {ref!r} is not declared")

    referenced: set[str] = set()
    for env in envelopes.values():
        referenced.update(env.get("required_conditions") or [])
    for cap in capabilities:
        referenced.update(cap.get("conditions") or [])
    for name in conditions:
        if name not in referenced:
            errors.append(
                f"condition {name!r} is declared but referenced by no envelope "
                "or capability (dead vocabulary)")

    return errors


def main(argv: list[str]) -> int:
    doc = load()
    errors = check(doc)
    if errors:
        print(f"CAPABILITY REGISTRY INVALID — {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    caps = doc.get("capabilities") or []
    stages = doc.get("stages") or []
    print(
        f"capability registry valid: {len(caps)} capabilities, "
        f"{len(stages)} stages, {len(doc.get('envelopes') or {})} envelopes, "
        f"{len(doc.get('conditions') or {})} conditions, "
        f"capability_semantics_version={doc['capability_semantics_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
