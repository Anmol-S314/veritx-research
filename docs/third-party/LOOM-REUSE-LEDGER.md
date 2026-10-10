# LOOM Reuse Ledger — third-party code audit

Status: **DRAFT — PARTIAL WEB VERIFICATION; FULL AUDIT PENDING**
Date opened: verified against the local working tree only (no network access in the
producing run; see §4). This is a ledger of what is *in this tree* and what is
*awaiting verification* — not an aspiration.

> Scope note: this ledger was initially produced under a no-web-access constraint.
> Rows 1–11 in the §3 candidate table remain **UNVERIFIED**. The separate §3c UVM
> entry records partial, source-linked verification only; it does not complete §3b or
> establish simulator compatibility, integration, or execution. Do not treat any
> `AWAITING_VERIFICATION` cell in rows 1–11 as established fact until the verifier
> completes §3b and records the fetched evidence.

---

## 1. POLICY — external-code integration rule (verbatim)

The governing rule for integrating external code into VERITX/LOOM:

> pin exact SHA → inspect implementation → inspect license → record modifications →
> isolate behind adapter → tests against canonical semantics → upstream types must
> never become the VERITX public model.

Preferred hierarchy:

> canonical VERITX semantics → adapter → third-party implementation.

And:

> reference semantics / differential oracle / small isolated adapter is preferred over
> copying a whole framework.

### 1.1 Consequences of that policy (operational reading)

- **Semantic-oracle use is the default.** An upstream project is most valuable to us
  as a *differential test reference* — run it on the same inputs and compare observable
  outputs, rather than importing its source. This keeps upstream types out of the
  VERITX public model and sidesteps license contamination.
- **Vendoring is the exception, not the rule.** Vendoring requires: a pinned SHA, an
  inspected implementation, an inspected license that *permits* redistribution, and a
  recorded list of local modifications (the `METADATA.json` pattern already used under
  `third_party/`).
- **Adapters only.** If third-party code must be executed in-process, it is wrapped
  behind a VeritX-owned adapter; its headers/types never appear in the public model.
- **Licenses that forbid vendoring** (e.g. GPL/AGPL-style copyleft, or any license that
  does not permit redistribution under our MIT LICENSE) must be used **only** as an
  external, separately-installed semantic oracle — never copied in, never linked into a
  distributed artifact in a way that would force our code under their terms.

---

## 2. LOCAL VENDORED COMPONENTS — verified from this tree

Method: direct file reads of `LICENSE`, `METADATA.json`, source headers, `Makefile`,
`Dockerfile`. **No shell / `git` was available in the producing run**, so
`git log -1 --format=%H` could **not** be executed; where a `.git` object was probed it
is noted. Commit SHAs below are quoted from in-tree `METADATA.json` / `Dockerfile` pins
(authoritative for *what this tree claims*, not re-verified against upstream).

| Component | Local path | Vendored as | License evidence (in tree) | Pin recorded in tree | Capability |
|---|---|---|---|---|---|
| booksim2 (fork) | `third_party/booksim2/` (canonical src `third_party/booksim2/src/`) | full source tree (no separate `.git`; `.git/HEAD` probed → not found) | **BSD-3-Clause-style, Stanford** — header verbatim in `src/main.cpp` and `src/Makefile`: `Copyright (c) 2007-2015, Trustees of The Leland Stanford Junior University … Redistribution and use in source and binary forms…` (no SPDX tag printed) | `METADATA.json` → `28f43299f1706a3160ffac721ca461d74eb6e618`; internal branch `updated-booksim @ 46059c8f` | Cycle-accurate NoC simulator (VeritX fork: GEC/Srota topologies, trace replay, percentile stats, embedding API `veritx_embed.hpp`) |
| astra-sim | `third_party/astra-sim/` | full source tree | `METADATA.json` present; LICENSE file **not located** at `third_party/astra-sim/LICENSE` (or `.txt`/`COPYING`) — NOT_CONFIRMED, may live elsewhere in tree | `METADATA.json` → `518bd51`, branch `master`, vendored 2026-08-17 | System-level multi-die AI-accelerator simulator; VeritX adds BookSim2 network frontend (`Booksim2NetworkApi.cc`, `main.cc`, `Booksim2Fabric`) |
| llmservingsim | `third_party/llmservingsim/` | full source tree (Python) | `METADATA.json` present; LICENSE file **not located** at `third_party/llmservingsim/LICENSE` — NOT_CONFIRMED | `METADATA.json` → `2c2042c`, branch `main`, vendored 2026-08-17 | LLM-serving traffic-trace generator (KAIST); runs as `python -m serving` |
| timeloop | `third_party/timeloop/` | full source tree | `METADATA.json` present; LICENSE file **not located** at `third_party/timeloop/LICENSE`/`.txt`/`COPYING` — NOT_CONFIRMED | `METADATA.json` → `6b70505`; `Dockerfile` pins full SHA `6b705056d7473a86d6439533879632d0979b85a1` (pre-barvinok), vendored 2026-08-26 | DNN dataflow mapper / cost model (`timeloop-mapper`, `-model`, `-metrics`) |
| ramulator2 | `third_party/ramulator2/` | full source tree (C++/CMake + Python bindings) | LICENSE file **not located** at `third_party/ramulator2/LICENSE`/`.md`/`.txt`/`COPYING`/`NOTICE`/`COPYRIGHT` — NOT_CONFIRMED; **no `METADATA.json` found** at `third_party/ramulator2/METADATA.json` (unlike the four tools above) | **no pin recorded in a METADATA.json**; `README.md` self-identifies as "Ramulator 2.1" | Cycle-level DRAM/memory-controller simulator; built by root `Makefile` (`release-build`, `write_ramulator_manifest.py`) |

### 2.1 Additional upstreams pinned *at image build time* (not vendored on disk)

The `Dockerfile` clones these from GitHub during image build and pins exact SHAs:

| Upstream | SHA pinned in `Dockerfile` | Note |
|---|---|---|
| Accelergy (`Accelergy-Project/accelergy`) | `6911d15686ee7efdceba7d95605102df4472ae3a` | apt/pip install, not vendored |
| Yosys (`YosysHQ/yosys`) | `6f876ae0e2095753bac358c88f93bc27a62b3d9b` | built in image only |
| SymbiYosys (`YosysHQ/sby`) | `b1a1e98cba941ec8433f8dc27f416cd7bb7f14be` | built in image only |
| CBMC (`diffblue/cbmc`) | `fd5dcee9e623c7d6539697abaafc15fbf73bd3ac` | built in image only |
| Timeloop (`Accelergy-Project/timeloop`) | `6b705056d7473a86d6439533879632d0979b85a1` | also vendored on disk (§2) |

No `.gitmodules` exists at repo root (verified by read → not found), so `third_party/`
entries are plain in-tree directories, not submodules.

### 2.2 Local hardware / RTL directories relevant to the reuse question

- `tracks/t4-formal/rtl/` — VeritX-authored SystemVerilog (e.g. `counter.sv`, and per
  README: `fifo.sv`, `arbiter.sv`). These are **first-party** scaffolding, not upstream
  RTL. No vendored third-party RTL (common_cells / axi / taxi / etc.) is present in the
  tree — see §4.

---

## 3. UPSTREAM CANDIDATES AWAITING VERIFICATION

**Every cell below is UNVERIFIED.** `AWAITING_VERIFICATION (no web access this run)`
means exactly that. "files relevant to us" is best-effort recall from local knowledge and
is marked **UNCERTAIN** — it must be replaced by paths actually read from the fetched
source. No candidate is approved for any use until §3b is complete.

| # | Repository | Commit SHA | License | Files relevant to us | Capability | vendor / adapt / reference | Dependencies | Maintenance | Tests | Semantic risks |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | https://github.com/pulp-platform/common_cells | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — FIFO/arbiter/counter/RR-arbiter RTL cells (names not verified) | Reusable SystemVerilog building blocks (FIFOs, arbiters, counters) | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED**; default = semantic oracle | AWAITING_VERIFICATION (likely SV toolchain only) | AWAITING_VERIFICATION | AWAITING_VERIFICATION | Upstream cell semantics (reset, credit, backpressure) may differ from VeritX RTL assertions; using code as a source would drag in upstream parameter/interface conventions |
| 2 | https://github.com/pulp-platform/axi | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — AXI4 crossbar/width-converter/ID-remap modules | AXI4 interconnect fabric | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED**; default = semantic oracle | AWAITING_VERIFICATION (depends on common_cells) | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AXI protocol subtleties (outstanding transactions, ID ordering) — high risk if any upstream types leak into our model |
| 3 | https://github.com/fpganinja/taxi | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — SystemVerilog AXI-stream/NoC helpers | AXI-Stream / interconnect utilities | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED** | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION (single-author repo — maintenance/licensing assumptions unverified) |
| 4 | https://github.com/shashankov/ReCONNECT | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — NoC RTL | Network-on-Chip design | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED**; academic repo — likely oracle-only | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION | Academic NoC assumptions (topology, flow control) may not match our semantic contract; license may restrict redistribution |
| 5 | https://github.com/sarabjeetsingh007/PANE | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN | NoC/accelerator interconnect | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED** | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION |
| 6 | https://github.com/jmjos/ratatoskr | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — NoC RTL/core | Asynchronous/NoC interconnect research core | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED**; default = semantic oracle | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION | Async design semantics are hard to differential-test; unclear maintainability |
| 7 | https://github.com/nizarsd/nocrtl | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN | NoC RTL | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED** | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION (cannot even confirm repo exists/maintained without fetch) |
| 8 | https://github.com/davin-san/garnet_standalone | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — Garnet NoC extracted from gem5 | Garnet mesh NoC model | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED**; gem5-derived — oracle candidate (already have BookSim2 as NoC oracle) | AWAITING_VERIFICATION (likely gem5/SConstruct) | AWAITING_VERIFICATION | AWAITING_VERIFICATION | **gem5-derived license scope** must be confirmed (BSD-style for gem5 core, but the extraction's license is unverified); overlaps with our existing BookSim2 oracle → redundant vendor candidate |
| 9 | https://github.com/The-OpenROAD-Project/OpenROAD | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — physical design / P&L flow, relevant only to handoff/viewer | RTL→GDS physical implementation | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED**; use as external tool, not vendored | AWAITING_VERIFICATION (large C++/Python dep tree) | AWAITING_VERIFICATION | AWAITING_VERIFICATION | Very heavy dep tree; only the handoff/output interfaces matter to us — avoid vendoring |
| 10 | https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — flow TCL + Makefiles | Reference RTL→GDS flow | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED**; reference flow, not vendored | AWAITING_VERIFICATION (needs OpenROAD + PDK) | AWAITING_VERIFICATION | AWAITING_VERIFICATION | PDK license is separate from flow license — must check both before any reuse |
| 11 | https://github.com/KLayout/klayout | AWAITING_VERIFICATION (no web access this run) | AWAITING_VERIFICATION | UNCERTAIN — GDS/OASIS read/write, layout viewer | Layout viewer / GDS handoff | **PENDING LICENSE REVIEW — NO VENDORING UNTIL VERIFIED**; external viewer only | AWAITING_VERIFICATION | AWAITING_VERIFICATION | AWAITING_VERIFICATION | GPL-family risk is material — if copyleft, MUST remain an external, separately-installed viewer and never be copied into a distributed VeritX artifact |

### 3b. Must-verify checklist (run these to convert each row to VERIFIED)

For every candidate above, a web-capable verifier must, and *record the output*:

1. `git ls-remote <url> HEAD` (or the GitHub API) → capture the default-branch SHA **and the date checked**; put it in the Commit SHA cell.
2. Fetch the repo's `LICENSE` / `COPYING` / `LICENSE.md` / `LICENSE-*` and any `COPYING` in subdirs → record the **exact SPDX identifier** (state `NO SPDX TAG` if only prose). Flag anything copyleft/GPL/AGPL and anything without an explicit redistribution grant.
3. Fetch and read the actual files listed in "files relevant to us" → replace every `UNCERTAIN` with real paths; confirm the capability claim from code, not README.
4. For each: record dependencies (from its manifest: `pyproject.toml`, `setup.py`, `CMakeLists.txt`, `.gemspec`, `*.core`, `scons`, etc.).
5. Record maintenance signal: date of last commit, release cadence, open-issue activity.
6. Record whether a test suite exists and how to run it.
7. Decide vendor vs adapt vs reference **only after** 1–6: if the license does not permit redistribution under MIT, the row is forced to **reference / semantic oracle only**.
8. For gem5-derived (#8) and OpenROAD/KLayout (#9–#11), explicitly resolve the *derived-work* license, not just the umbrella repo license.

---

### 3c. UVM collateral — partial verification (2026-10-09)

This is a separate, scoped check of the UVM reference candidate; it does not change the **UNVERIFIED** status of rows 1–11 or complete the broader §3b audit.

| Field | Finding | First-party evidence / limit |
|---|---|---|
| Repository pin | `accellera-official/uvm-core`, tag `2020.3.1`, resolves to `78c06547a2a0a29b3dc9dcafae62b75b2ff61544`. | [GitHub tag-ref API](https://api.github.com/repos/accellera-official/uvm-core/git/refs/tags/2020.3.1) |
| Scope/version | The tagged README identifies UVM 1800.2 2020.3.1 and IEEE 1800.2-2020. It lists an IEEE 1800-compliant SystemVerilog simulator and a C compiler for DPI code as prerequisites; exact simulator-version compatibility is left to vendors. | [README at tag](https://raw.githubusercontent.com/accellera-official/uvm-core/2020.3.1/README.md) |
| License and notices | `LICENSE.txt` contains Apache License 2.0; `NOTICE.txt` contains third-party copyright notices. Preserve the applicable license and notices if a later, separately approved redistribution is considered. This entry does not approve vendoring. | [LICENSE.txt at tag](https://raw.githubusercontent.com/accellera-official/uvm-core/2020.3.1/LICENSE.txt), [NOTICE.txt at tag](https://raw.githubusercontent.com/accellera-official/uvm-core/2020.3.1/NOTICE.txt) |
| Source/tests | The tagged contents API shows `src/`, `compat/`, and `docs/`. Test-suite paths and commands were not established; a root `Makefile` URL returned 404. | [Contents API at tag](https://api.github.com/repos/accellera-official/uvm-core/contents?ref=2020.3.1) |
| Disposition and remaining gates | Reference candidate only. No UVM was installed or vendored; no local integration or UVM test execution was performed. Simulator compatibility, test layout, maintenance, and local integration remain unqualified. | Partial source verification only; no execution evidence. |

## 4. VENDORING STATUS — unambiguous statement

- **No upstream code from any §3 candidate has been vendored, adapted, or referenced at
  this HEAD.** None of common_cells, axi, taxi, ReCONNECT, PANE, ratatoskr, nocrtl,
  garnet_standalone, OpenROAD, OpenROAD-flow-scripts, KLayout, or `uvm-core` is present in this tree
  (no such directories exist under `third_party/` or `tracks/`; `third_party/` contains
  only booksim2, astra-sim, llmservingsim, timeloop, ramulator2).
- **Nothing in §3 may be vendored before license review closes** (checklist §3b).
- The components in §2 are pre-existing vendored tools with `METADATA.json` provenance
  (booksim2, astra-sim, llmservingsim, timeloop) plus ramulator2 (no METADATA.json
  located — a gap). Their licenses were only *partially* confirmable from in-tree
  evidence this run (booksim2 = BSD-3-style Stanford; the others' LICENSE files were not
  located at conventional paths and remain NOT_CONFIRMED).

### 4.1 Confidence legend used above

- **Verified-from-this-tree** — established by reading a file in this working tree
  (contents quoted).
- **NOT_CONFIRMED** — a file expected at a conventional path was not found there; it may
  exist elsewhere (the initial ledger-producing run had no directory-listing or shell
  capability, so absence is not proven).
- **AWAITING_VERIFICATION** — requires network access; not established.

---

## 5. Open gaps carried forward

1. ramulator2 has **no `METADATA.json`** under `third_party/ramulator2/` (the four other
   tools do) — provenance/modifications are therefore unrecorded for it.
2. `third_party/ramulator2/LICENSE` (and variants) not located; license NOT_CONFIRMED.
3. astra-sim / llmservingsim / timeloop LICENSE files not located at conventional paths;
   NOT_CONFIRMED.
4. All eleven §3 candidates are entirely unverified — the audit's core deliverable is
   still owed and requires a web-capable run.
5. The §2 "exact commit SHA" column is quoted from in-tree pins; this partial UVM
   update did not re-check those pins against upstream.
