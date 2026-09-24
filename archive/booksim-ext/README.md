# Physical multicast — retained research (veritx-integrate §18)

Canonical MULTICAST is replicated unicast
(`model/resolved_fabric.py`: no canonical multicast replication/branching
artifact; hardware-multicast-group requests refuse with UNSUPPORTED).
It must NOT be called physical multicast.

Historical physical-multicast work, retained distinctly:

- `archive/booksim-ext/multicast.patch` (300 lines): optional fidelity
  mode (`mcast_k`, `mcast_naive`, `reduce_col`, `bcast_all`). NOT applied
  by default; recover as explicit opt-in only after its historical gates
  rerun. Do not make default until qualified.
- `tracks/t3-topology/hardware/noc_multicast_bw.cpp`: bandwidth model.
- `tracks/t3-topology/scripts/research/`: `serving_multicast.py`,
  `prefix_multicast.py`, `multicast_savings.py` (+ `ucie_bridge_multicast`
  where present in source).
- `experiments/vllm_kv_multicast/`: KV multicast connector + benches.

Known RTL multicast corners (F1–F3) remain explicit limitations
(see `tracks/t3-topology/rtl/t3/README.md`).
