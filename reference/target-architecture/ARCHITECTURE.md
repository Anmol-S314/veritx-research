# Final product architecture

## Rules

1. One live authority per scientific concept.
2. Development-wave names exist only in history/migration evidence.
3. Persisted children authenticate their parent identities.
4. Unsupported capability refuses explicitly.
5. Unit tests stay independent; integration scenarios prove the shared DAG.
6. Backend evidence authenticates the bytes it was derived from.

## Target package

```text
veritx_dse/
  core/          identity, errors, exact time
  model/         fabric, placement/mapping, parallelism, memory
  workload/      WorkloadGraph, collectives, messages, traffic, lowering
  performance/   timing model, scheduler, metrics, results
  backend/       BookSim, ASTRA, Ramulator, Timeloop adapters, evidence
  verification/  conservation, provenance, canonical scenarios
  optimization/  definition, search, constraints, Pareto, result
  application/   store, resources, service, comparison, results
  api.py
```

## Evidence authentication

An evaluation result is only as trustworthy as the bytes the backend
actually produced. One executed run yields exactly one `EvidenceArtifact`:

```text
PhysicalTraffic
    -> backend input bytes        backend_input_sha256
    -> backend executes
    -> raw evidence bytes         raw_evidence_sha256
    -> parsed counters            stats_sha256
    -> EvidenceArtifact           evidence_id (self-authenticating)
    -> EvaluationResult           refuses evidence from another input
```

- `BackendAdapter.evaluate()` returns the backend's own output bytes,
  unparsed; `parse()` turns exactly those bytes into counters plus the
  parser version that read them. Counters cannot be invented independently
  of the backend's output.
- A backend that emits no bytes fails (`BackendFailure`): counters with
  nothing to authenticate them are a fabrication risk, not a measurement.
- `EvaluationResult` refuses evidence whose `backend_input_id` is not its
  own `traffic_id`, so a valid artifact cannot be transplanted onto another
  traffic.
- `stats_sha256` authenticates the canonical counter mapping, and
  `parser_version` is identity-bearing: a different reader is a different
  scientific claim.
- `EvidenceArtifact.to_dict()` / `from_dict()` are tamper-closed: the
  embedded `evidence_id` is recomputed and checked on read.
- `ScientificChain` carries `evidence_id` and `stats_sha256`, so the parent
  chain covers the backend step rather than stopping at traffic.

## Explicitly absent from live code

- `waved/`
- `wavee/`
- `WaveDWorkload`
- `OperationGraph`
- `WorkloadArtifact`
- `WaveEPerformanceModel`
- wave-specific resource modules
- forwarding compatibility shims
