# Capability truth — why it exists

Extracted from `veritx_dse/application/capability_truth.py`.

## The recurring failure

We have repeatedly shipped documentation claiming a capability the compiler or
evaluator could not actually execute.

Historical instance: `docs/product/topology-family-registry.yaml` marked
`CONCENTRATED_MESH` as `PROJECTABLE: YES, EXECUTABLE: YES, QUALIFIED: YES` back
when `select_booksim_profile()` had only two certified profiles — the native
mesh-DOR profile (guard: `TopologyArtifact.family is MaterializedFamily.MESH`)
and the AnyNet profile (requires `ANYNET_MIN_HOPS`). Concentrated mesh
materializes as `MaterializedFamily.CONCENTRATED_MESH` and routes `DOR_XY`, so
it satisfied **neither**. The registry was describing an intention, not a fact.

P2 closed that specific gap with the dedicated
`CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1` profile. The live truth now derives
`CONCENTRATED_MESH` stages from the real selector, which chooses that profile
for a qualifying fabric.

## The law

A descriptive registry may add prose and provenance. It may **not** claim a
stage that has no implementation authority. This module derives stage truth by
**asking the actual implementation** — compiling a probe design and running the
real profile selector — and `scripts/check_capability_truth.py` fails CI when
the registry disagrees.

Stages are derived independently: one becoming `YES` never implies another.

## Stage sources (§18)

- **Probe coverage is derived from the topology-intent registry** (§18.1).
  A hand-maintained family list drifts (the previous one came from the legacy
  `TopologyFamily` enum and could not see FlatFly or FatTree). Coverage is
  `AUTHORABLE_INTENT_KINDS` plus the GEC physical subfamilies. A registered
  kind with no probe factory is a gate failure, not a silent omission
  (`missing_probe_kinds()`).
- **Probe shapes live with the probe** (§18.2): no second shape table. Each
  probe is the smallest design that exercises the family's real path; a probe
  that cannot materialize is itself the answer.
- **Structured stage recovery** (§18.3): `StagedDerivation.produced_stages` /
  `.stopped_at_stage` are the authority. The regex fallback is retained only
  for the historical v2 path, which has no structured record.
- **`PRODUCT_WIRED` has no family-name shortcut** (Phase B.2 §8): `.kind ==
  "gec"` is true for all four GEC modes, so a single generic GEC preset would
  wrongly wire every mode. The preset request is normalized through the real
  generation seam and the resulting capability label compared.
- **`PROJECTABLE` ≠ profile selection**: selection is necessary but not
  sufficient; the real `prepare_booksim_input` path answers it.
- **`EXECUTABLE` is fail-closed**: the registered handler must *resolve to a
  callable*; a registry string alone is not availability.
- **`QUALIFIED` is decided by the real qualifier** over the real canonical
  parents under an exact projection-semantics match; selecting or preparing a
  profile never implies qualification.
- **Direct materialize/route probes**: a compilation that fails at verification
  (e.g. torus `DEADLOCK_FREE`) drops its staged record and bundle, which would
  mis-report `MATERIALIZABLE`/`ROUTABLE` as `NO`. The probe calls the canonical
  seams directly with the same intent — never a parallel authority.
