# Srota Loom → VERITX / Srota Studio: UI/UX & Feature Gap Analysis

**Status:** evidence-based gap register, not a plan of record
**Date:** 2026-10-05
**Subject under review (theirs):** `https://srota-loom.onrender.com/` — app title `Srota Loom [dev]`
**Baseline (ours):** `apps/studio` (`srota-studio@0.1.0`, product title *VERITX Studio*), served from `dist/` against the live gateway on `:8123`
**Governing spec for ours:** `tracks/t3-topology/dse/docs/SROTA-STUDIO-PRD-001.md` (branch `origin/feat/srota-noc`)

**Update (2026-10-06):** the Loom workspace now ships in `apps/studio` as one
deep-linkable route (`/projects/:id/loom/:view`, rail item *Loom*) carrying all
six tabs — logical topology (three datapath planes), agent matrix, I–T mapping,
physical floorplan, workload profiling, simulation — under this register's own
guardrails. Cluster 1 (floorplan) renders certified coordinates, channel
adjacency and link lengths only, and refuses die/area/TDP/timing numbers.
Cluster 3 (multi-plane) keeps the three planes and marks telemetry/config as
named extension points instead of claiming `3 Planes Validated`. §6.6's I–T
matrix ships as a *measured* src→dst matrix plus a certified path query, with
the permission column and the cycle scrubber stating the artifact they need.
Still open: Cluster 2 (IP catalog + stamp), Cluster 4 (per-agent deep config),
Cluster 5 (in-canvas editing + `Generate RTL`), and the P0 doc/a11y items in §11.

---

## 0. TL;DR

Srota Loom is **a spatial, direct-manipulation fabric editor**: the topology is the primary object, every edit happens on or next to the canvas, and it boots to a complete 64-node design with no backend.

Our Studio is **a compiler console**: the certificate is the primary object, edits flow through a draft → compile → verify pipeline, and every number carries provenance.

The delta is therefore not "they have more pages" — we have 22 routes and they have 6 tabs. The delta is five feature clusters we do not have at all:

| # | Missing cluster | Their evidence | Ours |
|---|---|---|---|
| 1 | **Physical floorplan view** | `Physical Floorplan` tab: TSMC N3E, 24.5×24.5 mm die, 600.25 mm², 2.85 B transistors, M4–M10 metal stack, per-tile `Area 6.2 mm² / TDP 45 W`, congestion + WNS + clock-tree + thermal overlays | **0 floorplan code** (`grep -ri floorplan apps/studio/src` → empty) |
| 2 | **IP primitive catalog + spatial stamp** | `EDA IP CATALOG — 15 IPS`, search, `All/Compute/Memory/Routers/Bridges` chips, and a `Stamp Tool` ("click any node on the canvas to stamp this IP") | no primitive library, no placement, no search |
| 3 | **Multi-plane fabric** | `Data Plane 512-bit mesh` / `Telemetry Plane 32-bit diagnostic tree` / `Config Plane 32-bit 2D Hilbert curve`, drawn on the same canvas, colour-coded, `3 Planes Validated` | single fabric; `Multiplane` is a research tab with no visualisation |
| 4 | **Per-agent deep config** | AIU type/protocol/clock/power, sideband, access perms, connected targets, max outstanding, ordering rules, splitting rules, buffer depth/VC, root PLL, reset scheme | `grep` → **0 hits** for AIU, sideband, ordering, splitting, connected targets, flow control, PLL, buffer depth, VC mapping |
| 5 | **In-canvas editing + Generate RTL** | click a wire → `> Fwd / < Bwd / <> Full`; click a node → edit; `Generate RTL` button | selection only, no mutation; no export action from the fabric |

Plus **18 partials** (we have the data or a form, but not the direct interaction) — full register in §6.

**Do not copy:** their accessibility (Lighthouse 69 vs our 97), their layout (their own primary `Generate RTL` button is clipped off-screen at 1440 px), and their evidence model (concrete PPA numbers asserted with no artifact chain — which our own `DESIGN.md` forbids).

---

## 1. Scope, method and tooling

Everything below is measured, not inferred. Three passes:

**Pass 1 — black-box browser capture (Playwright).** Drove the JS password gate, then dumped DOM, accessibility tree, computed design tokens, network, console, and full-page + mobile screenshots for both apps.

**Pass 2 — exhaustive control inventory.** Clicked every one of their 6 nav tabs, both topology modes, both grid sizes, all 3 planes, and `Generate RTL`, capturing screenshots + text + counts per view. Extracted every `<select>` with its full option list.

**Pass 3 — Chrome DevTools via `chrome-devtools-axi`.** Real Lighthouse audits (accessibility / best-practices / SEO / agentic-browsing), real performance traces with LCP breakdown, and element-extent measurement to determine whether clipped content is reachable.

### Reproduction

```bash
# --- ours ---
cd tracks/t3-topology/dse && uvicorn veritx_dse.gateway.app:app --port 8123   # gateway
cd apps/studio && npm run build && npx vite preview --port 4173                # console

# --- theirs (playwright capture) ---
TARGET_URL=https://srota-loom.onrender.com/ TARGET_PWD=srota-2026-loom \
OUT_DIR=/tmp/srota-inspect NODE_PATH=$PWD/node_modules node /tmp/inspect_site.cjs

# --- theirs (per-view tour) ---
NODE_PATH=$PWD/node_modules node /tmp/tour_loom.cjs

# --- Chrome DevTools audits ---
chrome-devtools-axi open https://srota-loom.onrender.com/
chrome-devtools-axi fill @<uid> "srota-2026-loom" && chrome-devtools-axi click @<uid>
chrome-devtools-axi lighthouse --device desktop --mode snapshot --output-dir /tmp/lh-loom
chrome-devtools-axi perf-start --no-auto-stop && sleep 10 && chrome-devtools-axi perf-stop

# --- clipping/extent measurement ---
chrome-devtools-axi resize 390 844
chrome-devtools-axi eval "() => { let maxR=0; for (const el of document.querySelectorAll('body *')) { const r=el.getBoundingClientRect(); if (r.width===0&&r.height===0) continue; maxR=Math.max(maxR,r.right); } return {innerW:innerWidth, contentRight:maxR, bodyOverflow:getComputedStyle(document.body).overflow}; }"
```

---

## 2. What each surface actually is

### 2.1 Theirs — Srota Loom `[dev]`

- **Shape:** one screen, no URL routing, no scrolling, `body { overflow: hidden }`.
- **Layout at 1440 px:** fixed 3-column cockpit — `aside.panel-left` (260 px, parameters) · `main.canvas-wrapper` (830 px, the fabric) · `aside.panel-right` (350 px, agent inspector) — plus `header.studio-header` and `footer.bottom-status-bar`.
- **Stack:** React 18 UMD **development** builds + `@babel/standalone`, all three fetched from `unpkg.com` at runtime, JSX transpiled **in the browser**. Delivered as a 405 KB AES-GCM self-decrypting HTML document (`document.write` after `crypto.subtle` PBKDF2+AES-GCM).
- **Routes:** none. 0 `<a href>`. 26 `<button>`. Tabs are client state.
- **Content:** canned. Works with zero backend. Every control changes something visible immediately.

### 2.2 Ours — VERITX / Srota Studio

- **Shape:** 22 addressable routes (`/`, `/runs`, `/trust`, `/projects/:id/<section>`), real anchors, deep-linkable, back-button-safe.
- **Layout:** sticky topbar + numbered left rail + scrolling workspace, 900–7063 px tall per page.
- **Stack:** React 19 + Vite 6, prebuilt; `main` bundle 780 KB (209 KB gzip); gateway-backed FastAPI on `:8123`; fixture-backed offline demo when the gateway is down.
- **Content:** live. 2 projects, 4 revisions, 16 runs, 10/10 verification obligations, BookSim/ASTRA/Ramulator qualifications.

### 2.3 Their six views (what each one is)

| View | Elements | Canvas | What it is |
|---|---|---|---|
| **Logical Topology** (default) | 1125 | 990×924 SVG | the fabric editor |
| **Agent Matrix** | 1188 | — | 64-row table of *every agent's full config*, exportable |
| **I-T Mapping** | 1682 | — | initiator × target access/firewall matrix |
| **Physical Floorplan** | 1579 | 990×924 SVG | die floorplan with physical overlays |
| **Workload Profiling** | 569 | — | model → tensor→agent mapping + execution perspectives |
| **Simulation (8×8)** | 342 | 740×680 SVG | congestion heatmap + link drill-down + scrubbable timeline |

---

## 3. Measured comparison

### 3.1 Chrome DevTools Lighthouse (desktop, snapshot)

| Category | Theirs | Ours |
|---|---|---|
| Accessibility | **69** | **97** |
| Best Practices | 100 | 100 |
| SEO | 75 | 60 |
| **Agentic Browsing** | **0** | **50** |
| Passed / Failed audits | 15 / 5 | 33 / 5 |

**Their failing audits:** colour contrast (multiple), `Form elements must have labels`, `Select elements must have associated label elements`, `No meta description`, and `Accessibility tree is not well-formed` — the last one is why Agentic Browsing is 0. Lighthouse cites the exact node: `header.studio-header > div.header-actions > div > select.select-input` (the `⚡ Srota Engine Optimized` selector) has no accessible name.

**Our failing audits:** colour contrast on `.muted` text, `Elements with visible text labels do not have matching accessible names` (our rail items: `aria-label="Design"` while visible text renders `Design edit`), no meta description, and two SPA-fallback artifacts (`/robots.txt` and `/llms.txt` return `index.html` under `vite preview` — a server-config issue, **not** a product defect; neither file exists in `dist/`).

### 3.2 Performance trace

| | Theirs | Ours |
|---|---|---|
| **LCP** | **1922 ms** | **187 ms** |
| — TTFB | 357 ms (18.6%) | 2 ms |
| — element render delay | **1565 ms (81.4%)** | 185 ms |
| CLS | 0.00 | 0.00 |

Their result is not network-bound — 81% of LCP is render delay, caused by fetching three ~4 MB CDN scripts and then transpiling JSX in the browser:

| Resource | Size |
|---|---|
| `babel.min.js` | 3064 KB |
| `react-dom.development.js` | 1054 KB |
| `react.development.js` | 107 KB |
| encrypted document | 405 KB |

### 3.3 Layout integrity

Measured content extent vs viewport, with `body { overflow: hidden }`:

| Viewport | Their content right edge | Unreachable | Ours |
|---|---|---|---|
| 390×844 (iPhone) | **1587 px** | **1197 px — 75% of the UI, unscrollable** | `scrollWidth 390`, no overflow |
| 1440×900 | **1589 px** | 149 px | no overflow |
| 1600×1000 | 1600 px | none | no overflow |

**The 149 px clipped at 1440 is not cosmetic.** At 1440 the header lays out as: `.nav-tabs` 259→857, `.header-actions` 857→1587. Measured button/select boxes at a 1440 px viewport:

| Control | left → right | On screen? |
|---|---|---|
| `⚡ Srota Engine Optimized` | 1000 → 1176 | yes |
| `Tuned For:` preset select | 1236 → 1451 | **clipped by 11 px** |
| **`Generate RTL`** | **1468 → 1587** | **no — entirely outside the viewport** |

Because `body { overflow: hidden }` there is no horizontal scroll to reach it. Their single most important export action is unreachable at the most common laptop width.

### 3.4 Accessibility and semantics (DOM-level)

| | Theirs | Ours |
|---|---|---|
| Headings | **0** | 1–49 per page (12 on `/trust`, 49 on evidence) |
| Links | **0** | 3–20 per page |
| Tables | **0** | 0–13 per page |
| Labels / landmarks | 6 landmarks, **0 labelled** | e.g. capabilities 30 of 33 labelled |
| Labelled form controls | **1 of 20** | 15/15 on design, 28/35 on serving |
| Smallest type | **6.5 px (×72), 7 px (×68)**, 8, 8.5, 9, 9.5 px | 11 px floor |
| Focusables | 46 | 15–25 per page |
| Themes | dark only | dark + light |
| `lang` | `en` | `en` |

---

## 4. Complete feature inventory — Srota Loom

This is the full spec of what they built, so nothing is lost when the discussion moves on.

### 4.1 Header (26 buttons, 3 selects)

- Brand `Srota Loom` + `DEV` badge
- Grid switcher: `4×4 (16T)` / `8×8 (64T)`
- Nav tabs: `Logical Topology` · `Agent Matrix` · `I-T Mapping` · `Physical Floorplan` · `Workload Profiling` · `Simulation (8×8)`
- Topology mode: `2D Mesh` / `Torus`
- `⚡ Srota Engine Optimized` (auto-tuned topology) — *select*
- `Tuned For:` workload preset — *select* (4 presets)
- `Generate RTL`

### 4.2 Left panel

- **DATAPATH PLANES** — 3 selectable planes, each with its own topology family
- **GLOBAL SROTA IP PARAMETERS** — default spec setting, synchronizer cell, IP spec name, flit data bus width, default VC depth, flow control
- **⚡ SROTA SYNTHESIS SPEC** — tuned traffic pattern, custom fabric architecture, pruned ports, peak bisection BW, avg hop reduction, DRC/metal grid
- **🧩 EDA IP CATALOG — 15 IPS** — search field, category chips (`All`/`Compute`/`Memory`/`Routers`/`Bridges`), 15 IP cards each with glyph, name, protocol, and a spec line
- **Stamp tool** — `Apply to Agent_1_1`, mode hint "When active, click any node on the canvas to stamp this IP", per-IP readout `Area (N3E) / Gate Count / Est. Power`

The 15 primitives, verbatim:

| IP | Protocol / spec line |
|---|---|
| NPU Tensor Core | AXI5 · 512b Flits · 1.6 GHz · Initiator |
| Vector Coprocessor | CHI-E · 512b Flits · 1.4 GHz · CHI-E Direct |
| Streaming DMA Engine | AXI5 · 512b Bursts · 64 Outstanding Tx |
| Host PCIe/CXL Root | AXI5 · x16 Lanes · 64 GT/s · Cache/Mem |
| HBM3e Memory Controller | CHI-G · 1.2 TB/s · DFI 5.0 · 16 Pseudo-Ch |
| L2/L3 SRAM Scratchpad | AXI5 · 128 MB · Single-Cycle Bank · 512b |
| UCIe D2D Chiplet PHY | TileLink-UH · Standard Pkg · 32 Gbps/bump · Raw |
| 5-Port Mesh Router | N, S, E, W, Local · 4 VCs · 8 Flits |
| Concentrated 2:1 Router | 2 Clients / Node · Dedicated VCs |
| Concentrated 4:1 Router | 4 Clients / Node · Quad-Port Crossbar |
| RCU Collective Crossbar | Srota Native Stream · 1024b Highway · Hardware Sum/Max |
| Pipeline Retiming Stage | Forward/Backward/Full Reg · M4/M5 |
| CDC Async FIFO Bridge | MTBF > 10,000 Yrs · Depth 16 |
| CSR Config Tap / Controller | 32b @ 800 MHz · Zero Crossbar Area |
| Telemetry ATB Trace Hub | Watchpoint Trigger · Flit Monitor |

### 4.3 Centre canvas (Logic Topology)

- 64 numbered tiles (`0,0` … `7,7`) each showing role (`NPU` / `HBM3e` / `PCIe` / `UCIe` / `RCU`) and direction marker (`I` initiator / `T` target)
- Concentration badges on wired tiles (`P0 P1` + `2:1 DED`)
- 4 labelled cluster regions: `CLUSTER 0 (NW) · 16 TILES · MOE EXP 0..3` … `CLUSTER 3 (SE) … 12..15`
- Central overlay: `1024b CROSS-DIE ALL-TO-ALL HIGHWAY`
- `Click any wire to edit pipeline registers (> Fwd, < Bwd, <> Full)`
- Topology caption switches with mode: `▤ 2D MESH: Standard Orthogonal Grid (112 Bidirectional Links)` vs `🌀 TORUS TOPOLOGY: Wraparound Boundary Channels Active | Diameter: 4 Hops`

### 4.4 Right panel — AGENT MICRO-INSPECTOR

Header `AGENT_1_1`, `Assigned Role: NPU Compute`, then accordion groups:

- **NODE CONCENTRATION & VIRTUAL CHANNELS (VC)** — concentration ratio, active input ports, VC allocation mode, buffer depth per VC, `Apply Concentration & VC Scheme to All Nodes`
- **SROTA NOC & SYNCHRONIZER** — default setting, synchronizer cells
- **DOMAIN (CLOCK & POWER)** — frequency, root clock, reset scheme, power domain
- **AGENT INTERFACE UNIT (AIU)** — AIU type, protocol, AIU clock domain, AIU power domain, bus width
- **SIDEBAND INTERFACES**
- **MAPPING & CONNECTIVITY** — access perms, local address, window size, global address, connected target agents
- **ARCHITECTURAL PARAMETERS** — max outstanding, ordering rules, splitting rules

### 4.5 Footer status bar

`Grid: 8×8 (64 Nodes)` · `Topology: Srota Engine Optimized (Express 1024b)` · `Active Agent: Agent_1_1` · `Fabric: Srota 512b Crossbar (112 Physical Links)` · `✓ 3 Planes Validated (Data 512b, Telemetry 32b, Config 32b)`

### 4.6 The six views in detail

**Agent Matrix** — headline `64 SoC Fabric Agents`, `Full Crossbar Configuration & Address Remapping`; stat tiles `52 Init / 12 Target`, `4 PLLs (0.6 – 1.6 GHz)`, `512-bit Srota Flit (112 Links)`, `16.0 GB Mapped`; filters (AIU Type: all/initiators/targets; Clock: 7 domains; Power: collapsible/always-on); `Export CSV`; `Apply All`; a 12-column table: Agent ID · Tile (X,Y) · Assigned Role · AIU Type · Protocol · Clock Domain · Power Domain · CDC Synchronizer · Max OT · Ordering Rules · Splitting · Base Address · Access.

**I-T Mapping** — `Initiator-Target Access & Firewall Matrix`; stats `52 Init × 12 Target`, `624 Routing Paths`, `ALLOWED/BLOCKED 512 (82%) / 112 BLK`, `✓ Zero-Trust Rules Validated`; policy presets `Allow All (Full Crossbar)` / `HBM Partitioning` / `Zero-Trust Strict Isolation`; cell states `✓ RW · RO Read · ✕ BLK · SEC Secure`; `Export Matrix CSV`.

**Physical Floorplan** — `SILICON DIE SPECS`: process `TSMC N3E FinFET`, die `24.5 × 24.5 mm`, area `600.25 mm²`, transistors `2.85 Billion`; `PHYSICAL DESIGN OVERLAYS`: routing congestion (GRC density), wire delay slack (WNS/TNS), clock tree distribution, thermal/power density (TDP); `METAL LAYER STACK`: M4 horizontal 0.18 µm pitch, M5 vertical 0.24 µm pitch, M8/M9 clock trunk, M10/RDL power grid; hard IP blocks: 2× HBM3e 1024-bit PHY micro-bump arrays (CH 0–3, 4–7), PCIe Gen5 x16 SerDes + CXL 2.0 PHY, UCIe 32 Gbps D2D PHY; every tile annotated `Area: 6.2 mm² | TDP: 45W` (compute) or `22W` (memory/IO); tools `Select` / `Measure (µm)` / `Route All`.

**Workload Profiling** — `MODEL INPUT PARAMETERS`: model family (MoE Mixtral 8x7B / Dense LLaMA-3 70B / DiT-XL / ResNet-152 / custom), parameter count (140 B), sequence length (2048/4096/8192/32k), batch size, numeric precision (FP8/FP16-BF16/INT8); `PARALLELISM STRATEGY`: TP 8, EP 8, PP 1, DP 1, `Total Tile Budget 64/64 Tiles`; `SERVING MODE`: decode-heavy / prefill-heavy / mixed; a `TENSOR ➔ AGENT MAPPING (8x8 COMPUTE TILE MATRIX)` with per-tile `E<expert>` and `TP_<rank> EP_<expert> Shard` labels, `HBM3e 1.2 TB/s` and `UCIe Chiplet` annotations and `HOT` markers; `PERSPECTIVES`: 1. Phase Flow & Active Links, 2. Phase Injection & QoS Table, 3. Execution Gantt Timeline; actions `Auto-Map Model`, `Synthesize & Run ➔`.

**Simulation (8×8)** — metric selector (`Link Utilization %` / `Stall Cycles` / `Average Wait Latency`) driving a heatmap over the 8×8 router grid; `GLOBAL NETWORK TELEMETRY`: avg latency `36.8 cyc`, peak bisection `2,048 Gbps`; `TOP 5 CONGESTED LINKS (224 CHANNELS)` as a table (`R3,3➔R4,3 98% 480` …); `SELECTED LINK METRICS` (utilisation 98%, total flits tx 14,014, stall cycles 480) with a wait/latency breakdown; a scrubbable `Cycle: 4,092` timeline over `Phase 3: MoE All-to-All Dispatch (HOT SKEW)`; footer `Trace: Cycle-Accurate (10,000 cycles)`, `8×8 Mesh (64 Routers, 112 Bidirectional Links / 224 Channels)`, `● Trace Source: AI Workload Profiler (Mixtral 8x7B)`.

**The three planes** (same canvas, different overlay):
- `Data Plane — 512-bit High-Bw Mesh`: the mesh topology
- `Telemetry Plane — 32-bit Diagnostic Tree`: `TEL_HUB_0..3 (3.2 GB/s Agg)` + `TRACE ENGINE (12.8 GB/s Buffer)` on a tree
- `Config Plane — 32-bit 2D Hilbert Curve`: `CSR CONFIG INGRESS/EGRESS`, `⚡ 4-CLUSTER EXPRESS HUB`, and 64 `#n +0x…` register addresses laid out along a Hilbert curve

---

## 5. Their complete knob inventory (verbatim option lists)

These are the exact `<select>` controls and every option, extracted from the live DOM. Anything in this table that is absent from §6's "ours" column is a concrete, buildable gap.

| # | Control | Options |
|---|---|---|
| 0 | Workload preset (header) | MoE All-to-All Dispatch · Dense LLM TP/PP Pipeline · Diffusion Spatial Halo · Memory-Bound Stream (DLRM) |
| 1 | Tuned workload (canvas caption) | same 4, with example models: (Mixtral/DeepSeek) · (LLaMA-3) · (DiT-XL/SD) · (DLRM/Embedding) |
| 2 | Concentration Ratio | `1:1 (Direct PE ➔ Router)` · `2:1 (2 PEs Concentrated)` · `4:1 (4 PEs Concentrated)` |
| 3 | VC Allocation Mode | Same VC (Shared Dynamic Pool) · Separate VCs (Dedicated per Input) · **Custom VC Mapping Matrix** |
| 4 | Buffer Depth per VC | 4 Flits/VC (Low Area) · 8 (Balanced) · 16 (High Throughput) · 32 (Deep Buffers) |
| 5 | NoC default setting | Yes (Global Spec) · No (Custom Override) |
| 6 | Synchronizer Cells | Async FIFO (Depth 8, Gray) · 2-FF Synchronizer · 3-FF Synchronizer · None (Fully Synchronous) |
| 7 | Frequency | clk_npu (1.4 GHz) · clk_core (1.2 GHz) · clk_fabric (1.0 GHz) · clk_hbm (800 MHz) |
| 8 | Root Clock | PLL0_Core · PLL1_Mem · PLL2_Fabric |
| 9 | Reset Scheme | Async Assert / Sync Deassert · Synchronous Reset |
| 10 | Power Domain | Always-On · Collapsible (Power-Gated) |
| 11 | AIU Type | Initiator (Master) · Target (Slave) · Dual Initiator/Target |
| 12 | Protocol | AXI5 · AXI4 · ARM CHI.B · TileLink-UH · Srota Native Stream |
| 13 | Access Perms | Read / Write · Read Only · Write Only |
| 14 | Max Outstanding (OT) | 16 · 32 · 64 · 128 Transactions |
| 15 | Ordering Rules | RAW Hazard Check · Strongly Ordered · Relaxed Ordering |
| 16 | Splitting Rules | Split at 64B · 128B · 256B Flits |
| — | Simulation metric | Link Utilization % · Stall Cycles · Average Wait Latency |
| — | I-T policy preset | Allow All (Full Crossbar) · HBM Partitioning · Zero-Trust Strict Isolation |

---

## 6. Gap register — every feature mapped

Legend: **MISSING** = no code. **PARTIAL** = the data or a form exists but not the interaction. **HAVE** = present, noted for completeness.

### 6.1 Fabric canvas and editing

| Feature | Status | Evidence |
|---|---|---|
| Edit pipeline registers by clicking a wire | **MISSING** | `FabricCanvas.tsx:60-72` sets `selection` only; no write path back to the design |
| Edit a node by clicking it on the canvas | **MISSING** | same — `pickRouter`/`pickLink` are select-only |
| Stamp an IP primitive onto a node | **MISSING** | no placement model anywhere |
| Cluster region overlays with expert ranges | **MISSING** | `FabricCanvas.tsx:9-30` — 4 of 5 overlays hard-disabled; only `structure` renders |
| Central express-highway / corridor overlay | **MISSING** | "zero diagonal wires", corridor inspect has no equivalent |
| Concentration badges on tiles (`2:1 DED`) | **PARTIAL** | `concentration` exists as a design scalar (`DesignViewV2Editor.tsx:22`); never drawn as a per-tile badge |
| Role + direction markers per tile | **PARTIAL** | `fabricLayout.ts` buckets agent kinds and derives chips; no `I`/`T` initiator/target marker |
| Canvas is the primary surface, on screen by default | **PARTIAL** | ours is a 558×579 SVG inside a card behind a `Recent decisions / Topology graph` tab (`pages/index.tsx:385-437`) |
| Zoom / pan | **HAVE** | `FabricInspector2D.tsx:135-190` (viewBox + pan) — better than theirs |
| Click router/channel/endpoint → detail inspector | **HAVE** | `FabricCanvas.tsx:168,191`; `FabricInspector.tsx` |

### 6.2 Physical / PPA

| Feature | Status | Evidence |
|---|---|---|
| Physical floorplan view | **MISSING** | `grep -ri floorplan apps/studio/src` → 0 |
| Per-IP area / gate count / power readout | **MISSING** | only aggregate analytical estimates exist (`ImplementationLab/capabilityLedger.ts` energy authorities: `mm² / W` estimate) |
| Die specs (node, dimensions, area, transistors) | **MISSING** | no die model |
| Metal layer stack (M4/M5/M8/M9/M10) | **MISSING** | — |
| Physical overlays: congestion, WNS/TNS slack, clock tree, thermal density | **MISSING** | — |
| Hard-IP PHY blocks (HBM3e PHY, PCIe/CXL PHY, UCIe PHY) | **MISSING** | — |
| Measure / route tools on the floorplan | **MISSING** | — |
| Power domains as a design field | **HAVE** | `PhysicalContext.num_power_domains`, `Agent.power_domain` (`DesignViewV2Editor.tsx:28,36`) |
| Energy authorities with fidelity labels | **HAVE (deeper)** | Implementation Lab §37 — six separate authorities with units and calibration |

### 6.3 IP library and placement

| Feature | Status | Evidence |
|---|---|---|
| Browsable IP primitive catalog | **MISSING** | our `capabilities` page is engine capabilities, not placeable IPs |
| Search over primitives | **MISSING** | — |
| Category facets (Compute/Memory/Routers/Bridges) | **MISSING** | — |
| Per-primitive attribute line (protocol/BW/clock) | **MISSING** | — |
| Stamp / place primitive onto topology | **MISSING** | — |

### 6.4 Multi-plane fabric

| Feature | Status | Evidence |
|---|---|---|
| Data / Telemetry / Config planes as selectable views | **MISSING** | single fabric |
| Per-plane topology family (mesh / tree / Hilbert) | **MISSING** | — |
| Per-plane colour tokens | **MISSING** | theirs define `--plane-data`, `--plane-telemetry`, `--plane-config` |
| Per-plane validation status | **MISSING** | theirs: `✓ 3 Planes Validated (Data 512b, Telemetry 32b, Config 32b)` |
| Multiplane concept at all | **PARTIAL** | research tab only: `pages/implementation-lab.tsx:12` — no view, no model |

### 6.5 Per-agent configuration (field-level)

| Knob | Status | Evidence |
|---|---|---|
| Concentration ratio 1:1 / 2:1 / 4:1 | **PARTIAL** | `NocConfig.concentration` scalar; not per-agent |
| VC allocation mode (shared / dedicated / custom map) | **MISSING** | `grep buffer_depth\|vc_depth\|vc_mapping` → 0 |
| VC mapping matrix editor | **MISSING** | — |
| Buffer depth per VC | **MISSING** | — |
| Apply-to-all-nodes propagation | **MISSING** | — |
| Synchronizer cell choice (async FIFO / 2-FF / 3-FF / none) | **PARTIAL** | CDC is a research tab with a capability ledger entry; not a design knob |
| Clock domain per agent | **HAVE** | `Agent.clock_domain` row field |
| Root clock / PLL selection | **MISSING** | `grep pll\|root_clock` → 0 |
| Reset scheme | **MISSING** | — |
| Power domain per agent | **HAVE** | `Agent.power_domain` row field |
| AIU type (initiator / target / dual) | **MISSING** | `grep aiu` → 0 |
| AIU protocol (AXI5/AXI4/CHI.B/TileLink-UH/Srota Native Stream) | **PARTIAL** | `Agent.protocol` exists as a free-text row field with no option set |
| AIU clock / power domain, bus width | **PARTIAL** | `Agent.data_width` exists; no AIU-specific domains |
| Sideband interfaces | **MISSING** | `grep sideband` → 0 |
| Access perms (RW / RO / WO) | **MISSING** | no perm concept; `AddressRange` has only name/base/size/target |
| Local + global address and window size per agent | **PARTIAL** | `AddressRange{name,base,size,target_agent_idx}` table (`DesignViewV2Editor.tsx:41-44, 643`) — a range table, not per-agent windows |
| Connected target agents | **MISSING** | `grep connected_target` → 0 |
| Max outstanding transactions | **MISSING** | `grep outstanding` → only `ProjectHeader.tsx` (unrelated "outstanding limitations") |
| Ordering rules | **MISSING** | `grep ordering` → 0 |
| Splitting rules | **MISSING** | `grep splitting` → 0 |
| Flow control (credit-based) | **MISSING** | `grep flow_control` → 0 |
| Address map editor (PRD §4.3 asks for CSV/IP-XACT/JSON import) | **PARTIAL** | row editor exists; no import path |
| Agents table | **HAVE** | `DesignViewV2Editor.tsx` agent rows: kind/count/data_width/addr_width/protocol/clock_domain/power_domain |

### 6.6 Analysis views they have that we don't (or do differently)

| Feature | Status | Notes |
|---|---|---|
| **Agent Matrix** as a dedicated, filterable, exportable table | **PARTIAL** | we have agent rows + a capabilities table; not a matrix view with clock/power/AIU filters and CSV export |
| **I-T Mapping** access/firewall matrix with RW/RO/BLK/SEC cells | **MISSING** | — |
| I-T policy presets (Allow All / HBM Partitioning / Zero-Trust) | **MISSING** | — |
| Path-count stats (624 paths, 82% allowed) | **MISSING** | — |
| **Workload Profiling**: tensor→agent mapping matrix (TP/EP shards per tile) | **MISSING** | our synthesis candidate graph shows keep/added/removed, not an intent→tile map |
| Execution **Gantt timeline** perspective | **MISSING** | — |
| Phase Injection & QoS table perspective | **PARTIAL** | QoS classes exist as requirements; no phase view |
| Model input parameter panel (family/count/seq/batch/precision) | **PARTIAL** | workload catalog has family/parallelism; no seq/batch/precision knobs |
| Auto-Map Model / Synthesize & Run chained action | **PARTIAL** | `Synthesize` page exists but is not chained from a mapping view |
| **Simulation**: congestion heatmap over the router grid | **MISSING (as visual)** | we have per-run metrics and BookSim results as tables |
| Metric selector (util / stalls / wait latency) driving the heatmap | **MISSING** | — |
| Top-5 congested links table | **MISSING** | — |
| Per-link drill-down (util %, flits tx, stalls, wait breakdown) | **PARTIAL** | `TopologyInspector` has a route lookup and class→VC table |
| Scrubbable cycle timeline with phase markers | **MISSING** | — |
| Trace source / fidelity caption | **HAVE (deeper)** | we carry qualification + fidelity on every run |

### 6.7 Shell, actions and workflow

| Feature | Status | Evidence |
|---|---|---|
| `Generate RTL` action at the fabric | **MISSING** | RTL is a research tab + a Reproduce artifact; no generate/export action |
| `Export CSV` (agents, I-T matrix) | **MISSING** | — |
| `Apply All` bulk edit | **MISSING** | — |
| Workload preset switcher in the header that reshapes the fabric live | **PARTIAL** | 7 workloads exist but require the design editor + a compile |
| Persistent fabric status bar (grid/topology/agent/links/planes) | **MISSING** | our topbar shows project/revision/analysis context, not fabric state |
| Grid quick-switch 4×4 ⇄ 8×8 | **PARTIAL** | radix is a design scalar |
| Topology quick-switch 2D Mesh ⇄ Torus | **HAVE** | topology picker incl. torus (which correctly *refuses* at ROUTING) |
| Zero-setup demo with full content | **PARTIAL** | fixture demo exists (`pages/offline.tsx`) but shows one canned project and 4 of 5 overlays as "unavailable" |
| Live consequence on edit (pre-compile preview) | **MISSING** | by design; no cheap preview path |
| Tabbed navigation without page reload | **HAVE (better)** | real routes instead — deep-linkable, back-button, shareable |

### 6.8 Tally

Counted directly from the register tables above (77 features assessed):

- **MISSING, genuinely new:** 49
- **PARTIAL:** 18
- **HAVE (equal or better):** 10

By section:

| Section | MISSING | PARTIAL | HAVE |
|---|---|---|---|
| 6.1 Fabric canvas and editing | 5 | 3 | 2 |
| 6.2 Physical / PPA | 7 | 0 | 2 |
| 6.3 IP library and placement | 5 | 0 | 0 |
| 6.4 Multi-plane fabric | 4 | 1 | 0 |
| 6.5 Per-agent configuration | 14 | 6 | 3 |
| 6.6 Analysis views | 9 | 5 | 1 |
| 6.7 Shell, actions and workflow | 5 | 3 | 2 |
| **Total** | **49** | **18** | **10** |

---

## 7. The five clusters worth building

### Cluster 1 — Physical floorplan view
**Why:** it is the only place their PRD (§6 "Physical view (floorplan)", §7 "Area, Power, Timing reports") is satisfied visually, and it is the view a hardware customer asks for first.
**Seam:** `ImplementationLab/capabilityLedger.ts` already carries the six energy/area *authorities* with fidelity labels. A floorplan view must render **per-authority overlays, not one number** — i.e. reuse the authority model, do not invent a TDP.
**Guardrail:** their `TDP: 45W` per tile and `2.85 B transistors` are unsourced. Ours must show `ANALYTICAL_ESTIMATE` / `TOOL_CALIBRATED` / `BACKEND_ACTIVITY_MODEL` next to every value.

### Cluster 2 — IP primitive catalog + stamp placement
**Why:** it is the bridge between "design intent" (E3 agents) and "fabric" (E5) that currently requires a form.
**Seam:** `fabricLayout.ts` already models nodes/edges/attachments; `DesignViewV2Editor` agent rows already carry `kind`. A catalog is a typed list over `Agent.kind` plus a placement action that writes agent rows.
**Guardrail:** our engine derives placement from the certificate. Placement must be authored intent → compiled, never a direct edit of a materialized fabric.

### Cluster 3 — Multi-plane fabric
**Why:** data/telemetry/config planes are a real NoC architecture concern (three independent networks), and it is the most defensible thing Loom does — it is architecture, not decoration.
**Seam:** `TOPOLOGY`/`TopologyView` currently models one network. A plane is a discriminated union, not a new page.
**Guardrail:** their per-plane status (`✓ 3 Planes Validated`) is a claim; ours must come from the certificate per plane.

### Cluster 4 — Per-agent deep config
**Why:** this is where the 22 PARTIALs collapse into one coherent surface. Table §6.5 has the exact field list and every option set.
**Seam:** `DesignViewV2Editor`'s field registry (`DesignViewV2Editor.tsx:15-45`) is already a declarative `{kind, path}` map — new knobs are registry entries, not new components.
**Guardrail:** the PRD's tier model is explicit — routing / turn restrictions / VC map are **LOCKED** (`SROTA-STUDIO-PRD-001.md` §4.4), while topology / radix / arbitration / RCU / link width are **GUIDED**. Loom exposes VC mapping as editable, which contradicts our own PRD. Encode the tier badge in the registry.

### Cluster 5 — In-canvas editing + Generate RTL
**Why:** direct manipulation is the single largest UX delta, and the PRD makes it a principle ("Editable everywhere", "Live consequence", §3).
**Seam:** `FabricCanvas` already computes `selection` and resolves `channelByPair`; an edit mode would write GUIDED-tier fields back through the same `onChange` used by `DesignViewV2Editor`.
**Guardrail:** LOCKED fields stay read-only, and edits must land in the draft (uncompiled) revision so the certificate invariant holds.

---

## 8. Their defects — do-not-copy register

| # | Defect | Measurement |
|---|---|---|
| 1 | **Primary action clipped off-screen** | at 1440 px, `Generate RTL` occupies x **1468→1587 — entirely outside the viewport**, so the button never appears; the `Tuned For:` preset select (1236→1451) is also clipped; `body { overflow: hidden }` means neither can be scrolled to |
| 2 | **Broken on phones** | at 390×844, content extends to 1587 px — 1197 px unreachable; 20 elements clipped |
| 3 | **Accessibility 69/100** | colour contrast failures, `input` without label, `select` without accessible name |
| 4 | **Agentic Browsing 0/100** | "Accessibility tree is not well-formed" — an AI agent cannot drive this UI |
| 5 | **0 headings** | no document outline at all |
| 6 | **1 of 20 form controls labelled** | 6 landmarks, 0 labelled |
| 7 | **Type below legibility floor** | 6.5 px ×72, 7 px ×68 |
| 8 | **No routing, no shareable state** | 0 anchors; tabs are client state; deep links and back-button unusable |
| 9 | **Dark-only** | no theme; ours ships both |
| 10 | **Dev builds in production** | React + react-dom **development** builds, plus `@babel/standalone`, transpiling JSX in-browser |
| 11 | **CDN-coupled** | three `unpkg.com` scripts are hard dependencies for first render |
| 12 | **LCP 1922 ms, 81% render delay** | vs our 187 ms |
| 13 | **Fabricated PPA presented as fact** | `6.8 Tbps (+340%)`, `(-42% Area)`, `100% TSMC N3E Orthogonal`, `MTBF > 10,000 Yrs`, `TDP 45W` — all with no evidence chain. Directly violates our `DESIGN.md`: *"Don't show a metric, overlay or heatmap that has no backing artifact."* |
| 14 | **Internal inconsistency** | status bar says `112 Physical Links`; simulation says `112 Bidirectional Links / 224 Channels`; Agent Matrix says `Showing 64 of 16 Agents` |
| 15 | **SEO 75, no meta description** | minor, but free to fix on our side |

**Verdict:** copy their *interaction model and view taxonomy*. Copy none of their *evidence model, accessibility posture, layout robustness, or build*.

---

## 9. Where we are already ahead — do not regress

1. **Provenance discipline.** `DECLARED` / `DERIVED` / `EDITABLE` badges; every metric tied to an artifact; explicit refusals with the server's own reason (e.g. MoE→ASTRA refuses rather than flattening multi-class traffic).
2. **Evidence depth.** 49 headings and 13 tables on the evidence page; a Trust surface (`/trust`) with 10 tables covering engine qualification, trust levels, federation backends and campaign ledgers — Loom has no equivalent of any of it.
3. **Accessibility.** 97 vs 69; real headings, labelled controls, labelled landmarks, tables with headers, keyboard-reachable anchors.
4. **Layout integrity.** No overflow at 390 or 1440; light + dark; 11 px type floor.
5. **Deep linking.** Every state is a URL.
6. **Real execution.** BookSim / ASTRA / Ramulator actually run, with qualification and fidelity recorded.
7. **Performance.** LCP 187 ms vs 1922 ms.
8. **Reproducibility surfaces.** Reproduce, Capabilities, Validation Lab, Implementation Lab, Comparison — none of which exist in Loom.

---

## 10. Documentation drift found while measuring

`apps/studio/DESIGN.md` states:

> "The topology / traffic view is a 3D scene (Three.js, lazy-loaded) of the declared fabric: orbitable routers, mesh links and attachments, with a 2D fallback and an artifact strip bound to the compiler's real hashes."

**This is not shipped.** Verified:

```
$ grep -c '"three"' apps/studio/package.json                 → 0
$ grep -rn "import('three')\|from 'three'" apps/studio/src   → (nothing)
$ grep -rn "React.lazy\|lazy(" apps/studio/src               → (nothing)
$ grep -c "THREE\|WebGLRenderer\|OrbitControls" dist/assets/main-COWxCUin.js → 0
```

The rendered fabric view is SVG (`FabricCanvas.tsx`, `FabricInspector2D.tsx`). The doc describes the one capability that Loom actually delivers well — a large spatial fabric view — and claims we already have it. Either ship it or correct the doc; leaving it is the worst of the three.

---

## 11. Suggested build order

Mapped to our own PRD's build order (`SROTA-STUDIO-PRD-001.md` §15: P1 engine core → P2 generate → P3 views & reports → P4 interactive sim → P5 full editing), and to the gaps above.

| Priority | Item | Rationale | Size |
|---|---|---|---|
| **P0** | Fix `DESIGN.md` drift | it is a false claim about our own product | XS |
| **P0** | Fix our own Lighthouse failures: rail `aria-label` vs visible text; `.muted` contrast; add meta description | we are 97 and should be 100 — we have no excuse | S |
| **P1** | **Physical floorplan view** (Cluster 1) | only unbuilt view from PRD §6; highest customer-facing value | L |
| **P1** | **Per-agent config expansion** (Cluster 4) | collapses 22 PARTIALs; purely registry entries over an existing editor | M |
| **P2** | **Multi-plane model + view** (Cluster 3) | architectural, defensible, and the thing Loom does best | L |
| **P2** | **IP catalog + stamp placement** (Cluster 2) | intent→fabric bridge | M |
| **P3** | **In-canvas editing for GUIDED tiers** (Cluster 5) | highest UX delta; must respect LOCKED fields | L |
| **P3** | **Agent Matrix view** (filterable + CSV export) | cheap, mostly presentational over existing data | S |
| **P4** | **I-T Mapping / access-firewall matrix** | needs an engine-side permission model first | M |
| **P4** | **Simulation heatmap + cycle scrubber** | needs per-cycle trace data we do not currently emit | L |
| **P4** | **`Generate RTL` action** | needs the generate pipeline (§13) to be real first | M |
| **P5** | Zero-setup demo parity (richer fixtures, overlays enabled) | only after the views exist | S |

---

## Appendix A — evidence file index

| Path | Contents |
|---|---|
| `/tmp/srota-inspect/00-gate.png` | password gate |
| `/tmp/srota-inspect/10-desktop.png`, `10-desktop-fold.png`, `.json`, `.html`, `.txt` | their default view, desktop |
| `/tmp/srota-inspect/20-mobile.png`, `.json` | their default view, iPhone 13 |
| `/tmp/srota-inspect/000-meta.json` | gate structure, console, network log |
| `/tmp/srota-tour/*.png`, `*.txt`, `_report.json` | all 6 tabs, 3 planes, both topologies, both grid sizes, Generate RTL |
| `/tmp/loom-controls.json` | all 17 selects with every option; 26 buttons; 28 CSS custom properties |
| `/tmp/lh-loom/report.{json,html}` | Lighthouse: a11y 69, BP 100, SEO 75, agentic 0 |
| `/tmp/lh-studio/report.{json,html}` | Lighthouse: a11y 97, BP 100, SEO 60, agentic 50 |
| `/tmp/pstop-loom.txt`, `/tmp/pstop.txt` | performance traces (LCP 1922 ms vs 187 ms) |
| `/tmp/studio-inspect/d-*.png/.json/.html/.txt` | 22 of our routes, desktop |
| `/tmp/studio-inspect/m-offline-fold.png`, `mobile-overview*` | our mobile layout |
| `/tmp/studio-inspect/offline-demo*.png/.txt` | our no-gateway offline demo |
| `/tmp/SROTA-PRD.md` | the governing PRD, extracted from `origin/feat/srota-noc` |

## Appendix B — design token comparison

Their palette is dark-only, with a yellow primary and per-plane accents:

```
--bg-app #0D0D0F   --bg-chrome #141417   --bg-surface #1A1A1E
--bg-overlay #222228   --bg-input #111113
--border-subtle #2A2A32   --border-strong #383844
--focus-ring #FACC15   --action-primary #FACC15   --action-primary-text #0D0D0F
--text-primary #F4F4F6   --text-secondary #9E9EA8   --text-muted #636370
--status-danger #FF4655   --status-success #22C55E   --status-warning #F59E0B   --status-info #38BDF8
--plane-data #38BDF8   --plane-telemetry #A855F7   --plane-config #22C55E
--font-sans 'Inter'   --font-mono 'Roboto Mono'
```

Ours (`DESIGN.md`) is dark+light, single-accent, with status role pairs:

```
dark:  bg #14171c  bg-raise #1b2027  bg-card #1e242c  border #2e3640
       text #d7dde5  muted #8b95a3  accent #4da3c4  accent-dim #23424f
       ok #4caf7d  bad #e0655a  warn #d9a441  info #6aa8ff
light: bg #f2f4f6  bg-raise #e9edf1  bg-card #ffffff  border #d3d9e0
       text #1d242c  muted #5d6874  accent #0f6c9e  accent-dim #d3e7f2
mono: JetBrains Mono   sans: Inter   scale: 11 / 12 / 13 / 16 / 15 / 20
```

**Notable difference:** we have no per-plane accent tokens, and `DESIGN.md` explicitly bans gradients/glow/purple — while Loom's telemetry plane is `#A855F7` (purple). If multi-plane lands, add `--plane-*` tokens to the theme files rather than importing their palette wholesale.

## Appendix C — what we did not verify

- Their `Generate RTL`, `Export CSV`, `Apply All`, `Route All` and `Measure (µm)` were clicked but produced no visible DOM change and no download in a headless run. Their *behaviour* is unverified; only their presence is established.
- Their Agent Matrix / I-T Mapping tables render 64 and 624 cells respectively, but the 7000-character text capture truncates; cell-level correctness was not audited.
- The gateway on `:8123` holds live project data; our screenshots therefore reflect one point-in-time dataset (project `p-e0c99e7daed0`, revision `r04`).
- Lighthouse `SEO 60` and the `robots.txt` / `llms.txt` failures on our side are artifacts of `vite preview`'s SPA fallback, not of the built app; neither file is part of `dist/`.
