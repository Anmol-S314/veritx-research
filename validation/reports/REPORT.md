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

---

checks exact: 5/5
