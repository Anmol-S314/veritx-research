# VERITX Validation Report

## V01 — 2x2 mesh, single 1-flit P2P router 0 -> router 3

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 4, 'tp': 4, 'link_width': 64, 'num_vcs': 1}  ·  workload: p2p

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=1, flits=1, auth_flits=1/1 | exact |
| hand_counts | hand_calculated | independent_oracle | packets=1 (preregistered_hand), flits=1 (posthoc_hand) | exact |
| hand_route | hand_calculated | independent_oracle | hand=2 (preregistered_hand), canonical=2.0, authority=3.0 | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 17 == 17 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=17, windows={'veritx': 1001, 'authority': 2001, 'authority_alt': 3001} | exact |

**PASS**

## V02 — 4x4 mesh, 16-node TP ALLREDUCE, 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=960, flits=4800, auth_flits=4800/4800 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=480, bytes=30720, flits=4800, packets=960 | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 990 == 990 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=990, windows={'veritx': 1960, 'authority': 2960, 'authority_alt': 3960} | exact |

**PASS**

## V03 — 4x4 mesh, 16-node EP ALLTOALL, 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=480, flits=2400, auth_flits=2400/2400 | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 719 == 719 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=719, windows={'veritx': 1480, 'authority': 2480, 'authority_alt': 3480} | exact |

**PASS**

## V04 — 4x4 mesh ALLREDUCE: completion is non-increasing in link width

sweep `link_width` → `completion_cycles` (non_increasing)  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}

| link_width | packets | flits | VERITX completion_cycles | authority |
|---|---|---|---|---|
| 32 | 1920 | 12000 | 1962 | 1962 |
| 64 | 960 | 4800 | 990 | 990 |
| 128 | 480 | 2400 | 507 | 507 |
| 256 | 480 | 1440 | 505 | 505 |

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| monotonicity | monotonicity | independent_oracle | series={'32': 1962, '64': 990, '128': 507, '256': 505} authority={'32': 1962, '64': 990, '128': 507, '256': 505} | exact |
| trace_execution_conservation@32 | trace_conservation | integration_gate | {"authority_accepted_flits": 12000, "authority_injected_flits": 12000, "flits": 12000, "packets": 1920} | exact |
| workload_lowering_conservation@32 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 25, "header_bits": 11, "messages": 480, "packets_per_message": 4, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 12000, "total_packets": 1920, "usable_payload_bits": 21} | exact |
| standalone_parity@32 | standalone_booksim | semi_independent_shared_engine | 1962 == 1962 | exact |
| trace_execution_conservation@64 | trace_conservation | integration_gate | {"authority_accepted_flits": 4800, "authority_injected_flits": 4800, "flits": 4800, "packets": 960} | exact |
| workload_lowering_conservation@64 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 10, "header_bits": 11, "messages": 480, "packets_per_message": 2, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 4800, "total_packets": 960, "usable_payload_bits": 53} | exact |
| standalone_parity@64 | standalone_booksim | semi_independent_shared_engine | 990 == 990 | exact |
| trace_execution_conservation@128 | trace_conservation | integration_gate | {"authority_accepted_flits": 2400, "authority_injected_flits": 2400, "flits": 2400, "packets": 480} | exact |
| workload_lowering_conservation@128 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 5, "header_bits": 11, "messages": 480, "packets_per_message": 1, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 2400, "total_packets": 480, "usable_payload_bits": 117} | exact |
| standalone_parity@128 | standalone_booksim | semi_independent_shared_engine | 507 == 507 | exact |
| trace_execution_conservation@256 | trace_conservation | integration_gate | {"authority_accepted_flits": 1440, "authority_injected_flits": 1440, "flits": 1440, "packets": 480} | exact |
| workload_lowering_conservation@256 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 3, "header_bits": 11, "messages": 480, "packets_per_message": 1, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 1440, "total_packets": 480, "usable_payload_bits": 245} | exact |
| standalone_parity@256 | standalone_booksim | semi_independent_shared_engine | 505 == 505 | exact |

**PASS**

## V05 — 4x4 mesh P2P: transmitted flits are non-decreasing in payload size

sweep `payload_bytes` → `flits` (non_decreasing)  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}

| payload_bytes | packets | flits | VERITX flits | authority |
|---|---|---|---|---|
| 7 | 1 | 2 | 2 | 2 |
| 64 | 2 | 10 | 10 | 10 |
| 512 | 10 | 78 | 78 | 78 |
| 4096 | 78 | 619 | 619 | 619 |

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| monotonicity | monotonicity | independent_oracle | series={'7': 2, '64': 10, '512': 78, '4096': 619} authority={'7': 2, '64': 10, '512': 78, '4096': 619} | exact |
| trace_execution_conservation@7 | trace_conservation | integration_gate | {"authority_accepted_flits": 2, "authority_injected_flits": 2, "flits": 2, "packets": 1} | exact |
| standalone_parity@7 | standalone_booksim | semi_independent_shared_engine | 38 == 38 | exact |
| trace_execution_conservation@64 | trace_conservation | integration_gate | {"authority_accepted_flits": 10, "authority_injected_flits": 10, "flits": 10, "packets": 2} | exact |
| standalone_parity@64 | standalone_booksim | semi_independent_shared_engine | 48 == 48 | exact |
| trace_execution_conservation@512 | trace_conservation | integration_gate | {"authority_accepted_flits": 78, "authority_injected_flits": 78, "flits": 78, "packets": 10} | exact |
| standalone_parity@512 | standalone_booksim | semi_independent_shared_engine | 132 == 132 | exact |
| trace_execution_conservation@4096 | trace_conservation | integration_gate | {"authority_accepted_flits": 619, "authority_injected_flits": 619, "flits": 619, "packets": 78} | exact |
| standalone_parity@4096 | standalone_booksim | semi_independent_shared_engine | 809 == 809 | exact |

**PASS**

## V06 — 2x2 mesh, single 1-flit P2P 0 -> 3: T3 RTL (Verilator) parity

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 4, 'tp': 4, 'link_width': 64, 'num_vcs': 1}  ·  workload: p2p

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=1, flits=1, auth_flits=1/1 | exact |
| hand_counts | hand_calculated | independent_oracle | packets=1 (unstated), flits=1 (unstated) | exact |
| hand_route | hand_calculated | independent_oracle | hand=2 (unstated), canonical=2.0, authority=3.0 | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 17 == 17 | exact |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=1 canonical=1 | exact |
| rtl_calibrated_hop_equivalent | rtl_calibrated | calibrated_cross_engine | hop-equiv=[2] hand=2 (unstated) | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=17 vs canonical=17 (delta +0, tol 0) | exact |

**PASS**

## V07 — 4x4 mesh, single 1-flit P2P 0 -> 15 (longest route): RTL parity

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: p2p

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=1, flits=2, auth_flits=2/2 | exact |
| hand_counts | hand_calculated | independent_oracle | packets=1 (preregistered_hand), flits=2 (posthoc_hand) | exact |
| hand_route | hand_calculated | independent_oracle | hand=6 (preregistered_hand), canonical=6.0, authority=7.0 | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 38 == 38 | exact |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=2 canonical=2 | exact |
| rtl_calibrated_hop_equivalent | rtl_calibrated | calibrated_cross_engine | hop-equiv=[6] hand=6 (preregistered_hand) | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=38 vs canonical=38 (delta +0, tol 0) | exact |

**PASS**

## V08 — 4x4 mesh, 3-flit P2P burst 0 -> 15: RTL tail latency + cadence

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: p2p

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=1, flits=3, auth_flits=3/3 | exact |
| hand_counts | hand_calculated | independent_oracle | packets=1 (preregistered_hand), flits=3 (posthoc_hand) | exact |
| hand_route | hand_calculated | independent_oracle | hand=6 (preregistered_hand), canonical=6.0, authority=7.0 | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 39 == 39 | exact |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=3 canonical=3 | exact |
| rtl_calibrated_hop_equivalent | rtl_calibrated | calibrated_cross_engine | hop-equiv=[6] hand=6 (preregistered_hand) | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=39 vs canonical=39 (delta +0, tol 0) | exact |

**PASS**

## V09 — 2x2 mesh, 4-node ALLREDUCE: independent RTL execution of the canonical trace

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 4, 'tp': 4, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=24, flits=24, auth_flits=24/24 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=24, bytes=48, flits=24, packets=24 | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 39 == 39 | exact |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=24 canonical=24 | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=39 vs canonical=39 (delta +0, tol 0) | exact |

**PASS**

## V10 — 4x4 mesh, 16-node ALLREDUCE 1024B: independent RTL execution of the canonical trace

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=960, flits=4800, auth_flits=4800/4800 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=480, bytes=30720, flits=4800, packets=960 | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 990 == 990 | exact |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=4800 canonical=4800 | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=990 vs canonical=990 (delta +0, tol 0) | exact |

**PASS**

---

checks exact: 65/65
