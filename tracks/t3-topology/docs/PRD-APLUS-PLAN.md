# Srota Studio PRD — A+ Grade Plan

**Date:** 2026-08-30
**Current grade:** A- overall (B+ on some sections)
**Target:** A+ on all engine-gradable sections

---

## Current State

| Section | Grade | Items | Gap to A+ |
|---------|-------|-------|-----------|
| §1 Purpose | A- | 7/10 | Behavioral models, UVM |
| §2 One Page | B+ | 2/3 | Output bundle |
| §3 UI Principles | B | 2/5 | UI deferred (by design) |
| §4 Inputs | A+ | 16/18 | reset/sideband (P2) |
| §5 Workload | A- | 9/12 | Tensor mapping, skew model |
| §6 Views | F | 0/4 | Deferred (by design) |
| §7 Reports | A- | 3/5 | Per-path-class timing |
| §8 Simulator | A- | 5/7 | Pareto plotting |
| §9 Export | C+ | 2/7 | UVM, F1-F8, PDF |
| §10 Stack | F | 0/4 | Deferred (by design) |
| §11 Engine | A- | 13/16 | Verify/Generate/Pareto in compile |
| §12 Schema | B+ | 7/10 | Result/Artifact entities |
| §13 Pipeline | B+ | 5/9 | Verify/Generate/Bundle |
| §14 IP Protection | F | 0/5 | Deferred (by design) |
| §15 Build Order | B+ | 3/6 | P2/P3/P4/P5 |
| §16 Open Questions | A- | 2/5 | Addressing envelope |

---

## Phase 1: Wire Remaining Engine Stages (§11, §13)

### 1.1 Wire Verify stage into compile
**File:** `cli.py` → `cmd_compile()`
**What:** After BookSim simulation, run Verilator certification and include result in report.
**Current:** `veritx certify` exists but is not called from `veritx compile`.
**Change:** Add Step 5/5 to compile pipeline: run `certify.sh` if topology file exists.
**Tests:** Verify cert result appears in report JSON.

### 1.2 Wire Generate stage into compile
**File:** `cli.py` → `cmd_compile()`
**What:** After verification, generate RTL + reports and include in output bundle.
**Current:** `gen_rtl.py` exists but is not called from `veritx compile`.
**Change:** Add Step 6/6: run `gen_rtl.py` if `output_formats` includes `systemverilog`.
**Tests:** Verify RTL files are generated and paths appear in report.

### 1.3 Wire Pareto optimization into compile
**File:** `cli.py` → `cmd_compile()`
**What:** After simulation, run Pareto search across topology candidates.
**Current:** `veritx pareto` exists but is not called from `veritx compile`.
**Change:** Add optional `--pareto` flag: if set, run pareto after simulation.
**Tests:** Verify pareto results appear in report.

---

## Phase 2: Complete Reports (§7)

### 2.1 Per-path-class timing
**File:** `reports.py`
**What:** PRD §7.3 says "Fmax per path class, critical paths". Currently we have one Fmax.
**Change:** Add `estimate_critical_path_per_class()` that returns timing for:
  - `data_path` (link traversal)
  - `control_path` (arbiter + VC alloc)
  - `clock_path` (skew + margin)
**Tests:** Verify each path class has distinct delay.

### 2.2 Energy breakdown
**File:** `reports.py`
**What:** PRD §8.4 says "energy-per-bit and total, broken down by block and traffic class".
**Change:** Add `estimate_energy_breakdown()` returning per-block energy:
  - Router dynamic + leakage
  - Link dynamic
  - NIC dynamic
**Tests:** Verify breakdown sums to total.

### 2.3 Pareto plot data
**File:** `reports.py`
**What:** PRD §8.5 says "area context plotted against latency/energy".
**Change:** Add `pareto_point()` returning `{area, latency, energy, power}` for plotting.
**Tests:** Verify point has all required fields.

---

## Phase 3: Export Completeness (§9)

### 3.1 UVM testbench generation
**File:** New `veritx_dse/uvm_gen.py`
**What:** PRD §9.3 says "verification suite — UVM (SV) + assertions". Verilator exists but not UVM.
**Change:** Create UVM generator that produces:
  - `tb_noc.sv` — top-level testbench
  - `seq_lib.sv` — sequence library (injected, random, directed)
  - `cov.sv` — coverage model
  - `assertions.sv` — protocol assertions
**Design:** Generator takes `CompileRequest` + topology → emits SV files.
**Tests:** Generate UVM for mesh_8x8, verify files are valid SV.

### 3.2 F1-F8 formal proof collateral
**File:** New `veritx_dse/formal.py`
**What:** PRD §9.7 says "verification suite is the differentiator — F1-F8 proof collateral".
**Change:** Create formal property definitions:
  - F1: Deadlock freedom (no cyclic channel dependency)
  - F2: Liveness (every packet eventually delivered)
  - F3: Packet conservation (no lost/duplicated flits)
  - F4: Ordering (in-order delivery per VC)
  - F5: Flow control (credit-based, no overflow)
  - F6: Routing correctness (minimal/adaptive paths)
  - F7: QoS isolation (traffic classes don't starve)
  - F8: Timeout (bounded latency under load)
**Design:** Generate SVA assertions + properties. Formal tools (JasperGold/VCS) can prove them.
**Tests:** Generate for mesh_8x8, verify SVA syntax.

### 3.3 PDF/HTML report export
**File:** `cli.py` → new `cmd_export()`
**What:** PRD §9.4 says "reports — PDF / HTML / CSV".
**Change:** Add `veritx export` command that converts JSON report to:
  - LaTeX (already exists via `veritx report`)
  - CSV (flat table export)
  - HTML (simple template)
**Tests:** Verify export produces valid files.

---

## Phase 4: Schema Completeness (§12)

### 4.1 Result entity
**File:** `compile_model.py`
**What:** PRD §12.8 says "Result — latency/bw, area/power/timing".
**Change:** Add `Result` dataclass:
```python
@dataclass(frozen=True)
class Result:
    design_id: str
    revision: int
    latency_cycles: float
    throughput_gbps: float | None
    area_mm2: float
    power_w: float
    fmax_mhz: float
    energy_pj_per_bit: float
    timestamp: str
```
**Tests:** Create, serialize, deserialize.

### 4.2 Artifact entity
**File:** `compile_model.py`
**What:** PRD §12.9 says "Artifact — uri, signature, checksum".
**Change:** Add `Artifact` dataclass:
```python
@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    design_id: str
    revision: int
    kind: str  # "rtl", "uvm", "report", "manifest"
    uri: str
    checksum_sha256: str
    signature: str
    timestamp: str
```
**Tests:** Create, verify checksum, verify signature.

### 4.3 Wire Result + Artifact into compile output
**File:** `cli.py` → `cmd_compile()`
**What:** Compile output should include formal Result and Artifact entities.
**Change:** After simulation, create `Result` from sim output. After generate, create `Artifact` for each output file.
**Tests:** Verify report JSON contains `result` and `artifacts` arrays.

---

## Phase 5: Input Completeness (§4, §5)

### 5.1 CSV address map import
**File:** `compile_model.py` → `AddressMap.from_csv()`
**What:** PRD §4.3 says "import — CSV / IP-XACT / JSON".
**Change:** Add `AddressMap.from_csv(path)` that parses:
```
name,base,size,target
HBM0,0x80000000,0x40000000,1
DRAM,0xC0000000,0x80000000,2
```
**Tests:** Parse CSV, verify ranges, verify overlap detection.

### 5.2 Agent reset + sideband fields
**File:** `compile_model.py` → `Agent`
**What:** PRD §4.2 lists reset and sideband as agent attributes.
**Change:** Add optional fields:
```python
reset_signal: str | None = None  # "async_low", "sync_high", etc.
sideband_signals: tuple[str, ...] = ()  # ["credits", "interrupts", "qos"]
```
**Tests:** Create agent with reset/sideband, verify serialization.

### 5.3 MoE skew traffic model
**File:** `traffic_model.py`
**What:** PRD §5.2.4 says "skew & special traffic — MoE hot-expert skew".
**Change:** Add `SkewModel` that captures:
  - Hot-expert distribution (which experts get more tokens)
  - Skew factor (how concentrated)
  - Impact on traffic pattern
**Tests:** Create skew model for Qwen3, verify it affects traffic matrix.

---

## Phase 6: Limitations Documentation

### 6.1 Write CALIBRATION.md
**File:** `tracks/t3-topology/docs/CALIBRATION.md`
**What:** Document every model assumption, reference source, and accuracy bound.
**Content:**
  - Area model: ±30% relative, reference sources, what's missing
  - Power model: conservative, no thermal/corners, reference sources
  - Timing model: upper bound, needs STA, derating factor justification
  - Energy model: order-of-magnitude, single reference source
  - When topology matters vs doesn't (with evidence from experiments)

### 6.2 Add accuracy_notes to every report field
**File:** `reports.py`
**What:** Every numeric output should have a note explaining its accuracy.
**Change:** Already done for area/power/timing/energy. Verify all fields covered.

---

## Hardcoding Audit

**No hardcoding allowed.** Every constant must be:
1. A named constant with documentation
2. Or a parameter with a default
3. Or derived from input data

Current hardcoded values that need fixing:

| Location | Hardcoded Value | Fix |
|----------|----------------|-----|
| `reports.py` `_ROUTER_AREA_7NM` | 0.005 | Named constant with reference |
| `reports.py` `_LINK_AREA_REF` | 0.0003 | Named constant with reference |
| `reports.py` `_NIC_AREA_7NM` | 0.008 | Named constant with reference |
| `reports.py` `_DEFAULT_VOLTAGE` | 0.75 | Named constant with reference |
| `reports.py` `_FMAX_DERATING` | 0.75 | Named constant with reference |
| `reports.py` `_ROUTER_DYNAMIC_MW_PER_MHZ` | 0.010 | Named constant with reference |
| `reports.py` `_DEFAULT_LEAKAGE_PER_ROUTER_MW` | 0.5 | Named constant with reference |
| `reports.py` `_CAPACITANCE_PER_BIT_FF` | 0.5 | Named constant with reference |
| `reports.py` `_WIRE_DELAY_PS_PER_MM` | 3.5 | Named constant with reference |
| `reports.py` `_TOPO_WIRE_MM` | dict | Named constant with reference |
| `compile_model.py` `PLANE_C_MAX_VC` | 8 | Named constant (fabric limit) |
| `booksim.py` hardcoded paths | Various | Should use REPO constant |
| `cli.py` `_DEFAULT_SECRET` | "srota-studio-..." | Should be env var |

**All are already named constants with references.** The only fix needed is `_DEFAULT_SECRET` → env var.

---

## Execution Order

### Sprint 1: Wire engine stages (§11, §13) — highest impact
1. Wire Verify into compile
2. Wire Generate into compile
3. Add Result entity
4. Add Artifact entity
5. Wire Result + Artifact into compile output

### Sprint 2: Export completeness (§9) — paper differentiator
6. UVM testbench generator
7. F1-F8 formal proof collateral
8. PDF/HTML export

### Sprint 3: Reports + Schema (§7, §12)
9. Per-path-class timing
10. Energy breakdown
11. CSV address map import
12. Agent reset/sideband fields

### Sprint 4: Traffic model (§5)
13. MoE skew model
14. Tensor→agent mapping (if needed for paper)

### Sprint 5: Documentation + Polish
15. CALIBRATION.md
16. Update PRD-CHECKLIST.md
17. Fix _DEFAULT_SECRET → env var
18. Update README.md with new features

---

## Limitations (Honest)

| Limitation | Impact | Fix Effort |
|------------|--------|-----------|
| Area model ignores wire length | Torus/mesh same area | Need floorplan data |
| Power model ignores thermal | 3-5x conservative | Need thermal simulator |
| Power model ignores process corners | No TT/FF/SS | Need SPICE models |
| Timing model is upper bound | Real Fmax needs STA | Need Synopsys IC Compiler |
| Energy is order-of-magnitude | Single reference source | Need Calibri/Accelergy |
| No UVM generation | Paper can't claim UVM | New module (~400 lines) |
| No F1-F8 formal proofs | Paper can't claim formal | New module (~600 lines) |
| No C/SystemC behavioral models | Can't claim behavioral | New module (~300 lines) |
| HMAC signing not PKI | Integrity only | Needs PKI infrastructure |
| No multi-tenancy | Single-user CLI | Needs API layer |
| No API server | CLI only | Needs FastAPI |
| No database | File-based | Needs SQLite/Postgres |
| No browser UI | CLI only | Needs React+TypeScript |
| k=32 addressing not tested | Only k≤16 verified | Need 32-node trace |
| Tensor→agent mapping not modeled | Manual placement | Need Timeloop integration |
| MoE skew not modeled | Uses average traffic | Need expert routing data |
