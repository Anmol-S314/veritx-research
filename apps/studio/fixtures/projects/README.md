# Offline Loom project samples

Each JSON file is a portable Loom project fixture. In the Studio's Loom Graph editor, use **load project.json** and choose one of these files. Loading a local file requires no network service; the editor validates the document before replacing the current graph. These are authored examples, not qualification evidence.

- `small-custom.project.json` — small editable topology.
- `multi-domain.project.json` — graph/domain and crossing example.
- `floorplanned.project.json` — three-node placement and die outline. Geometry is authored intent only, not physical-tool measurement or signoff.
- `workload-bound.project.json` — workload/graph mapping example. The web checkout has no real simulation engine; its Simulation view may display a clearly labelled mock preview only. This file is not a real simulation result.
- `mesh-8x8.project.json` — larger topology example.

Files can also be checked offline from the repository with the Studio's project parser. Keep an untouched copy of each sample when experimenting.
