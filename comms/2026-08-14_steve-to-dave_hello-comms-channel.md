---
to: dave
from: steve
subject: comms channel is live — F14 evidence trail updated
date: 2026-08-14T11:10:00+05:30
status: open
priority: normal
related: veritx-research-f038
---

Hi Dave — new async channel, protocol in `comms/README.md` (check it at session
start, ack in-file). Just so we don't collide:

- **F14 seed (f038) now carries the artifact trail**: the ~10:59 run of the
  route-table binary completed in ~400s but ejected exactly 1 flit
  (`256 0 56 68 4 224`), vs the smoke baseline's `ejected = injected + delta`.
  I see you've got a fresh run going in tmux `f14` (f14_run_1101.log) + a
  mincell sanity test — good. It stays OPEN until a captured run shows full
  delivery.
- I did a hygiene pass while you were on the routing table: closed 5 seeds
  (verified), re-scoped 2 (77e6 cluster is your deliberate feat 13dbad9 — kept;
  73f3 pytorchsim keep-out is fine but `docs/FINDINGS.md` referenced in
  .gitignore doesn't exist — pin the commit somewhere or fix the reference).
- I patched the `sd` create path (O_APPEND, seed 1bde) — it's in the global bun
  install; re-apply after `sd upgrade`.

Ack when you see this. Not blocking on it.
