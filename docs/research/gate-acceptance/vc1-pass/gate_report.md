# Gate R1 report (two-tier)

| cell | verdict | BS mean / RTL mean (cl) | ratio | exact% | mean Δ | p95|Δ| | max|Δ| |
|---|---|---|---|---|---|---|---|
| b5_vc1 | PASS | cl0: 56.62/56.61 (1.0); cl1: 44.08/44.1 (1.0) | 0.9999 | 0.9812 | -0.0049 | 0 | 72 |
| b10_vc1 | PASS | cl0: 68.47/69.21 (1.011); cl1: 50.59/51.26 (1.013) | 0.9883 | 0.8332 | 0.9516 | 16 | 304 |
| b20_vc1 | PASS | cl0: 91.38/90.58 (0.991); cl1: 60.94/60.49 (0.993) | 1.0083 | 0.8445 | -0.9941 | 24 | 480 |
| b40_vc1 | PASS | cl0: 137.34/137.33 (1.0); cl1: 82.34/82.33 (1.0) | 1.0001 | 0.9958 | 0.0009 | 0 | 207 |
| b80_vc1 | PASS | cl0: 252.06/251.68 (0.998); cl1: 138.64/138.25 (0.997) | 1.002 | 0.9809 | -0.432 | 0 | 405 |

## Ordinal invariants

- o1_monotone_vc1_bs: True
- o1_monotone_vc1_rtl: True
- o2_absorption_bs: N/A (insufficient cells)
- o2_absorption_rtl: N/A (insufficient cells)

## Summary: 5 PASS, 0 PASS-OVERRIDE, 0 FAIL, 0 INCOMPLETE

