# family-binding-guards — binding-time request↔bundle conformance guards

Status: **proposal**. Implemented module:
`tracks/t3-topology/dse/veritx_dse/product/family_binding_guards.py`
(imports cleanly as `veritx_dse.product.family_binding_guards`; NOT yet wired
into `project_top_rtl.py` — no existing files were edited).

Covers the 13 `NOT_COVERED` entries in
`tracks/t3-topology/dse/tests/test_family_bad_design.py`: the composed family
profile and the two shared profiles attest bundles that were *compiled from
some other request*, then hand them a *different* declared intent. Each guard
below re-reads the declared intent and the bundle together, and refuses with a
named reason instead of attest silently.

---

## 0. House rules honored

- No comments in the module; docstrings only, like the rest of `veritx_dse`.
- Typed error: `FamilyBindingMismatch(ValueError)` — subclasses `ValueError`
  on purpose so every `_refusal`-style harness in the test suite
  (`except ValueError`) catches it unchanged, exactly like `_refuse_family`.
- Exact ints everywhere (`int(...)` at the boundary, plain `==`).
- The **bundle is binding-time truth**. The intent is the declared claim.
  Guards compare the two; the bundle is never re-derived FROM the request
  alone (that is what `_validate_compiled_topology_binding` already does and
  why these guards exist: it produces one opaque hash-mismatch message, not a
  named per-family reason).
- Guards re-derive the construction law in-module* instead of importing
  private helpers, so they cannot drift with a refactor of the materializers.
  `*` one deliberate exception: none — see §3 GEC notes.
- Every guard returns `None` when the request topology is not its family
  (dispatch is the caller's job), and calls the two shared re-verification
  helpers (bundle presence, endpoint↔agent-instance rebinding) before its
  family-specific checks.

### Shared rebinding checks (run first, all families)

| Named reason | Condition |
|---|---|
| `COMPILED_BUNDLE_MISSING` | `compiled.status != "COMPILED"` or `compiled.bundle is None` or `bundle.topology is None`. |
| `COMPILED_ROUTER_IDS_NOT_CONTIGUOUS` | Bundle router ids are not exactly `0..len-1`. |
| `ENDPOINT_INSTANCE_MISMATCH` | `len(bundle.attachment.endpoints) != sum(int(a.count) for a in request.agents)` — carries the phrase `compiled endpoint count does not match agent instances` so existing-style assertions can grep it. |

All three are mismatch, not family law; they are emitted with the family name
in the message detail.

### Module-level contract

```python
FAMILY_BINDING_GUARDS_SCHEMA = "veritx/family-binding-guards/1"
FAMILY_BINDING_GUARDS = (<the 13 guard functions>)

def check_family_binding_guards(request, compiled) -> None:
    """Run every guard in order; first mismatch raises FamilyBindingMismatch."""
```

Signature of every guard:

```python
def check_<family>_<guard>_binding(request: CompileRequestV4, compiled: object) -> None
```

`CompileRequestV4` is imported under `TYPE_CHECKING` only; the module does not
import `project_top_rtl` (no import cycle, no 9k-line import cost, no shadow of
`KNCUBE_BLOCKER` — the string is re-declared locally with the same value).

---

## 1. Per-guard reference

### 1.1 `check_mesh_seat_concentration_binding` — family `mesh`

```python
check_mesh_seat_concentration_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `MeshIntent` only; anything else returns `None`.
- **What the bundle would emit** (`materialize_family(MESH, radix=side_length,
  concentration=concentration)`): `side_length**2` routers, row-major
  `coordinates=(r % k, r // k)`, uniform `seat_capacity == concentration`,
  no shared links.
- **Exact refusal conditions** (any one raises; named reason
  `MESH_SEAT_CONCENTRATION_MISMATCH`):
  1. Bundle router count ≠ `side_length**2`.
  2. Bundle coordinates ≠ row-major `(r % k, r // k)`.
  3. Bundle `seat_capacity` tuple ≠ uniform `concentration` — **this is the
     missing check**: `check_composed_family_profile` never compares
     `request.topology.concentration` to the bundle's `seat_capacity`, so a
     `MeshIntent(concentration=2)` request against a concentration=1 bundle
     attests silently.
  4. Shared checks (bundle presence, router-id contiguity,
     `ENDPOINT_INSTANCE_MISMATCH`).
- **NOT_COVERED note addressed:** mesh — "bundle seat/concentration
  conformance guard".
- **Wiring site:** `composed_family_params_from_request`, immediately after
  `_validate_compiled_topology_binding(request, compiled)` and before
  `fam = _family_id_from_topology(...)`; family dispatch `fam == "mesh"`.

### 1.2 `check_torus_wrap_degree_binding` — family `torus`

```python
check_torus_wrap_degree_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `TorusIntent` only.
- **What the bundle would emit** (`materialize_family(TORUS,
  radix=side_length)`, wrap grid): `side_length**2` routers,
  `2 * |grid_edges(wrap=True)|` directed channels (36 for 3×3), undirected
  edge set identical to the wrap grid's neighbor pairs.
- **Exact refusal conditions** (named reason `TORUS_WRAP_DEGREE_MISMATCH`):
  1. Router count ≠ `side_length**2`.
  2. Coordinates ≠ row-major `(x, y)`.
  3. `seat_capacity` ≠ uniform `concentration`.
  4. Bundle undirected channel edge set ≠ `_grid_edges(k, wrap=True)`
     (missing wrap channels are named in the message; the "drop the 12
     wraparound channels, re-id 0..23" corruption fails here — 24 ≠ 36 edges
     and the wrap pairs `(0,3),(1,4),(2,5),(3,6),(6,7),(7,8)` are absent).
  5. Directed channel count ≠ `2 * |grid_edges(k, wrap=True)|`.
  6. Channel ids not dense from 0 (re-id detection defense-in-depth).
  7. Shared checks.
- **NOT_COVERED note addressed:** torus — "torus wraparound-degree conformance
  re-verification in check_composed_family_profile".
- **Wiring site:** same; `fam == "torus"`.

### 1.3 `check_cmesh_concentration_binding` — family `cmesh`

```python
check_cmesh_concentration_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `ConcentratedMeshIntent` only.
- **What the bundle would emit**: `side_length**2` routers, row-major
  coordinates, uniform `seat_capacity == concentration`, `concentration >= 2`.
- **Exact refusal conditions** (named reason `CMESH_CONCENTRATION_MISMATCH`):
  1. Intent `concentration < 2` (family law; construction would refuse, but a
     post-hoc `object.__setattr__` bypass is a binding lie).
  2. Router count ≠ `side_length**2`.
  3. Coordinates ≠ row-major.
  4. Bundle `seat_capacity` ≠ uniform `concentration` — the missing
     re-check: request re-declared `concentration=3` against a
     concentration=4 bundle used to attest silently.
  5. Shared checks.
- **NOT_COVERED note addressed:** cmesh — "cmesh concentration conformance
  guard".
- **Wiring site:** same; `fam in ("concentrated_mesh",)` (the composed profile
  internally calls cmesh `concentrated_mesh`; the public family id stays
  `cmesh`).

### 1.4 `check_ring_router_count_dateline_binding` — family `ring`

```python
check_ring_router_count_dateline_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `RingIntent` only.
- **What the bundle would emit** (`materialize_ring`): `router_count`
  routers, coordinates `(r,)`, one seat per router, adjacency
  `{r: [(r+1) % n, (r-1) % n]}` with the **+1 port at `seat_capacity`,
  −1 port at `seat_capacity + 1`**, exactly `2*n` directed channels, and
  exactly one undirected wrap edge `{0, n-1}` — the dateline.
- **Exact refusal conditions** (named reasons `RING_ROUTER_COUNT_MISMATCH`,
  `RING_DATELINE_MISMATCH`):
  1. Router count ≠ `router_count` (`RING_ROUTER_COUNT_MISMATCH`) — the 32-vs-64
     corruption fails here.
  2. Coordinates ≠ `((r,))₀..n-1` (`RING_ROUTER_COUNT_MISMATCH`).
  3. Any `seat_capacity != 1` (`RING_ROUTER_COUNT_MISMATCH`).
  4. Directed channel count ≠ `2 * n` (`RING_ROUTER_COUNT_MISMATCH`).
  5. Port law: for every router `r`, exactly one channel leaves port
     `seat_capacity` toward `(r+1) % n`, exactly one leaves port
     `seat_capacity + 1` toward `(r-1) % n` (`RING_DATELINE_MISMATCH`).
  6. Dateline: the undirected edge set equals `{(r, r+1)}₀..n-2 ∪ {(0, n-1)}`
     — the single `n-1/0` wrap edge must exist, and no other non-consecutive
     edge may exist (`RING_DATELINE_MISMATCH`).
  7. Channel ids not dense from 0 (`RING_DATELINE_MISMATCH`).
  8. Shared checks.
- **NOT_COVERED note addressed:** ring — "ring router_count/dateline
  conformance guard".
- **Wiring site:** same; `fam == "ring"`.

### 1.5 `check_flatfly_stage_law_binding` — family `flatfly`

```python
check_flatfly_stage_law_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `FlatFlyIntent` only.
- **What the bundle would emit** (`materialize_flatfly(k=radix_per_dimension,
  n=dimension_count)`): `k**n` routers, coordinates
  `tuple((r // k**i) % k for i in range(n))`, every router of degree
  `(k-1) * n`, `k**n * (k-1) * n` directed channels, **zero shared links**
  (pure point-to-point), uniform `seat_capacity == concentration`.
- **Exact refusal conditions** (named reason `FLATFLY_STAGE_LAW_MISMATCH`):
  1. Router count ≠ `radix_per_dimension ** dimension_count` — the
     dimension_count 2→3 re-declaration against a 16-router k=4,n=2 bundle
     fails here (64 ≠ 16).
  2. Coordinates ≠ the digit law.
  3. `seat_capacity` ≠ uniform `concentration`.
  4. Any shared link present (flatfly is point-to-point).
  5. Per-router degree ≠ `(k-1) * n` (FLATFLY_MIN realizability, re-verified).
  6. Directed channel count ≠ `k**n * (k-1) * n`.
  7. Channel ids not dense from 0.
  8. Shared checks.
- **NOT_COVERED note addressed:** flatfly — "flatfly dimension/radix conformance
  guard".
- **Wiring site:** same; `fam == "flatfly"`.

### 1.6 `check_fly_ejection_seat_binding` — family `fly`

```python
check_fly_ejection_seat_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `FlyIntent` only.
- **What the bundle would emit** (`materialize_fly(k=4, n=3)`, BookSim
  `fly`): 48 routers in 3 stages of 16; stage-0 routers `seat_capacity=4,
  egress_seat_capacity=0` (injection-only), stage-1 middle routers both 0,
  stage-2 ejection routers `seat_capacity=0, egress_seat_capacity=4`. 64
  terminals, 128 directed channels.
- **Exact refusal conditions** (named reason `FLY_EJECTION_SEAT_MISMATCH`):
  1. Intent `(radix, levels) ≠ (4, 3)` (native law).
  2. Router count ≠ 48 (`levels * k**(levels-1)`).
  3. Per router: stage-0 `seat_capacity == k`; middle-stage `== 0`; ejection
     stage `seat_capacity == 0` **and** `egress_seat_capacity == k` — the
     zeroed-egress corruption fails here.
  4. Injection split (`seat_capacity > 0`) ≠ routers `0..15`;
     ejection split (`egress_seat_capacity not in (None, 0)`) ≠ routers
     `32..47` — this is exactly the split `_eligible_routers("fly", …)`
     declares in `project_top_rtl.py` and is never called.
  5. Sum of ingress seats ≠ sum of egress slots (64 ≠ 64), or either is
     smaller than the request's agent instances.
  6. Shared checks.
- **NOT_COVERED note addressed:** fly — "fly ejection-seat conformance guard".
- **Wiring site:** same; `fam == "fly"`.

### 1.7 `check_qtree_depth_law_binding` — family `qtree`

```python
check_qtree_depth_law_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `QTreeIntent` only.
- **What the bundle would emit** (`materialize_qtree`): 21 routers
  (1 + 4 + 16), coordinates `(level, position)`, offsets `(0, 1, 5)`,
  children-before-parent wiring, terminals on level-2 leaves only
  (`seat_capacity=4`), every internal router `seat_capacity=0`.
- **Exact refusal conditions** (named reason `QTREE_DEPTH_LAW_MISMATCH`):
  1. Intent `(radix, levels) ≠ (4, 3)`.
  2. Router count ≠ 21.
  3. Per router: coordinates ≠ `(level, position)` from the offset law.
  4. Per router: `seat_capacity` ≠ `4 if level == 2 else 0` — the +1 bump on
     router 0 fails here.
  5. Undirected adjacency ≠ the radix=4, levels=3 indirect quad-tree wiring
     (branching and depth re-verified; a hierarchy-depth corruption changes
     the edge set).
  6. Shared checks.
- **NOT_COVERED note addressed:** qtree — "qtree depth/levels conformance
  guard".
- **Wiring site:** same; `fam == "qtree"`.

### 1.8 `check_tree4_depth_law_binding` — family `tree4`

```python
check_tree4_depth_law_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `Tree4Intent` only.
- **What the bundle would emit** (`materialize_tree4`): 28 routers —
  4 roots, 8 middles, 16 leaves; coordinates `(level, position)`, level
  counts `(4, 8, 16)`, offsets `(0, 4, 12)`; roots wired to every middle;
  middle `p` wired to leaves `4*(p//2)+0..3` and to all 4 roots; leaf `p`
  wired to middles `2*(p//4)+0..1`; leaves only seat terminals (4 each).
- **Exact refusal conditions** (named reason `TREE4_DEPTH_LAW_MISMATCH`):
  1. Intent `(radix, levels) ≠ (4, 3)`.
  2. Router count ≠ 28.
  3. Per router: coordinates ≠ the offset law.
  4. Per router: `seat_capacity` ≠ `4 if level == 2 else 0` — the +1 bump on
     router 0 fails here.
  5. Undirected adjacency ≠ the four-root/eight-middle/sixteen-leaf wiring.
  6. Shared checks.
- **NOT_COVERED note addressed:** tree4 — "tree4 depth/levels conformance
  guard".
- **Wiring site:** same; `fam == "tree4"`.

### 1.9 `check_fattree_level_radix_binding` — family `fattree`

```python
check_fattree_level_radix_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `FatTreeIntent` only.
- **What the bundle would emit** (`materialize_ir(fat_tree_graph(...),
  seat_capacity=switch_radix)`): `level_count * switch_radix**(level_count-1)`
  routers, **every router `seat_capacity == switch_radix`**, tiers numbered
  level-major, undirected edges = the constant-bisection up-link rotation
  `up = (lo + uplink) % per_tier`, `(L-1) * per_tier * k` undirected links →
  `2 * (L-1) * per_tier * k` directed channels.
- **Exact refusal conditions** (named reason `FATTREE_LEVEL_RADIX_MISMATCH`):
  1. Router count ≠ `level_count * switch_radix**(level_count-1)` — the
     level_count 2→3 re-declaration fails here (expected 48, bundle 8).
  2. Any `seat_capacity != switch_radix` — the re-read of `switch_radix`
     that never happened.
  3. `switch_radix**level_count < sum(agent counts)` (endpoint capacity
     underflow).
  4. Bundle undirected edge set ≠ the tier-rotation fat-tree law.
  5. Directed channel count ≠ `2 * (L-1) * per_tier * k`.
  6. Channel ids not dense from 0.
  7. Shared checks.
- **NOT_COVERED note addressed:** fattree —
  "fattree level_count/switch_radix conformance guard".
- **Wiring site:** same; `fam == "fattree"`.

### 1.10 `check_dragonflynew_radix_group_count_binding` — family `dragonflynew`

```python
check_dragonflynew_radix_group_count_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `StructuredTopologyIntent` with `family in ("dragonfly",
  "dragonflynew")` only.
- **What the bundle would emit** (`structured_graph("dragonfly", …)` →
  `materialize_ir`, `seat_capacity=1`): `radix * group_count` routers, local
  cliques per group, one global link per (src_group, dst_group, a) with the
  `(a + src_group) % radix` rotation, one seat per router.
- **Exact refusal conditions** (named reason
  `DRAGONFLYNEW_RADIX_GROUP_COUNT_MISMATCH`):
  1. `radix` or `group_count` missing from structured params.
  2. Router count ≠ `radix * group_count` — the group_count 3→4
     re-declaration fails here (expected 16, bundle 12). STRUCTURED_FAMILIES
     is re-consulted through this re-derivation, which is why the guard
     exists: the composed profile never re-reads it.
  3. Any `seat_capacity != 1`.
  4. Bundle undirected edge set ≠ `cliques ∪ rotation-global-links`.
  5. Directed channel count ≠ `2 * (g*C(p,2) + p*g*(g-1)/2)`.
  6. Channel ids not dense from 0.
  7. Shared checks.
- **NOT_COVERED note addressed:** dragonflynew — "structured dragonfly
  radix/group_count conformance guard".
- **Wiring site:** same; `fam == "dragonflynew"`.

### 1.11 `check_gec_mecs_tap_cardinality_binding` — family `gec_mecs`

```python
check_gec_mecs_tap_cardinality_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `GecTopologyIntent` with `mode == MULTIDROP` only
  (the composed profile maps `gec` multidrop → `gec_mecs`).
- **What the bundle would emit** (`materialize_gec_mecs`): `k*k` routers,
  zero channels, `2 * k*k * o` shared links; every wire `src_router` = the
  driving router; **taps in ascending peer index, self skipped, group
  `peer_index // d`, tap `peer_index % d`** — hence exactly `d` taps per
  wire and exactly `o * d == k - 1` covered peers.
- **Exact refusal conditions** (named reason
  `GEC_MECS_TAP_CARDINALITY_MISMATCH`; every message contains `gec_mecs` and
  either `tap cardinality` or `tap identity`):
  1. Router count ≠ `k*k`; `seat_capacity` ≠ uniform `concentration`.
  2. Any point-to-point channel present (multidrop is wire-only).
  3. Shared-wire count ≠ `2 * k*k * o`.
  4. Per wire: `len(taps)` ≠ `destinations_per_express_channel` —
     **the missing check** (`taps_per_wire` is assigned `d` inside
     `gec_mecs_shared_params_from_request` and never compared per wire).
  5. Per wire: taps not ascending/self-skipping per the GEC law, duplicated
     taps, or a self-tap — **tap identity is re-verified, not just tap
     multiset cardinality**.
  6. `shared_link_id` not dense from 0.
  7. Shared checks.
- **Relation to the existing shared profile:** `gec_mecs_shared_params_from_request`
  compares the whole `shared_links` tuple against a re-materialized artifact
  and refuses on hash of that tuple. The guard makes the per-wire cardinality
  and identity a named, greppable refusal (`GEC_MECS_TAP_CARDINALITY_MISMATCH`)
  so a partial corruption (one tap on wire 0) is classified precisely, and so
  the check also runs on the *composed* path, which never looks at taps at all.
- **NOT_COVERED note addressed:** gec_mecs — "per-wire tap-count/tap-identity
  check in gec_mecs_shared_params_from_request".
- **Wiring site:** (a) in `gec_mecs_shared_params_from_request`, after the
  `topo.shared_links != expected.shared_links` comparison, before
  `return GecMecsSharedParams(...)`; and (b) in
  `composed_family_params_from_request`, `fam == "gec_mecs"`.

### 1.12 `check_gec_hybrid_tap_cardinality_binding` — family `gec_hybrid`

```python
check_gec_hybrid_tap_cardinality_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** `GecTopologyIntent` with `mode == HYBRID` only.
- **What the bundle would emit** (`materialize_gec_hybrid`): the k×k
  nearest-neighbour mesh channels **plus** the same MECS express wires law as
  1.11 (`mesh channels` directed count = `2 * |grid_edges(k, wrap=False)|`;
  48 for k=4), `2 * k*k * o` wires with exactly `d` taps each.
- **Exact refusal conditions** (named reason
  `GEC_HYBRID_TAP_CARDINALITY_MISMATCH`; messages contain `per-tap
  occupancy` semantics via `tap cardinality`/`tap identity`):
  1. Router count ≠ `k*k`; `seat_capacity` ≠ uniform `concentration`.
  2. Mesh channel edge set ≠ nearest-neighbour grid law / directed count ≠
     `2 * (2*k*(k-1))` = `4*k*(k-1)` — the bundle is missing its mesh half,
     or has stale wrap edges.
  3. Shared-wire count, per-wire cardinality (`len(taps) != d`), per-wire
     identity (`taps != _gec_wire_law(k, o, d)[i].taps`), duplicates,
     self-taps, dense `shared_link_id`s — identical law to 1.11.
  4. Shared checks.
- **NOT_COVERED note addressed:** gec_hybrid — "per-tap occupancy/tap-cardinality
  check in hybrid_shared_params_from_request".
- **Wiring site:** (a) in `hybrid_shared_params_from_request`, after the
  `topo.shared_links != expected.shared_links` comparison; and (b) in
  `composed_family_params_from_request`, `fam == "gec_hybrid"`.
- **Named-reason relationship:** distinct from `GEC_HYBRID_BLOCKER`
  (`GEC_HYBRID_CREDIT_OBSERVABILITY_CONTRACT_UNVERIFIED`); this guard is about
  bundle topology, not about the missing credit observable. Do not conflate.

### 1.13 `check_kncube_general_intent_equivalence_binding` — family `kncube`

```python
check_kncube_general_intent_equivalence_binding(request: CompileRequestV4, compiled: object) -> None
```

- **Applicable to:** any request topology that mentions kncube — `kind ==
  "kncube"`, or `kind == "structured"` with `parameters()["family"] ==
  "kncube"`. Mention detection uses `getattr` only, so a
  `SimpleNamespace(kind="kncube", parameters=lambda: {"k": 4, "n": 2})` stub
  is detected too (the exact `test_kncube_family_id_is_unguarded` stub).
- **Exact refusal condition:** kncube is mentioned ⇒ raise
  `FamilyBindingMismatch` whose message **starts with the exact blocker
  string** `KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING`
  (module constant `KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING`,
  value identical to `project_top_rtl.KNCUBE_BLOCKER`; alias `KNCUBE_BLOCKER`
  provided). No approximation, no structural fake-check, no silent pass.
  Otherwise return `None`.
- **What it deliberately does NOT do:** it does not validate a kncube bundle
  (there is nothing certified to validate it against: kncube has no
  `CompileRequestV4` topology intent class, `kncube` is not registered in
  `STRUCTURED_FAMILIES`, and `_family_id_from_topology` returns `"kncube"`
  unguarded). The refusal is the checker: a kncube binding cannot be
  attested because the general-intent/native-equivalence checker does not
  exist.
- **NOT_COVERED note addressed:** kncube — "Missing checker:
  KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING".
- **Wiring site:** at the **top** of `composed_family_params_from_request`
  (before the contiguous-router-id rule) and at the top of
  `_family_id_from_topology`'s caller — so a kncube mention names the blocker
  instead of dying on the contiguous-router-id rule. Also acceptable: raise
  from `check_composed_family_profile` directly.

---

## 2. Exact wiring recipe (proposal — do NOT apply blindly)

In `project_top_rtl.py`, inside `composed_family_params_from_request`:

```python
    _validate_compiled_topology_binding(request, compiled)
    from veritx_dse.product import family_binding_guards as _fbg
    for _guard in _fbg.FAMILY_BINDING_GUARDS:
        try:
            _guard(request, compiled)
        except _fbg.FamilyBindingMismatch as exc:
            raise _refuse_family(str(exc)) from exc
    fam = _family_id_from_topology(request.topology)
```

- `FamilyBindingMismatch` is a `ValueError`; wrapping it in `_refuse_family`
  keeps every `UNSUPPORTED_COMPOSED_FAMILY`-greppable assertion in the suite
  green and keeps the `(owner stage = … module = ProjectTop)` suffix.
- `str(exc)` already carries the named reason (e.g.
  `MESH_SEAT_CONCENTRATION_MISMATCH: …`) plus the family, so
  `assert UNSUPPORTED_COMPOSED_FAMILY in message` still matches.
- The kncube guard raises the bare blocker message; the wrapper preserves it
  verbatim except for the `_refuse_family` prefix — if the blocker must appear
  verbatim, special-case it:
  `if str(exc).startswith(KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING): raise`.
- For the two shared profiles: call
  `check_gec_mecs_tap_cardinality_binding` /
  `check_gec_hybrid_tap_cardinality_binding` at the point where
  `topo.shared_links != expected.shared_links` is compared today; the guard
  subsumes it with per-wire named reasons.
- After wiring, `NOT_COVERED`'s 13 entries in `test_family_bad_design.py`
  should either be deleted (families now covered) or flipped to assert the
  new named reasons — see §3.

No existing file was edited by this proposal; the module stands alone and is
imported lazily at the wiring site only.

---

## 3. Test skeleton to wire it in

New file `tracks/t3-topology/dse/tests/test_family_binding_guards.py`
(do not modify `test_family_bad_design.py` in the same change; flip it in the
wiring commit):

```python
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    PhysicalContext, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import (
    ConcentratedMeshIntent, FatTreeIntent, FlatFlyIntent, FlyIntent,
    GecMode, GecTopologyIntent, MeshIntent, QTreeIntent, RingIntent,
    StructuredTopologyIntent, TorusIntent, Tree4Intent,
)
from veritx_dse.product.family_binding_guards import (
    FamilyBindingMismatch,
    KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING,
    check_cmesh_concentration_binding,
    check_dragonflynew_radix_group_count_binding,
    check_family_binding_guards,
    check_fattree_level_radix_binding,
    check_flatfly_stage_law_binding,
    check_fly_ejection_seat_binding,
    check_gec_hybrid_tap_cardinality_binding,
    check_gec_mecs_tap_cardinality_binding,
    check_kncube_general_intent_equivalence_binding,
    check_mesh_seat_concentration_binding,
    check_qtree_depth_law_binding,
    check_ring_router_count_dateline_binding,
    check_torus_wrap_degree_binding,
    check_tree4_depth_law_binding,
)

FAMILY_GUARDS = {
    "mesh": (MeshIntent(3, 1), check_mesh_seat_concentration_binding,
             {"concentration": 2}, "MESH_SEAT_CONCENTRATION_MISMATCH"),
    "torus": (TorusIntent(3, 1), check_torus_wrap_degree_binding,
              "DROP_WRAP", "TORUS_WRAP_DEGREE_MISMATCH"),
    "cmesh": (ConcentratedMeshIntent(4, 4), check_cmesh_concentration_binding,
              {"concentration": 3}, "CMESH_CONCENTRATION_MISMATCH"),
    "ring": (RingIntent(64), check_ring_router_count_dateline_binding,
             {"router_count": 32}, "RING_ROUTER_COUNT_MISMATCH"),
    "flatfly": (FlatFlyIntent(4, 2, 1), check_flatfly_stage_law_binding,
                {"dimension_count": 3}, "FLATFLY_STAGE_LAW_MISMATCH"),
    "fly": (FlyIntent(4, 3), check_fly_ejection_seat_binding,
            "ZERO_EJECTION", "FLY_EJECTION_SEAT_MISMATCH"),
    "qtree": (QTreeIntent(4, 3), check_qtree_depth_law_binding,
              "BUMP_FIRST_SEAT", "QTREE_DEPTH_LAW_MISMATCH"),
    "tree4": (Tree4Intent(4, 3), check_tree4_depth_law_binding,
              "BUMP_FIRST_SEAT", "TREE4_DEPTH_LAW_MISMATCH"),
    "fattree": (FatTreeIntent(4, 2), check_fattree_level_radix_binding,
                {"level_count": 3}, "FATTREE_LEVEL_RADIX_MISMATCH"),
    "dragonflynew": (StructuredTopologyIntent(
        "dragonfly", {"radix": 4, "group_count": 3}),
        check_dragonflynew_radix_group_count_binding,
        {"params": {"radix": 4, "group_count": 4}},
        "DRAGONFLYNEW_RADIX_GROUP_COUNT_MISMATCH"),
    "gec_mecs": (GecTopologyIntent(GecMode.MULTIDROP, 4, 1, 1, 3),
                 check_gec_mecs_tap_cardinality_binding,
                 "DROP_TAP", "GEC_MECS_TAP_CARDINALITY_MISMATCH"),
    "gec_hybrid": (GecTopologyIntent(GecMode.HYBRID, 4, 1, 1, 3),
                   check_gec_hybrid_tap_cardinality_binding,
                   "DROP_TAP", "GEC_HYBRID_TAP_CARDINALITY_MISMATCH"),
}


def _agents():
    return (
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
    )


def _intents():
    return (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True,
                          atomic=False),)),
        AgentIntentV4(1, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=False,
                          atomic=False),)),
        AgentIntentV4(2),
    )


def _request(intent):
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE,
            dimension=CollectiveDimension.TP, payload_bytes=8192,
            traffic_class="tp_collective"),))
    return CompileRequestV4(
        workload=workload, agents=_agents(),
        dependencies=DependencyGraph(()), topology=intent,
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=2),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000),
        agent_intents=_intents())


def _compile(intent):
    request = _request(intent)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    return request, compiled


def _corrupt(compiled, spec):
    if spec == "DROP_WRAP":
        topology = compiled.bundle.topology
        coords = [tuple(r.coordinates) for r in topology.routers]
        kept = tuple(c for c in topology.channels
                     if not any(abs(a - b) == 2
                                for a, b in zip(coords[c.src_router],
                                                coords[c.dst_router])))
        object.__setattr__(
            topology, "channels",
            tuple(replace(c, channel_id=i) for i, c in enumerate(kept)))
        return compiled
    if spec == "ZERO_EJECTION":
        routers = list(compiled.bundle.topology.routers)
        target = next(r for r in routers
                      if getattr(r, "egress_seat_capacity", None)
                      not in (None, 0))
        routers[target.router_id] = replace(target, egress_seat_capacity=0)
        object.__setattr__(compiled.bundle.topology, "routers",
                           tuple(routers))
        return compiled
    if spec == "BUMP_FIRST_SEAT":
        routers = list(compiled.bundle.topology.routers)
        first = routers[0]
        routers[0] = replace(first, seat_capacity=first.seat_capacity + 1)
        object.__setattr__(compiled.bundle.topology, "routers",
                           tuple(routers))
        return compiled
    if spec == "DROP_TAP":
        links = list(compiled.bundle.topology.shared_links)
        first = links[0]
        object.__setattr__(first, "taps", tuple(first.taps[:-1]))
        return compiled
    raise AssertionError(f"unknown corruption {spec}")


@pytest.mark.parametrize("family", sorted(FAMILY_GUARDS), ids=sorted(FAMILY_GUARDS))
def test_baseline_passes(family):
    intent, guard, _, _ = FAMILY_GUARDS[family]
    request, compiled = _compile(intent)
    assert guard(request, compiled) is None
    assert check_family_binding_guards(request, compiled) is None


@pytest.mark.parametrize("family", sorted(FAMILY_GUARDS), ids=sorted(FAMILY_GUARDS))
def test_corruption_refuses_with_named_reason(family):
    intent, guard, spec, reason = FAMILY_GUARDS[family]
    request, compiled = _compile(intent)
    if isinstance(spec, dict):
        corrupted = replace(
            request, topology=replace(request.topology, **spec))
        with pytest.raises(FamilyBindingMismatch) as excinfo:
            guard(corrupted, compiled)
    else:
        _corrupt(compiled, spec)
        with pytest.raises(FamilyBindingMismatch) as excinfo:
            guard(request, compiled)
    assert reason in str(excinfo.value)


def test_kncube_mention_raises_blocker_verbatim_stub():
    stub_topology = SimpleNamespace(
        kind="kncube", parameters=lambda: {"k": 4, "n": 2})
    stub_request = SimpleNamespace(topology=stub_topology, agents=())
    stub_compiled = SimpleNamespace(
        status="COMPILED", bundle=SimpleNamespace(
            topology=SimpleNamespace(routers=())))
    with pytest.raises(FamilyBindingMismatch) as excinfo:
        check_kncube_general_intent_equivalence_binding(
            stub_request, stub_compiled)
    assert KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING in str(
        excinfo.value)


def test_kncube_structured_mention_raises_blocker():
    class _Stub:  # registry refuses construction; simulate post-hoc mention
        kind = "structured"

        @staticmethod
        def parameters():
            return {"family": "kncube", "params": {"k": 4, "n": 2}}

    request = SimpleNamespace(topology=_Stub(), agents=())
    with pytest.raises(FamilyBindingMismatch) as excinfo:
        check_kncube_general_intent_equivalence_binding(request, None)
    assert KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING in str(
        excinfo.value)


def test_non_applicable_family_returns_none():
    request, compiled = _compile(TorusIntent(3, 1))
    assert check_mesh_seat_concentration_binding(request, compiled) is None
    assert check_cmesh_concentration_binding(request, compiled) is None
    assert (check_kncube_general_intent_equivalence_binding(
        request, compiled) is None)
```

Notes on the skeleton:

- The `DROP_WRAP`, `ZERO_EJECTION`, `BUMP_FIRST_SEAT`, `DROP_TAP` corruptions
  are lifted verbatim from `tests/test_family_bad_design.py` so behavior
  parity is auditable.
- `test_baseline_passes` also pins the dispatcher: any future guard that
  false-positives on a certified baseline fails loudly here.
- The wiring change to `test_family_bad_design.py` (separate commit):
  move the 13 entries out of `NOT_COVERED`, assert the new named reasons in
  `test_family_bad_design_knob_has_no_watcher`, and keep the
  `test_not_covered_map_is_exactly_the_families_without_asserted_refusal`
  invariant by renaming the surviving map.

---

## 4. Verification performed (this change)

| Check | Result |
|---|---|
| `PYTHONPATH=tracks/t3-topology/dse python -c "import veritx_dse.product.family_binding_guards"` | OK, 13 guards registered |
| `PYTHONPATH=tracks/t3-topology/dse python -c "import family_binding_guards"` (literal command from the brief) | `ModuleNotFoundError` — expected: the module is a package submodule (`veritx_dse.product.family_binding_guards`), not a top-level module; `tracks/t3-topology/dse` is the package root, and nothing may be added outside the two new files to change that |
| FabricCompiler baselines ×12 (mesh, torus, cmesh, ring, flatfly, fly, qtree, tree4, fattree, dragonflynew, gec_mecs, gec_hybrid) through every owning guard | All `None` |
| `check_family_binding_guards` on each baseline | `None` |
| Corruption probes ×12 (concentration re-declare, wrap-channel drop+re-id, seat bump, egress zeroing, tap drop, level/group/dimension re-declare) | All raise `FamilyBindingMismatch` with the expected named reason |
| kncube stub (`SimpleNamespace(kind="kncube")`) | Raises `KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING` |

No builds, no RTL, no test-suite execution; smoke checks were in-process and
left no files behind. The only files created are
`tracks/t3-topology/dse/veritx_dse/product/family_binding_guards.py` and this
document.

## 5. Limitations and honest non-claims

- Guards are **binding attestations**, not proofs: a bundle whose declared
  intent matches every guard can still be functionally wrong. They close the
  "handed the wrong bundle" hole the `NOT_COVERED` notes describe, nothing
  more.
- `fattree` and `dragonflynew` re-derive the construction law in-module
  (`_fat_tree_edges`, `_dragonfly_edges`) instead of calling
  `STRUCTURED_FAMILIES["fattree"]["build"]`. Intentional: avoids importing
  `topology_artifact` at module scope and keeps `family_binding_guards` a
  leaf-ish module. If the canonical graph moves, this re-derivation must move
  with it — flagged in §1.9/§1.10.
- `gec_mecs`/`gec_hybrid` subsume the existing tap-identity comparison with a
  named per-wire reason; the `taps_per_wire = destinations_per_express_channel`
  assignment in `gec_mecs_shared_params_from_request` is now checked, not
  assumed.
- `kncube` has no positive predicate to verify, by design — the guard refuses
  to attest. Any future general-intent/native-equivalence checker must replace
  `check_kncube_general_intent_equivalence_binding`, not silence it.
- Wiring into `project_top_rtl.py` is specified in §2 but **not applied**;
  until it lands, the guards are inert (importable, callable, uncalled).


## SUPERSEDED — 2026-11-10

While this proposal was being written, the parallel session wired binding conformance directly into the product checkers: `check_composed_family_profile` (and the shared GEC/SROTA profile checks) now compare the **saved topology intent** against the compiled bundle and refuse with `UNSUPPORTED_COMPOSED_FAMILY`, proven by a mutation witness per family in `tracks/t3-topology/dse/tests/test_family_bad_design.py` (`BINDING_MUTATIONS` = 13 families; srota covered by its own witnesses; 58/58 green).

Because that closes the same gap with the product's own checker, the standalone module written here (`veritx_dse/product/family_binding_guards.py`) was **deleted rather than wired**: two independent implementations of the same rules is a second source of truth, which this repo's own audit flags as a footgun (`_tmp_router.py` precedent in the P4 audit). The per-family refusal semantics documented below remain the reference for *what each guard must catch*; the implementation now lives in the product checker.

Coverage after supersession: mesh concentration, torus wrap-degree, cmesh concentration, ring router_count/dateline, flatfly stage law, fly ejection-seat split, qtree/tree4 depth law, fattree level_count/switch_radix, dragonflynew radix/group_count, gec_mecs/gec_hybrid per-wire tap identity, kncube general intent (wrap/dimension binding) — all asserted as mutation witnesses.
