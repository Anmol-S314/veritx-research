# GEC-MECS credited AXI integration — bounded progress

## Goal

Build one truthful bounded 4×4 GEC-MECS request-to-response path that connects the existing AXI5 initiator/destination adapters to the per-tap credited fabric. This is a first end-to-end slice, not full family qualification or physical signoff; `final_implementation` stays false.

## Bound profile

- `_gec_mecs_request()` compiles 16 routers, 32 shared wires, 3 taps/wire, 3 VCs, and endpoints 0/1/2 placed on routers 0/1/2.
- Compiled 64-bit fields: `payload[55:0]`, `source_endpoint[57:56]`, `destination_endpoint[59:58]`, `flit_type[61:60]`, `vc_id[63:62]`.
- The credited fabric accepts those compiled destination/VC offsets and endpoint→router mapping. Credit returns use physical ingress identity; packet bits are not repurposed for tap identity.

## Results

1. **Mapped fabric PASS.** K=4 / 16 routers / 3 endpoints: all 9 ordered endpoint pairs; all three VCs; stalled output stability; no credit alias; all credit pools restored. Overlapping packet fields and duplicate endpoint mappings fail closed.
2. **AXI-connected composed top PASS.** `build_family_router` emits a bridge around the credited fabric for GEC-MECS while other families retain their existing transports. The existing AXI initiator/destination adapters are connected through that bridge. The test passes 13/13 scenarios: read/write payload and response, IDs, permission allow/deny, address errors, strong ordering stall/in-order completion, backpressure, concurrent initiators, conservation, and drain.
3. **Ordering limit is explicit.** The request declares `max_outstanding=4`, but the current `initiator_slice` state machine allows one outstanding request per initiator. The generated manifest records both values; no four-outstanding claim is made.
4. **Lint PASS, not clean.** Verilator exits 0 with 272 nonfatal warnings (primarily unused signals, plus one SYNCASYNCNET). The previous UNDRIVEN warning on reserved payload bits is fixed by driving those bits to zero.

Focused command:

```sh
PYTHONPATH=tracks/t3-topology/dse timeout 300 python3 -m pytest -q \
  tracks/t3-topology/dse/tests/test_project_top_slice.py \
  tracks/t3-topology/dse/tests/test_gec_mecs_credited_fabric.py \
  -k 'gec_mecs and composed_family_lints_and_sims or compiled_gec_field_map_routes_axially_and_restores_credits'
```

Result: **2 passed** in 42.29 s. Pytest warns that the configured `timeout` plugin is unavailable; GNU `timeout` bounded the run.

## Remaining limits

This is not a durable release-run artifact or independent audit of every generated manifest/file hash. It does not establish four outstanding requests per initiator, broader workload/topology qualification, full AXI5 certification, asynchronous CDC, physical implementation, or final signoff. Keep `final_implementation=false`.
