# Llama TP=4 paper-informed synthetic projection: run record

**Evidence class:** synthetic packet traffic informed by paper-reported
collective counts/sizes. This is not a captured NCCL trace and is not a
reproduction of the paper's measured runtime. Section V-A's TP-invariance
statement supports interpreting the counts as collective calls, but no raw
participant-rank events are available for verification. The generator repeats
operations across four ranks and assumes two-byte Gather elements; Gather bytes
are not independently reported measurements.

**Acceptance scope:** execution smoke test only. This does not validate realistic
inference timing, communication volume on wires, NCCL bandwidth, or a topology
ranking. The fixed round gaps are open-loop scheduling assumptions, not
completion-dependent collective barriers.

## Input and projection

- Measured source: Xu et al., [arXiv:2507.14392](https://arxiv.org/abs/2507.14392), Tables III–IV; source ledger: `collectives.json`.
- Input counts: prefill 65 AllReduces + 1 Gather; decode 8,255 AllReduces + 127 Gathers.
- Generator: `project_ring.py`; explicit transport and timing assumptions are in the generated trace header and `../README.md`.
- Simulated fabric: 2×2 BookSim mesh, DOR routing, 256-bit channels, 2 VCs, 8-flit VC buffer; class 0.
- Trace rows: 1,639,584 packets, maximum timestamp 2,015,431 cycles. Generated trace size: 26,288,102 bytes.
- Trace SHA-256: `f6e6df9a0184d6285e50975547808a08ce191828985f7b8d173cc23ad22ad8f6`.
- Generated trace lived at `/tmp/llama-tp4-full.trace`; it is intentionally not checked in. Recreate with:

  ```bash
  python3 tracks/t3-topology/data/public-inference/llama31-8b-tp4/project_ring.py \
    --out /tmp/llama-tp4-full.trace
  ```

## BookSim result

The full trace completed with exit code 0 (29.8047 s simulator-reported wall
time). Output included:

- average flit latency: **16.7592 cycles** (min 12, max 203);
- average packet hops: **2.49508**;
- average injected/accepted packet rate: **0.0574518 packets/cycle**;
- average injected/accepted flit rate: **0.919067 flits/cycle**.

BookSim build identity: source revision `332bc9d90b8ced2fad4212d79c9f650b37b1f050`,
binary SHA-256
`ec80b469c885abfa2f15f78c2a94a45095ac32714c1ac0855321ba56d8d85d0e`.

These metrics describe only this selected 2×2 mesh and the declared projected
schedule. They are not measured H100/NVLink latency, throughput, NCCL behavior,
or evidence that the source paper used a ring algorithm. The fixed barrier,
packet spacing, missing compute gaps, rank mapping, and Gather root are modeling
assumptions. Do not compare this result directly with the separate Qwen/CAL26
counter data; its published NVLink scale remains unresolved.
