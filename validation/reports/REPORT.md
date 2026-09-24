# VERITX Validation Report

## V01 — 2x2 mesh, single 1-flit P2P router 0 -> router 3

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 4, 'tp': 4, 'link_width': 64, 'num_vcs': 1}  ·  workload: p2p

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| conservation | conservation | independent | packets=1, flits=1, auth_flits=1/1 | exact |
| hand_counts | hand_calculated | independent | {"flits": 1, "packets": 1} | exact |
| hand_route | hand_calculated | independent | hand=2, canonical=2.0, authority=3.0 (expected 3) | exact |
| standalone_parity | standalone_booksim | semi_independent | 17 == 17 | exact |
| window_invariance | standalone_booksim | semi_independent | completion=17, windows={'veritx': 1001, 'authority': 2001, 'authority_alt': 3001} | exact |

**PASS**

## V02 — 4x4 mesh, 16-node TP ALLREDUCE, 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| conservation | conservation | independent | packets=960, flits=4800, auth_flits=4800/4800 | exact |
| standalone_parity | standalone_booksim | semi_independent | 990 == 990 | exact |
| window_invariance | standalone_booksim | semi_independent | completion=990, windows={'veritx': 1960, 'authority': 2960, 'authority_alt': 3960} | exact |

**PASS**

## V03 — 4x4 mesh, 16-node EP ALLTOALL, 1024 B payload

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 16, 'tp': 16, 'link_width': 64, 'num_vcs': 1}  ·  workload: collective

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| conservation | conservation | independent | packets=480, flits=2400, auth_flits=2400/2400 | exact |
| standalone_parity | standalone_booksim | semi_independent | 719 == 719 | exact |
| window_invariance | standalone_booksim | semi_independent | completion=719, windows={'veritx': 1480, 'authority': 2480, 'authority_alt': 3480} | exact |

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
| monotonicity | monotonicity | independent | series={'32': 1962, '64': 990, '128': 507, '256': 505} authority={'32': 1962, '64': 990, '128': 507, '256': 505} | exact |
| conservation@32 | conservation | independent | packets=1920, flits=12000, auth_flits=12000/12000 | exact |
| standalone_parity@32 | standalone_booksim | semi_independent | 1962 == 1962 | exact |
| conservation@64 | conservation | independent | packets=960, flits=4800, auth_flits=4800/4800 | exact |
| standalone_parity@64 | standalone_booksim | semi_independent | 990 == 990 | exact |
| conservation@128 | conservation | independent | packets=480, flits=2400, auth_flits=2400/2400 | exact |
| standalone_parity@128 | standalone_booksim | semi_independent | 507 == 507 | exact |
| conservation@256 | conservation | independent | packets=480, flits=1440, auth_flits=1440/1440 | exact |
| standalone_parity@256 | standalone_booksim | semi_independent | 505 == 505 | exact |

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
| monotonicity | monotonicity | independent | series={'7': 2, '64': 10, '512': 78, '4096': 619} authority={'7': 2, '64': 10, '512': 78, '4096': 619} | exact |
| conservation@7 | conservation | independent | packets=1, flits=2, auth_flits=2/2 | exact |
| standalone_parity@7 | standalone_booksim | semi_independent | 38 == 38 | exact |
| conservation@64 | conservation | independent | packets=2, flits=10, auth_flits=10/10 | exact |
| standalone_parity@64 | standalone_booksim | semi_independent | 48 == 48 | exact |
| conservation@512 | conservation | independent | packets=10, flits=78, auth_flits=78/78 | exact |
| standalone_parity@512 | standalone_booksim | semi_independent | 132 == 132 | exact |
| conservation@4096 | conservation | independent | packets=78, flits=619, auth_flits=619/619 | exact |
| standalone_parity@4096 | standalone_booksim | semi_independent | 809 == 809 | exact |

**PASS**

## V06 — 2x2 mesh, single 1-flit P2P 0 -> 3: T3 RTL (Verilator) parity

profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`  ·  fabric: {'compute_tiles': 4, 'tp': 4, 'link_width': 64, 'num_vcs': 1}  ·  workload: p2p

| check | authority | independence | value | verdict |
|---|---|---|---|---|
| conservation | conservation | independent | packets=1, flits=1, auth_flits=1/1 | exact |
| hand_counts | hand_calculated | independent | {"flits": 1, "packets": 1} | exact |
| hand_route | hand_calculated | independent | hand=2, canonical=2.0, authority=3.0 (expected 3) | exact |
| standalone_parity | standalone_booksim | semi_independent | 17 == 17 | exact |
| rtl_conservation | rtl | independent | {"canonical_flits": 1, "canonical_packets": 1, "rtl_ejected_flits": 1, "rtl_ejected_packets": 1, "rtl_injected_packets": 1} | exact |
| rtl_route | rtl | independent | {"hand_router_hops": 2, "rtl_hops": [2]} | exact |
| rtl_latency | rtl_calibrated | semi_independent | {"rtl_latency": 17, "rtl_law": "7 + 5*hop", "veritx_completion": 17} | exact |

**PASS**

---

checks exact: 36/36
