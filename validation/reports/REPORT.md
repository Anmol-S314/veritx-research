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
| collective_graph_conformance | ring_oracle | independent_oracle | {"conforms": false, "extra_non_neighbour_pairs": {"0->10": 2, "0->11": 2, "0->12": 2, "0->13": 2, "0->14": 2, "0->15": 2, "0->2": 2, "0->3": 2, "0->4": 2, "0->5": 2, "0->6": 2, "0->7": 2, "0->8": 2, "0->9": 2, "1->0": 2, "1->10": 2, "1->11": 2, "1->12": 2, "1->13": 2, "1->14": 2, "1->15": 2, "1->3": 2, "1->4": 2, "1->5": 2, "1->6": 2, "1->7": 2, "1->8": 2, "1->9": 2, "10->0": 2, "10->1": 2, "10->12": 2, "10->13": 2, "10->14": 2, "10->15": 2, "10->2": 2, "10->3": 2, "10->4": 2, "10->5": 2, "10->6": 2, "10->7": 2, "10->8": 2, "10->9": 2, "11->0": 2, "11->1": 2, "11->10": 2, "11->13": 2, "11->14": 2, "11->15": 2, "11->2": 2, "11->3": 2, "11->4": 2, "11->5": 2, "11->6": 2, "11->7": 2, "11->8": 2, "11->9": 2, "12->0": 2, "12->1": 2, "12->10": 2, "12->11": 2, "12->14": 2, "12->15": 2, "12->2": 2, "12->3": 2, "12->4": 2, "12->5": 2, "12->6": 2, "12->7": 2, "12->8": 2, "12->9": 2, "13->0": 2, "13->1": 2, "13->10": 2, "13->11": 2, "13->12": 2, "13->15": 2, "13->2": 2, "13->3": 2, "13->4": 2, "13->5": 2, "13->6": 2, "13->7": 2, "13->8": 2, "13->9": 2, "14->0": 2, "14->1": 2, "14->10": 2, "14->11": 2, "14->12": 2, "14->13": 2, "14->2": 2, "14->3": 2, "14->4": 2, "14->5": 2, "14->6": 2, "14->7": 2, "14->8": 2, "14->9": 2, "15->1": 2, "15->10": 2, "15->11": 2, "15->12": 2, "15->13": 2, "15->14": 2, "15->2": 2, "15->3": 2, "15->4": 2, "15->5": 2, "15->6": 2, "15->7": 2, "15->8": 2, "15->9": 2, "2->0": 2, "2->1": 2, "2->10": 2, "2->11": 2, "2->12": 2, "2->13": 2, "2->14": 2, "2->15": 2, "2->4": 2, "2->5": 2, "2->6": 2, "2->7": 2, "2->8": 2, "2->9": 2, "3->0": 2, "3->1": 2, "3->10": 2, "3->11": 2, "3->12": 2, "3->13": 2, "3->14": 2, "3->15": 2, "3->2": 2, "3->5": 2, "3->6": 2, "3->7": 2, "3->8": 2, "3->9": 2, "4->0": 2, "4->1": 2, "4->10": 2, "4->11": 2, "4->12": 2, "4->13": 2, "4->14": 2, "4->15": 2, "4->2": 2, "4->3": 2, "4->6": 2, "4->7": 2, "4->8": 2, "4->9": 2, "5->0": 2, "5->1": 2, "5->10": 2, "5->11": 2, "5->12": 2, "5->13": 2, "5->14": 2, "5->15": 2, "5->2": 2, "5->3": 2, "5->4": 2, "5->7": 2, "5->8": 2, "5->9": 2, "6->0": 2, "6->1": 2, "6->10": 2, "6->11": 2, "6->12": 2, "6->13": 2, "6->14": 2, "6->15": 2, "6->2": 2, "6->3": 2, "6->4": 2, "6->5": 2, "6->8": 2, "6->9": 2, "7->0": 2, "7->1": 2, "7->10": 2, "7->11": 2, "7->12": 2, "7->13": 2, "7->14": 2, "7->15": 2, "7->2": 2, "7->3": 2, "7->4": 2, "7->5": 2, "7->6": 2, "7->9": 2, "8->0": 2, "8->1": 2, "8->10": 2, "8->11": 2, "8->12": 2, "8->13": 2, "8->14": 2, "8->15": 2, "8->2": 2, "8->3": 2, "8->4": 2, "8->5": 2, "8->6": 2, "8->7": 2, "9->0": 2, "9->1": 2, "9->11": 2, "9->12": 2, "9->13": 2, "9->14": 2, "9->15": 2, "9->2": 2, "9->3": 2, "9->4": 2, "9->5": 2, "9->6": 2, "9->7": 2, "9->8": 2}, "missing_neighbour_pairs": {}, "observed_distinct_pairs": 240, "ring_distinct_pairs": 16, "ring_pairs": {"0->1": 30, "1->2": 30, "10->11": 30, "11->12": 30, "12->13": 30, "13->14": 30, "14->15": 30, "15->0": 30, "2->3": 30, "3->4": 30, "4->5": 30, "5->6": 30, "6->7": 30, "7->8": 30, "8->9": 30, "9->10": 30}, "wrong_multiplicity": {"0->1": [2, 30], "1->2": [2, 30], "10->11": [2, 30], "11->12": [2, 30], "12->13": [2, 30], "13->14": [2, 30], "14->15": [2, 30], "15->0": [2, 30], "2->3": [2, 30], "3->4": [2, 30], "4->5": [2, 30], "5->6": [2, 30], "6->7": [2, 30], "7->8": [2, 30], "8->9": [2, 30], "9->10": [2, 30]}} | mismatch (QUARANTINED F-0004) |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 990 == 990 | exact (QUARANTINED F-0004) |
| window_invariance | standalone_booksim | semi_independent_shared_engine | completion=990, windows={'veritx': 1960, 'authority': 2960, 'authority_alt': 3960} | exact (QUARANTINED F-0004) |

**PASS**

quarantined findings: ['F-0004']

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
| monotonicity | monotonicity | independent_oracle | series={'32': 1962, '64': 990, '128': 507, '256': 505} authority={'32': 1962, '64': 990, '128': 507, '256': 505} | exact (QUARANTINED F-0004) |
| trace_execution_conservation@32 | trace_conservation | integration_gate | {"authority_accepted_flits": 12000, "authority_injected_flits": 12000, "flits": 12000, "packets": 1920} | exact |
| workload_lowering_conservation@32 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 25, "header_bits": 11, "messages": 480, "packets_per_message": 4, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 12000, "total_packets": 1920, "usable_payload_bits": 21} | exact |
| collective_graph_conformance@32 | ring_oracle | independent_oracle | {"conforms": false, "extra_non_neighbour_pairs": {"0->10": 2, "0->11": 2, "0->12": 2, "0->13": 2, "0->14": 2, "0->15": 2, "0->2": 2, "0->3": 2, "0->4": 2, "0->5": 2, "0->6": 2, "0->7": 2, "0->8": 2, "0->9": 2, "1->0": 2, "1->10": 2, "1->11": 2, "1->12": 2, "1->13": 2, "1->14": 2, "1->15": 2, "1->3": 2, "1->4": 2, "1->5": 2, "1->6": 2, "1->7": 2, "1->8": 2, "1->9": 2, "10->0": 2, "10->1": 2, "10->12": 2, "10->13": 2, "10->14": 2, "10->15": 2, "10->2": 2, "10->3": 2, "10->4": 2, "10->5": 2, "10->6": 2, "10->7": 2, "10->8": 2, "10->9": 2, "11->0": 2, "11->1": 2, "11->10": 2, "11->13": 2, "11->14": 2, "11->15": 2, "11->2": 2, "11->3": 2, "11->4": 2, "11->5": 2, "11->6": 2, "11->7": 2, "11->8": 2, "11->9": 2, "12->0": 2, "12->1": 2, "12->10": 2, "12->11": 2, "12->14": 2, "12->15": 2, "12->2": 2, "12->3": 2, "12->4": 2, "12->5": 2, "12->6": 2, "12->7": 2, "12->8": 2, "12->9": 2, "13->0": 2, "13->1": 2, "13->10": 2, "13->11": 2, "13->12": 2, "13->15": 2, "13->2": 2, "13->3": 2, "13->4": 2, "13->5": 2, "13->6": 2, "13->7": 2, "13->8": 2, "13->9": 2, "14->0": 2, "14->1": 2, "14->10": 2, "14->11": 2, "14->12": 2, "14->13": 2, "14->2": 2, "14->3": 2, "14->4": 2, "14->5": 2, "14->6": 2, "14->7": 2, "14->8": 2, "14->9": 2, "15->1": 2, "15->10": 2, "15->11": 2, "15->12": 2, "15->13": 2, "15->14": 2, "15->2": 2, "15->3": 2, "15->4": 2, "15->5": 2, "15->6": 2, "15->7": 2, "15->8": 2, "15->9": 2, "2->0": 2, "2->1": 2, "2->10": 2, "2->11": 2, "2->12": 2, "2->13": 2, "2->14": 2, "2->15": 2, "2->4": 2, "2->5": 2, "2->6": 2, "2->7": 2, "2->8": 2, "2->9": 2, "3->0": 2, "3->1": 2, "3->10": 2, "3->11": 2, "3->12": 2, "3->13": 2, "3->14": 2, "3->15": 2, "3->2": 2, "3->5": 2, "3->6": 2, "3->7": 2, "3->8": 2, "3->9": 2, "4->0": 2, "4->1": 2, "4->10": 2, "4->11": 2, "4->12": 2, "4->13": 2, "4->14": 2, "4->15": 2, "4->2": 2, "4->3": 2, "4->6": 2, "4->7": 2, "4->8": 2, "4->9": 2, "5->0": 2, "5->1": 2, "5->10": 2, "5->11": 2, "5->12": 2, "5->13": 2, "5->14": 2, "5->15": 2, "5->2": 2, "5->3": 2, "5->4": 2, "5->7": 2, "5->8": 2, "5->9": 2, "6->0": 2, "6->1": 2, "6->10": 2, "6->11": 2, "6->12": 2, "6->13": 2, "6->14": 2, "6->15": 2, "6->2": 2, "6->3": 2, "6->4": 2, "6->5": 2, "6->8": 2, "6->9": 2, "7->0": 2, "7->1": 2, "7->10": 2, "7->11": 2, "7->12": 2, "7->13": 2, "7->14": 2, "7->15": 2, "7->2": 2, "7->3": 2, "7->4": 2, "7->5": 2, "7->6": 2, "7->9": 2, "8->0": 2, "8->1": 2, "8->10": 2, "8->11": 2, "8->12": 2, "8->13": 2, "8->14": 2, "8->15": 2, "8->2": 2, "8->3": 2, "8->4": 2, "8->5": 2, "8->6": 2, "8->7": 2, "9->0": 2, "9->1": 2, "9->11": 2, "9->12": 2, "9->13": 2, "9->14": 2, "9->15": 2, "9->2": 2, "9->3": 2, "9->4": 2, "9->5": 2, "9->6": 2, "9->7": 2, "9->8": 2}, "missing_neighbour_pairs": {}, "observed_distinct_pairs": 240, "ring_distinct_pairs": 16, "ring_pairs": {"0->1": 30, "1->2": 30, "10->11": 30, "11->12": 30, "12->13": 30, "13->14": 30, "14->15": 30, "15->0": 30, "2->3": 30, "3->4": 30, "4->5": 30, "5->6": 30, "6->7": 30, "7->8": 30, "8->9": 30, "9->10": 30}, "wrong_multiplicity": {"0->1": [2, 30], "1->2": [2, 30], "10->11": [2, 30], "11->12": [2, 30], "12->13": [2, 30], "13->14": [2, 30], "14->15": [2, 30], "15->0": [2, 30], "2->3": [2, 30], "3->4": [2, 30], "4->5": [2, 30], "5->6": [2, 30], "6->7": [2, 30], "7->8": [2, 30], "8->9": [2, 30], "9->10": [2, 30]}} | mismatch (QUARANTINED F-0004) |
| standalone_parity@32 | standalone_booksim | semi_independent_shared_engine | 1962 == 1962 | exact (QUARANTINED F-0004) |
| trace_execution_conservation@64 | trace_conservation | integration_gate | {"authority_accepted_flits": 4800, "authority_injected_flits": 4800, "flits": 4800, "packets": 960} | exact |
| workload_lowering_conservation@64 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 10, "header_bits": 11, "messages": 480, "packets_per_message": 2, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 4800, "total_packets": 960, "usable_payload_bits": 53} | exact |
| collective_graph_conformance@64 | ring_oracle | independent_oracle | {"conforms": false, "extra_non_neighbour_pairs": {"0->10": 2, "0->11": 2, "0->12": 2, "0->13": 2, "0->14": 2, "0->15": 2, "0->2": 2, "0->3": 2, "0->4": 2, "0->5": 2, "0->6": 2, "0->7": 2, "0->8": 2, "0->9": 2, "1->0": 2, "1->10": 2, "1->11": 2, "1->12": 2, "1->13": 2, "1->14": 2, "1->15": 2, "1->3": 2, "1->4": 2, "1->5": 2, "1->6": 2, "1->7": 2, "1->8": 2, "1->9": 2, "10->0": 2, "10->1": 2, "10->12": 2, "10->13": 2, "10->14": 2, "10->15": 2, "10->2": 2, "10->3": 2, "10->4": 2, "10->5": 2, "10->6": 2, "10->7": 2, "10->8": 2, "10->9": 2, "11->0": 2, "11->1": 2, "11->10": 2, "11->13": 2, "11->14": 2, "11->15": 2, "11->2": 2, "11->3": 2, "11->4": 2, "11->5": 2, "11->6": 2, "11->7": 2, "11->8": 2, "11->9": 2, "12->0": 2, "12->1": 2, "12->10": 2, "12->11": 2, "12->14": 2, "12->15": 2, "12->2": 2, "12->3": 2, "12->4": 2, "12->5": 2, "12->6": 2, "12->7": 2, "12->8": 2, "12->9": 2, "13->0": 2, "13->1": 2, "13->10": 2, "13->11": 2, "13->12": 2, "13->15": 2, "13->2": 2, "13->3": 2, "13->4": 2, "13->5": 2, "13->6": 2, "13->7": 2, "13->8": 2, "13->9": 2, "14->0": 2, "14->1": 2, "14->10": 2, "14->11": 2, "14->12": 2, "14->13": 2, "14->2": 2, "14->3": 2, "14->4": 2, "14->5": 2, "14->6": 2, "14->7": 2, "14->8": 2, "14->9": 2, "15->1": 2, "15->10": 2, "15->11": 2, "15->12": 2, "15->13": 2, "15->14": 2, "15->2": 2, "15->3": 2, "15->4": 2, "15->5": 2, "15->6": 2, "15->7": 2, "15->8": 2, "15->9": 2, "2->0": 2, "2->1": 2, "2->10": 2, "2->11": 2, "2->12": 2, "2->13": 2, "2->14": 2, "2->15": 2, "2->4": 2, "2->5": 2, "2->6": 2, "2->7": 2, "2->8": 2, "2->9": 2, "3->0": 2, "3->1": 2, "3->10": 2, "3->11": 2, "3->12": 2, "3->13": 2, "3->14": 2, "3->15": 2, "3->2": 2, "3->5": 2, "3->6": 2, "3->7": 2, "3->8": 2, "3->9": 2, "4->0": 2, "4->1": 2, "4->10": 2, "4->11": 2, "4->12": 2, "4->13": 2, "4->14": 2, "4->15": 2, "4->2": 2, "4->3": 2, "4->6": 2, "4->7": 2, "4->8": 2, "4->9": 2, "5->0": 2, "5->1": 2, "5->10": 2, "5->11": 2, "5->12": 2, "5->13": 2, "5->14": 2, "5->15": 2, "5->2": 2, "5->3": 2, "5->4": 2, "5->7": 2, "5->8": 2, "5->9": 2, "6->0": 2, "6->1": 2, "6->10": 2, "6->11": 2, "6->12": 2, "6->13": 2, "6->14": 2, "6->15": 2, "6->2": 2, "6->3": 2, "6->4": 2, "6->5": 2, "6->8": 2, "6->9": 2, "7->0": 2, "7->1": 2, "7->10": 2, "7->11": 2, "7->12": 2, "7->13": 2, "7->14": 2, "7->15": 2, "7->2": 2, "7->3": 2, "7->4": 2, "7->5": 2, "7->6": 2, "7->9": 2, "8->0": 2, "8->1": 2, "8->10": 2, "8->11": 2, "8->12": 2, "8->13": 2, "8->14": 2, "8->15": 2, "8->2": 2, "8->3": 2, "8->4": 2, "8->5": 2, "8->6": 2, "8->7": 2, "9->0": 2, "9->1": 2, "9->11": 2, "9->12": 2, "9->13": 2, "9->14": 2, "9->15": 2, "9->2": 2, "9->3": 2, "9->4": 2, "9->5": 2, "9->6": 2, "9->7": 2, "9->8": 2}, "missing_neighbour_pairs": {}, "observed_distinct_pairs": 240, "ring_distinct_pairs": 16, "ring_pairs": {"0->1": 30, "1->2": 30, "10->11": 30, "11->12": 30, "12->13": 30, "13->14": 30, "14->15": 30, "15->0": 30, "2->3": 30, "3->4": 30, "4->5": 30, "5->6": 30, "6->7": 30, "7->8": 30, "8->9": 30, "9->10": 30}, "wrong_multiplicity": {"0->1": [2, 30], "1->2": [2, 30], "10->11": [2, 30], "11->12": [2, 30], "12->13": [2, 30], "13->14": [2, 30], "14->15": [2, 30], "15->0": [2, 30], "2->3": [2, 30], "3->4": [2, 30], "4->5": [2, 30], "5->6": [2, 30], "6->7": [2, 30], "7->8": [2, 30], "8->9": [2, 30], "9->10": [2, 30]}} | mismatch (QUARANTINED F-0004) |
| standalone_parity@64 | standalone_booksim | semi_independent_shared_engine | 990 == 990 | exact (QUARANTINED F-0004) |
| trace_execution_conservation@128 | trace_conservation | integration_gate | {"authority_accepted_flits": 2400, "authority_injected_flits": 2400, "flits": 2400, "packets": 480} | exact |
| workload_lowering_conservation@128 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 5, "header_bits": 11, "messages": 480, "packets_per_message": 1, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 2400, "total_packets": 480, "usable_payload_bits": 117} | exact |
| collective_graph_conformance@128 | ring_oracle | independent_oracle | {"conforms": false, "extra_non_neighbour_pairs": {"0->10": 2, "0->11": 2, "0->12": 2, "0->13": 2, "0->14": 2, "0->15": 2, "0->2": 2, "0->3": 2, "0->4": 2, "0->5": 2, "0->6": 2, "0->7": 2, "0->8": 2, "0->9": 2, "1->0": 2, "1->10": 2, "1->11": 2, "1->12": 2, "1->13": 2, "1->14": 2, "1->15": 2, "1->3": 2, "1->4": 2, "1->5": 2, "1->6": 2, "1->7": 2, "1->8": 2, "1->9": 2, "10->0": 2, "10->1": 2, "10->12": 2, "10->13": 2, "10->14": 2, "10->15": 2, "10->2": 2, "10->3": 2, "10->4": 2, "10->5": 2, "10->6": 2, "10->7": 2, "10->8": 2, "10->9": 2, "11->0": 2, "11->1": 2, "11->10": 2, "11->13": 2, "11->14": 2, "11->15": 2, "11->2": 2, "11->3": 2, "11->4": 2, "11->5": 2, "11->6": 2, "11->7": 2, "11->8": 2, "11->9": 2, "12->0": 2, "12->1": 2, "12->10": 2, "12->11": 2, "12->14": 2, "12->15": 2, "12->2": 2, "12->3": 2, "12->4": 2, "12->5": 2, "12->6": 2, "12->7": 2, "12->8": 2, "12->9": 2, "13->0": 2, "13->1": 2, "13->10": 2, "13->11": 2, "13->12": 2, "13->15": 2, "13->2": 2, "13->3": 2, "13->4": 2, "13->5": 2, "13->6": 2, "13->7": 2, "13->8": 2, "13->9": 2, "14->0": 2, "14->1": 2, "14->10": 2, "14->11": 2, "14->12": 2, "14->13": 2, "14->2": 2, "14->3": 2, "14->4": 2, "14->5": 2, "14->6": 2, "14->7": 2, "14->8": 2, "14->9": 2, "15->1": 2, "15->10": 2, "15->11": 2, "15->12": 2, "15->13": 2, "15->14": 2, "15->2": 2, "15->3": 2, "15->4": 2, "15->5": 2, "15->6": 2, "15->7": 2, "15->8": 2, "15->9": 2, "2->0": 2, "2->1": 2, "2->10": 2, "2->11": 2, "2->12": 2, "2->13": 2, "2->14": 2, "2->15": 2, "2->4": 2, "2->5": 2, "2->6": 2, "2->7": 2, "2->8": 2, "2->9": 2, "3->0": 2, "3->1": 2, "3->10": 2, "3->11": 2, "3->12": 2, "3->13": 2, "3->14": 2, "3->15": 2, "3->2": 2, "3->5": 2, "3->6": 2, "3->7": 2, "3->8": 2, "3->9": 2, "4->0": 2, "4->1": 2, "4->10": 2, "4->11": 2, "4->12": 2, "4->13": 2, "4->14": 2, "4->15": 2, "4->2": 2, "4->3": 2, "4->6": 2, "4->7": 2, "4->8": 2, "4->9": 2, "5->0": 2, "5->1": 2, "5->10": 2, "5->11": 2, "5->12": 2, "5->13": 2, "5->14": 2, "5->15": 2, "5->2": 2, "5->3": 2, "5->4": 2, "5->7": 2, "5->8": 2, "5->9": 2, "6->0": 2, "6->1": 2, "6->10": 2, "6->11": 2, "6->12": 2, "6->13": 2, "6->14": 2, "6->15": 2, "6->2": 2, "6->3": 2, "6->4": 2, "6->5": 2, "6->8": 2, "6->9": 2, "7->0": 2, "7->1": 2, "7->10": 2, "7->11": 2, "7->12": 2, "7->13": 2, "7->14": 2, "7->15": 2, "7->2": 2, "7->3": 2, "7->4": 2, "7->5": 2, "7->6": 2, "7->9": 2, "8->0": 2, "8->1": 2, "8->10": 2, "8->11": 2, "8->12": 2, "8->13": 2, "8->14": 2, "8->15": 2, "8->2": 2, "8->3": 2, "8->4": 2, "8->5": 2, "8->6": 2, "8->7": 2, "9->0": 2, "9->1": 2, "9->11": 2, "9->12": 2, "9->13": 2, "9->14": 2, "9->15": 2, "9->2": 2, "9->3": 2, "9->4": 2, "9->5": 2, "9->6": 2, "9->7": 2, "9->8": 2}, "missing_neighbour_pairs": {}, "observed_distinct_pairs": 240, "ring_distinct_pairs": 16, "ring_pairs": {"0->1": 30, "1->2": 30, "10->11": 30, "11->12": 30, "12->13": 30, "13->14": 30, "14->15": 30, "15->0": 30, "2->3": 30, "3->4": 30, "4->5": 30, "5->6": 30, "6->7": 30, "7->8": 30, "8->9": 30, "9->10": 30}, "wrong_multiplicity": {"0->1": [2, 30], "1->2": [2, 30], "10->11": [2, 30], "11->12": [2, 30], "12->13": [2, 30], "13->14": [2, 30], "14->15": [2, 30], "15->0": [2, 30], "2->3": [2, 30], "3->4": [2, 30], "4->5": [2, 30], "5->6": [2, 30], "6->7": [2, 30], "7->8": [2, 30], "8->9": [2, 30], "9->10": [2, 30]}} | mismatch (QUARANTINED F-0004) |
| standalone_parity@128 | standalone_booksim | semi_independent_shared_engine | 507 == 507 | exact (QUARANTINED F-0004) |
| trace_execution_conservation@256 | trace_conservation | integration_gate | {"authority_accepted_flits": 1440, "authority_injected_flits": 1440, "flits": 1440, "packets": 480} | exact |
| workload_lowering_conservation@256 | ring_oracle | independent_oracle | {"chunk_bytes": 64, "flits_per_message": 3, "header_bits": 11, "messages": 480, "packets_per_message": 1, "payload_bytes": 1024, "ranks": 16, "total_bytes": 30720, "total_flits": 1440, "total_packets": 480, "usable_payload_bits": 245} | exact |
| collective_graph_conformance@256 | ring_oracle | independent_oracle | {"conforms": false, "extra_non_neighbour_pairs": {"0->10": 2, "0->11": 2, "0->12": 2, "0->13": 2, "0->14": 2, "0->15": 2, "0->2": 2, "0->3": 2, "0->4": 2, "0->5": 2, "0->6": 2, "0->7": 2, "0->8": 2, "0->9": 2, "1->0": 2, "1->10": 2, "1->11": 2, "1->12": 2, "1->13": 2, "1->14": 2, "1->15": 2, "1->3": 2, "1->4": 2, "1->5": 2, "1->6": 2, "1->7": 2, "1->8": 2, "1->9": 2, "10->0": 2, "10->1": 2, "10->12": 2, "10->13": 2, "10->14": 2, "10->15": 2, "10->2": 2, "10->3": 2, "10->4": 2, "10->5": 2, "10->6": 2, "10->7": 2, "10->8": 2, "10->9": 2, "11->0": 2, "11->1": 2, "11->10": 2, "11->13": 2, "11->14": 2, "11->15": 2, "11->2": 2, "11->3": 2, "11->4": 2, "11->5": 2, "11->6": 2, "11->7": 2, "11->8": 2, "11->9": 2, "12->0": 2, "12->1": 2, "12->10": 2, "12->11": 2, "12->14": 2, "12->15": 2, "12->2": 2, "12->3": 2, "12->4": 2, "12->5": 2, "12->6": 2, "12->7": 2, "12->8": 2, "12->9": 2, "13->0": 2, "13->1": 2, "13->10": 2, "13->11": 2, "13->12": 2, "13->15": 2, "13->2": 2, "13->3": 2, "13->4": 2, "13->5": 2, "13->6": 2, "13->7": 2, "13->8": 2, "13->9": 2, "14->0": 2, "14->1": 2, "14->10": 2, "14->11": 2, "14->12": 2, "14->13": 2, "14->2": 2, "14->3": 2, "14->4": 2, "14->5": 2, "14->6": 2, "14->7": 2, "14->8": 2, "14->9": 2, "15->1": 2, "15->10": 2, "15->11": 2, "15->12": 2, "15->13": 2, "15->14": 2, "15->2": 2, "15->3": 2, "15->4": 2, "15->5": 2, "15->6": 2, "15->7": 2, "15->8": 2, "15->9": 2, "2->0": 2, "2->1": 2, "2->10": 2, "2->11": 2, "2->12": 2, "2->13": 2, "2->14": 2, "2->15": 2, "2->4": 2, "2->5": 2, "2->6": 2, "2->7": 2, "2->8": 2, "2->9": 2, "3->0": 2, "3->1": 2, "3->10": 2, "3->11": 2, "3->12": 2, "3->13": 2, "3->14": 2, "3->15": 2, "3->2": 2, "3->5": 2, "3->6": 2, "3->7": 2, "3->8": 2, "3->9": 2, "4->0": 2, "4->1": 2, "4->10": 2, "4->11": 2, "4->12": 2, "4->13": 2, "4->14": 2, "4->15": 2, "4->2": 2, "4->3": 2, "4->6": 2, "4->7": 2, "4->8": 2, "4->9": 2, "5->0": 2, "5->1": 2, "5->10": 2, "5->11": 2, "5->12": 2, "5->13": 2, "5->14": 2, "5->15": 2, "5->2": 2, "5->3": 2, "5->4": 2, "5->7": 2, "5->8": 2, "5->9": 2, "6->0": 2, "6->1": 2, "6->10": 2, "6->11": 2, "6->12": 2, "6->13": 2, "6->14": 2, "6->15": 2, "6->2": 2, "6->3": 2, "6->4": 2, "6->5": 2, "6->8": 2, "6->9": 2, "7->0": 2, "7->1": 2, "7->10": 2, "7->11": 2, "7->12": 2, "7->13": 2, "7->14": 2, "7->15": 2, "7->2": 2, "7->3": 2, "7->4": 2, "7->5": 2, "7->6": 2, "7->9": 2, "8->0": 2, "8->1": 2, "8->10": 2, "8->11": 2, "8->12": 2, "8->13": 2, "8->14": 2, "8->15": 2, "8->2": 2, "8->3": 2, "8->4": 2, "8->5": 2, "8->6": 2, "8->7": 2, "9->0": 2, "9->1": 2, "9->11": 2, "9->12": 2, "9->13": 2, "9->14": 2, "9->15": 2, "9->2": 2, "9->3": 2, "9->4": 2, "9->5": 2, "9->6": 2, "9->7": 2, "9->8": 2}, "missing_neighbour_pairs": {}, "observed_distinct_pairs": 240, "ring_distinct_pairs": 16, "ring_pairs": {"0->1": 30, "1->2": 30, "10->11": 30, "11->12": 30, "12->13": 30, "13->14": 30, "14->15": 30, "15->0": 30, "2->3": 30, "3->4": 30, "4->5": 30, "5->6": 30, "6->7": 30, "7->8": 30, "8->9": 30, "9->10": 30}, "wrong_multiplicity": {"0->1": [2, 30], "1->2": [2, 30], "10->11": [2, 30], "11->12": [2, 30], "12->13": [2, 30], "13->14": [2, 30], "14->15": [2, 30], "15->0": [2, 30], "2->3": [2, 30], "3->4": [2, 30], "4->5": [2, 30], "5->6": [2, 30], "6->7": [2, 30], "7->8": [2, 30], "8->9": [2, 30], "9->10": [2, 30]}} | mismatch (QUARANTINED F-0004) |
| standalone_parity@256 | standalone_booksim | semi_independent_shared_engine | 505 == 505 | exact (QUARANTINED F-0004) |

**PASS**

quarantined findings: ['F-0004']

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
| collective_graph_conformance | ring_oracle | independent_oracle | {"conforms": false, "extra_non_neighbour_pairs": {"0->2": 2, "0->3": 2, "1->0": 2, "1->3": 2, "2->0": 2, "2->1": 2, "3->1": 2, "3->2": 2}, "missing_neighbour_pairs": {}, "observed_distinct_pairs": 12, "ring_distinct_pairs": 4, "ring_pairs": {"0->1": 6, "1->2": 6, "2->3": 6, "3->0": 6}, "wrong_multiplicity": {"0->1": [2, 6], "1->2": [2, 6], "2->3": [2, 6], "3->0": [2, 6]}} | mismatch (QUARANTINED F-0004) |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 39 == 39 | exact (QUARANTINED F-0004) |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=24 canonical=24 | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=39 vs canonical=39 (delta +0, tol 0) | exact (QUARANTINED F-0004) |

**PASS**

quarantined findings: ['F-0004']

## V10 — 4x4 mesh, 16-node ALLREDUCE 1024B: independent RTL execution of the canonical trace

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| trace_execution_conservation | trace_conservation | integration_gate | packets=960, flits=4800, auth_flits=4800/4800 | exact |
| workload_lowering_conservation | ring_oracle | independent_oracle | messages=480, bytes=30720, flits=4800, packets=960 | exact |
| collective_graph_conformance | ring_oracle | independent_oracle | {"conforms": false, "extra_non_neighbour_pairs": {"0->10": 2, "0->11": 2, "0->12": 2, "0->13": 2, "0->14": 2, "0->15": 2, "0->2": 2, "0->3": 2, "0->4": 2, "0->5": 2, "0->6": 2, "0->7": 2, "0->8": 2, "0->9": 2, "1->0": 2, "1->10": 2, "1->11": 2, "1->12": 2, "1->13": 2, "1->14": 2, "1->15": 2, "1->3": 2, "1->4": 2, "1->5": 2, "1->6": 2, "1->7": 2, "1->8": 2, "1->9": 2, "10->0": 2, "10->1": 2, "10->12": 2, "10->13": 2, "10->14": 2, "10->15": 2, "10->2": 2, "10->3": 2, "10->4": 2, "10->5": 2, "10->6": 2, "10->7": 2, "10->8": 2, "10->9": 2, "11->0": 2, "11->1": 2, "11->10": 2, "11->13": 2, "11->14": 2, "11->15": 2, "11->2": 2, "11->3": 2, "11->4": 2, "11->5": 2, "11->6": 2, "11->7": 2, "11->8": 2, "11->9": 2, "12->0": 2, "12->1": 2, "12->10": 2, "12->11": 2, "12->14": 2, "12->15": 2, "12->2": 2, "12->3": 2, "12->4": 2, "12->5": 2, "12->6": 2, "12->7": 2, "12->8": 2, "12->9": 2, "13->0": 2, "13->1": 2, "13->10": 2, "13->11": 2, "13->12": 2, "13->15": 2, "13->2": 2, "13->3": 2, "13->4": 2, "13->5": 2, "13->6": 2, "13->7": 2, "13->8": 2, "13->9": 2, "14->0": 2, "14->1": 2, "14->10": 2, "14->11": 2, "14->12": 2, "14->13": 2, "14->2": 2, "14->3": 2, "14->4": 2, "14->5": 2, "14->6": 2, "14->7": 2, "14->8": 2, "14->9": 2, "15->1": 2, "15->10": 2, "15->11": 2, "15->12": 2, "15->13": 2, "15->14": 2, "15->2": 2, "15->3": 2, "15->4": 2, "15->5": 2, "15->6": 2, "15->7": 2, "15->8": 2, "15->9": 2, "2->0": 2, "2->1": 2, "2->10": 2, "2->11": 2, "2->12": 2, "2->13": 2, "2->14": 2, "2->15": 2, "2->4": 2, "2->5": 2, "2->6": 2, "2->7": 2, "2->8": 2, "2->9": 2, "3->0": 2, "3->1": 2, "3->10": 2, "3->11": 2, "3->12": 2, "3->13": 2, "3->14": 2, "3->15": 2, "3->2": 2, "3->5": 2, "3->6": 2, "3->7": 2, "3->8": 2, "3->9": 2, "4->0": 2, "4->1": 2, "4->10": 2, "4->11": 2, "4->12": 2, "4->13": 2, "4->14": 2, "4->15": 2, "4->2": 2, "4->3": 2, "4->6": 2, "4->7": 2, "4->8": 2, "4->9": 2, "5->0": 2, "5->1": 2, "5->10": 2, "5->11": 2, "5->12": 2, "5->13": 2, "5->14": 2, "5->15": 2, "5->2": 2, "5->3": 2, "5->4": 2, "5->7": 2, "5->8": 2, "5->9": 2, "6->0": 2, "6->1": 2, "6->10": 2, "6->11": 2, "6->12": 2, "6->13": 2, "6->14": 2, "6->15": 2, "6->2": 2, "6->3": 2, "6->4": 2, "6->5": 2, "6->8": 2, "6->9": 2, "7->0": 2, "7->1": 2, "7->10": 2, "7->11": 2, "7->12": 2, "7->13": 2, "7->14": 2, "7->15": 2, "7->2": 2, "7->3": 2, "7->4": 2, "7->5": 2, "7->6": 2, "7->9": 2, "8->0": 2, "8->1": 2, "8->10": 2, "8->11": 2, "8->12": 2, "8->13": 2, "8->14": 2, "8->15": 2, "8->2": 2, "8->3": 2, "8->4": 2, "8->5": 2, "8->6": 2, "8->7": 2, "9->0": 2, "9->1": 2, "9->11": 2, "9->12": 2, "9->13": 2, "9->14": 2, "9->15": 2, "9->2": 2, "9->3": 2, "9->4": 2, "9->5": 2, "9->6": 2, "9->7": 2, "9->8": 2}, "missing_neighbour_pairs": {}, "observed_distinct_pairs": 240, "ring_distinct_pairs": 16, "ring_pairs": {"0->1": 30, "1->2": 30, "10->11": 30, "11->12": 30, "12->13": 30, "13->14": 30, "14->15": 30, "15->0": 30, "2->3": 30, "3->4": 30, "4->5": 30, "5->6": 30, "6->7": 30, "7->8": 30, "8->9": 30, "9->10": 30}, "wrong_multiplicity": {"0->1": [2, 30], "1->2": [2, 30], "10->11": [2, 30], "11->12": [2, 30], "12->13": [2, 30], "13->14": [2, 30], "14->15": [2, 30], "15->0": [2, 30], "2->3": [2, 30], "3->4": [2, 30], "4->5": [2, 30], "5->6": [2, 30], "6->7": [2, 30], "7->8": [2, 30], "8->9": [2, 30], "9->10": [2, 30]}} | mismatch (QUARANTINED F-0004) |
| standalone_parity | standalone_booksim | semi_independent_shared_engine | 990 == 990 | exact (QUARANTINED F-0004) |
| rtl_execution_conservation | rtl_execution | independent_execution_engine | flits rtl=4800 canonical=4800 | exact |
| rtl_completion | rtl_calibrated | calibrated_cross_engine | rtl=990 vs canonical=990 (delta +0, tol 0) | exact (QUARANTINED F-0004) |

**PASS**

quarantined findings: ['F-0004']

---

checks exact: 65/72 (18 quarantined by a filed finding)

by independence category (exact/total):
  calibrated_cross_engine            8/8
  independent_execution_engine       5/5
  independent_oracle                 17/24
  integration_gate                   16/16
  semi_independent_shared_engine     19/19

independent_oracle by provenance (exact/total):
  posthoc_hand                       3/3
  preregistered_hand                 3/3
  preregistered_oracle               3/6
  preregistered_physics              2/2
  unstated                           6/10
