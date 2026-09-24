# VERITX F-0003 Schedule Intervention

Same packets, topology, routing and sizes; only the injection
schedule changes. If completion tracks the injection horizon
the metric is injection-bound (F-0003 supported).

| schedule | spacing | horizon | completion | drain |
|---|---|---|---|---|
| per_cycle | 1 | 959 | 1006 | 47 |
| half_rate | 2 | 1918 | 1964 | 46 |
| quarter_rate | 4 | 3836 | 3880 | 44 |
| eighth_rate | 8 | 7672 | 7712 | 40 |

drain spread: 7 cycles

**F-0003 SUPPORTED**
