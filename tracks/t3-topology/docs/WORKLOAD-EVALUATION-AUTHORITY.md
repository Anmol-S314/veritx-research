# Workload → evaluation authority (P1B.1)

What the product lowerer may assume, and what it must refuse.
Every claim below names its code site; grep-verified 2026-09-21.

## 1. `bytes_per_element` has no computational meaning

- Defined `model/compile_model.py:296-305`: `CollectiveOp.kind`,
  `group_size`, `bytes_per_element` (default 2048). No element-count
  field exists anywhere on the object.
- Producers: `CollectiveOp.from_dict` default only (`compile_model.py:321`).
- Consumers: NONE. Repository-wide grep for `bytes_per_element` hits
  only the definition, `to_dict`/`from_dict`, and a reports echo
  (`reports/reports.py:466`). The VC floor reads `group_size` only
  (`collective_vc_floor`, `compile_model.py:859`); no code path
  multiplies, divides, or packetizes it.
- Verdict: an opaque historical scalar. There is NO proof it means
  "total logical payload bytes contributed by one rank", so per the
  P1B hard rule it is not reinterpreted.
- Decision: new OPTIONAL `payload_bytes` on `CollectiveOp`
  (`None` = undeclared). `to_dict` omits it when `None`, so every
  pre-P1B document serializes and hashes byte-identically (proven by
  `test_collective_payload_contract.py`). `bytes_per_element` still
  parses and still hashes — historical versions keep their identity —
  but no lowering path reads it. Lowering without `payload_bytes`
  is `UNSUPPORTED_SEMANTICS`, not a guess.

## 2. A declared collective names no participant set

- `CollectiveOp` carries `group_size: int` only — no member list, no
  group id (`compile_model.py:296-300`).
- Participant law (P1B MVP): `group_size == workload.world_size`
  (`tp*pp*ep*dp`, `compile_model.py:389-392`) lowers to ranks
  `0..N-1`. Any other `group_size` without an explicit group
  declaration is `UNSUPPORTED_SEMANTICS` — ranks `0..7` are never
  chosen because they "seem lonely". Exact TP/DP/EP-derived groups
  come from the later workload synthesizer, not from inference here.

## 3. Order implies nothing the compiler can execute

- Dependencies: UNORDERED under semantics v2 — `canonical_dict`
  sorts them (`compile_model.py:1229-1230`); v1 order was
  identity-bearing and stays frozen for v1 documents.
- Collectives: ORDERED — `collective_vc_map` indexes contexts by
  position (`compile_model.py:862-874`), and the identity table in
  `CompileRequest.canonical_dict` lists collectives as ORDERED.
- P1B consequence: exactly one collective lowers to exactly one
  `COLLECTIVE` op (`deps=()`). Multi-collective sequencing is
  `UNSUPPORTED_SEMANTICS` until ordering is explicitly represented;
  BROADCAST without an explicit root is `UNSUPPORTED_SEMANTICS`
  (the canonical graph refuses an invented root —
  `workload/messages.py:141-147`).

## 4. What names a traffic class

- Dependency edges name classes: `Dependency.source/target` are
  free strings (`compile_model.py:445-455`).
- The P1A example declares `prefill-attn → prefill-ffn`, so VC
  derivation owns classes `{prefill-attn, prefill-ffn}`.
- Logical messages default to one artifact-level class
  `DEFAULT_TRAFFIC_CLASS = "DEFAULT"` (`workload/messages.py:46`);
  `LogicalMessageArtifactV2.traffic_class` defaults to it
  (`messages.py:461`).
- The VC artifact is authoritative at bind time only: class support
  is validated against `VCAssignmentArtifact.traffic_class_to_vcs`
  (`messages.py:49-56`), but nothing before P1B.3 called that check
  on the product path. P1A proved fabric legality, never message
  admission — the P1B.3 gate closes exactly this seam.

## 5. How a class name reaches the VC artifact

- `derive_vc_assignment` (`compile_model.py:908-993`): cycle
  victims get VC 1..k; every dependency class name not separated
  lands on VC 0 (`per_class_vc`, lines 969-976). `DEFAULT` is never
  inserted — a dependency-derived map alone cannot admit
  `DEFAULT` messages (P1B.3 fix).
- `derive_vc_assignment_artifact` (`compile_model.py:996-1042`)
  binds that map against the resolved route: every VC names its
  routing class, every route class gets ≥1 VC (coverage assertion).
  Acyclicity is proven by the certificate CDG obligation, never by
  the derivation string.

## 6. Content-addressed workload inputs

- `CompileRequest.design_hash()` — canonical semantic envelope
  (`compile_model.py:1238-1248`); execution provenance excluded.
- `WorkloadGraph.workload_id()` — semantic content only, provenance
  excluded (`workload/canonical_graph.py:878`).
- `LogicalMessageArtifactV2.message_artifact_id()`
  (`messages.py:598`), `PhysicalTrafficArtifactV2`
  `.physical_traffic_id()`, backend config/input hashes
  (`PreparedBackend`), `EvidenceRef.sha256`, stats digest
  (`performance/network.py:155-162`). The P1B evaluation binds all
  of these; see `application/fabric_evaluator.py`.

## 7. Lowerable without inference (P1B subset)

| Intent field | Lowered to | Rule |
|---|---|---|
| `model_family == DENSE_TRANSFORMER` | gate pass | anything else: `UNSUPPORTED_SEMANTICS` |
| `trace_path is None` | gate pass | any path: `UNSUPPORTED_SEMANTICS` (trace is a different authority) |
| `tp/pp/ep/dp` | `ParallelismArtifact` verbatim, `participant_count = world_size` | geometry must equal the bundle's inventory shape (`traffic.py:217-249`) |
| one collective, kind in {ALLREDUCE, ALLGATHER, REDUCESCATTER, ALLTOALL} | one `COLLECTIVE` op via `collective_detail`, participants `0..N-1` | kind string uppercased verbatim; `scope=None` stays `None` (undeclared is not ALL) |
| `collective.payload_bytes` | `payload_bytes` | `None`: `UNSUPPORTED_SEMANTICS`; never `bytes_per_element` |
| `serving_mode` | NOT lowered | `PREFILL_HEAVY` is a mix, not a phase; global phase stays absent |
| `requirements` | NOT consumed | aggregate BookSim latency is not per-QoS latency (P1C) |
| `dependencies` | NOT sequenced | single op has `deps=()`; edges only shaped VCs at compile time |

## 8. Network clock binding

- `PhysicalContext.default_clock_freq_mhz` is the system-level clock
  default (`compile_model.py:817-823`); the P1B slice declares no
  per-agent `clock_domain`, so it IS the fabric clock contract here.
- The evaluator builds `ClockDef("net", hz)` from it exactly
  (`Fraction(str(mhz)) * 10**6` — no float drift) and names it the
  model's `network_clock`. Cycles without this binding stay cycles
  (`bind_network_window` cycles-only mode).
- If per-agent clock domains ever appear, this binding must be
  revisited — not silently extended.
