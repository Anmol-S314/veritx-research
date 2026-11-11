# Workload-driven custom topology synthesis

The synthesizers and the explicit-topology path already existed; this bridge
connects them:

```python
from veritx_dse.synthesis.definition import SynthesisDefinition
from veritx_dse.synthesis.workload_topology import synthesize_request

result = synthesize_request(
    base_request,
    SynthesisDefinition(
        nodes=16, layout="grid", k=4, radix=4, max_len=4.0,
        bandwidth_GBs=50.0, latency_ns=500.0,
        max_nodes=20, timeout_s=30,
    ),
)
result.request        # CompileRequestV4 with ExplicitTopologyIntent
result.candidate      # TopologyCandidate: links, algorithm, solver status
result.matrix         # SynthesisTrafficMatrix with provenance
result.compilation    # FabricCompiler outcome
```

## Pipeline

1. Lower the workload and build the logical-message artifact (V3 for
   multi-class, V2 otherwise).
2. `SynthesisTrafficMatrix.from_message_artifact` → N×N byte-demand matrix.
3. Pad to the definition's node count when the graph must seat more agents
   than workload participants. Padding adds zero-demand nodes and changes the
   matrix identity.
4. `synthesize(definition, matrix)` → `TopologyCandidate`.
5. Convert links to a `TopologyIR(kind="custom")` and an
   `ExplicitTopologyIntent`.
6. Compile through `FabricCompiler`; attachment and verification are the
   authority.

## Constraints

- Synthesis definitions are `grid` (`k*k == nodes`) or `interposer`
  (`rows*cols == nodes`) only.
- An explicit graph seats one agent per router node. A graph smaller than the
  agent inventory is refused at `ATTACHMENT`; no agent is dropped.
- The RTL preview still supports 2–64 routers. A graph large enough to seat
  74 agents (9×9 = 81) is outside that slice.
- Explicit graphs route on `ANYNET_MIN_HOPS`; they are not the native
  mesh-DOR path.

## The real gate is deadlock freedom, not graph generation

A 16-node/22-agent example was refused at `ATTACHMENT` because the graph had
too few seats. A 25-node SA-synthesized graph seated the agents but was
refused at `VERIFICATION`:

```text
certificate obligations failed: ['DEADLOCK_FREE']
```

A 25-node MILP-synthesized graph was refused even earlier, at `ROUTING`:

```text
UNREPRESENTABLE: ANYNET_MIN_HOPS cannot be materialized on this topology:
topology is disconnected — a partial first-hop table is not a route artifact
```

That is the correct refusal. The synthesizers optimize traffic-weighted hops;
they do not enforce connectivity or a deadlock-free routing/VC assignment.
Zero-demand padded nodes can be left disconnected, and a cyclic graph under a
single-VC min-hop route has a cyclic channel dependency graph.

So the missing layer is not another graph generator. It is a **fabric
validity layer**: connectivity repair, then a deadlock-free routing/VC law
(up*/down* with an escape tree/VC, or a graph class with a proof). Until that
exists, custom synthesis is a candidate generator with an honest verification
gate, not a guaranteed fabric. The 12-family catalog remains the reliable
selection path.
