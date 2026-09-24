# VERITX Validation Report

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
| collective_graph_conformance@32 | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "steps_match": true, "two_phases_present": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity@32 | standalone_booksim | semi_independent_shared_engine | 1983 == 1983 | exact |
| trace_execution_conservation@64 | trace_conservation | integration_gate | {"authority_accepted_flits": 4800, "authority_injected_flits": 4800, "flits": 4800, "packets": 960} | exact |
| workload_lowering_conservation@64 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 10, "header_bits": 11, "messages": 480, "packets_per_message": 2, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 4800, "total_packets": 960, "usable_payload_bits": 53} | exact |
| collective_graph_conformance@64 | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "steps_match": true, "two_phases_present": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity@64 | standalone_booksim | semi_independent_shared_engine | 1006 == 1006 | exact |
| trace_execution_conservation@128 | trace_conservation | integration_gate | {"authority_accepted_flits": 2400, "authority_injected_flits": 2400, "flits": 2400, "packets": 480} | exact |
| workload_lowering_conservation@128 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 5, "header_bits": 11, "messages": 480, "packets_per_message": 1, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 2400, "total_packets": 480, "usable_payload_bits": 117} | exact |
| collective_graph_conformance@128 | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "steps_match": true, "two_phases_present": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity@128 | standalone_booksim | semi_independent_shared_engine | 520 == 520 | exact |
| trace_execution_conservation@256 | trace_conservation | integration_gate | {"authority_accepted_flits": 1440, "authority_injected_flits": 1440, "flits": 1440, "packets": 480} | exact |
| workload_lowering_conservation@256 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 3, "header_bits": 11, "messages": 480, "packets_per_message": 1, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 1440, "total_packets": 480, "usable_payload_bits": 245} | exact |
| collective_graph_conformance@256 | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "steps_match": true, "two_phases_present": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity@256 | standalone_booksim | semi_independent_shared_engine | 518 == 518 | exact |

**PASS**

## V10 — 4x4 mesh, 16-node ALLREDUCE 1024B: independent RTL execution of the canonical trace

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=960, flits=4800, auth_flits=4800/4800 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=480, bytes=30720, flits=4800, packets=960 | exact |
| collective_graph_conformance | ring_oracle | independent_oracle | {"aggregate_bytes": 30720, "checks": {"aggregate_bytes_match": true, "chunk_bytes_match": true, "dst_is_next_ring_neighbour": true, "every_rank_receives_once_per_step": true, "every_rank_sends_once_per_step": true, "every_step_has_k_messages": true, "message_count_match": true, "no_non_neighbour_pairs": true, "no_self_messages": true, "steps_match": true, "two_phases_present": true}, "chunk_bytes": 64, "conforms": true, "extra_non_neighbour_pairs": {}, "kind": "ALLREDUCE", "messages": 480, "observed_distinct_pairs": 16, "payload_bytes": 1024, "problems": [], "ranks": 16, "steps": 30} | exact |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 1006 == 1006 | exact |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=4800 canonical=4800 | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=1006 vs canonical=1006 (delta +0, tol 0) | exact |

**PASS**

---

checks exact: 23/23 (0 quarantined by a filed finding)

by independence category (exact/total):
  calibrated_cross_engine            1/1
  independent_execution_engine       1/1
  independent_oracle                 11/11
  integration_gate                   5/5
  semi_independent_shared_engine     5/5

independent_oracle by provenance (exact/total):
  preregistered_oracle               2/2
  preregistered_physics              1/1
  unstated                           8/8
