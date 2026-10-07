# Remaining work — prioritized backlog

**Base:** working tree after the shared-wire line (SROTA row-first/two-shape,
GEC-MECS compile, certify, render, execute live). Verified by 722 focused
tests, `make product-gates`, both registry gates, `git diff --check` clean.
Full DSE suite NOT run in that session, by operator instruction.

**Rule for every item below:** the definition of done is a live run or a
typed refusal, never a new status word. An item is done when a test shows
the behavior it names — compile + certificate for model work, flit
conservation for execution work.

---

## P0 — commit the green tree (blocks ALL evidence)

The 32 live-evidence tests refuse by design because the tree is dirty:

- `third_party/booksim2/src/networks/{network.cpp,network.hpp,gec.cpp}`
  (tap + VC-range route dumps, `dor_gec_gec` aliases)
- all model/verification/backend/test additions from the shared-wire line

**DoD:** the fork change and the model change land as separate commits on a
clean tree; the 32 refusals become passes. Until then, **neither shared-wire
qualification is usable as pinned evidence** — the producer guard forbids it,
and that is correct behavior, not a bug.

Pre-existing unrelated Studio work in the tree must NOT be swept into these
commits.

---

## P1 — GEC-hybrid materializer (moves the wall, proves nothing new)

`gec_hybrid` is `BLOCKED at MATERIALIZABLE` with a refusal that already names
the real reason (runtime credit choice, needs the escape method). Its
materializer is a separate, smaller piece: union `materialize_family(MESH)`
channels with `materialize_gec_mecs` wires under a `GEC_HYBRID` family, plus
the registry row, with routing still refusing on the adaptive choice
(`take_mesh = (mesh_cost < mecs_cost)` in `networks/gec.cpp:1105`).

**DoD:** hybrid reports `MATERIALIZABLE=YES, ROUTABLE=NO` with the adaptive
reason; no proof claimed. ~40 lines + tests + registry row.

---

## P2 — GEC-hybrid escape proof (genuinely open)

`hybrid_gec` has no decision table, so `RouteArtifactV3`/`ShapePolicyRoute`
cannot express it. It needs `ESCAPE_SUBNETWORK_THEOREM` (already in
`DEADLOCK_PROOF_METHODS`) ported onto a graph where the two choices share a
VC set. `verification/adaptive_escape.py` (SROTA-scoped v1 escape
subfunction, already wired into orchestration) is the template — but it
proves separated choices, and hybrid has none.

**DoD:** a hybrid decision set that certifies `DEADLOCK_FREE` under the
escape method, with a negative control that fails without the escape VC.
Research-grade; not a template copy.

---

## P3 — SROTA shape-mixing compiler wiring (proof exists, wiring missing)

The proof half is done and green: the row+column union with the real
`SrotaShapeVCPartitionPolicy` is acyclic (`test_srota_shape_policy_union.py`),
and collapsing the partition reproduces the exact RT-R7 four-resource
cycle. But `derive_route` still refuses two-shape SROTA, so nothing in the
compiler consumes the policy artifact — its only consumers are tests.

Thread it the same way Phase A went:

1. VC derivation yields `num_vcs = 2` for `vc_policy="shape"`
   (same seam as the `vcs_from_multidrop` fix);
2. `derive_route` returns the union (`ShapePolicyRoute`) for two-shape designs;
3. `resolved_route` / VC / certificate consume it (union branch already
   exists in `shared_resource_cdg`; the downstream needs the same);
4. profile branch (`srota_path_en = 3`, `srota_vc_policy = shape`)
   and a live conservation run.

**DoD:** a two-shape SROTA preset compiles, certifies, renders, and executes
with conservation. One focused session.

---

## P4 — SROTA Valiant (blocked by the source, not by us)

Valiant turns twice and closes a cycle on its own; the fork refuses
`shape`+Valiant outright. Needs the 4-VC rank split wound through VC
derivation, routing, and the CDG — three files minimum, each with its own
invariant.

**DoD:** Valiant-only design certifies under the rank policy; the fork's own
refusal table agrees it is the correct envelope. Separate slice.

---

## P5 — SROTA islands and Plane C (model work first)

- **Islands:** the artifact cannot carry a rate regulator's state, and the
  model explicitly does not simulate one. Either add a regulator primitive
  or prove a placement-only rule; compiler work comes second, never first.
- **Plane C:** a second subnet with its own REQ/RSP/SNP VC structure,
  through all nine pipeline stages.

**DoD per item:** typed refusal removed AND a live multi-plane run conserves
flits on both planes.

---

## P6 — V5 intent materialization (the broad track)

From `docs/product/LOOM-CAPABILITY-CLOSURE.md`: nearly every V5 capability
is `PARTIAL / root identity only, blocked at MATERIALIZABLE`. Each is its
own compile→verify→execute→qualify slice, using the MECS line as template:

- transactions (outstanding / ordering / splitting) — no issue scheduler
- access policy — artifact exists, not emitted, not bound to Access Loom
- sidebands, clocks/domains, reset, power — identity only
- CDC + async-FIFO model — no RTL differential
- IP catalog — 12 templates, not bound to stamps or compiler
- multi-plane fabric — `PlaneComposition` accepts single plane only

**DoD per item:** a compiled, certified, executed design — or the refusal
stays and says exactly which stage owns it.

---

## P7 — verification and generation

- **UVM** (`PARTIAL`): generated DUT binding does not lint against
  `rtl/t3/mesh.sv`; no UVM library in-tree. DoD: generated collateral
  compiles and runs against the repository DUT.
- **RTL generation** (`NOT_IMPLEMENTED`): no emitter. DoD: supported-subset
  emitter with lint + simulation smoke before any READY claim.

---

## P8 — physical, packaging, measurements

- **OpenROAD** (`NOT_IMPLEMENTED`): needs a PDK choice, LEF/Liberty/SDC/DEF
  contracts, tool provenance. DoD: one placed-and-routed block with
  provenance, before any PPA-adjacent claim.
- **Desktop/Tauri** (`NOT_IMPLEMENTED`).
- **Throughput/PPA** (`NOT PROVIDED` everywhere, by explicit design):
  assert only what the fork measures. Completion, conservation, and latency
  are already in the evidence and asserted for SROTA/GEC-MECS.

---

## P9 — process and hygiene (never silent)

- Upstream reuse audit incomplete (rate-limited, partial license
  evidence): **nothing may be vendored** until exact commits, licenses,
  sources, and tests are recorded.
- Full DSE suite was not run in the shared-wire session (operator
  instruction); run it on the clean tree before any release claim.
- `fattree` spelling normalization, concentrated-mesh 2:1 lowering, and
  the Studio P2 notes remain open with ownership outside this line.
