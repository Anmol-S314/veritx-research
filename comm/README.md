# Agent Comms — the mailbox

A text-based inter-agent mailbox so Laura / Dave / junior / Steve can talk
to each other without stomping on each other's sessions.

## Protocol (read this once)

1. **Your inbox**: `comm/inbox/<you>/`. Check it at session start and
   before/after significant actions (builds, commits, seed changes).
2. **Sending**: `bash comm/send.sh <to> "<subject>"` — prompts for body,
   or `bash comm/send.sh <to> "<subject>" <<< "body"`. Creates a dated
   message file in the recipient's inbox. Commit it: `git add comm && git commit`.
3. **Message format**: one file per message:
   `comm/inbox/<to>/<YYYY-MM-DD-HHMM>-<from>-<slug>.txt`
   Header block (From / To / Date / Subject) + body. Plain text.
4. **Replying**: reply in the SAME thread file (append `--- reply from X`),
   or new message with `Re:` subject. Appending keeps context.
5. **Reading**: mark a message `Status: READ` (first line) once you've
   acted on it, so others know it's handled. Keep the file (history).
6. **Archive**: move handled threads to `comm/archive/` only when the topic
   is fully dead. Keep recent ones in the inbox.
7. **Rules**:
   - NEVER edit/delete another agent's unread message.
   - NEVER write to another agent's inbox except via `send.sh` (which
     stamps From from your name).
   - Coordination-critical facts ALSO go to seeds (`sd create`) — the
     mailbox is for conversation, seeds is the durable tracker.
   - The mailbox is NOT a substitute for the RAM/build rules in
     GATE-R1-COORD.md. If you're about to build, check the box first.
8. **Naming**: laura, dave, junior, steve, jane (lowercase, no spaces).

## Current roster (2026-08-14)

| name | lane |
|---|---|
| laura | RTL gate, deadlock (0344), F13/F14, paper §1/§5 |
| dave | trace pipeline (e77a), BookSim/ASTRA-Sim, framing evidence |
| junior | gate subcommand acceptance (T3-002), 15-cell corpus |
| steve | hygiene audits, seed/mulch maintenance |
| jane | ASTRA-sim serving leg (pl-ac00), booksim2 network backend, trace prep |

## How to check for new mail quickly

```
grep -l "Status: NEW" comm/inbox/<you>/*.txt 2>/dev/null
```

## Pub-sub topics (added 2026-08-14)

In addition to point-to-point inboxes, shared topics for broadcast:

| topic | use |
|---|---|
| `status` | live state — canonical "where things are" |
| `decisions` | made calls (framing, closures, scope) |
| `alerts` | blockers, build hazards, environment kills |
| `questions` | open questions to anyone |

- **Publish**: `bash comm/publish.sh <topic> "<subject>"` (body via stdin or prompt)
- **Read**: `bash comm/read.sh <topic>` (NEW only) or `--all`
- Rules: same as the mailbox — stamp From, commit after, don't edit others'
  messages. The `status` topic is the single source of truth for live state;
  keep it updated when you change something material.

## Approval gate (added 2026-08-14, per project owner)

Important changes move forward ONLY with approval. Protocol:

1. **Propose**: publish to `decisions` topic: `bash comm/publish.sh decisions "PROPOSAL: <what>"` — state the change, the evidence, and why it matters.
2. **Review**: others read it (`bash comm/read.sh decisions`) and reply — agreement, objection, or questions — by publishing to `decisions` with `Re:` subject or sending p2p mail.
3. **Approve**: the change moves forward when the relevant agents have reviewed and no blocking objection stands. For RTL/verification changes: the RTL owner (laura) + the lane owner. For paper claims: dave + laura. For deletions: the author of the code.
4. **Record**: the approver publishes a `decisions` note "APPROVED: <id>" with who approved; the seed (if any) gets the approval noted in its description.
5. **What counts as "important"**: RTL changes, seed closures/reopens of P1 bugs, paper claim changes, build-environment changes, anything that would cost an hour if wrong. Hygiene (dead code, typos) doesn't need approval — just record it.

When in doubt, propose. A 5-line proposal is cheaper than a reverted change.
