# Wave D implementation handoff (for review)

Status: **implementation committed, NOT sealed.** The Wave-D semantics
chain is implemented and its proof suites pass, but the items under
"Open items" are unresolved. This file exists so the next reviewer does
not have to re-derive them.

Branch: `wave-d/distributed-semantics` (based on Wave C-SEAL.1
`8455c0450e27486ae034028b76c9a05b94f2ea72`, via D0/D0.1/D0.2 contract
commits).

## What is implemented

```
dse/veritx_dse/waved/parallelism.py   ParallelismArtifact: rank space + group laws
dse/veritx_dse/waved/semantics.py     WaveDWorkloadSemantics: versioned envelope
dse/veritx_dse/waved/operations.py    OperationGraph: DAG laws + identity
dse/veritx_dse/waved/messages.py      LogicalMessageArtifact: schedules + messages
dse/veritx_dse/waved/traffic.py       PhysicalTrafficArtifact + ConservationLedger
dse/veritx_dse/waved/backend.py       qualified BookSim projection
dse/veritx_dse/waved/{identity,oracles,errors,__init__}.py
```

Identity DAG as specified by D0.2 §23.2:
`operation_graph_id ← workload_id + parallelism_id + wave_d_semantics_id`,
`message_artifact_id ← operation_graph_id`,
`physical_traffic_id ← message_artifact_id + resolved_fabric_hash +
packet_format_hash`.

## Verified evidence (re-run these)

```bash
cd tracks/t3-topology
python3 -m pytest dse/tests/test_wave_d_semantics.py dse/tests/test_wave_d_physical.py \
  dse/tests/test_wave_d_authenticity.py dse/tests/test_wave_d_contract.py -q
# 168 passed

python3 -m pytest dse/tests/test_backend_*.py dse/tests/test_phase_api_boundary.py \
  dse/tests/test_route_artifact.py dse/tests/test_resolved_route.py dse/tests/test_resolved_fabric.py \
  dse/tests/test_fabric_artifact.py dse/tests/test_packet_format.py dse/tests/test_address_decode.py \
  dse/tests/test_attachment.py dse/tests/test_vc_assignment.py dse/tests/test_channel_vc_cdg.py \
  dse/tests/test_router_behavior.py dse/tests/test_routing_stopgap.py -q
# 747 passed (frozen Wave-B chain)

python3 -m pytest dse/tests -q --ignore=dse/tests/test_astrasim_spine_contract.py
# 2903 passed / 26 failed / 40 skipped; failure node set identical to the
# pre-Wave-D baseline (no new failures)
```

Real execution (my independent run, not just the suite): dp=4 ALLREDUCE
1024 B → 120 packets injected == delivered == expected, 864 flits
injected == accepted, `route_equivalence == EXACT`.

## Open items

1. **Contract matrices not updated (P1).** Only the doc header/status
   table changed. §27–31 (property/bounded/metamorphic/mutation/support)
   still read as plan. The new header claims "the implementation status
   column of §31 ... [is] now executed code" — §31 has no such column.
   Code/tests cite section numbers that do not exist in the 36-section
   contract (`§42`, `§46–§50`, `§52`, `§56`, `§60–§62`, `§67–§68`,
   `§72–§73`, and ranges `§15–19`, `§24–26`, `§27–29`, `§31–41`); they
   come from the original D0 brief. Fix the citations or add an explicit
   brief→contract mapping table.

2. **Wave-B evidence schema addition (P1).** `injected_packets` was
   added to `CertifiedBookSimEvidence` and its `to_dict()`
   (`backend/booksim.py`), parsed from the fork's pre-existing stderr
   marker by `simulation/booksim.py:parse_trace_injected`. Evidence
   identity is `sha256(canonical_json(to_dict()))`, so evidence bytes —
   and therefore `evidence_sha256`/result IDs — change for new runs.
   Stored artifacts still verify and all tests pass. Decide: keep it in
   the sealed evidence (with an explicit version/declaration) or move it
   to a Wave-D-side evidence wrapper.

3. **No persistence round-trip for the new artifacts (P2).** Only
   `ParallelismArtifact` and `WaveDWorkloadSemantics` have `from_dict()`
   with identity verification. `OperationGraph`,
   `LogicalMessageArtifact` and `PhysicalTrafficArtifact` expose
   `to_dict()` but cannot be reloaded and re-verified, so the D0.2
   content-addressed rule (`filename == embedded == recomputed`) is only
   half-implemented at the Wave-D layer.

4. **No product integration (P2).** Nothing outside `waved/` and its
   tests imports the package: no control-plane, CLI or experiment path
   consumes Wave-D artifacts yet. The JSON implementation block scopes
   this honestly to the standalone BookSim projection.

5. **Misleading test name (P3).**
   `test_ledger_tamper_detected_by_revalidation` no longer tests a
   validator: the ledger is derived from the artifact
   (`conservation_ledger()` recomputes from `_traffic`), and
   `PhysicalTrafficArtifact` has no persisted form to tamper. The
   rewritten body is defensible; the name overstates it.

6. **Process (P3).** D1–D5 were implemented in a single pass without the
   per-slice audits the plan called for, so this review covers the whole
   chain at once.

## Suggested closure order

```text
1. decide items 2 and 3 (evidence placement; persistence scope)
2. update contract §27-31 + fix citations (item 1)
3. implement or declare item 3; declare item 4
4. rename/reframe the ledger test (item 5)
5. full battery + seal report from committed SHAs
```
