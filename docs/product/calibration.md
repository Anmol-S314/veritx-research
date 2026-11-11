# Calibration: VC count dominates the fabric ranking

The decision-accuracy matrix varied demand shape and found small effects. This
sweep varies the fabric configuration on the same 5,000-packet trace and finds
a much larger one.

Setup: same trace, same endpoints, same seed; mesh 9×9 and torus 9×9; native
`dim_order` and AnyNet `min` routing; `num_vcs` 1/2/4; `vc_buf_size` 4/8/16.

## Completion cycles

| Topology | VCs | buf 4 | buf 8 | buf 16 |
|---|---:|---:|---:|---:|
| mesh DOR | 1 | 21,405 | 18,387 | 18,390 |
| mesh DOR | 2 | 12,277 | 11,054 | 11,040 |
| mesh DOR | 4 | 12,258 | **8,661** | 8,649 |
| mesh min | 1 | 17,798 | 14,501 | 14,524 |
| mesh min | 2 | 12,556 | 8,752 | 8,665 |
| mesh min | 4 | 12,547 | **8,170** | 8,160 |
| torus DOR | 1 | fail | fail | fail |
| torus DOR | 2 | 24,240 | 19,633 | 19,602 |
| torus DOR | 4 | 14,380 | **11,496** | 11,718 |
| torus min | 1 | 24,606 | 15,447 | 15,447 |
| torus min | 2 | 12,251 | 8,866 | 8,841 |
| torus min | 4 | 12,251 | **8,160** | 8,160 |

## What dominates

1. **VC count.** Mesh DOR goes 18,387 → 11,054 → 8,661 as VCs go 1 → 2 → 4.
   That is a 2.1× effect, far larger than any demand-shape difference.
2. **Routing law.** At 4 VCs, mesh DOR is 8,661 and mesh min is 8,170 — about
   6%. Torus DOR 1 VC fails because the dateline law needs two halves.
3. **Buffer depth.** 8 vs 16 is negligible (<1%) once VCs are sufficient.
4. **Demand shape.** The five-trace matrix moved mesh/torus by ~1–3%.

## Matched-VC matrix (five traces, min-hop)

At **2 VCs**:

| Trace | Winner | Ties |
|---|---|---|
| Hotspot | torus | — |
| Read-heavy | mesh | — |
| Mixed | — | mesh/torus |
| Uniform | — | mesh/torus |
| Write-heavy | — | mesh/torus |

At **4 VCs**:

| Trace | Winner | Ties |
|---|---|---|
| Read-heavy | mesh | — |
| Mixed | — | mesh/torus |
| Uniform | — | mesh/torus |
| Write-heavy | — | mesh/torus |
| Hotspot | — | all four (saturated) |

The VC budget changes the answer. At 2 VCs, hotspot favors torus and read-heavy
favors mesh; at 4 VCs, only read-heavy distinguishes mesh and hotspot becomes a
four-way tie. The fabric is overprovisioned at 4 VCs, so topology stops
mattering; at 2 VCs, topology and demand shape interact.

## The selection problem this exposes

The collective catalog compares **mesh at 1 VC** with **torus at 2 VCs**. That
is not a topology comparison; it is a VC-count comparison. At matched 4 VCs,
mesh and torus are a tie under min-hop (8,170 vs 8,160), and mesh wins under
DOR (8,661 vs 11,496). The catalog's near-tie (11,720 vs 11,694) is therefore
not evidence that torus is the better topology — the mesh was running with
half the VCs.

## Recommendation

Make VC count a first-class selection dimension:

- Compare fabrics at equal VC counts, or show the VC count next to every
  result and include it in the Pareto/decision.
- Do not claim a topology winner from unmatched VC counts.
- Prioritize calibration of VC/buffer/routing configuration over additional
  traffic fidelity. The traffic layer is not the dominant uncertainty.

This is the strongest calibration result so far: the model is more sensitive
to a configuration choice than to the workload shape it was built to model.
