# External artifact intake update

## Operator-relayed report

The operator relayed another coding agent's status during planning:

> Verilog confirmed present: torus8x8, ring, gec_mecs, fly64, dragonfly, qtree, mesh8x8 (per-router + diag), tree4, flatfly, cmesh (10 files incl. variants).
> SROTA mf7g monolithic — alive at 9:39 CPU, first big loop in flight.
> Hybrid mf7g — new JVM at 0:28 CPU (second big loop starting).
> Memory is tight (10/14 used, 1 free, 5 swap) — the serial-lock lanes are the bottleneck now, not heap exhaustion.

This is useful reported progress, not a completed qualification receipt. Distinct original names in that list are nine of the required twelve; Dragonfly is optional and variants do not add denominator rows. Fat-tree is not named in that report. SROTA/Hybrid live generation is not completion.

## Independent point-in-time observation

At **2026-11-08T15:25:31Z**, a read-only filesystem/process/memory inspection observed:

- Actual `CandidateNoCTop.v` at `/tmp/opencode/m5-rtl/{ring,torus8x8,gec_mecs,fly64,dragonflynew,mesh8x8-perrouter,cmesh-7g,mesh8x8-diag7g,mesh8x8-diag2vc,mesh8x8-diag2vc-factored}/`.
- Inventory files also exist for several unfinished/partitioned roots, including fattree-perrouter, gec_hybrid-perrouter, srota8x8-perrouter, cmesh-perrouter, srota8x8 and gec_hybrid. An inventory file is not evidence of finished connected Verilog.
- This shallow filename inspection was not a recursive completeness check for QTree/Tree4/FlatFly or differently named assembled tops. Do not turn an unobserved shallow match into an absence claim.
- Foreign JVM PID408567 was compiling a Tree4 partition with `-Xmx3g` from `/tmp/opencode/m5-rtl-per-router-v2/scala`.
- Foreign JVM PID408432 was compiling a Hybrid mf7g partition with **`-Xmx6g`**, not this plan's `-Xmx3g` setting, from `/tmp/opencode/m5-rtl-isolated/scala`.
- These are historical process IDs and argv, not ongoing ownership proof. No foreign process was modified/signaled.
- Memory at this later snapshot: about14Gi total,5.8Gi used,5.7Gi free,8.6Gi available; swap6.1Gi used. The operator-relayed tighter-memory snapshot and this later observation concern different times. Neither alone proves absence of prior OOM, successful generation or stability under another job.

No top/helper/source hashes, complete build receipts, post-elaboration nets, lint, decoder equivalence or packet simulations were validated by this inspection.

## Effect on execution order

1. WP00 records and coherently freezes external candidates before considering regeneration.
2. WP01/WP06 validate actual profile/source/build/hierarchy completeness; reject a partial router partition collection as a finished fabric.
3. WP07 performs actual simulation on a ready reviewed artifact as soon as heavy ownership permits. Fresh source reproduction remains a separate later obligation for historically unbound outputs.
4. Family packages repair only demonstrated policy/connection/test gaps and rebuild when needed. Never regenerate the entire existing catalog blindly.
5. Record cap deviations for external artifacts. Bytes can be useful diagnostic inputs even if their producing run exceeded approved caps, but do not label the original capped-reproduction gate passed. The operator must explicitly approve any future cap change; this update does not grant that authority.
6. Generation scheduling/memory pressure and hardware correctness are separate axes. Keep a queue of concrete ready jobs, one owned heavy run at a time for this effort, while lightweight implementation/review continues.
