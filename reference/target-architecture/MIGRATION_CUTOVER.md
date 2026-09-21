# Cutover from the current repository

This archive is the **destination shape**. Do not copy it over the repository in
one commit.

Recommended cutover:

1. Finish the current WorkloadGraph runtime cutover.
2. Delete `WorkloadArtifact`, `WaveDWorkload`, `OperationGraph`, and old
   communication side lists.
3. Rename the surviving workload module to `workload/graph.py`.
4. Move Wave-E implementation mechanically into `performance/`.
5. Keep historical persisted-resource readers narrow and read-only.
6. Carry evidence authentication across the cutover: backend input digest,
   raw evidence digest, stats digest, and parser version belong in
   `backend/evidence.py`, and a result must refuse evidence it cannot
   authenticate. The current repository already authenticates the exact
   evidence bytes (`EvidenceRef`, digest-on-reuse, refuse-different-content);
   the destination must not weaken that.
7. Move new persistence to semantic resource names (`workload`, `messages`,
   `traffic`, `evidence`, `performance`, `result`) with new schema/hash
   domains.
8. Remove live `wave_d`, `wave_e`, `waved`, and `wavee` vocabulary.
9. Reconcile Wave F against the consolidated application/performance API.
10. Build a dedicated integration worktree and replay only surviving
    capabilities from divergent branches.
11. Seal with canonical scenarios, identity-DAG metamorphic tests,
    cross-backend semantic checks, and real backend qualification.

Do not preserve a dead package merely because an old artifact name contains its
historical vocabulary. Old formats are data formats, not architecture.
