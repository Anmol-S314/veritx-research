# Group-name attachment binding — proposal (P1.5 follow-on, binding half)

**Status:** PROPOSAL — design only. No code, tests, fixtures, or stored artifacts
were changed to write this document. Nothing in this file has been built, run,
or pinned. Date: 2026-11-10. Owner: this repo. Effort: M.
**Ancestors:** `docs/product/INTENT-TO-PLACED-RTL-P0-P1-STATUS.md` ("### P1.5 —
stable identity (substrate landed 2026-11-10)", line 645) and
`docs/product/REMAINING-WORK.md` item 8 ("P1.5 — attachment-side stable
identity binding"). P1.5 stays **OPEN**; this document does not close it and
does not authorize reporting it closed.
**Scope:** `Agent.group_name` (v4, landed) → `AgentAttachmentArtifact` binding.
Locked families, mapping, routes, RTL, and the frontend are out of scope.

All paths are rooted at `tracks/t3-topology/dse/` unless absolute. Line numbers
are as of the 2026-11-10 tree and were read, not assumed.

---

## 0. What the substrate already landed (do not re-propose, do not weaken)

From the P1.5 status record and verified against the tree:

- v4 `Agent.group_name` exists end-to-end: field on the shared `Agent`
  dataclass (`veritx_dse/model/compile_model.py:246`), strict-keys `_AGENT_KEYS`
  (`compile_model.py:46-50`), character law `[A-Za-z0-9_-]{1,}`
  (`compile_model.py:260-266`), parse/round-trip (`compile_model.py:1181`,
  `:2499`), and both `_agent_dict` sites emit it **only when declared**
  (`compile_model.py:972-973` for `CompileRequest`, `:2233-2234` for
  `CompileRequestV3`, which v4 reuses via `CompileRequestV3._agent_dict` at
  `compile_request_v4.py:200`). Absent names keep stored hashes byte-stable.
- `CompileRequestV4.__post_init__` enforces all-or-nothing and uniqueness at
  construction: any named group forces every group to declare
  (`compile_request_v4.py:96-103`), and duplicate names refuse
  (`compile_request_v4.py:104-107`). These are construction-time
  `ValueError`s, before any compiler stage runs.
- Frontend round-trips `group_name` losslessly and the substrate evidence
  line reports "11/11 browser exact pins" (`apps/studio/prototype/src/agentMap.ts`
  BigInt authorities; `agentMapExact.test.ts` 11/11). Those pins belong to the
  P1.4/P1.5 exactness discipline and are untouched by this proposal.
- Backend `tests/test_group_name_binding.py` (7 tests) and
  `tests/test_attachment.py` (named/unnamed binding, tamper, reorder) are green
  on this tree per the status doc; this document proposes extending, not
  editing, their contract.

**Open half (this proposal):** the attachment side. Today the attachment binds
positionally — group declaration order → `(group_index, instance_index)` —
there is no `group_name → attachment` mapping table *inside the artifact
bytes*, and no stable refusal code for identity failures on the product
surface (the stage-1 finding list).

---

## 1. What exists today (evidence)

### 1.1 What the attachment artifact carries

`veritx_dse/model/attachment.py` — `AgentAttachmentArtifact` (schema v3,
`_HASH_TYPE_TAG = "srota/AgentAttachment"`, `ATTACHMENT_SCHEMA_VERSION = 3`,
`attachment.py:16-17`). Each `Endpoint` (`attachment.py:89-108`) carries:

- `endpoint_id` (contiguous from 0, enforced `attachment.py:241-243`),
- `agent`: an `AgentInstance` (see 1.4) — serialized as
  `{"group_index", "instance_index", "kind"}` (`placement.py:96-100`,
  strict keys at `attachment.py:170-171`),
- `router_id`, `port_id` (ingress seat), `interface`
  (`AgentInterfaceDescriptor`, same file),
- optional `egress_router_id`/`egress_port_id` — emitted **only** when the
  fabric ejects agents somewhere other than they inject ("Emitted ONLY …",
  `attachment.py:153-157`). This is the established precedent for a
  conditional key inside schema v3: symmetric attachments keep byte-identical
  bytes and the legacy hash.
- `group_name: str | None = None` (`attachment.py:108`) — emitted into the
  endpoint dict **only when non-None** (`attachment.py:151-152`). An unnamed
  endpoint dict carries no `group_name` key at all.

So the artifact *already* carries `group_name` per endpoint, and it is already
hash-bound. The binding gap is not "names absent from endpoints" — it is that
there is no explicit, group-indexed **names table** in the artifact, so the
declaration-order ↔ name pairing exists only implicitly (via endpoint order),
with no artifact-level check that a loaded document presents it.

### 1.2 Where the attachment artifact is emitted

`derive_attachment` (`attachment.py:431-490`) is the single derivation site;
it seats endpoints in inventory order (`attachment.py:474-484`) and copies
`group_name` from the design groups (`attachment.py:478`). Callers (findable
via `grep -rn derive_attachment`):

- `veritx_dse/compiler/canonical.py:456-458` — `_stage(CompileStage.ATTACHMENT)`
  inside `compile_deterministic_candidate` (stage enum member `ATTACHMENT = "ATTACHMENT"`,
  `canonical.py:63`),
- `veritx_dse/compiler/orchestration.py:103-106` — `_v3_stages` (the v3/v4
  compile path, ATTACHMENT before ROUTING_REALIZATION before VC), and
  `:229-233` — `build_resolved_bundle_v3`,
- `veritx_dse/application/design_view_v2.py:213-231` — the draft/preview
  derivation,
- preview/service path `veritx_dse/product/service.py:664` (preview endpoints).

`attachment_hash()` emission (`attachment.py:293-296`):

```python
from veritx_dse.core.artifact import content_id
return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}", self.canonical_dict())
```

and `to_dict()` (`attachment.py:298-301`) copies `canonical_dict()` and adds
`attachment_hash`. `content_id` (`core/artifact.py:68-76`) is domain-separated
SHA-256 over the canonical bytes; `canonical_json` (`core/spec.py:194-197`)
is `json.dumps(d, sort_keys=True, separators=(",", ":"))` — **keys sorted,
array order preserved**. `test_attachment.py` pins the legacy pin: unnamed
attachments hash exactly as `content_id("srota/AgentAttachment/v3", legacy)`
(`tests/test_attachment.py:88-99`), and compiler-path parity rides on it
(`tests/test_compiler_path_parity.py:47`).

### 1.3 `grep attachment` in `compile_model.py` — honest result

There is **no match** for `attachment` in
`veritx_dse/model/compile_model.py` (case-insensitive, this tree). The v3/v4
request files carry no attachment concepts; the attachment artifact lives
entirely in `attachment.py` and is derived *after* the request is frozen. The
request↔attachment contract exists in exactly two places: the request declares
groups in order (`compile_request_v4.py:200`), and `derive_attachment` expands
that order into endpoints. Anything else — seats, ports, interfaces, names —
is attachment-side.

### 1.4 The `AgentInstance` boundary

`veritx_dse/model/placement.py:76-101` — `AgentInstance` is the **only**
identity the attachment binds to hardware:

```python
group_index: int
instance_index: int
kind: AgentKind
```

plus `instance_id` = `f"agent_group[{group_index}]/{kind}[{instance_index}]"`.
The inventory expands groups in **declaration order**, instances 0..count-1 per
group (`placement.py:206-211`), so endpoint order ≡ declaration order of
groups. No `group_name` crosses this boundary — by construction, an
`AgentInstance` cannot carry one. This is the right boundary to keep; the
binding must not blur it.

### 1.5 What the compiler does with `group_name` today — and what it never does

Today `group_name` feeds exactly four consumers, all of them
compare-for-equality, none of them a binding artifact:

1. `design_hash` via `_agent_dict` when declared (`compile_model.py:972`,
   `:2233`; v4 at `compile_request_v4.py:200`, envelope at
   `compile_request_v4.py:247-257`),
2. Endpoint bytes/hash (present-or-absent key, `attachment.py:108,151-152`),
3. `AgentAttachmentArtifact.__post_init__` — internally consistent names or
   refuse ("inconsistent group_name within Agent group" / "group_name must be
   unique and declared for every Agent group", `attachment.py:246-263`),
4. `validate_against` — endpoint name must equal the group's name, else
   "rebuild attachment after identity changes" (`attachment.py:376-380`),
   reached in the real compile path only through the certificate obligation
   `ATTACHMENT_COMPLETE` (`veritx_dse/verification/certificate.py:111-121`).

**No downstream consumer keys off the name:** resolved routes, routing
realization, VC assignment, fabric artifact, packet format, address decode,
meshdor identity-prefix acceptance, native ring/qtree terminal laws, ASTRA
class-id selection — all index by seat, endpoint id, kind, or class ids;
none reads `group_name`. The positional binding
(`group declaration order → (group_index, instance_index)`) is load-bearing
for correctness today, and the names are decorative unless compares fire.

### 1.6 The gap, stated precisely

1. **No group-indexed table in the bytes.** A stored artifact lets you check
   "does endpoint *i* carry the name of group *j*?" only by walking endpoints
   and re-deriving group spans; there is no explicit, order-bound
   `group_names[group_index]` to verify, to diff, or to hash-check against.
2. **No stable refusal codes on the product surface.** Identity failures
   surface as bare `ValueError` (constructor) or `AttachmentError`
   (artifact) — never as a stage-1 finding. The stage-1 finding list
   (`fabric_compiler.py:_run_stage1`, collected at `:252-253`, extended by
   `_record` at `:255-271`, and surfaced to product via `Compilation.findings`
   → `product/service.py:1954-1969` `stage1_findings`,
   `application/compile_result_view.py:756-808`, and
   `product/rtl_export.py:453`) has no `ATTACHMENT_GROUP_NAME_*` code. The one
   existing non-verdict finding, `AGENT_PROTOCOL_UNOWNED: …`
   (`fabric_compiler.py:449-458`), is the format precedent.
3. **The ATTACHMENT-stage refusal path does not thread stage-1 findings.** If
   `derive_attachment` throws post-stage-1, `fabric_compiler.compile` reaches
   the `if bundle is None:` branch (`fabric_compiler.py:536-551`), which
   returns `Compilation(status="INVALID", stopped_at_stage=…)` **without**
   `stage1_verdicts=` or `findings=`. Identity failures on that path are
   invisible in the stage-1 finding list no matter what the artifact says.

---

## 2. The binding (proposed)

### 2.1 Endpoint records — contract restated, not changed

Each attachment `Endpoint` carries `group_name` when and only when its parent
Agent group declared one; otherwise the key is absent from the endpoint dict
and `None` on the object (existing behavior, `attachment.py:108,151-152`).
This restatement is deliberately a no-op: endpoint bytes for unnamed designs
stay bit-identical, which is what keeps every stored unnamed hash stable.

### 2.2 The `group_names` table — new, conditional, hash-bound

`AgentAttachmentArtifact.canonical_dict()` (`attachment.py:285-291`) emits a
`group_names` list **alongside the endpoints table** (the endpoints table is
the per-endpoint kind list; `group_names` is the per-group name table) **iff
every group represented in the artifact declares a name**. The rule is
all-or-nothing, mirroring the request-side law
(`compile_request_v4.py:96-107`) and the artifact-internal law
(`attachment.py:261-263`):

- **Named mode** — every group declares. `canonical_dict()` becomes
  `{"type", "schema_version", "topology_hash", "endpoints", "group_names"}`
  with `group_names[group_index] = design.agents[group_index].group_name`,
  in **request declaration order**, length G, `group_names[i]` paired with
  `group_index == i`. Contract:
  - indices are contiguous `0..G-1` in order of first appearance (a loaded
    artifact claiming `group_index = 2` with no `0,1` refuses — see 2.4),
  - names are unique across groups (existing law, re-checked on the table),
  - `group_names[i]` equals endpoint group_name of every endpoint whose
    `agent.group_index == i` (redundant check, deliberately),
  - the list is inside the hashed bytes: deleting or reordering any entry
    changes `attachment_hash`.
- **Unnamed mode** — no group declares. The `group_names` key is **absent**
  (not `null`, not `[]`), endpoint dicts carry no `group_name` keys, and the
  canonical bytes are bit-identical to today's. **No artifact carrying no
  names refuses; unnamed stays legal forever.**
- **Mixed mode** — some declare, some don't, or names collide. **Refused.**
  This is the otherwise in "…or refuses otherwise", and it is never silently
  repaired, never defaulted, never inferred from position.

`group_names` is a new conditional key inside schema v3, following the
established `egress` precedent (`attachment.py:96-99`, `:153-157`): pre-binding
builds refuse a named artifact via their existing strict-keys law
(`attachment.py:163-164` allows `"group_name"`, the new key would be
`unknown fields` — loud, immediate, and before any hash check). **No schema
bump and no tag change**: `ATTACHMENT_SCHEMA_VERSION = 3` and
`srota/AgentAttachment/v3` stay; a bump to v4 is explicitly rejected because it
would invalidate every stored hash for zero semantic gain over a conditional
key whose absence is already the byte-stable legacy mode.

Per-group redundancy with per-instance endpoint names is accepted deliberately:
the table is the only artifact-level, order-bound encoding of the
declaration-order↔name pairing, and it is one string per group, not per
instance.

### 2.3 Refusal semantics — one rule, three layers, two stable codes

Two stable codes, used at every layer. A refusal that emits neither code is a
bug.

- `ATTACHMENT_GROUP_NAME_MISSING` — some group declares and some does not
  (mixed), or a named-mode artifact/request is missing a name it requires.
  Message names the indices: `ATTACHMENT_GROUP_NAME_MISSING: agent groups
  missing group_name: [1, 3]`.
- `ATTACHMENT_GROUP_NAME_DUPLICATE` — a name repeats across groups. Message
  names the duplicates: `ATTACHMENT_GROUP_NAME_DUPLICATE: group_name values
  must be unique; duplicates: ['grp']`.

**L1 — request boundary (construction).** Exact site:
`veritx_dse/model/compile_request_v4.py`, `CompileRequestV4.__post_init__`,
`:96-107`. The two existing `ValueError` sites keep refusing and gain the code
prefix on their first line. Construction-time refusal is *not* converted to a
stage-1 finding; a request that fails construction never reaches stage 1, and
weakening that to "compile and report" would let an inconsistent identity into
every artifact in the pipeline.

**L2 — stage-1 finding list (the exact site, the chosen one).** Exact site:
`veritx_dse/application/fabric_compiler.py`, `_run_stage1` (`:242`), as a new
gate **immediately after the M3 block and before the `# M4 — Protocol Adapter`
comment (`:430`)**, i.e. after the `clock_power_cdc` `_record(...)` at
`:419-428` returns no refusal, and before M4's `_record`. Concretely:

- module-level constants `ATTACHMENT_GROUP_NAME_MISSING` /
  `ATTACHMENT_GROUP_NAME_DUPLICATE` near the top of `fabric_compiler.py`,
- a helper `_attachment_group_name_gate(request) -> tuple[str, ...]` (same
  file) that re-derives the all-or-nothing + uniqueness law from the frozen
  request's `agents` (it owns no state and reads no artifact),
  producing stable-coded strings,
- a `_record("attachment_binding", verdict, "ATTACHMENT")`-shaped call so the
  gate also appears in `stage1_verdicts`, with `ok=False` refusing as
  `Compilation(status="INVALID", stopped_at_stage="ATTACHMENT",
  stage1_verdicts=verdicts, findings=findings)` — the identical return shape
  as M3's refusal at `:427-429` and as the existing `AGENT_PROTOCOL_UNOWNED`
  finding appends to the same `findings` list at `:449-458` (the format
  precedent, the blocking-vs-warn distinction being that the gate refuses).

Why here and not elsewhere, explicitly:

- The stage-1 finding list *is* the product surface
  (`service.py:1954-1969`, `compile_result_view.py:756-808`,
  `rtl_export.py:453`). A group-name identity refusal that does not appear
  there is invisible to every product consumer.
- M3's owner stage is already `"ATTACHMENT"`; the gate belongs to the same
  owner and inherits its stage attribution for free.
- `_run_stage1` is the only layer that can refuse **before** derivation, so a
  bad identity cannot be baked into a bundle and then half-reported.
- Not placed in `certificate.py` (`_attachment_complete`, `:111-121`): the
  certificate is the verification net, not a finding source; duplicating the
  gate there would double-count without adding a product-visible finding.
- Not placed in `orchestration.derive_stages_v3`'s `except` branch: that branch
  produces `StagedDerivation`, and its caller maps it to a `Compilation` in
  the `bundle is None` branch (`fabric_compiler.py:536-551`) **which drops
  `stage1_verdicts` and `findings` entirely**. Fixing or threading that branch
  is an optional, separable follow-up (see §6); L2 deliberately does not
  depend on it.

Reachability, stated honestly: for a natively constructed v4 request,
`__post_init__` refuses first, so the L2 gate never fires on the happy path —
it is defense in depth for (a) post-construction tampering
(`object.__setattr__`, the pattern the test suite already uses), (b) v5
product wrappers whose `base_v4` could in principle be mutated between
construction and compile, and (c) any future repair/migration flow that relaxes
L1. It must exist anyway, because L3 artifacts loaded from disk do not pass
through L1 at all — but the codes they raise are L3-scoped, not stage-1
findings. L2 and L3 never substitute for each other.

**L3 — artifact boundary (fail closed).** Exact site:
`veritx_dse/model/attachment.py`. The same two codes prefix the
`AttachmentError` messages raised by:

- `AgentAttachmentArtifact.__post_init__` — the all-or-nothing/unique law on
  the names table (`:246-263` extended to check `group_names` when present:
  length, contiguity, uniqueness, and equality with per-endpoint names),
- `AgentAttachmentArtifact.from_dict` — accept the known key `"group_names"`
  in strict keys (`:410-412`); require it in named mode; require its absence
  in unnamed mode (a nameless artifact with a table refuses);
  contiguity/uniqueness failures raise the coded error,
- `validate_against` — extend the group_name equality check (`:376-380`) to
  also compare `group_names` to `[g.group_name for g in design.agents]`; keep
  the existing "rebuild attachment after identity changes" detail,
- `derive_attachment` — emit the table from the same expansion loop
  (`:474-484`), in the same order the endpoints are produced.

L3 stays `AttachmentError` (a `SemanticError`, `core/errors.py:38`), which
`derive_stages_v3` already maps via `map_semantic_error` → `ControlPlaneError`
→ `Compilation(INVALID, stopped_at_stage="ATTACHMENT")`. L3 is the layer that
protects stored/merged artifacts; L2 is the layer that reports on the product
surface; L1 is the layer that makes bad requests unrepresentable.

### 2.4 Exact refusal table (named mode)

| Case | Layer | Code / error |
|---|---|---|
| Some groups declare, some don't (request) | L1 | `ValueError` prefixed `ATTACHMENT_GROUP_NAME_MISSING` |
| Duplicate names (request) | L1 | `ValueError` prefixed `ATTACHMENT_GROUP_NAME_DUPLICATE` |
| Mixed/duplicate after post-construction tamper | L2 | finding `ATTACHMENT_GROUP_NAME_MISSING` / `..._DUPLICATE`; `Compilation(INVALID, stopped_at_stage="ATTACHMENT")`, gate appears in `stage1_verdicts` |
| Endpoints mixed (artifact) | L3 | `AttachmentError` prefixed `ATTACHMENT_GROUP_NAME_MISSING` |
| Table missing in named mode (`from_dict`) | L3 | `AttachmentError` prefixed `ATTACHMENT_GROUP_NAME_MISSING` |
| Table present with no named endpoints | L3 | `AttachmentError` prefixed `ATTACHMENT_GROUP_NAME_MISSING` |
| Table duplicates / per-endpoint mismatch | L3 | `ATTACHMENT_GROUP_NAME_DUPLICATE` / equality detail |
| Table non-contiguous (`group_index` 0..G-1 not covered) | L3 | `AttachmentError` "group_names must cover groups 0..G-1 contiguously" (shape refusal, no code — see note) |
| Table tampered on disk | L3 | existing "attachment_hash missing or does not match content" (`attachment.py:426-429`) — hash mismatch, no new code |
| `group_names` key in unnamed artifact | L3 | `ATTACHMENT_GROUP_NAME_MISSING` (table requires named mode) |

Shape refusals (contiguity, unknown keys) keep plain `AttachmentError` text
with **no** code; only missing/duplicate identity failures carry codes. That
keeps `grep -rn "ATTACHMENT_GROUP_NAME_"` exhaustive: every hit is an identity
decision, and every identity decision has a hit.

### 2.5 Who consumes `group_names`

`validate_against`/`from_dict` (L3) and nothing else, in v1. The table exists
for fail-closed checking and for reorder-safety audits, not for
routing/fabric/RTL consumers. Downstream identity annotations (RTL, telemetry,
Studio labels) are follow-ups, each blocked on this landing; none is designed
here.

---

## 3. Honesty clauses

### 3.1 Emission order is request declaration order — full stop

`group_names` is emitted in the order `design.agents` is declared in the
request document. It is **not** sorted by name, **not** sorted by kind,
**not** deduplicated beyond the uniqueness law, and **not** influenced by
`agent_intents` (which *are* sorted by `agent_idx` at
`compile_request_v4.py:123-125` — an asymmetry worth noting: the request
canonicalizes intents but never reorders agent groups, precisely because
declaration order is identity). Endpoints remain in the same expansion order
(`placement.py:206-211`), so `group_names` and the endpoint stream agree on
order by construction. Any consumer that wants alphabetical order sorts a
copy; the artifact does not.

### 3.2 Reordering agents changes `design_hash` — the exact flip

`canonical_json` sorts object keys but preserves array order
(`core/spec.py:194-197`), and `CompileRequestV4.canonical_dict()` emits the
`agents` array in declaration order (`compile_request_v4.py:200`), so swapping
two groups changes bytes and therefore the digest. Toy example, two groups —
`compute_tile ×2` named `"tile"`, `hbm_controller ×1` named `"hbm0"` — the
serialized `agents` arrays are (byte-exact, `json.dumps(sort_keys=True,
separators=(",", ":"))` run on the literal dicts this `_agent_dict` produces):

Order A (declare tile first):

```json
[{"addr_width":64,"clock_domain":null,"count":2,"data_width":256,"group_name":"tile","kind":"compute_tile","power_domain":null,"protocol":"AXI"},{"addr_width":64,"clock_domain":null,"count":1,"data_width":256,"group_name":"hbm0","kind":"hbm_controller","power_domain":null,"protocol":"AXI"}]
```

Order B (declare hbm0 first):

```json
[{"addr_width":64,"clock_domain":null,"count":1,"data_width":256,"group_name":"hbm0","kind":"hbm_controller","power_domain":null,"protocol":"AXI"},{"addr_width":64,"clock_domain":null,"count":2,"data_width":256,"group_name":"tile","kind":"compute_tile","power_domain":null,"protocol":"AXI"}]
```

First byte difference at index 46 (`"count":2` vs `"count":1` in the first
element); both strings are 291 bytes and differ throughout — there is no
suffix/prefix sharing that could rescue a shared prefix hash. (Fragment
SHA-256s, labeled as fragment digests of exactly those byte strings, not of
any full document: A = `7c86c63a…cb4fc9`, B = `d2a9d39d…0938b`.) The real
`design_hash` is

```
sha256("srota/CompileRequest/v4/v4/c4\0" + canonical_json(canonical_dict()))
```

(`compile_request_v4.py:253-257`), so any byte flip anywhere in the envelope —
starting with index 46 of the `agents` fragment — yields a different
`design_hash`, and therefore a different design identity, a different
attachment (endpoints follow group order; seats shift), a different
`instance_id` meaning for every index (`agent_group[0]/compute_tile[…]` re-points
to a different physical group), and a different mapping. Reordering agents is
not a no-op, never has been, and this proposal does not try to make it one —
instead it makes the flip **detectable downstream**: after this lands, a stored
named attachment refuses `validate_against` against the reordered design, and
its `group_names` table shows the order flip as `["tile","hbm0"]` →
`["hbm0","tile"]` instead of hiding inside instance coordinates.
(The `design_hash` reorder sensitivity itself pre-exists this proposal; what
is new is an artifact-level, hash-checked witness of group order.)

### 3.3 Diff-noise cost on stored hashes, and the migration plan

**Unnamed artifacts: zero change, structurally.** No endpoint `group_name`
keys, no `group_names` key, same tag, same schema v3 — byte-identical output,
so every stored unnamed artifact, every example pin, and every parity test
(`test_compiler_path_parity.py:47`) is bit-stable through this change. This
tree partially confirms the premise: `grep -rl group_name` over
`tracks/t3-topology/dse/examples` is empty and the four stored example
attachments found there (`rcu_reference_v1.json`, `local_island_positive.json`,
`local_island_negative.json`, `multicast_tree_v1.json`, all unnamed)
keep their hashes; a repo-wide grep for stored `group_name` hits was not
feasible here (timed out), so the landing PR must re-run it over
`tracks/t3-topology/dse/runs` and any out-of-tree evidence store before
merging. This is a verification step in the landing plan, not an assumption.

**Named artifacts: one-time break at landing.** Endpoint bytes do **not**
change; only the added `group_names` key changes `canonical_dict()`, so
`attachment_hash` changes for every named artifact on the day this lands.
`design_hash` does **not** change (it never includes the attachment, and
`group_name` already entered `_agent_dict` when declared). Concretely:

- affected stored artifacts in this repo: none found in-tree (examples grep
  empty; the residual `runs/` verification is a landing-PR step, see above);
  named attachments exist today only in test constructions
  (`tests/test_attachment.py:51-110`, `tests/test_group_name_binding.py`),
  which must be re-derived/re-pinned in the landing change,
- in-memory hashes computed before the landing in long-lived services are
  stale by one schema-conditional key; no persisted index keys attachment_hash
  for lookup in-tree (hashes are carried as evidence, not as primary keys),
- certificate evidence strings for unnamed compiles are unchanged (bytes
  unchanged); named compiles get the same obligations with a new evidence
  digest — no obligation text changes.

**Migration plan (in landing order, each step its own verified commit):**

1. Land L3 in `attachment.py` (emit/verify `group_names`; strict-keys accept;
   coded `AttachmentError`s). Named artifacts now carry the table.
2. Land L1 message prefixes in `compile_request_v4.py` (no behavior change —
   refusal stays a `ValueError`; only the message gains the code).
3. Land L2 in `fabric_compiler.py` (gate + constants + `_record` mapping).
4. Re-derive and re-pin every named hash-bearing test expectation; run the
   named-mode test set; confirm the unnamed set is byte-stable by comparing
   `attachment_hash` before/after on one known unnamed fixture kept as the
   canary (its pin must not move).
5. Re-pin any out-of-tree stored attachments owned downstream (enumerate in
   the landing PR description before merge, not after); any named stored
   artifact that cannot be re-derived from source is **refused**, not
   migrated-in-place.
6. Record the new behavior in `docs/product/REMAINING-WORK.md` (item 8) and
   the P1.5 status doc; leave P1.5 open until the full P1.5 exit criteria
   (named compile COMPILED + certificate green) are re-measured on this tree.
7. Rollback: revert steps 1-3. Pre-binding builds refuse named artifacts via
   strict keys (loud, not silent) — rollback breaks named compiles loudly and
   unnamed compiles never. Downgrade never rewrites bytes.

**Diff-noise honesty:** the tree will show one-time hash churn in named
fixtures and any regenerated evidence; reviewers should expect exactly that
and nothing else. Any diff touching unnamed bytes or `design_hash` for an
unchanged document is a defect, not a cost.

### 3.4 What this proposal does not do

- No change to `AgentInstance`, `NodeInventory`, `build_inventory`,
  `MappingArtifact`, routes, VC assignment, fabric, packet format, RTL, or
  the frontend.
- No new schema version, no new tag, no artifact-format migration tool.
- No weakening of L1; no inferring or repairing mixed documents; no default
  names; no alphabetization; no sorting of agent groups.
- No claim that this binds hardware. The attachment is proven against the
  *model* (design + inventory + topology) by the existing laws; nothing here
  is a silicon, timing, or DRC claim.
- P1.5 remains **OPEN** until this lands and the named-mode compile evidence
  is re-measured; "substrate + binding green" is still not "hardware boots".

---

## 4. Proof plan — exact tests to land

New file `tracks/t3-topology/dse/tests/test_attachment_group_name_gate.py`
(stage-1/product-surface tests, v4 `FabricCompiler` path) plus extensions in
`tests/test_attachment.py` (artifact-boundary tests, v3-style requests, matching
its existing fixture pattern). Names are the contract:

Round trip

1. `test_named_group_names_table_round_trip` — derive from a named v4 request;
   assert `att.to_dict()["group_names"] == ["tile", "hbm0"]` in declaration
   order; `AgentAttachmentArtifact.from_dict(att.to_dict()) == att`;
   `attachment_hash()` stable across the round trip; the accepted key is
   known to strict keys.
2. `test_group_names_order_follows_declaration_not_alphabet` — named groups
   declared `["zeta", "alpha"]`; assert table order `["zeta", "alpha"]` and
   endpoint order unchanged.
3. `test_endpoint_group_name_matches_table` — every endpoint's `group_name`
   equals `group_names[endpoint.agent.group_index]`.

Refusals

4. `test_mixed_naming_refused_at_artifact_boundary` — hand-built artifact with
   one nameless endpoint among named → `AttachmentError` prefixed
   `ATTACHMENT_GROUP_NAME_MISSING`.
5. `test_duplicate_names_table_refused` — `from_dict` of a named artifact with
   `group_names: ["grp", "grp"]` (endpoints name-consistent) →
   `ATTACHMENT_GROUP_NAME_DUPLICATE`.
6. `test_named_artifact_missing_table_refused` — named endpoints, `group_names`
   deleted from the dict → `ATTACHMENT_GROUP_NAME_MISSING`.
7. `test_table_with_no_named_endpoints_refused` — unnamed endpoints + a
   `group_names` key → `ATTACHMENT_GROUP_NAME_MISSING`.
8. `test_non_contiguous_group_names_refused` — artifact with endpoints grouped
   `group_index = 1, 0` … table claiming `group_index = 1` only →
   shape `AttachmentError` (contiguity), no code, per §2.4.
9. `test_table_tamper_fails_hash` — mutate one table entry on disk →
   "attachment_hash … does not match content" (existing law, unchanged).
10. `test_stage1_missing_finding_blocks_compile` — v4 request with mixed
    naming built via `object.__setattr__` post-construction;
    `FabricCompiler().compile(req)` returns
    `status == "INVALID"`, `stopped_at_stage == "ATTACHMENT"`, a stage-1
    verdicts entry `{"module": "attachment_binding", "ok": False, "stopped_at_stage": "ATTACHMENT"}`,
    and `findings` containing a string starting
    `ATTACHMENT_GROUP_NAME_MISSING:` naming the missing indices.
11. `test_stage1_duplicate_finding_blocks_compile` — same shape with tampered
    duplicate names; finding code `ATTACHMENT_GROUP_NAME_DUPLICATE` and the
    duplicate values in the message.
12. `test_stage1_gate_absent_on_clean_named_request` — fully-named request
    compiles to `status == "COMPILED"` and no `ATTACHMENT_GROUP_NAME_*`
    string appears anywhere in `findings` or verdict reasons.

Hash-stability-absent

13. `test_unnamed_artifact_bytes_unchanged` — unnamed derive; assert
    `canonical_dict()` has **no** `group_names` and no endpoint `group_name`;
    assert `attachment_hash()` equals the pre-change pin
    (`content_id("srota/AgentAttachment/v3", legacy_dict)`), byte-identical to
    the pin asserted at `tests/test_attachment.py:88-99`; `from_dict` accepts
    it exactly as before.
14. `test_unnamed_compile_keeps_parity` — extend `test_compiler_path_parity`
    evidence path expectation: unnamed named-free compile emits identical
    `attachment` hash as today's recorded value (re-derived, not re-pinned —
    it must not move).

Reorder sensitivity

15. `test_agent_reorder_flips_design_and_attachment_hashes` — named two-group
    request; derive `att_a`; swap `agents`; assert `design_hash()` differs,
    derived `attachment_hash()` differs, `group_names` flips order, and
    `att_a.validate_against(swapped, …)` refuses with the
    group_name-identity message (extending
    `test_saved_attachment_refuses_same_kind_group_reorder`).
16. `test_group_names_table_is_hash_bound_to_order` — same artifact with
    `group_names` permuted (endpoints untouched) → `from_dict` hash mismatch;
    table order is identity-bearing, not cosmetic.
17. `test_reorder_unnamed_keeps_attachment_bytes_stable_only_if_instances_align`
    — unnamed request, swapped groups with different counts → different
    inventory, different seats, different hash (the positional law is
    intentionally unchanged); the test documents, it does not moralize.

Product surface

18. `test_compile_result_view_surfaces_attachment_group_name_findings` — a
    compile refused at L2 shows the code in the `stage1_findings` payload of
    the compile result view (`stage1_findings` list), proving the finding
    reaches the product surface, not just `Compilation.findings`.

Certificate backstop

19. `test_certificate_attachment_complete_fails_on_tampered_named_artifact` —
    tamper an endpoint's `group_name` post-derivation, force
    `verify_compiled_fabric(bundle)`; assert the `ATTACHMENT_COMPLETE`
    obligation is not PASS and its evidence carries the mismatch string.

Frontend

20. No new frontend tests; `agentMapExact.test.ts` stays at its landed
    11/11. This proposal touches no `apps/` file; a change there would be a
    defect, not a feature.

---

## 5. Operator opt-in

Operators opt into the binding per compile by declaring `group_name` on every
Agent group — declaring none compiles exactly as before with no `group_names`
table emitted and every stored hash byte-stable, and the binding is off by
default, never inferred, never enabled by a flag.

## 6. Landing order, effort, and open follow-ups

Landing order: L3 (`attachment.py`) → L1 (`compile_request_v4.py`, message
prefix only) → L2 (`fabric_compiler.py`) → test re-pins/canary check → status
docs. Effort: M (one focused day plus evidence re-measurement; XS if only
unnamed designs are ever exercised, which is the default).

Follow-ups explicitly **not** in this proposal, recorded so they are not
forgotten: (i) thread `stage1_verdicts`/`findings` into the
`bundle is None` refusal branch (`fabric_compiler.py:536-551`) so
ATTACHMENT-stage derivation refusals also carry stage-1 findings — separable,
low risk, and worth its own PR; (ii) surface the binding in Studio's endpoint
inspector once (i) exists; (iii) P1.5 status doc re-measurement and closure
review — the only document authorized to close P1.5, and only with fresh
evidence.

Findable anchors for review (all single-site):
`grep -rn "ATTACHMENT_GROUP_NAME_MISSING" tracks/t3-topology/dse` → the two
constants/messages plus L1/L2/L3 sites and tests;
`grep -rn '"group_names"'` → `attachment.py` emission/parsing and tests;
`grep -rn "attachment_binding"` → the L2 gate module entry in verdicts.
