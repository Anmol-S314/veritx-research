# T3 RTL — retained research (veritx-integrate §17)

Source: `t3-rtl-noc-backup-20260815` (`f8ab4a63`), verbatim under `rtl/t3/`
plus `tb/noc_tb.sv`. Binding evidence:
`tracks/t3-topology/research/rtl-audit-2026-08-13.md`.

Classification (audit is binding):

- 2D / two-die (`router.sv`, `mesh.sv`, `nic.sv`, `noc_2die.sv`,
  `noc_pkg.sv`, `islip.sv`): substantially implemented →
  RETAIN_RESEARCH / optional qualified backend only after F1–F3 fixes.
- Known-broken multicast corners → explicit limitation, not default:
  F1 mixed-traffic fork-copy collision (`router.sv`),
  F2 multicast reorder deadlock (`nic.sv`),
  F3 multi-flit multicast forks head-only (`router.sv`).
- 3D (`mesh_3d.sv`, `router_3d.sv`, `noc_3d_pkg.sv`): functional-only,
  not a timing oracle.
- 4D (`mesh_4d.sv`, `router_4d.sv`): incomplete/stub, unqualified —
  do not run or cite.

No RTL rewrite in this slice. Consolidation and truthful retention only.
