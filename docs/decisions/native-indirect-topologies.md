# Native topology contracts, without rewriting historical graphs

## Status

QTree implemented and product-wired as `qtree_native64`. Ring implemented and
product-wired as `ring_native64`. Native Tree4 implemented and product-wired as
`tree4_native64`. Multi-stage Fly implemented and product-wired as
`fly_native64`. None of these inherit another network's alias or
qualification. All four exact native constructions are now closed; what remains
is the optional generalization described at the end.

## Decision

Terminals and routers are independent namespaces. Transit-only routers have
zero local seats; attachment follows physical terminal placement, not a
router-count heuristic. The shared topology constructor accepts a complete
per-router seat map, while uniform fabrics retain their original bytes and
hashes. Zero seats are valid; negative, boolean and malformed values still
refuse. No historical document needs migration.

The existing structured `qtree` and `tree4` balanced-tree definitions keep
their names, graph constructions and hashes. They are not native BookSim
QTree/Tree4 definitions. New exact constructions receive distinct typed intent
and materialized-family identities.

## QTree implementation

- `QTreeIntent(radix=4, levels=3)`, serialized kind `qtree_native`.
  Unsupported native shapes and user-selected routing/VC fields refuse.
- 21 routers, 40 directed inter-router channels, and 64 terminals on 16 leaves.
  The root and four intermediate routers have no endpoint seats.
- Leaf terminal `t` attaches to router `5 + t // 4`, local port `t % 4`.
  Native child ports precede the parent port; the latter is port 4.
- A sealed `QTREE_NCA` routing class derives nearest-common-ancestor steps.
  Compiler certification operates on that actual policy, not an AnyNet alias.
- A dedicated `CERTIFIED_BOOKSIM_QTREE_NCA_V1` profile renders
  `topology=qtree; k=4; n=3; routing_function=nca`.
  Native geometry, terminal seating, algorithm parameters, unit link timing,
  single class and one derived VC are mandatory.
- Canonical router indices are dense. Native QTree internally uses
  `level * 256 + position` as Router::GetID. The existing dump ABI emits dense
  source indices, internal next-router IDs, and dense source indices again for
  local ejection with a null channel sink. The lowerer explicitly translates
  this ABI; it never conflates internal router IDs with terminal IDs.
- Every one of the 1,344 router/terminal pairs must match both next hop and
  output port. Port obligations enter prepared-input identity and cannot be
  stripped. A wrong ejection port is refused even if next-hop and aggregate
  delivery counters still match.
- Execution uses the existing pinned producer, supervised process, conservation
  and authenticated-evidence gates. No BookSim C++ change or producer exception
  was necessary.

Native smoke evidence:
[`native-qtree-smoke.json`](../design/reviews/evidence/native-qtree-smoke.json).
This is model execution, not measured hardware calibration. The new one-VC
canonical preset does not retroactively qualify or relabel historical four-VC
research results.

## Ring implementation

- `RingIntent(router_count=64)`, serialized kind `ring_native`. Fewer than
  three routers, boolean/negative counts and any locked routing or VC field
  refuse.
- 64 routers, 128 directed channels, one terminal seat on every router. The
  port law is fixed per router — index 0 leaves toward `+1`, index 1 toward
  `-1`, on every router INCLUDING the wrap router. The historical test-only
  `ring` fixture orders ports by neighbour id, which flips the port order on
  every interior router, so it cannot be reused as the native law.
- The native construction is its own `MaterializedFamily.RING_NATIVE`, the
  way the native tree is `QTREE` rather than `qtree`: sharing an enum member
  with the fixture would let either one's sealed routing class be reached
  from the other's geometry. `RING` therefore keeps no certified policy and
  `ring_native` is the only family the dateline envelope will accept.
- A sealed `RING_DATELINE` routing class derives the minimal wrap hop with a
  positive-direction tie. BookSim renders this as `topology=torus` with `n=1`,
  which IS one wraparound dimension; the square-torus class
  `DOR_TORUS_XY` is not inherited and would refuse a 1-D fabric.
- The ring needs exactly two VCs because the fork's 1-D dimension-order
  function integer-halves the VC range. That is a FABRIC requirement, added as
  `dateline_vc_floor` alongside the existing multidrop/shape/rank floors — a
  ring workload with no cyclic dependency still needs both halves.
- The VC half is a FLOW property, not a hop property: the fork sets `ph` once,
  at the decision that turns into the ring dimension, and every later hop only
  flips the output port. 12,823 executed hops across 731 flits confirm it:
  zero half violations against `partition(injection router, destination)`, and
  zero flits that change direction. A per-hop reading would invent a crossing
  on every wrapping flow.
- The even-k midpoint tie is a real `RandomInt(1)`, so the fork's deterministic
  dump REFUSES the whole fabric ("a state/RNG-dependent function has no
  deterministic first-hop table"). That refusal is correct and is not worked
  around by pretending the tie is deterministic. The producer now supports
  `routing_dump_choice_probes`: it probes each (router, destination) N times
  and emits every DISTINCT outcome under a versioned legal-choice-union
  header. The consumer compares that union against its own legal set, so the
  coin is evidence.
- Certification is total over the fabric: all 4,032 router/destination pairs
  present, 3,968 deterministic pairs matching the model's hop AND native port
  exactly, 64 diametral pairs confined to their two legal hops, and more than
  one outcome on a deterministic pair refused as nondeterminism the law does
  not declare. The deadlock proof expands both faces of every tie.
- The runtime route-compute dump adds what a first-hop table cannot carry: the
  VC half of every executed hop, port continuity (`in == previous out ^ 1`),
  injection-port entry and single-direction traversal.
- Product execution records both evidence sets in the run's backend evidence
  (`ring_route_union`, `ring_route_computations`) with the union digest as the
  route digest. A prepared input carrying single-row ring obligations is
  refused, so a fictional deterministic dialect cannot slip in.

Native smoke evidence:
[`native-ring-smoke.json`](../design/reviews/evidence/native-ring-smoke.json).
Model execution, not measured hardware calibration.

## Tree4 implementation

- `Tree4Intent(radix=4, levels=3)`, kind `tree4_native`; any other radix/level
  pair and every locked routing/VC field refuse.
- 28 routers — 4 roots, 8 middles, 16 leaves — with 128 directed channels and
  64 terminal seats (four per leaf, none on transit routers). The port law is
  fixed by level: a root leaves down through ports 0..7 (its middles), a middle
  through 0..3 (its four leaves) and 4..7 (the four roots), a leaf through 0..3
  (its seats) and 4..5 (its two parents). The native construction is its own
  `MaterializedFamily.TREE4_NATIVE`, so the structured balanced `tree4` preset
  cannot reach this routing class or vice versa.
- `RandomInt(max)` in this fork is INCLUSIVE. `gK + RandomInt(gK-1)` therefore
  picks ANY of the four roots, not three of them: reading it as exclusive would
  have claimed root 3 is unreachable, and the producer's union dump shows port
  7 in use. The class parameters record the union rather than a single parent.
- Sealed `TREE4_NCA` class declares the executed law as a legal-choice union —
  two destination-group middles at a root, four roots at a middle, two parents
  at a leaf — while its canonical `entries` table carries only the smallest
  legal port as a witness. `tree4_witness_path` proves that witness reaches all
  28x28 router pairs within four hops, so the table is total and legal.
- Deadlock is proven with a DESTINATION-INDEXED channel/VC expansion: channel
  `a` may be followed by `b` only when both carry the SAME terminal. A coarse
  graph would report a cycle nobody can take (`middle -> leaf` is only chosen
  when the leaf is the destination, and a flit at its destination ejects). The
  up*/down* discipline is therefore derived from the law, not assumed: the
  proof has 128 channel-VC nodes and is acyclic.
- The first-hop table cannot state this fabric, so certification uses the
  producer's legal-choice union dump AND the runtime route-compute dump. The
  profile pins `routing_dump_choice_probes = 64`: with eight probes a four-face
  coin is genuinely sampled rather than exhausted (real pairs came back as
  strict subsets), which would have looked like an incomplete union.
- Union verification is two-directional: every hop the producer realises is
  inside the law, every deterministic pair matches exactly, and fabric-wide
  every legal face appears at least once. A model face the producer never shows
  is refused as invented. 1,792 pairs verify (192 deterministic, 1,600
  choice-valued).
- The runtime dump adds what a first-hop union cannot carry: the executed hop
  for each flit, the source terminal's seat port on its first decision, the full
  0..vcEnd range the fork assigns to ANY_TYPE, destination-only ejection, and
  the climb-then-descend discipline (a climb after a descent is not a Tree4
  traversal). 39,312 executed decisions across 24,192 flits verify with zero
  violations.

Native smoke evidence:
[`native-tree4-smoke.json`](../design/reviews/evidence/native-tree4-smoke.json).
Model execution, not measured hardware calibration.

## Verification

`tracks/t3-topology/dse/tests/test_native_qtree.py` covers declaration,
round-trip identity, geometry, leaf placement, native profile selection,
changed-parent refusal, complete native hop/port differential, authenticated
execution, missing obligations and corrupted local-ejection evidence.
Existing routing/attachment/topology goldens and historical tree hashes remain
checks, not rewritten expected values.

The ring slice adds `test_native_ring.py` (18 tests: declaration, geometry and
the wrap-router port law, designed 2-VC derivation, flow-level halves, CDG
acyclicity over both tie faces, profile selection, union-dialect parsing,
complete union differential, runtime half/continuity differential,
authenticated product execution, and adversarial union/half/nondeterminism
refusal).

The Tree4 slice adds `test_native_tree4.py` (19 tests: declaration and locked
fields, 28-router geometry and per-level port law, identity distinct from the
balanced tree, the legal union including the inclusive `RandomInt` face,
canonical-witness termination over all 784 router pairs, destination-indexed
CDG acyclicity, profile selection and pinned probe count, geometry/seat-law
refusal, the union differential against the real producer, deterministic-dialect
refusal, authenticated product execution, single-row refusal, illegal-hop
refusal, undeclared-nondeterminism refusal, incomplete-union refusal,
unreached-face refusal, corrupted runtime refusal and pinned-geometry refusal).

Verification for this slice: **413 targeted tests passed**, plus **six preset
catalog/project checks**. The native QTree test also exercises preset project
creation, compile, a real federation job and archived run analysis, in addition
to native hop/port comparison and adversarial evidence rejection. The family-registry checker
and `git diff --check` pass. Pytest still warns about the pre-existing unknown
`timeout` configuration option. The preset is available through the existing
catalog; the prototype's generic topology editor preserves this new declaration
read-only rather than guessing unsupported editing fields. Installed desktop
bundles require rebuilding; no installer or native GUI performance claim is
made by these compiler tests.

## Fly implementation

- `FlyIntent(radix=4, levels=3)`, serialized kind `fly_native`. Unsupported
  shapes and user-selected routing fields refuse.
- 48 routers (3 stages of 16), 128 one-directional inter-stage channels, 64
  terminals. Router ids and channel ids are BookSim's own
  (`stage * k**(n-1) + addr`, `stage * k**n + addr * k + port`).
- Slot law is DIRECTION-SPECIFIC: stage-0 routers own the `k` ingress slots,
  stage-2 routers own the `k` egress slots, the middle stage owns none. This is
  a new topology-model field (`Router.egress_seat_capacity`), emitted only when
  it is set, so every existing fabric keeps its exact bytes and hash.
- A terminal's attachment is the pair
  `(stage-0 router, port) -> (stage-2 router, port)`. `Endpoint` gained an
  OPTIONAL egress location with the same serialization rule, and an artifact is
  either symmetric everywhere or asymmetric everywhere — never mixed.
- `routing_router(endpoint)` names the router a flow is *routed toward*
  (ingress normally, egress here). `ResolvedRouteArtifact` records the ingress
  in `endpoint_to_router` and the differing routing addresses in a separate
  optional field, so "where the agent attaches" and "where its traffic is
  destined" cannot collapse into one another.
- Sealed routing class `FLY_DEST_TAG` (`algorithm = destination_tag`): the
  literal `dest_tag_fly` rule, deterministic, one port per
  (router, destination). Its pair domain is therefore partial — the routable
  destinations are the stage-2 ejection routers — and the class DECLARES that
  domain, which is what `ROUTE_COMPLETE` and `RouteArtifact.validate_against`
  now measure instead of assuming router x router.
- The generic stateless routing normalizer refuses `FLY_DEST_TAG` rather than
  inventing a total router relation; the destination-indexed CDG (per terminal
  3-hop chain) is the deadlock proof.
- Profile `CERTIFIED_BOOKSIM_FLY_DEST_TAG_V1`, lowerer `FLYDESTTAG/1`. The
  one-way channel graph is the construction (BookSim's `KNFly` builds the
  wiring itself from `k` and `n`), so the symmetric-fabric guard exempts this
  profile only for a fabric whose every channel advances exactly one stage.
- Both evidence obligations are required and were produced by a
  manifest-verified clean producer (`ec80b469…` @ `f71b10b3…`, `dirty false`):
  the deterministic static dump is compared row-for-row AND port-for-port over
  all 3,072 (router, terminal) pairs, and the runtime route-compute dump proves
  one-stage-per-hop advance, the flow's own injection router, the
  destination-tag port, the whole VC range and ejection at the destination's
  own stage-2 router. Evidence:
  `docs/design/reviews/evidence/native-fly-smoke.json`.
- Preset `fly_native64`; registry row `fly_native`; tests
  `tests/test_native_fly.py`.

## Remaining construction-specific work

### Tree4 (done)

Shipped as documented above. The producer instrumentation it needed
(`routing_dump_choice_probes`, the versioned legal-choice union dump) landed as
a clean attributable build before this evidence was produced.

### Ring (done)

Shipped as documented above. Its runtime route-compute evidence has since been
joined by Tree4 and Fly, which use the same dump for the same reason: a static
table cannot show which hop the hardware executed.

### Multi-stage Fly (done)

Shipped as documented above. The versioned attachment interface was the
blocking item, and it landed as an OPTIONAL field on `Endpoint` plus an
optional direction-specific slot count on `Router`, so not one historical
attachment or fabric identity moved.

### Left over, and deliberately not done

- The generic routing normalizer still refuses `FLY_DEST_TAG` and
  `RING_DATELINE`. Giving them an allocation-time adapter is Phase B work; the
  destination-indexed / dateline CDGs are the proofs in the meantime.
- A fabric whose terminals inject and eject at different routers has no v3
  (shared-wire) endpoint expansion; that path refuses by name instead of
  approximating.
