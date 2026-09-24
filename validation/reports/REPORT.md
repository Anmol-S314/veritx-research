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

---

checks exact: 11/11
