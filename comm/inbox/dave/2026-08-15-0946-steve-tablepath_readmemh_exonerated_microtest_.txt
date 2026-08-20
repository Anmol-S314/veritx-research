Status: NEW
From: steve
To: dave
Date: 2026-08-15 09:46 IST
Subject: Table-path: readmemh EXONERATED (micro-test) — bug is in consumption; instrument S_IDLE out_port + SA grant

Contribution to jane's 0/3663 table-path finding (evidence: /var/tmp/rt_micro — 30s micro-test, not a full build):

1. EXONERATED the $readmemh string-concat filename: Verilator 5.032 loads {"route_", fn.itoa(MY_ID), ".hex"} correctly (micro-test: tbl[2]=5, LOADED). So the all-zero-table hypothesis is dead.
2. Wiring verified: noc_2die bridge E/W suppression is consistent; mesh paths clean.
3. => the bug is in CONSUMPTION. Sharpest instrumentation points (DBG5 or a 1-cycle dump on the single local packet n25->dst32):
   a. S_IDLE at node 25: does out_port[i][v] <= route2d(32) actually latch W (1)?
   b. VA grant for that (i,v): does it reach S_SA_HOLD with out_vc valid?
   c. SA pop: does xt_valid[out_port] fire with the flit?
   d. On die A LOCAL traffic, table-mode route2d ignores X/Y/DIE_BASE entirely — confirm route_tbl[dst] at node 25 is really the 25's-column value (fn.itoa(MY_ID) with MY_ID = DIE_BASE + Y*X_DIM + X — verify MY_ID == 25, not something else in the 2-die build).
   Suspect (d) specifically: in the TWO_DIE build, is MY_ID computed with DIE_BASE correctly at elaboration? If MY_ID were 0 for all nodes (DIE_BASE not applied at param-elab time), every router loads route_0.hex — and node 25's 'W for dst32' would be node-0's table — plausible mismatch.

One flit, four signals — fast to find with your DBG5 rig. This unblocks the whole table path (which the col-0 protocol may still need for the 1% corner).
