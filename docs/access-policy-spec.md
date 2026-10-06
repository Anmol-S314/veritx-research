# Access-policy model — design spec (NOT IMPLEMENTED)

Status: **design only**. There is no policy artifact, no permission
evaluation, and no SystemVerilog firewall generation in the tree
(`access.firewall` is `NOT_IMPLEMENTED` in the capability registry; the
Loom access view shows permission as NO ARTIFACT). This document is the
spec the implementation must satisfy — it creates no capability by
existing.

## Why this exists

The Loom access view answers five separate questions (physical
reachability, address reachability, permission, route, measured traffic)
because merging them asserts permissions nobody evaluated. This spec
defines the sixth artifact — the permission policy — so that when it is
built, the I–T permission matrix and any firewall collateral derive from
one source instead of being hand-written twice.

## Canonical model

All types frozen dataclasses with content identity (`policy_id` over the
canonical JSON). Schema version 1. Unknown fields refuse.

### AddressRegion

```text
AddressRegion {
  region_id: str            # stable handle, unique within the artifact
  base: int                 # >= 0
  size: int                 # > 0; [base, base+size) must not overflow
  target_agent: AgentInstanceId   # (group_index, instance_index, kind)
}
```

Regions address the same `(name, base, size, target)` contract as the
existing `AddressRange` intent rows; a policy may subset them but never
redefine an agent's address map.

### InitiatorSet / TargetSet

Explicit, closed enumerations — no wildcards in v1:

```text
InitiatorSet { members: [AgentInstanceId, ...] }   # non-empty, deduped
TargetSet    { regions: [region_id, ...] }         # non-empty, deduped
```

A wildcard ("all initiators") is a policy hole dressed as convenience:
with default-deny, every allowed initiator is named.

### PermissionRule

```text
PermissionRule {
  rule_id: str
  initiators: InitiatorSet
  targets: TargetSet
  access: RW | RO | WO        # NONE is expressed by absence (default deny)
  priority: int               # >= 0; higher wins; ties refuse (below)
}
```

### SecurityDomain

```text
SecurityDomain {
  domain_id: str
  initiators: InitiatorSet
  regions: [region_id, ...]
}
```

Domains are administrative grouping for review and generation scoping.
They grant nothing by themselves; every access still resolves through
rules.

### PolicyArtifact

```text
PolicyArtifact {
  schema_version: 1
  regions: [AddressRegion, ...]        # region_ids unique; see overlap rule
  rules: [PermissionRule, ...]         # rule_ids unique
  domains: [SecurityDomain, ...]       # optional; must reference existing ids
  policy_id: sha256("srota-access-policy/v1" || canonical_json)
}
```

### PolicyCheckReport

The checker's output — the only thing a UI or generator may read:

```text
PolicyCheckReport {
  policy_id: str
  verdict: ACCEPT | REFUSE
  decisions: [{ initiator, region, access, via_rule }]  # full cross product
  overlaps_resolved: [{ region_pair, winner_rule }]     # every overlap named
  refusals: [str]                                       # typed reasons
}
```

## Semantics

1. **Default deny.** Any (initiator, region) pair matched by no rule
   resolves to no access. The report lists every denied pair as decided,
   not as missing data.
2. **Explicit deny wins by construction.** There is no DENY rule kind:
   to deny is to not allow. A policy cannot simultaneously allow and
   deny the same pair, so the conflict class does not exist.
3. **Overlap requires distinct priority.** Two rules covering the same
   (initiator, region) pair with equal priority refuse the whole
   artifact (`ambiguous policy is not a policy`). Distinct priorities
   resolve highest-first, and every such resolution appears in
   `overlaps_resolved`.
4. **Regions may overlap in address space** (shared windows over private
   windows are real designs); access resolves per region, and the
   report names which region granted each decision.
5. **Dangling references refuse.** A rule naming an unknown region, an
   initiator outside the declared agent census, or a domain naming
   either, refuses the artifact. Policy never floats free of the
   fabric it protects.
6. **No silent narrowing.** A generator must implement exactly the
   decided matrix; a target that cannot express a decision (e.g. a
   firewall LUT without per-region RO/WO bits) refuses generation for
   that pair rather than widening it to RW or dropping it.

## Derivation (when built)

- **I–T permission matrix** = `PolicyCheckReport.decisions` rendered as
  a table. It is never edited as a table; edits go to the rules and the
  matrix re-derives.
- **SystemVerilog firewall/config** = code generation over the same
  `PolicyArtifact` + its `PolicyCheckReport`. Generation from any other
  input is forbidden; a firewall file whose decisions differ from the
  report is a defect in the generator, detectable by re-checking.
- **Measured traffic is not permission.** A counted packet between two
  agents proves traffic flowed, not that it was allowed. The matrix and
  the trace stay separate views.

## Non-goals for v1

Dynamic/revokable policy, capability tokens, encrypted regions,
per-burst quotas, formal proof of the generated RTL against the policy
(desirable later; the check report is designed to be a proof input, not
a proof).

## Implementation seams (typed, present tense)

- Capability: `access.firewall` → NOT_IMPLEMENTED with reason (exists).
- UI: permission cells render NO ARTIFACT (exists).
- Engine: no `PolicyArtifact` type, no checker, no generator (absent —
  this spec is the design they must satisfy).
