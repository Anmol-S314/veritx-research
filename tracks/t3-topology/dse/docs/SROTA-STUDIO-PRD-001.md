# SROTASEMI — AI-NATIVE NETWORK-ON-CHIP IP
## Srota Studio — Product Requirements & Software Architecture

**Document ID:** SSM-PRD-STUDIO-001  
**Revision:** 0.1 (initial draft)  
**Classification:** Internal — Confidential  
**Owner:** Nachiket Acharya, Founder & CEO  
**Date:** 22 August 2026  
**Status:** For review

---

## Contents
1. Purpose & Scope
2. How the Tool Works — One Page
3. UI Design Principles
4. Inputs — Describing the System
5. Workload Scenario Capture
6. Output Views
7. Reports & Estimates
8. In-Tool Simulator
9. Export & Downloads
10. Stack Overview
11. The Srota Engine
12. Backend Schema
13. The Generate Pipeline
14. IP Protection & Trust
15. Suggested Build Order
16. Open Questions

---

## 1. Purpose & Scope

Srota Studio is a browser-based tool that lets a chip design team describe the system they are building and receive, in return, a complete Srota Network-on-Chip (NoC) fabric tailored to that system: its topology, its RTL, its models, its verification suite, and every report needed to sign it off.

**Central product position:** Srota Studio is the front door. Behind it sits the Srota Fabric Compiler and the SrotaSemi runtime-intelligence methodology. The user supplies agents, attributes, an address map, and a workload; the tool returns a fabric that is synthesizable, simulatable, and shipped with its proofs.

---

## 2. How the Tool Works — One Page

Three stages: the client expresses intent through the UI; the Srota engine ingests, synthesizes, simulates, verifies, and generates; the client receives a set of views, reports, and downloadable collateral.

---

## PART A — UI Requirements

### 3. UI Design Principles

| Principle | What it means in the UI |
|-----------|------------------------|
| Clean by default | One primary object on screen at a time (the topology). |
| Derive, don't ask | The tool never requests a value it can compute. |
| Live consequence | Every edit updates live estimates within seconds. |
| Editable everywhere | Any element can be selected and modified. |
| Guardrails, visible | Parameters shown with tier badge: LOCKED / GUIDED / FREE. |

### 4. Inputs — Describing the System

#### 4.1 Agents (nodes) and their counts
- Compute tile: 64–1024+ 
- HBM controller: 4–16
- NIC: 1–8
- Peripheral: as needed
- UCIe port: 0–full edge

#### 4.2 Per-agent attributes
- data_width, addr_width, clock, power domain, reset, protocol, sideband

#### 4.3 Address map & configuration
- Interactive editor, CSV/IP-XACT/JSON import, or inherit from previous revision

#### 4.4 Srota NoC IP configuration inputs

| Knob | Tier | Meaning |
|------|------|---------|
| topology_family | GUIDED | Mesh / concentrated mesh / future families |
| radix / concentration | GUIDED | Router radix and tiles-per-router |
| arbitration policy | GUIDED | High-level arbitration preference |
| RCU (in-network reduction) | GUIDED | Enable/scope in-fabric all-reduce & gather |
| link width | GUIDED | Physical link width |
| output models | FREE | Which collateral to emit |
| obfuscation level | FREE | IP-protection level |
| routing / turn restrictions / VC map | LOCKED | Derived by engine — no override |

### 5. Workload Scenario Capture

Three descending levels of abstraction:

**Level A — Model & serving:**
- Model family, shape, parallelism, serving mode

**Level B — Phase & dataflow:**
- Phases, tensor→agent mapping, collective operations, skew traffic

**Level C — Per-class traffic profile:**
- Spatial pattern, temporal shape, QoS class, requirement, dependencies

### 6. Output Views
- Logical / topological view
- Structural (block) view  
- Physical view (floorplan)

### 7. Reports & Estimates
- Area, Power, Timing reports

### 8. In-Tool Simulator
- Cycle-approximate NoC model (Booksim-class)
- Packet latency, throughput, energy, area context

### 9. Export & Downloads
- RTL (SystemVerilog), Behavioral models (C/SystemC), Verification suite (UVM), Reports, Estimates, Design manifest

---

## PART B — Software Architecture

### 10. Stack Overview
- Presentation: React + TypeScript
- API / Gateway: Python FastAPI
- Srota engine: Python orchestration + C++ simulation cores
- Data & jobs: Postgres + S3 + Redis + Celery/Ray
- Infrastructure: Kubernetes

### 11. The Srota Engine

#### 11.1 Compile data model (E1–E5)
- E1: Workload
- E2: Requirements
- E3: Agents
- E4: Dependencies
- E5: NocConfig

#### 11.2 Guardrail model — LOCKED / GUIDED / FREE

#### 11.3 Dependency-driven VC derivation

#### 11.4 Engine stages
1. Ingest & validate
2. Synthesize
3. Simulate
4. Optimize
5. Verify
6. Generate

### 12. Backend Schema
- Project, Design (revision), Agent, Workload, NocConfig, Job, Result, Artifact

### 13. The Generate Pipeline
- Submit → Validate → Simulate → Optimize → Verify → Sign & store → Return

### 14. IP Protection & Trust
- Engine runs server-side only
- Per-tenant isolation, artifact signing, obfuscation levels

### 15. Suggested Build Order
- P1: Engine core
- P2: Generate path
- P3: Views & reports
- P4: Interactive sim
- P5: Full editing

### 16. Open Questions
- Workload library scope
- Simulator fidelity vs. speed
- On-prem option
- k≤16 / k=32 addressing envelope
- Licensing model
