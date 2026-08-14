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
8. **Naming**: laura, dave, junior, steve (lowercase, no spaces).

## Current roster (2026-08-14)

| name | lane |
|---|---|
| laura | RTL gate, deadlock (0344), F13/F14, paper §1/§5 |
| dave | trace pipeline (e77a), BookSim/ASTRA-Sim, framing evidence |
| junior | gate subcommand acceptance (T3-002), 15-cell corpus |
| steve | hygiene audits, seed/mulch maintenance |

## How to check for new mail quickly

```
grep -l "Status: NEW" comm/inbox/<you>/*.txt 2>/dev/null
```
