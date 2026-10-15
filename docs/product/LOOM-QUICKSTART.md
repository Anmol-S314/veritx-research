# Loom quickstart (web Studio)

This guide covers the graph-authoring and workload-preview workflow in the
current Studio checkout. The Studio UI is fixture-backed and has **no engine
connectivity**. The simulation panel described below is explicitly mock,
geometry-only playback; it is not a fabric execution, performance measurement,
or simulator result. Do not use its utilization/stall illustrations as
measured design evidence.

## Start Studio

From the repository root:

```sh
cd apps/studio
npm ci
npm run dev
```

Open the local URL printed by Vite. Choose a project route from the Studio UI,
or open `/projects/quickstart/loom/graph` to inspect the Loom graph authoring
surface. The `quickstart` path segment is a route identifier; it does not
create a server-backed project. The graph editor currently keeps one
browser-local autosave key rather than isolating graph documents by project
ID.

## Create and edit a graph

1. In **Fabric canvas**, choose a starter topology from **Shape**. The preset
   seeds editable nodes and links; later edits turn it into a custom graph.
2. Select a node on the canvas or in the **Nodes** list to edit its role, port
   count, clock, or VC depth in the inspector.
3. Use **node (auto-wired)** to add a node next to the current graph, or select
   a node and use link mode to connect two nodes. A new empty graph offers
   **create first node** in the Nodes panel.
4. Check the **Validation** summary. Refused edits leave the project unchanged;
   inspect the visible error before proceeding.
5. Use **save project.json** to download the current editable Loom project.
   To reopen it, use **load project.json** and select that file. The editor
   also keeps a browser-local autosave for the current workspace key. Keep the
   downloaded JSON if you need a portable copy; browser autosave is not a
   backup or a synchronized project store.

The imported file is schema-validated before it replaces the current graph.
The current editor accepts Loom project schema version 1 only.

## Configure a workload

Open **Workload profiling**. If there is no workload block, choose **Load
starter (dense-47B TP8/EP8)**. This is authored workload intent, not a claim
that a 47-billion-parameter model or engine workload is bundled. Edit the model
label, sequence length, batch, precision and phase parallelism as needed. The
page reports when the requested TP×EP×PP×DP parallelism exceeds the graph's
node count. Workload profiling and Simulation use the project-scoped authoring
draft store, while the standalone Fabric canvas uses a separate local graph
autosave. These stores are not joined into one project export in this checkout;
exporting `project.json` from Fabric canvas therefore does not include workload
changes made on Workload profiling.

## Inspect the available playback

Open **Simulation** and use **Play**, **Pause**, the scrubber and metric
selector to inspect the preview. The panel labels this output **MOCK trace**:
its frames are generated for graph geometry, and queue latency, router power,
and per-cycle buffer figures are not measured or supplied. A visible mock
trace is not a completed engine run. The current checkout does not provide the
local-engine run path needed to execute and inspect a real simulation.

## Known limits

- Studio in this checkout is a web application, not a Tauri desktop package.
- The graph editor exports/imports a Loom project JSON file, but its local
  autosave is not project-ID scoped and is separate from the workload/simulation
  authoring draft. This is not a complete unified project-store,
  crash-recovery, licensing or multi-user workflow.
- The workload and playback surfaces do not connect to a real simulation
  engine. No performance budget, physical result or release qualification is
  implied by this quickstart.
- The fixture validator's normal fast path checks schema, linkage and engine
  vocabulary only; it explicitly does not prove backend realizability.
