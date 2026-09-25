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
| collective_graph_conformance | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "phase_labels_exact": true, "steps_exact": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 1006 == 1006 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=1006, windows={'veritx': 1968, 'authority': 2960, 'authority_alt': 3960} | exact |

**PASS**

## V03 — 4x4 mesh, 16-node EP ALLTOALL, 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=480, flits=2400, auth_flits=2400/2400 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=240, bytes=15360, flits=2400, packets=480 | exact |
| collective_graph_conformance | ring_oracle | independent_oracle | {"checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "every_rank_receives_k_minus_1": true, "every_rank_sends_k_minus_1": true, "message_count_match": true, "no_self_messages": true, "pair_multiplicity_exact": true, "steps_exact": true}, "conforms": true, "kind": "ALLTOALL", "messages": 240, "payload_bytes": 1024, "problems": [], "ranks": 16, "source": null} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 719 == 719 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=719, windows={'veritx': 1600, 'authority': 2480, 'authority_alt': 3480} | exact |

**PASS**

## V04 — 4x4 mesh ALLREDUCE: completion is non-increasing in link width

sweep `link_width` → `completion_cycles` (non_increasing)  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}

| link_width | packets | flits | VERITX completion_cycles | authority |
|---|---|---|---|---|
| 32 | 1920 | 12000 | 1983 | 1983 |
| 64 | 960 | 4800 | 1006 | 1006 |
| 128 | 480 | 2400 | 520 | 520 |
| 256 | 480 | 1440 | 518 | 518 |

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| monotonicity | monotonicity | independent_oracle | series={'32': 1983, '64': 1006, '128': 520, '256': 518} authority={'32': 1983, '64': 1006, '128': 520, '256': 518} | exact |
| trace_execution_conservation@32 | trace_conservation | integration_gate | {"authority_accepted_flits": 12000, "authority_injected_flits": 12000, "flits": 12000, "packets": 1920} | exact |
| workload_lowering_conservation@32 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 25, "header_bits": 11, "messages": 480, "packets_per_message": 4, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 12000, "total_packets": 1920, "usable_payload_bits": 21} | exact |
| collective_graph_conformance@32 | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "phase_labels_exact": true, "steps_exact": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity@32 | standalone_booksim | semi_independent_shared_engine | 1983 == 1983 | exact |
| trace_execution_conservation@64 | trace_conservation | integration_gate | {"authority_accepted_flits": 4800, "authority_injected_flits": 4800, "flits": 4800, "packets": 960} | exact |
| workload_lowering_conservation@64 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 10, "header_bits": 11, "messages": 480, "packets_per_message": 2, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 4800, "total_packets": 960, "usable_payload_bits": 53} | exact |
| collective_graph_conformance@64 | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "phase_labels_exact": true, "steps_exact": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity@64 | standalone_booksim | semi_independent_shared_engine | 1006 == 1006 | exact |
| trace_execution_conservation@128 | trace_conservation | integration_gate | {"authority_accepted_flits": 2400, "authority_injected_flits": 2400, "flits": 2400, "packets": 480} | exact |
| workload_lowering_conservation@128 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 5, "header_bits": 11, "messages": 480, "packets_per_message": 1, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 2400, "total_packets": 480, "usable_payload_bits": 117} | exact |
| collective_graph_conformance@128 | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "phase_labels_exact": true, "steps_exact": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity@128 | standalone_booksim | semi_independent_shared_engine | 520 == 520 | exact |
| trace_execution_conservation@256 | trace_conservation | integration_gate | {"authority_accepted_flits": 1440, "authority_injected_flits": 1440, "flits": 1440, "packets": 480} | exact |
| workload_lowering_conservation@256 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 3, "header_bits": 11, "messages": 480, "packets_per_message": 1, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 1440, "total_packets": 480, "usable_payload_bits": 245} | exact |
| collective_graph_conformance@256 | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "phase_labels_exact": true, "steps_exact": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity@256 | standalone_booksim | semi_independent_shared_engine | 518 == 518 | exact |

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
| collective_graph_conformance | ring_oracle | independent_oracle | {"aggregate_bytes": 48, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "phase_labels_exact": true, "steps_exact": true}, "chunk_bytes": 2, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 24, "observed_distinct_pairs": 4, "payload_bytes": 8, "problems": [], "ranks": 4, "steps": 6} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 40 == 40 | exact |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=24 canonical=24 | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=40 vs canonical=40 (delta +0, tol 0) | exact |

**PASS**

## V10 — 4x4 mesh, 16-node ALLREDUCE 1024B: independent RTL execution of the canonical trace

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=960, flits=4800, auth_flits=4800/4800 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=480, bytes=30720, flits=4800, packets=960 | exact |
| collective_graph_conformance | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "phase_labels_exact": true, "steps_exact": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 1006 == 1006 | exact |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=4800 canonical=4800 | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=1006 vs canonical=1006 (delta +0, tol 0) | exact |

**PASS**

## V11 — 4x4 mesh, 16-node TP ALLGATHER (ring), 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=480, flits=2400, auth_flits=2400/2400 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=240, bytes=15360, flits=2400, packets=480 | exact |
| collective_graph_conformance | ring_oracle | independent_oracle | {"aggregate_bytes": 15360, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "steps_exact": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLGATHER", "messages": 240, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 15} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 526 == 526 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=526, windows={'veritx': 1488, 'authority': 2480, 'authority_alt': 3480} | exact |

**PASS**

## V12 — 4x4 mesh, 16-node TP REDUCESCATTER (ring), 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=480, flits=2400, auth_flits=2400/2400 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=240, bytes=15360, flits=2400, packets=480 | exact |
| collective_graph_conformance | ring_oracle | independent_oracle | {"aggregate_bytes": 15360, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "steps_exact": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "REDUCESCATTER", "messages": 240, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 15} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 526 == 526 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=526, windows={'veritx': 1488, 'authority': 2480, 'authority_alt': 3480} | exact |

**PASS**

## V13 — 4x4 mesh, 16-node TP BROADCAST (root fanout, source rank 7), 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=300, flits=2325, auth_flits=2325/2325 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=15, bytes=15360, flits=2325, packets=300 | exact |
| collective_graph_conformance | ring_oracle | independent_oracle | {"checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "message_count_match": true, "no_self_messages": true, "only_root_sends": true, "root_sends_to_every_other_exactly_once": true, "steps_exact": true}, "conforms": true, "kind": "BROADCAST", "messages": 15, "payload_bytes": 1024, "problems": [], "ranks": 16, "source": 7} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 2939 == 2939 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=2939, windows={'veritx': 3325, 'authority': 2942, 'authority_alt': 3300} | exact |

**PASS**

## V14 — 2x2 mesh, 4-node TP ALLGATHER (ring, k=2 boundary), 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 4, 'tp': 4, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=60, flits=432, auth_flits=432/432 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=12, bytes=3072, flits=432, packets=60 | exact |
| collective_graph_conformance | ring_oracle | independent_oracle | {"aggregate_bytes": 3072, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "steps_exact": true}, "chunk_bytes": 256, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLGATHER", "messages": 12, "observed_distinct_pairs": 4, "payload_bytes": 1024, "problems": [], "ranks": 4, "steps": 3} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 167 == 167 | exact |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=167, windows={'veritx': 1123, 'authority': 2060, 'authority_alt': 3060} | exact |

**PASS**

---

checks exact: 94/94 (0 quarantined by a filed finding)

by independence category (exact/total):
  calibrated_cross_engine            8/8
  independent_execution_engine       5/5
  independent_oracle                 34/34
  integration_gate                   20/20
  semi_independent_shared_engine     27/27

independent_oracle by provenance (exact/total):
  posthoc_hand                       3/3
  preregistered_hand                 3/3
  preregistered_oracle               16/16
  preregistered_physics              2/2
  unstated                           10/10
