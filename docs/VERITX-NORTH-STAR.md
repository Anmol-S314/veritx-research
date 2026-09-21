# VeriTX North Star — frozen target-state reference

**This is a reference architecture, not runtime code.** It is the destination
shape the live repository is being cut over to. Production code must not import
it, depend on it, or be validated against it at runtime.

- Reference tree: [`reference/target-architecture/`](../reference/target-architecture/)
- Rules and layout: [`ARCHITECTURE.md`](../reference/target-architecture/ARCHITECTURE.md)
- Cutover order: [`MIGRATION_CUTOVER.md`](../reference/target-architecture/MIGRATION_CUTOVER.md)
- Module inventory: [`TARGET_FILE_TREE.txt`](../reference/target-architecture/TARGET_FILE_TREE.txt)
- Validation: [`TEST_REPORT.txt`](../reference/target-architecture/TEST_REPORT.txt),
  `MANIFEST.sha256` (63 entries)

## What it settles

These are rulings, not suggestions. Future work is rejected against them
instead of re-litigating the architecture every few commits.

1. **One live authority per scientific concept.** `WorkloadGraph`,
   `ParallelismArtifact`, `MappingArtifact`, `ResolvedFabric`, `EvidenceArtifact`,
   `PerformanceResult`, optimization definition/result. No shadow copies.
2. **Development-wave vocabulary does not survive.** `waved/`, `wavee/`,
   `WaveDWorkload`, `WaveEPerformanceModel`, wave-specific resource modules and
   forwarding compatibility shims are absent from live code by design.
3. **Backend evidence is byte-authenticated.** `EvidenceArtifact` digests the
   backend input bytes, the raw backend output bytes, and the parsed counters,
   and carries the parser version. A result refuses evidence produced for a
   different backend input. This is stronger than "counters with a backend
   name" and must not regress during the cutover.
4. **Mapping is a persisted authority, not an integer comparison.**
   `participant rank -> physical endpoint` is identified and persisted, so a
   multi-instance workload fails physical lowering because no mapping exists —
   not because two unrelated integers happen to differ.
5. **Unsupported capability refuses explicitly.** Backends that cannot produce
   authenticated evidence raise; they never fabricate a scientific claim.

## What is transitional in the live repository

The following exist **only** to keep historical evidence verifiable while the
cutover lands. They are scaffolding with a deletion owner, not destination
architecture:

- chain `v1`/`v2` generations, `chain_schema_version`, `PLAN_CHAIN_KEYS_V1/V2`,
  dual loaders;
- `waved_resources.py` / `wave_e_resources.py` and other wave-named resource
  modules;
- `NetworkWindowBinding`'s v1 generation, retained for byte-identical
  historical serialization.

## How to use it

- Before adding a concept, check whether the reference already names its owner.
- When live code and the reference disagree, one of them is wrong: fix the
  disagreement explicitly rather than growing a third option.
- Do not "improve" the reference opportunistically — its digests and manifest
  are what make it a ruler. A change to it is an architecture change and needs
  the same evidence discipline as a cutover commit.

## Enforcement

`tracks/t3-topology/dse/tests/test_architecture_law.py::TestTargetArchitectureReferenceIsNotRuntime`
guards the boundary:

- no production module imports the reference tree;
- the reference `src/` is never on `sys.path` (its package is also named
  `veritx_dse`, so it would shadow production silently);
- the importable `veritx_dse` resolves inside the production tree;
- the reference manifest verifies whenever the tree is present on the branch.
