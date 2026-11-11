# Microchip use case: the fabric inside a Gen 6 switch

Status: demo brief with public source numbers. It is a design-space exploration
for a **next-generation** switch fabric, not a model of a shipping Switchtec
product.

## Bottom line

The honest fit is **Switchtec, not PolarFire**.

- A 160-lane, 20-port, 16-partition PCIe Gen 6 switch with hardware multicast is
  a real on-chip fabric problem: buffer sizing, arbitration, head-of-line
  blocking, multicast replication, partition isolation, and tail latency.
- PolarFire’s FPGA routing is island-style segmented routing, not a packet
  network. Modelling it as a NoC would be dishonest.
- There is no public Microchip UCIe/die-to-die product. Do not pitch a chiplet
  use case.

## Public facts

| Fact | Value | Source | Confidence |
|---|---:|---|---|
| Switchtec PFX Gen 6 lanes | 160 | Microchip product page | vendor claim |
| Ports / stacks | 20 / 10 | Microchip product page | vendor claim |
| PSX Gen 6 virtual switch partitions | 16 | Microchip product page | vendor claim |
| Non-transparent bridges | 16 | Microchip product page | vendor claim |
| Per-lane rate | 64 GT/s | Microchip Gen 6 announcement | vendor claim |
| Process | 3 nm | Microchip Gen 6 announcement | vendor claim |
| Aggregate raw bandwidth | ≈1.28 TB/s per direction | derived: 160 × 64 GT/s ÷ 8 | derived |
| FLIT-adjusted bandwidth | ≈1.21 TB/s per direction | derived: 242/256 payload | derived |
| Hardware multicast | one-to-many within a PCIe domain | Microchip product page | vendor claim |
| PolarFire SoC MPFS460T | 461 K LE, 4× U54 @ 625 MHz, 2 MB L2 | Microchip product page | vendor claim |
| PolarFire SoC PCIe | Gen 2 only | Microchip product page | vendor claim |
| LAN9668 | 8-port 10/100/1000/2500 TSN switch | Microchip product page | vendor claim |
| Ethernet Sensor Bridge R2 | dual MIPI CSI-2 → 10G Ethernet | Microchip dev-tool page | vendor claim |

## Demo #1 — Gen 6-class fan-out for AI storage / accelerator pooling

This is the strongest story. Microchip’s August 2026 Micron demo describes a
Gen 6 fan-out switch between hosts and multiple Gen 6 SSDs, with “composable and
disaggregated” framing and multicast for one-to-many distribution.

**Workload.** 1–4 hosts fan out to 8–16 endpoints (NVMe SSDs or accelerators),
70/30 read/write, 4 KB–256 KB payloads, bursty incast, plus a multicast stream
to 4/8/16 destinations.

**Fabric question.** At 160 lanes / 20 ports / 16 partitions, which combination
of:

- single crossbar vs two-stage Clos,
- per-port buffer depth,
- VC count,
- multicast replication point (source / spine / destination),

holds p99 latency under incast without blowing the area-power budget? And does a
saturated partition leak latency into a neighbour?

**What we show.**

- Latency CDF and p99 vs offered load for three topologies.
- Buffer-depth sensitivity.
- Multicast fan-out cost.
- Partition-isolation experiment: pin one partition at 100%, measure p99 in
  another.
- Normalised area/power Pareto frontier.

**Positioning.** Call it a “Gen 6-class 160-lane switch fabric,” never “the
Switchtec fabric.” The internal topology is not public.

## Demo #2 — multi-sensor bridge (backup)

Two MIPI CSI-2 4K60 streams → preprocessing → one 10G Ethernet egress;
isochronous, bursty, no-drop. This is a shipping Microchip product with a
low-latency claim.

**Fabric question.** Crossbar vs shared ring for 2–4 producers; buffer depth to
stay drop-free at 90% egress utilisation; p99 when a second consumer subscribes.

**What we show.** Drop-free buffer sizing, p99 vs egress utilisation, marginal
cost of a second consumer.

**Caveat.** The bridge likely uses direct AXI-Stream paths, not a NoC. Keep this
as a credibility backup, not the lead.

## Demo #3 — TSN + EtherCAT converged industrial fabric (weakest)

1 Gbps link, 1 ms cyclic motion control, vision/best-effort background, 8 queues
with time-aware gating. Matches Microchip’s October 2026 TSN/EtherCAT launch.

**Fabric question.** Queue/buffer allocation and gate schedule that holds p99
for cyclic traffic under background load.

**Why it is weaker.** Microchip ships the TSN IP; a customer integrates it. It
is less clearly a design-space problem for Microchip itself.

## Do not claim

- PCIe TLP ordering, config space, credit correctness, FLIT encoding,
  compliance, or Gen 6 electricals. We model a fabric, not a PCIe stack.
- Retimer/SerDes latency. Microchip’s pin-to-pin retimer number is analog, not
  fabric.
- Ethernet/TSN/EtherCAT conformance or wire-level determinism.
- FPGA place-and-route, timing closure, LUT/BRAM cost, bitstream behaviour.
- Functional safety (ISO 26262/IEC 61508) or security (secure boot, root of
  trust).
- UCIe/BoW/chiplet products at Microchip.
- CXL protocol semantics.
- Absolute 3 nm PPA without calibrated libraries; use relative/normalised
  numbers.
- Any implication that a Microchip number was measured by us.

## What makes it credible

1. **One calibration point.** A Switchtec Gen 5/6 eval board + ChipLink
   diagnostics; measure latency/throughput vs offered load and fit buffer and
   arbitration parameters. Without this, it is a simulation of a hypothetical
   switch.
2. **A stated reference fabric.** PCIe 6.0 public constants (64 GT/s, 256B FLIT
   / 242B payload, credit units) plus a parameterised topology. Label the
   topology an assumption.
3. **Workload justification.** Public Micron 9650 Gen 6 SSD specs and a
   queue-depth/incast model; state that the mix is synthetic.
4. **A defensible PPA axis.** Relative area/power vs baseline, or a public 3 nm
   standard-cell/SerDes reference. No absolute mm² or watt claim.
5. **One boundary slide.** “We model the fabric; we do not model the protocol.”
   Say it before an engineer does.

## Sources

- Switchtec PCIe switches: https://www.microchip.com/en-us/products/interface-networking-connectivity/pcie/pcie-switches
- Microchip + Micron Gen 6 storage demo, Aug 4 2026:
  https://www.microchip.com/en-us/about/news-releases/products/microchip-technology-in-collaboration-with-micron-technology-demonstrates-high-performance-pcie-gen-6
- PolarFire SoC:
  https://www.microchip.com/en-us/products/fpgas-and-plds/system-on-chip-fpgas/polarfire-soc-fpgas
- PCI1001: https://www.microchip.com/en-us/product/PCI1001
- LAN9668: https://www.microchip.com/en-us/product/LAN9668
- TSN/EtherCAT on PolarFire, Oct 29 2026:
  https://www.microchip.com/en-us/about/news-releases/products/microchip-brings-ethercat-and-tsn-networking-solutions-to-polarfire-fpga-platform
- Ethernet Sensor Bridge R2:
  https://www.microchip.com/en-us/development-tool/MPF200-ETH-SENSOR-BRIDGE-R2
