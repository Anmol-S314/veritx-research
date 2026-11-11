# Gateway restart — current state (2026-11-10)

## Status: fresh gateway live on :8099

On 2026-11-10 the stale gateway (PID 808049) was found stopped (no listener
on :8099 at all). The gateway was relaunched from the current tree in this
checkout:

```bash
PYTHONPATH=tracks/t3-topology/dse VERITX_BOOKSIM_BIN=third_party/booksim2/src/booksim \
  python3 -m uvicorn veritx_dse.gateway.app:app --host 127.0.0.1 --port 8099
```

Verified: `GET /api/v1/health` returns `{"status":"ok","code":{"stale":false,...}}`,
`source_age_s: 0.0`, all three backends `PRESENT` (BOOKSIM_STANDALONE,
ASTRA2_EMBEDDED_BOOKSIM, ASTRA2_STANDALONE). PID recorded in this file's
precedent is not pinned; check with `ss -tlnp | grep :8099`.

## Why restarts are operator-owned

The gateway serves the prototype proxy (:5174 → :8099) and holds project
state in its live store. Restarting from an agent session was done only at
the operator's explicit direction. Prefer `status: ok` + `stale: false`
before trusting any response.

## Stale-health semantics (unchanged)

`veritx_dse/gateway/staleness.py` flags drift when a source file is newer
than the process — a **code-version drift warning, not a liveness failure**.
The fix is always the same: relaunch from the current tree (above), then
re-check `/api/v1/health`.

## Related incident (closed 2026-11-10)

The 12 Playwright delivery-flow failures recorded with the stale gateway were
later shown to be stale against the *current* delivery page (it renders
**Research RTL evidence** and **Current project preview**; “RTL delivery” no
longer exists). The specs were updated to the current page and now pass
(8/8). The gateway being fresh was necessary but not sufficient for green.

## Final restart record — 2026-11-10 ~14:2x UTC

After the last code edits of the day (reports uncalibrated-fallback label, bigint 2^53 pins, ROADMAP blocker renames, kncube harness routing, locked-TB contention scenarios), the gateway was relaunched from the current tree; `/api/v1/health` reports:

```json
{"status":"ok","api":"v1","code":{"stale":false,"pid":16846,"loaded_at":1794300028.441909,"newest_source_mtime":1794299998.315805,"source_age_s":0.0}}
```

`loaded_at` and `newest_source_mtime` differ by ~30 s; `stale: false` is a verdict on record only for this process and only until the next code edit. Any later edit makes the running gateway stale again by the rule above.
