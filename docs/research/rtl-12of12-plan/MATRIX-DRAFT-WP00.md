# Twelve-row matrix draft (WP00) — honest NOT_RUN baseline

Date: 2026-11-08. Snapshot: rtl-12of12-release-v1 (hashes in WORK/evidence/snapshot-manifest.json).
Track A denominator is exactly the 12 lines below. dragonflynew (72 terminals) and Track B are separate tables.

| ID | native_contract | production_policy | source_reproduced | emitted_inventory | reachable_proof | decoder_correspondence | packets_and_credits | accepted_replay | fresh_reproduction | independent_review | overall |
|---|---|---|---|---|---|---|---|---|---|---|---|
| mesh8x8 | PASS (WP02 table) | NOT_RUN (WP04+) | NOT_RUN | NOT_RUN (candidate graph only) | PASS historical (old budget n/a) | NOT_RUN | NOT_RUN | NOT_RUN (ring path historical only) | NOT_RUN | NOT_RUN | NOT_RUN |
| torus8x8 | PASS | NOT_RUN | NOT_RUN | NOT_RUN | PASS historical | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| cmesh | PASS (wrap div recorded) | NOT_RUN | NOT_RUN | NOT_RUN | PASS historical | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| fattree | PASS (probe only) | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| flatfly | PASS (XY/YX invocations recorded) | NOT_RUN (order enforcement WP10) | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| srota8x8 | PASS (O1TURN rank recorded) | NOT_RUN (FIU WP12) | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| gec_mecs | PASS | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| **gec_hybrid** | PASS (144=48+96, live occupancy recorded) | NOT_RUN (selector WP11) | NOT_RUN | NOT_RUN | **REGen needed** (WP03 strict model: Python verified, Scala regen blocked pending slot) | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| qtree | PASS (sparse IDs) | NOT_RUN | NOT_RUN | NOT_RUN | PASS historical | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| tree4 | PASS (sparse 0..3/16..23/32..47) | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| ring | PASS | NOT_RUN | NOT_RUN | NOT_RUN | PASS historical | NOT_RUN | historical ring Verilator only (not fresh) | ring capture historical only | NOT_RUN | NOT_RUN | NOT_RUN |
| fly64 | PASS | NOT_RUN | NOT_RUN | NOT_RUN | PASS historical | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

## External intake summary (evidence/external-intake.json)

- `/tmp/opencode/m5-rtl/*/CandidateNoCTop.v` tops hashed; helper `plusarg_reader.v` present where noted. All carry caps deviation (7G/8G/mf7g diagnostics) — usable as diagnostics, NOT as capped-reproduction evidence.
- Verdict per family: ring/torus8x8/gec_mecs/fly64/dragonflynew/cmesh-7g/mesh variants have tops; fattree/flatfly/srota8x8/gec_hybrid/qtree/tree4 mostly partitioned/monitorfree only (no assembled top) — reject as finished fabric.
- No top/helper/source binding validated in WP00; WP06 owns real net/decoder checks.

## WORK-PACKAGES addendum (WP00)

No change to WP00-WP15 scope. Operator caps (6G/512M, -Xmx5G) supersede plan's 4G/3G numbers for new heavy runs; prior 7G/4G artifacts remain diagnostic. Hybrid proof-model correction (WP03) applies as written in this draft + WP03-STATE-MAP.
