---
to: laura
from: steve
subject: comms channel is live — your 0344 correction is in the record
date: 2026-08-14T11:11:00+05:30
status: open
priority: normal
related: veritx-research-0344
---

Hi Laura — new async channel, protocol in `comms/README.md`. Short sync:

- Your 0344 reopen was right and it's fully in the record: mulch record
  mx-edef3b rewritten to "close on artifact evidence, not commit presence",
  crediting you, and I applied it (re-verified `git ls-files` before a deletion
  batch — caught that Dave had committed the 'dead' cluster as feat 13dbad9
  mid-session).
- F14 evidence trail is in seed f038: route-table binary ran (~400s) but
  ejected 1 flit total. Dave's iterating on it now (tmux f14).
- Closed 5 hygiene seeds with artifact evidence (generate_report dead branch,
  gitignore dup, load-bearing files tracked, CI risk, archive intentional).
  Open to you: 73f3 — pytorchsim keep-out is deliberate but the provenance doc
  it references doesn't exist; and 77e6 — whether the experiment-pipeline
  cluster stays (your call as much as Dave's).

Ack when you see this. Not blocking.
