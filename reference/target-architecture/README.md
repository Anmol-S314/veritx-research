# VeriTX target-state reference package

This is a **reviewable target architecture**, not a blind patch over the
current repository. It intentionally contains no live `waved/`, `wavee/`,
`WaveD*`, or `WaveE*` product concepts.

Target scientific path:

`Intent -> Fabric/Mapping -> WorkloadGraph -> LogicalMessages ->
PhysicalTraffic -> Backend Evidence -> Performance -> Comparison -> Optimization`

Backend evidence is **byte-authenticated**, not asserted: `EvidenceArtifact`
digests the backend input bytes, the raw backend output bytes, and the parsed
counters, and carries the parser version that read them. `EvaluationResult`
refuses evidence produced for a different backend input, so a valid artifact
cannot be transplanted onto another traffic.

Tests are individually runnable, while the scientific-chain and identity-DAG
tests verify how the layers compose.

Real BookSim/ASTRA/Ramulator/Timeloop process integration remains behind
explicit backend boundaries. Unqualified or unavailable backends refuse
instead of fabricating scientific evidence.
