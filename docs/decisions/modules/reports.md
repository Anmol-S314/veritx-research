# `reports` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/reports/artifact.py`

```text
veritx_dse.artifact — PRD §12, §14: Artifact signing and design manifests.

Implements HMAC-SHA256 integrity checking for design manifests and an
immutable revision chain so every Result or Artifact can be traced to the
exact inputs and engine version that produced it.

SIGNING-MODE HONESTY (verified-PRD Integrity PR B, §3.13 / §17.3).
RECLAIMED from the stronger lineage (p1b/verified-evaluation ==
integration/p1-product): the weaker copy signed with a SOURCE-EMBEDDED
default secret (``srota-studio-default-key-change-in-production``) whenever
a caller omitted the key. A key that ships in the source is public, so that
behaviour presented INTEGRITY as AUTHENTICITY — an evidence/provenance
defect, not a convenience. There is deliberately NO default secret now.

  SIGNED               an explicit caller-supplied key exists.
  CHECKSUMMED_UNSIGNED no key; integrity comes from ``manifest_hash``
                       (a plain SHA-256 checksum), the signature is EMPTY,
                       and the mode is recorded in ``metadata``.

This is HMAC with a shared secret: it is NOT public-verifiable signing (no
PKI) and is NOT a security boundary. Product signing (SIGNED_LOCAL /
SIGNED_SROTA_SERVICE / SIGNED_CUSTOMER_ON_PREM) is deferred until a real
key-management requirement exists.
```

## `tracks/t3-topology/dse/veritx_dse/reports/energy_fidelity.py`

```text
Energy/power fidelity registry — six quantities, never one number.

Each estimator carries its own fidelity, units, inputs, source and scope.
combine_estimates() always raises: merging a hops-proxy with a serving
power model is a category error, not a feature.

BookSim native power is INVALID for GEC-MECS until multidrop activity is
included: Power_Module walks Network::GetChannels() (_chan only) while
MECS shared links live in _md_chan.
```

## `tracks/t3-topology/dse/veritx_dse/reports/reports.py`

```text
veritx_dse.reports — PRD §7: Formal area, power, timing estimates.

Per-block area models based on published NoC synthesis results at
various technology nodes. Power model uses standard CMOS dynamic +
leakage estimation. Timing model estimates Fmax from pipeline depth
and wire delay.

References:
  - M. A. A. Faruque et al., "Thermal Budget Allocation for
    Network-on-Chip", DAC 2022 (area per router)
  - ARM CMN-600 datasheet (router area at 7nm)
  - JEDEC HBM3 spec (interface widths)
```


# `reports` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/reports/energy_fidelity.py`

line 9:

```text
#: Placeholder-calibrated bridge coefficient, verbatim from
#: tracks/t3-topology/timeloop/noc_ERT.yaml (traversal 2.5 + buffer_read
#: 0.8 + buffer_write 0.9 + link transfer 1.2). PLACEHOLDER until
#: DSENT/ORION/synthesis/datasheet calibration.
```

## `tracks/t3-topology/dse/veritx_dse/reports/reports.py`

line 39:

```text
# _LINK_AREA_REF == LINK_AREA_MM2_256B_7NM (0.0003). Intentionally diverges
# from LINK_AREA_MM2_PER_MM (0.0001/mm wire-only): per-link (repeaters +
# shielding) vs per-mm abstraction — do NOT substitute.
```

line 152:

```text
# Published per-router power at 7nm, ~1GHz, 30% utilization:
#   ARM CMN-600:     ~8-12 mW per mesh port (128-port config)
#   Melia et al.:    ~5-15 mW per 5-stage pipelined router (DAC 2010)
#   TUM survey:      ~10 mW typical for 64-node mesh at 7nm (2022)
# We use a per-router dynamic power model calibrated to these references.
```

line 285:

```text
# Derating factor: real Fmax = ideal Fmax × derating.
# Accounts for clock skew, setup/hold margins, IR drop, PVT variation.
# Reference: Synopsys timing closure reports for 7nm NoC designs.
# Canonical: core.constants FMAX_DERATING (alias kept for backward compat).
```

line 416:

```text
    # Collective sizing block (PRD §5.2 Level B — estimates, not sign-off).
    # Incast buffer note: worst-case concurrent arrivals at one port ≈
    # incast_degree × packet_size flits (canonical: BOOKSIM_DEFAULTS in
    # core.constants). A fabric absorbing full-fan-in bursts without
    # backpressure needs vc_buf at or above that; below it, expect the
    # saturation seen in trace replay.
    # Hypercast estimate: alltoall/allgather among G ranks takes G*(G-1)
    # unicast messages vs G hardware-multicast messages, saving G*(G-2).
```

line 433:

```text
    # Ring-algorithm phase estimates for reduce collectives: a ring
    # allreduce/reducescatter over G ranks takes 2*(G-1) phases. Assumes the
    # ring algorithm (bandwidth-optimal, latency-suboptimal); a tree or
    # in-network-compute collapse is NOT modeled — see note below.
```


# `reports` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/reports/artifact.py` :: `DesignManifest`

```text

    Each design has a unique design_id. Revisions are numbered sequentially.
    Each revision carries the hash of the previous revision, forming a chain.

```

## `tracks/t3-topology/dse/veritx_dse/reports/reports.py` :: `estimate_dynamic_power`

```text

    Uses calibrated per-router model (not first-principles wire capacitance).
    Per-router dynamic power = activity × base_power_per_mhz × freq_mhz
    where base_power is calibrated to published CMN-600 / DAC survey data.

```
