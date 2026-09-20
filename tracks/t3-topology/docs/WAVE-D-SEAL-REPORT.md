# Wave D seal report

Status: **SEALED v1 supported domain** (final patch: D-SEAL.1 result
provenance binding).

```
branch      wave-d/distributed-semantics
base        Wave C-SEAL.1 8455c0450e27486ae034028b76c9a05b94f2ea72
D0 freeze   75452bd34c0673303a51da83b0d0871fc9623acb (D0.2)
contract    docs/WAVE-D-SCIENTIFIC-CONTRACT.md (38 sections)
machine     docs/wave-d-contract.json (revision 5, status SEALED_V1)
```

The D0 audit listed six open items; the architecture audit that followed
found five deeper failures underneath them. This report closes all of
them and states what remains out of scope.

## 1. What the seal changed

| # | Failure | Closure |
|---|---|---|
| 1 | `WaveDWorkloadSemantics.shape_metadata` and `OperationNode.detail` were mutable dicts inside frozen dataclasses, so a caller could mutate an artifact's identity after construction (and split a parent ID from already-lowered child semantics) | `waved/immutable.py` — every caller-owned container is copied into a `FrozenMap`/tuple tree; `thaw()` at JSON boundaries. Swept across all Wave-D dataclasses; `PhysicalTrafficArtifact` no longer retains mutable rank→endpoint caches |
| 2 | Same-world-size cross-geometry transposition was not refused (TP=4/PP=1 logical traffic could bind a TP=2/PP=2 bundle) | `PhysicalTrafficArtifact` requires `logical.graph.parallelism == bundle.inventory.parallelism` **and** the compiled design workload geometry; `SrotaControlPlane` applies the same seam at compile time. Equal world size is explicitly not semantic equivalence |
| 3 | Physical traffic trusted a `ResolvedFabricBundle` by type | `bundle.revalidate()` (Wave-B's own seam) runs before any rank→endpoint binding; a bundle assembled around a stale child refuses |
| 4 | `from_dict` accepted missing embedded IDs / missing type tags, and graph/messages/traffic had no parsing at all | `waved/strict.py` + `strict=True` parsers for all six artifacts: exact type tag, exact schema version, required embedded ID, unknown fields refused, parent IDs required and matched |
| 5 | No persisted chain, no verified loaders | Six content-addressed resource kinds (`wavedworkload`, `parallelism`, `wavedsemantics`, `opgraph`, `messages`, `traffic`) + `application/waved_resources.py` loaders enforcing `filename == embedded == recomputed` and resolved verified parents. The ConservationLedger is derived, never persisted |
| 6 | Adversarial tests were fake (mutated a copy, validated the original; conditional asserts; a test named for flit width that built two identical bundles) | Rewritten. Every adversarial test feeds a mutated object into a real production validator/loader, or asserts on a genuinely different artifact |
| 7 | Wave D had modified the sealed Wave-B evidence schema (`injected_packets`) | Reverted. `CertifiedBookSimEvidence` and `parse_trace_injected` are back to their Wave-B-frozen form; quiescence uses only sealed counters (`delivered`, `flits_injected`, `flits_accepted`) |
| 8 | Wave-C never consumed Wave D: two science paths existed | `SrotaControlPlane` is the single authority. `Intent.workload.wave_d` declares an explicit semantic workload; compile/plan/evaluate route it through the verified chain, and the BookSim trace is a DERIVED backend input. Legacy packet traces keep the legacy path and are labelled `LEGACY_TRACE` |
| 9 | **Result → plan provenance edge unverified.** The verifier proved the result's Wave-D chain was *internally valid*, never that it was *this plan's* chain. Phase is not representable in the five-column BookSim trace, so a DECODE and a PREFILL workload render byte-identical traffic; a fully valid chain from the other experiment could be transplanted into a successful result and still verify. The result's `wave_d` block was also not schema-closed, so arbitrary scientific-looking fields survived VERIFIED | `_verify_waved_result()` now closes the block schema (exactly `PLAN_CHAIN_KEYS + EXECUTION_RESULT_KEYS`), requires every plan-chain field to match the result exactly, re-derives the chain from the **plan's** traffic parent, and re-derives the execution counters from that traffic and the authenticated evidence. `waved_resources` owns the one key-set definition and both block constructors assert they emit exactly it |

## 2. Bug found by the new tests

The multicast branch of `PhysicalTrafficArtifact.conservation_ledger()`
read `payload_bytes` from the node's link detail, which carries only the
multicast id. Every multicast workload raised `KeyError` at the ledger
stage — the pre-existing tests never exercised it. Fixed to read the
authoritative `MulticastIntent`; `test_multicast_end_to_end` now runs a
real multicast trace through qualified BookSim.

## 3. Proof suites

```
dse/tests/test_wave_d_semantics.py       collective/P2P/multicast laws,
                                         256-combination parallelism sweep,
                                         F=65 non-byte-aligned flits,
                                         oracle differentials
dse/tests/test_wave_d_physical.py        packet/flit identity, real
                                         logical↔physical separation,
                                         strict-parser refusals,
                                         forged-row detection,
                                         real executions (ALLREDUCE, mixed
                                         P2P, BROADCAST, multicast) with
                                         sealed-counter quiescence
dse/tests/test_wave_d_authenticity.py    parent binding + mutation matrix
dse/tests/test_wave_d_contract.py        contract/D0 audit pins
dse/tests/test_wave_d_seal.py            transitive immutability, geometry
                                         transposition refusal, strict
                                         parsing, verified loaders,
                                         parent transplants, plan identity
                                         separation at identical bytes,
                                         product E2E, product tamper,
                                         result->plan provenance binding
```

## 4. What is verified, mechanically

```
immutability     mutating a caller's dict never changes an ID or a child
geometry         TP=4/PP=1 logical vs TP=2/PP=2 bundle refuses (ws=4 both)
strict parse     missing type/version/ID, unknown fields, forged IDs refuse
transplants      workload_id / parallelism_id / wave_d_semantics_id /
                 operation_graph_id / message_artifact_id /
                 resolved_fabric_hash / packet_format_hash swaps refuse
separation       different mapping or packet format keeps operation_graph_id
                 and message_artifact_id, moves physical_traffic_id
anti-collision   identical rendered trace bytes from a legacy intent and a
                 Wave-D intent produce different workload/plan identities
product E2E      compile -> plan -> evaluate -> load_verified_result, then
                 walk every verified parent and match all IDs
product tamper   tampering a persisted opgraph/messages/traffic row, or the
                 result's own wave_d block, makes the result non-VERIFIED
provenance       a fully VALID Wave-D chain from another experiment cannot
                 be transplanted into a result (refused as a provenance
                 mismatch, proven after independently verifying the
                 transplanted chain); unknown, missing-chain and
                 missing-execution fields all refuse
reuse            a transplanted result link never reuses another
                 experiment's science
```

## 5. Residuals (declared, not hidden)

| item | status |
|---|---|
| KV movement and expert-routing lowering | UNSUPPORTED (refused), contract §14 |
| physical-node semantics, multi-instance, P/D disaggregation | DEFERRED, contract §31 |
| uneven collective chunking (`B % k != 0`) | UNSUPPORTED (refused), contract §10.2 |
| model-shape → operation synthesis | DEFERRED — nothing infers ops from shape |
| embedded route dump export | NOT_RUN (external contract, contract §36) |
| ASTRA / serving / analytical / RTL-UVM-formal execution | unchanged from Wave C: NOT INTEGRATED / BLOCKED / UNSUPPORTED / NOT_RUN |
| `EXTERNAL-CONTRACT-NEEDED` EXT-1..EXT-5 | open, contract §36 |
| pre-existing DSE test failures (26) | environment-dependent (gitignored `archive/`/`runs/` assets, unbuilt vendored binaries); identical node set to the pre-Wave-D baseline |

## 6. The provenance edge (D-SEAL.1)

Two individually truthful statements can collaborate on a lie: "plan A
is valid" and "chain B is valid" do not imply "result A came from chain
B". The attack is real and was reproduced before the fix:

```
A: DECODE  ALLREDUCE ranks 0..3 payload 1024 mesh4
B: PREFILL ALLREDUCE ranks 0..3 payload 1024 mesh4
A.plan_id != B.plan_id, A.wave_d.*_id != B.wave_d.*_id
rendered BookSim trace A == rendered BookSim trace B   (phase is lossy)
120/120 packets, 864/864/864 flits for both

transplant B's valid chain into result A, keep A's result_id /
experiment_id / plan_id / evidence_ref
  before: VERIFIED
  after:  EVIDENCE_INVALID -- "result.wave_d.waved_workload_id does not
          match its authority"
```

The verifier now proves `result.wave_d chain == plan.wave_d chain` on
every field, using the plan as the authority, and refuses any block
whose key set is not exactly the declared chain + execution schema.

## 7. Evidence-grade reuse (verified on the sealed tree)

`_try_reuse` additionally requires a clean source tree (sealed Wave-B
producer policy). In a dirty working tree reuse declines and a fresh
attempt runs; that is unchanged Wave-B behaviour, not a Wave-D defect.

Verified on the sealed tree:

```
same chain, run 1        reused=False  result c16e105042c0106a
evaluate again           reused=True   result c16e105042c0106a
changed operation bytes  reused=False  different result id
```

## 8. Final battery (from the committed tree)

```
wave-D suites (semantics/physical/authenticity/contract/seal)  246 passed
Wave-C control plane                                          221 passed
frozen Wave-B focused chain                                   747 passed
frozen production BookSim goldens                               6 passed
broad DSE pytest                   26 failed / 2961 passed / 40 skipped
  failed node IDs vs pre-Wave-D baseline    IDENTICAL (zero new)
```

The 26 pre-existing failures are environment-dependent (gitignored
`dse/archive/` + `dse/runs/` assets and unbuilt vendored binaries);
their node set is byte-identical to the baseline recorded before Wave D.

## 9. Real BookSim evidence (production path, sealed counters)

All three required scenarios ran through `SrotaControlPlane.evaluate()`
and verified through `load_verified_result`:

| scenario | op graph | messages | traffic | pkts exp/del | flits exp/inj/acc | route |
|---|---|---|---|---|---|---|
| DP ALLREDUCE | `544f8c86…` | `e59df64b…` | `e875f980…` | 120/120 | 864/864/864 | EXACT |
| PREFILL mixed P2P+collective | `10c9076d…` | `e315cf3d…` | `55999448…` | 26/26 | 187/187/187 | EXACT |
| BROADCAST | `a6a989e2…` | `1ba02ec8…` | `3497b036…` | 15/15 | 108/108/108 | EXACT |

Backend-injected packet equality is deliberately NOT claimed: that
counter does not exist in the sealed Wave-B evidence schema.

## 10. Reproduce

```bash
cd tracks/t3-topology
python3 -m pytest dse/tests/test_wave_d_*.py -q
python3 -m pytest dse/tests/test_control_plane_*.py -q
python3 -m pytest dse/tests -q   # compare FAILED node IDs to the baseline
```
