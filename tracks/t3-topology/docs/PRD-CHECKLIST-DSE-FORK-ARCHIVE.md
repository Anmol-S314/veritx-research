# PRD Compliance Checklist — Srota Studio §1–§16

Last updated: 2026-08-30 | VeritX v0.3.0

## Summary

| Section | Grade | Status | Notes |
|---------|-------|--------|-------|
| §1 Purpose | A- | ✅ Done | Intent-to-fabric compiler via `veritx compile` |
| §2 One Page | B+ | ✅ Done | 6-stage pipeline (Validate→Derive→Simulate→Verify→Generate→Report) |
| §3 UI Principles | C | ⏳ Deferred | Derivation in build_config(), guardrails in NocConfig. No UI yet. |
| §4 Inputs | A+ | ✅ Done | Agent model + AddressMap + NocConfig with LOCKED/GUIDED/FREE tiers |
| §5 Workload | A- | ✅ Done | Shape fields + collective ops + 9 presets + 3-level capture model |
| §6 Views | F | ⏳ Deferred | No visualization. CLI-only. UI deferred to P3. |
| §7 Reports | A- | ✅ Done | Formal area/power/timing with accuracy notes |
| §8 Simulator | A | ✅ Done | BookSim2 cycle-accurate + sensitivity analysis |
| §9 Export | A | ✅ Done | RTL tracking + UVM generation + F1-F8 assertions + coverage |
| §10 Stack | F | ⏳ Deferred | CLI package. No web infrastructure (React, FastAPI, Postgres). |
| §11 Engine | A+ | ✅ Done | E1-E5 complete, VC derivation, guardrail hash, 6 stages |
| §12 Schema | A+ | ✅ Done | Result + Artifact dataclasses, DesignManifest with revision chain |
| §13 Pipeline | A+ | ✅ Done | All 6 stages wired: Validate→Derive→Simulate→Verify→Generate→Report |
| §14 IP Protection | A- | ✅ Done | HMAC-SHA256 signing, artifact checksums. No PKI, no tenant isolation. |
| §15 Build Order | B | ✅ Done | P1 ~80%, P2 ~30%, P3–P5 ~0% (engine complete, product layer deferred) |
| §16 Open Questions | — | ⏳ Deferred | Workload library, simulator fidelity, on-prem, k=32, licensing |

## Detailed Status

### §1 Purpose & Scope
**Grade: A-**
- ✅ Intent-to-fabric compiler: `veritx compile request.json`
- ✅ CompileRequest JSON as structured input (E1-E5)
- ⚠️ No web UI — CLI-only for now

### §2 How the Tool Works — One Page
**Grade: B+**
- ✅ 6-stage pipeline implemented in `cmd_compile()`:
  1. Validate (guardrail check)
  2. Derive (VC assignment + topology, LOCKED)
  3. Simulate (BookSim2 cycle-accurate)
  4. Verify (F1-F8 proof obligations)
  5. Generate (RTL + UVM + artifacts)
  6. Report (area/power/timing + manifest signing)
- ⚠️ I/O is CLI text, not interactive dashboard

### §3 UI Design Principles
**Grade: C**
- ✅ Derive, don't ask: VC count derived from dependency graph
- ✅ Guardrails visible: Tier badges in NocConfig
- ⚠️ No canvas, inspector, or live estimates (no UI)

### §4 Inputs — Describing the System
**Grade: A+**
- ✅ Agent model with 5 kinds: compute_tile, hbm_controller, nic, peripheral, ucie_port
- ✅ Per-agent attributes: data_width, addr_width, protocol, clock_domain, power_domain
- ✅ AddressMap with overlap validation
- ✅ NocConfig with LOCKED/GUIDED/FREE tiers (type-enforced)

### §5 Workload Scenario Capture
**Grade: A-**
- ✅ Level A: model_family, tp/ep/dp, serving_mode, precision
- ✅ Level B: collective_operations (allreduce, allgather, reducescatter, broadcast, alltoall)
- ✅ Level C: traffic_class with spatial/temporal patterns
- ✅ 9 built-in presets (qwen3, llama70b, llama1b, dense, moe, hpc, automotive, diffusion)

### §6 Output Views
**Grade: F**
- ⏳ No visualization. CLI-only. UI deferred to P3.

### §7 Reports & Estimates
**Grade: A-**
- ✅ Area: routers + links + NICs, process-scaled (7nm reference)
- ✅ Power: dynamic + leakage, activity-weighted
- ✅ Timing: Fmax derating, critical path estimation
- ✅ Energy: pJ/bit
- ✅ Accuracy notes for every metric

### §8 In-Tool Simulator
**Grade: A**
- ✅ BookSim2 cycle-accurate simulation
- ✅ Trace replay mode (real timestamps, no Bernoulli)
- ✅ Sensitivity analysis across injection rates
- ⚠️ Not interactive (no tweak-and-replot)

### §9 Export & Downloads
**Grade: A**
- ✅ RTL tracking (artifacts list, checksum verification)
- ✅ UVM generation: tb_noc.sv, seq_lib.sv, assertions.sv, cov.sv
- ✅ F1-F8 formal property assertions
- ✅ Coverage model (cross-coverage: traffic class × latency bucket)
- ✅ Manifest signing (HMAC-SHA256)
- ⚠️ No behavioral C/SystemC models
- ⚠️ No obfuscation levels

### §10 Stack Overview
**Grade: F**
- ⏳ CLI package only. No React, FastAPI, Postgres, K8s.
- Deferred to P3-P5 (product layer).

### §11 The Srota Engine
**Grade: A+**
- ✅ E1-E5 complete: Workload, Requirements, Agents, DependencyGraph, NocConfig
- ✅ Guardrail model: LOCKED fields absent from NocConfig (type-enforced)
- ✅ VC derivation from dependency graph (cycle detection → VC separation)
- ✅ Guardrail hash (SHA-256 of full config)
- ✅ All 6 engine stages wired

### §12 Backend Schema
**Grade: A+**
- ✅ Result dataclass (latency, throughput, area, power, fmax, energy)
- ✅ Artifact dataclass (kind, uri, checksum, signature)
- ✅ DesignManifest with revision chain (create → revise → chain)
- ✅ HMAC-SHA256 signing
- ⚠️ File-based (no Postgres, no immutable revision DB)

### §13 The Generate Pipeline
**Grade: A+**
- ✅ All 6 stages wired: Validate → Derive → Simulate → Verify → Generate → Report
- ✅ Fail-fast validation (empty agents → ValueError in seconds)
- ✅ UVM generation in Generate stage
- ✅ Manifest creation with signing in Report stage

### §14 IP Protection & Trust
**Grade: A-**
- ✅ HMAC-SHA256 signing for integrity
- ✅ Artifact checksums (SHA-256)
- ✅ DesignManifest revision chain
- ⚠️ No PKI (shared secret, not asymmetric)
- ⚠️ No tenant isolation (local CLI)
- ⚠️ No RTL obfuscation

### §15 Suggested Build Order
**Grade: B**
- ✅ P1 Engine core: ~80% (E1-E5, guardrails, VC derivation, simulation, verification)
- ✅ P2 Generate path: ~30% (UVM, manifest, RTL tracking)
- ⏳ P3 Views & reports: ~0% (no visualization)
- ⏳ P4 Interactive sim: ~0% (no tweak-and-replot)
- ⏳ P5 Full editing: ~0% (no live editing)

### §16 Open Questions
**Status: Deferred**
- Workload library: 9 presets (needs 20+ for production)
- Simulator fidelity: BookSim2 is cycle-accurate (good)
- On-prem: Not implemented (local CLI only)
- k=32 addressing: 4-bit dest fields cap at k≤16 (known limitation)
- Licensing: Not implemented

## What's Missing for True A+

| Gap | Effort | Impact |
|-----|--------|--------|
| F1-F8 formal proof (JasperGold/VCS) | 8hrs | §9 — needs EDA tool |
| CSV/IP-XACT address map import | 3hrs | §4.3 |
| k=32 addressing envelope | 2hrs | §16.4 |
| Interactive tweak-and-replot | 8hrs | §8.2 (no UI) |
| Web UI (React + FastAPI) | 40hrs | §3, §6, §10 |
| On-prem deployment | 4hrs | §16.3 |
| 20+ workload presets | 3hrs | §16.1 |
| RTL obfuscation | 2hrs | §14.3 |
