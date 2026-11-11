# Native-model Pareto: available evidence and remaining gaps

## Executed

```bash
python3 tracks/t3-topology/scripts/sweep_supported.py \
  --native-power --out tracks/t3-topology/runs/supported-sweep/20261026-native-power \
  --copy-to-prototype --jobs 4 --timeout 30
```

143 BookSim attempts: 13 arms × 11 offered loads, uniform traffic, 16 endpoints,
5 flits/packet, 128-bit flits, 8 buffer flits/VC. Routing and VC count remain
arm-specific. 92 windows were steady-state (`ok`); the others were unstable,
not hard execution failures.

Native results: **46 available observations across 7 arms**, 31 unavailable
post-instability observations in those arms, and 66 explicitly unsupported
observations across the 6 SROTA/GEC arms. No unavailable value is set to zero.
The allowlist is conservative: GEC-express is unaudited here, not claimed to
be inherently impossible to model.

Sweep SHA-256: `bdfa41f0a9e78a39663dbbcb6f130485c60effc0ea87f76d287376eada61fdf5`.
The gateway reads this named run; the bundled offline snapshot contains the
same rows. Configs, full command/output logs and native-model input snapshots
are preserved under its run directory.

## Example at offered load 0.005 packets/node/cycle

These are **BookSim native model estimates**, not measured silicon values.

| Arm | Modeled power (W) | Modeled area (mm²) | Modeled network energy (pJ/cycle) |
|---|---:|---:|---:|
| cmesh16 | 2.65224 | 0.158104 | 273.076 |
| explicit16 | 3.62105 | 0.203109 | 372.825 |
| fattree16 | 3.16262 | 0.205773 | 325.625 |
| fattree16_anynet | 3.20248 | 0.205773 | 329.729 |
| flatfly16 | 4.82118 | 0.483687 | 496.391 |
| mesh4x4 | 4.10796 | 0.280976 | 422.958 |
| torus4x4 | 3.81567 | 0.280976 | 392.864 |

`cmesh16` dominates the area–energy/cycle projection at this particular load
within this model-covered set. That is **not a product recommendation**: its
reported product qualification is withdrawn, and the result excludes the
six unaudited arms. The explorer preserves qualification and routing labels.
Load, latency/throughput constraints and additional objectives can change the
comparison; there is no universal winner inferred from the zero-load point.

## Implemented UI

Analysis → Curves & Pareto now supports:

- Common-load latency, throughput, hops and structural cost comparisons.
- Multiple optimization objectives, with two axes shown as a labelled 2D
  projection. Front membership uses every selected objective.
- Explicit research opt-in for native modeled power, area and energy/cycle.
- Budget filters for all three native estimates; unavailable native evidence
  excludes a candidate instead of falling back to a proxy.
- Model-identity compatibility checks, candidate exclusion reasons, native
  coverage and assumptions, and JSON export with source and model provenance.

## Limits / genuine remaining work

The native technology file is **2007 ITRS 32nm high-performance prediction**,
not calibrated modern-process data. The native clock formula yields about
9.712 GHz and uses 2 mm wire length per channel-latency cycle. It is not the
project's clock or floorplan. Technology and executable digests are recorded.

Energy/cycle = native W ÷ model clock Hz × 10¹². With a common clock it ranks
identically to native power, so selecting both adds no independent objective.
It is **not energy/packet**: native power counters and steady-state packet
statistics span different observation windows. A packet-energy metric needs
aligned delivered-packet counters and a defined measurement window.

MECS/SROTA require complete shared-wire/side-buffer activity and cost coverage
before their native power/area values can be admitted. No generic router
coefficient is applied to those realizations. Accurate process-specific costs
need characterized technology/component models. Existing Accelergy NoC ERT
constants remain explicitly placeholder inputs, and accelerator energy is not
silently substituted for fabric energy. Analytical report area estimates
retain their comparison-only policy; the new opt-in path uses the separate
native BookSim model.
