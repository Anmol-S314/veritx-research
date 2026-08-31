# Multi-Agent Harness Design — Architecture Notes

**Date:** 2026-08-14
**Status:** Design phase — v2 (post-Qwen review incorporated)
**Context:** veritx-research project, 4-agent team (laura, dave, junior, steve), currently using opencode + custom comm/ + seeds
**Reviewers:** Qwen (Staff Engineer review — incorporated below)

---

## 1. Problem Statement

### Current failures observed with opencode:

| Failure | Description |
|---|---|
| Blocking subagents | Main agent blocks when spawning a subagent. No async-ness. Entire loop stalls. |
| Forgotten check-ins | Agent says "waiting for X" — X completes — agent stays stuck until human manually prompts. |
| No event-driven coordination | Agents rely on polling (grep for new mail). Polling frequency is unknown. Messages can be missed. |
| No failure recovery | If generation stops mid-thinking (API timeout, context overflow, rate limit), agent stalls. No automatic retry. |
| No voice interface | All interaction is text-based. Human must type to coordinate. |
| Context pollution | Agents lose track of tasks when full mail/status is injected every turn. |
| Infinite tool loops | LLMs get stuck calling grep→read→grep repeatedly, burning time and money. |

### Root cause:

Agent context window is a lossy, attention-limited state store. "Remember to check the inbox" is a volitional memory obligation that fails under long context. The harness (opencode) has no mechanism to inject state between turns or notify agents of completion events.

---

## 2. Solutions Evaluated

### 2.1 herdr (herdrdev/herdr) — 30k stars, Rust

**What it is:** Terminal workspace manager / agent runtime. Background server that owns agent terminals.

**Key features relevant to our problem:**
- Every pane marked as `working`, `blocked`, `idle`, or `done` — real-time state tracking
- `herdr agent prompt <name> "..." --wait` — deterministic wait for agent completion
- `herdr pane wait-output <pane> --match "text" --timeout N` — wait for specific output
- `herdr agent wait <name> --until blocked` — wait for specific state
- `herdr notification show "title" --body "..." --sound done` — push notifications
- Always running — sessions survive lid-close, network drop, restart
- Socket API for programmatic access
- Supports: pi, opencode, claude, codex, cursor, grok, and 10+ others
- **Linux support:** Full. `src/platform/linux.rs` with WSL detection. Cross-platform Rust.

**Tested:** Installed v0.8.0, verified workspace/pane/agent commands, `wait-output` works deterministically.

**Verdict:** Solves the "forgetting to check" and "stays stuck" problems. Replaces polling with event-driven state tracking.

### 2.2 cmux (manaflow-ai/cmux) — 26k stars

**What it is:** Ghostty-based macOS terminal multiplexer with vertical tabs + notifications for AI agents.

**Verdict:** Useful for UX (organized tabs, notifications), but herdr is more mature and Linux-compatible. cmux is macOS-only.

### 2.3 warren (jayminwest/warren) — 319 stars

**What it is:** "Coolify for coding agents" — control plane for agent orchestration, self-manage, self-repair.

**Key features:**
- Same author as seeds (jayminwest)
- Agent lifecycle management
- Sandbox/isolation
- Self-healing

**Verdict:** Interesting but lower maturity (319 stars vs herdr's 30k). Could be useful later for production orchestration.

### 2.4 seeds (jayminwest/seeds) — 127 stars

**What it is:** Git-native issue tracker for AI agent workflows. JSONL storage, Bun runtime.

**Already in use** in this project. Good for task tracking, dependency management (`blocks`/`blockedBy`).

**Verdict:** Fine for task tracking at our scale. Not a real task queue (polling-based, no delivery guarantees).

### 2.5 pi (@earendil-works/pi-coding-agent)

**What it is:** Agent harness with extension system, hooks, custom tools, skills.

**Key features relevant to our problem:**
- `before_agent_start` hook — inject state every turn (structural, not volitional)
- `tool_call` hook — block, modify, or wrap tool calls
- `turn_start` / `turn_end` — inject coordination state at boundaries
- `context` hook — modify messages before each LLM call
- Custom tools — register async tools that don't block main loop
- `pi.appendEntry()` — persistent state across restarts
- `/reload` — hot-reload extensions
- Session management, forking, tree navigation

**Verdict:** Pi's extension system is the missing piece that opencode lacks. The `before_agent_start` hook makes check-ins structural, not volitional.

---

## 3. Architecture

### 3.1 Layered approach

```
┌──────────────────────────────────────────────────┐
│  LAYER 3: ORCHESTRATION (standalone process)     │
│  - Task dispatch (push to queue, not serial)     │
│  - Failure recovery                              │
│  - Voice pipeline (STT → summarizer → TTS)       │
│  - Task lifecycle management                     │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────┴───────────────────────────┐
│  LAYER 2: COORDINATION (harness-agnostic)        │
│  - Agent state detection (herdr socket API)      │
│  - Messaging (SQLite WAL — not file-based)       │
│  - Task tracking (seeds — git-native)            │
│  - Notifications (herdr — push-based)            │
│  - Structured IPC (JSON heartbeats, not scraping)│
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────┴───────────────────────────┐
│  LAYER 1: RUNTIME (herdr)                        │
│  - Terminal multiplexing                          │
│  - Agent lifecycle states                        │
│  - Pane management                               │
│  - Session persistence                           │
└──────────────────────┬───────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
   ┌─────────┐   ┌──────────┐   ┌──────────┐
   │   pi    │   │ opencode │   │claude code│
   │ (hooks) │   │ (file    │   │ (hooks)  │
   │  PRIMARY│   │  watch)  │   │  PRIMARY │
   └─────────┘   └──────────┘   └──────────┘
```

### 3.2 Harness adapter pattern

The framework keeps a thin adapter interface for harness-agnosticism, but pi and claude code are primary. OpenCode is "best effort" (no state injection).

```typescript
interface HarnessAdapter {
  name: string;
  canInject(): boolean;           // Can this adapter inject state?
  injectState?(state: StateDiff): void;  // Inject STATE DIFF, not full content
  readOutput(paneId: string): string;      // Read agent output
  detectState(paneId: string): AgentState; // Detect working/blocked/idle/crashed
  sendPrompt(paneId: string, prompt: string): void;  // Send work
  waitComplete(paneId: string, timeout: number): Promise<boolean>;  // Wait for done
  reportCompletion(result: CompletionReport): void;  // Structured IPC, not terminal scraping
}

interface CompletionReport {
  status: "done" | "failed" | "blocked";
  tests_passed?: boolean;
  files_changed?: string[];
  summary?: string;  // For voice summarizer
  error?: string;
}
```

**Adapters:**

| Harness | canInject | Priority | Strategy |
|---|---|---|---|
| pi | ✅ true | PRIMARY | Extension hooks + structured IPC via `appendEntry` |
| claude code | ✅ true | PRIMARY | Claude Code hooks + structured IPC |
| opencode | ❌ false | BEST EFFORT | File watching + herdr state (fallback only) |

### 3.3 State flow (v2 — parallel dispatch, not serial)

```
1. Dispatcher reads seeds (sd ready --format json)
2. Finds ALL unblocked tasks
3. For each idle agent:
   a. Assigns next unblocked task
   b. Creates git worktree for isolation (git worktree add ../agent-<name>-wt)
   c. Sends seed title+description AS prompt (no LLM paraphrase)
   d. herdr agent prompt <agent> "Task: <title>\n<description>\nWorktree: ../agent-<name>-wt" --wait
4. Agent works in isolated worktree
5. Agent reports completion via structured IPC (JSON heartbeat)
6. Dispatcher reads CompletionReport
7. Updates seed status (sd update <id> --status done)
8. Merges worktree into main branch (or creates PR)
9. Publishes summary to coordination channel
10. Agent becomes idle → dispatcher assigns next task
```

**Key change from v1:** Dispatcher pushes tasks to idle agents (pull model), not a serial loop. All 4 agents work in parallel.

### 3.4 Git worktree isolation (NEW — Qwen review)

Each agent MUST operate in its own git worktree to prevent file conflicts:

```
veritx-research/
├── main/                          # Main branch (protected)
├── worktrees/
│   ├── laura-task-123/            # Laura's isolated workspace
│   ├── dave-task-124/             # Dave's isolated workspace
│   ├── junior-task-125/           # Junior's isolated workspace
│   └── steve-task-126/            # Steve's isolated workspace
```

**Benefits:**
- No file conflicts between agents
- Parallel work on the same codebase
- Clean merge/PR workflow on completion
- Easy rollback if agent breaks something

---

## 4. Component Design

### 4.1 Dispatcher (task assignment — v2, not serial loop)

**Trigger:** `agent_settled` event (pi) or herdr state change → `idle`

**Flow:**
1. `sd ready --format json` → get ALL unblocked tasks
2. `herdr agent list` → get all agents and their states
3. For each `idle` agent:
   a. Pick highest-priority unassigned task
   b. Create worktree: `git worktree add worktrees/<agent>-<task> -b <agent>/<task-slug>`
   c. Send prompt via herdr: `herdr agent prompt <agent> "Task: <title>\n\n<description>\n\nWorktree: worktrees/<agent>-<task>" --wait --timeout 300000`
   d. Mark seed as in_progress: `sd update <id> --status in_progress`
4. When agent reports completion:
   a. Read CompletionReport from structured IPC
   b. If tests_passed: merge worktree → main
   c. If failed: log to alerts, retry or escalate
   d. Delete worktree: `git worktree remove worktrees/<agent>-<task>`
   e. Mark seed as done: `sd update <id> --status done`
5. Agent becomes idle → step 2

**Guardrails:**
- Max 1 task per agent at a time (no parallel tasks per agent)
- Max 3 retries per task (then escalate to human)
- Timeout per task (default 5 minutes, configurable)
- Cost limit per session (track LLM spend)
- Human approval required for: `git push`, `rm`, `sudo`, financial actions

### 4.2 Failure detector (v2 — structured IPC, not terminal scraping)

**Detection methods:**

| Method | Source | Catches |
|---|---|---|
| Structured IPC heartbeat | Agent writes JSON on completion | Confirms actual completion (tests passed, files changed) |
| `after_provider_response` hook | pi extension | HTTP errors (429, 500, 503), rate limits |
| `turn_end` hook | pi extension | Incomplete responses (empty content, too short) |
| `tool_execution_end` hook | pi extension | Tool failures (command timeout, file not found) |
| Infinite tool loop detection | Extension tracks tool call history | Same tool called 3x with similar args |
| `herdr agent get <name>` | herdr socket API | State stuck in `working` for too long |
| `herdr pane process-info` | herdr socket API | Process exited (crash) |

**Infinite tool loop detection (NEW — Qwen review):**

```typescript
// Track tool call history per agent
const toolHistory: Map<string, Array<{tool: string, args: string, timestamp: number}>> = new Map();

pi.on("tool_execution_start", async (event, ctx) => {
  const history = toolHistory.get(ctx.agentName) || [];
  history.push({ tool: event.toolName, args: JSON.stringify(event.args), timestamp: Date.now() });
  
  // Check for 3 consecutive similar calls
  if (history.length >= 3) {
    const last3 = history.slice(-3);
    if (last3.every(h => h.tool === last3[0].tool && similarArgs(h.args, last3[0].args))) {
      // Infinite loop detected — force compact or escalate
      ctx.ui.notify("Infinite tool loop detected. Compacting context.", "warning");
      ctx.compact({ customInstructions: "You appear stuck. Rethink your approach." });
      toolHistory.set(ctx.agentName, []); // Reset history
    }
  }
  
  toolHistory.set(ctx.agentName, history);
});
```

**Recovery actions:**
1. Log failure to SQLite coordination channel
2. Retry with exponential backoff (max 2 retries — Qwen: "3rd try rarely fixes logic errors")
3. On final failure: notify human via herdr notification + voice alert
4. On context overflow: trigger compaction (`/compact` in pi)
5. On rate limit: exponential backoff (429 is recoverable)
6. On infinite tool loop: force compaction or escalate

**Escalation threshold (Qwen recommendation):**
- **Retry:** Rate limits (429), context overflow, transient network errors
- **Escalate:** Logic errors, test failures, API down (500+), infinite loops after 2 retries

### 4.3 Voice pipeline (v2 — with summarizer)

**Architecture:**
```
Microphone → Whisper (STT) → text → pi input → agent processes
Agent output → Fast LLM (summarizer) → text → Piper (TTS) → Speaker
```

**Why the summarizer:** If an agent outputs 500 lines of code diffs or logs, Piper will take 15 minutes to read it aloud. A fast LLM (haiku/flash) summarizes to 1-2 sentences first.

**Components:**

| Component | Tool | Latency | Quality |
|---|---|---|---|
| STT | whisper.cpp (tiny model) | ~1-3s | Good (clear speech) |
| Summarizer | claude-haiku or gemini-flash | ~1-2s | Good (fast + cheap) |
| TTS | piper (en_US-lessac-medium) | ~0.5-1s | Good (functional) |

**Voice commands:**
- "What's the status?" → reads seeds + SQLite → summarizes → speaks
- "Start the next task" → dispatcher loop
- "What failed?" → reads alerts → summarizes → speaks
- "Retry task X" → sends prompt to agent
- "Stop all" → kills all agent processes

**Implementation:** pi extension with `voice_listen` and `voice_speak` custom tools, plus a `summarize_for_voice` helper.

### 4.4 Coordination extension (pi)

```typescript
// ~/.pi/agent/extensions/coordination.ts
export default function (pi: ExtensionAPI) {
  // Inject STATE DIFF (not full content) every turn
  pi.on("before_agent_start", async (event, ctx) => {
    const diff = getStateDiff(ctx.agentName);  // From SQLite
    if (diff) {
      return {
        message: {
          customType: "coordination-diff",
          content: `[System: ${diff.newMessages} new messages, ${diff.statusChanges} status changes. Call check_inbox() to read.]`,
          display: false,
        },
      };
    }
  });

  // Detect failures
  pi.on("after_provider_response", async (event, ctx) => {
    if (event.status >= 400) { /* log, retry, notify */ }
  });

  pi.on("turn_end", async (event, ctx) => {
    if (isIncomplete(event.message)) { /* retry, compact */ }
  });

  // Infinite tool loop detection
  pi.on("tool_execution_start", async (event, ctx) => {
    /* track history, detect loops, force compact */
  });

  // Report completion via structured IPC
  pi.on("agent_settled", async (_event, ctx) => {
    const report: CompletionReport = {
      status: "done",
      tests_passed: await runTests(),
      files_changed: getChangedFiles(),
      summary: await generateSummary(),
    };
    reportCompletion(report);  // Write to SQLite
  });

  // Register coordination tools
  pi.registerTool({
    name: "check_inbox",
    description: "Read unread messages (structured, not full dump)",
    // Returns only unread, recent, relevant messages
  });

  pi.registerTool({
    name: "wait_for_agent",
    description: "Wait for another agent to complete via herdr",
    // herdr agent wait <name> --until done --timeout N
  });

  pi.registerTool({
    name: "send_to_agent",
    description: "Send a task to another agent via herdr",
    // herdr agent prompt <agent> "..." --wait
  });
}
```

---

## 5. Communication Layer — SQLite WAL (replacing file-based comm/)

### Why SQLite WAL (Qwen recommendation):

| Aspect | comm/ (files) | SQLite WAL |
|---|---|---|
| Atomicity | ❌ Partial writes possible | ✅ ACID transactions |
| Ordering | ❌ File timestamps unreliable | ✅ Monotonic row IDs |
| Delivery | ❌ Agent might miss message | ✅ Query-based, guaranteed read |
| Concurrency | ❌ Race conditions on writes | ✅ WAL allows concurrent reads |
| Debugging | ✅ `cat` files | ✅ `sqlite3` CLI |
| Dependencies | ✅ None | ✅ Single binary, no daemon |
| Git integration | ✅ Git tracks files | ⚠️ Binary file (but small) |

### Schema:

```sql
-- Messages (replaces comm/inbox/)
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_agent TEXT NOT NULL,
  to_agent TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT DEFAULT 'unread',  -- unread, read, archived
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Task queue (extends seeds)
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,  -- seed ID
  title TEXT NOT NULL,
  description TEXT,
  assignee TEXT,
  status TEXT DEFAULT 'pending',  -- pending, in_progress, done, failed
  priority INTEGER DEFAULT 0,
  blocked_by TEXT,  -- JSON array of task IDs
  worktree TEXT,    -- Path to git worktree
  retries INTEGER DEFAULT 0,
  max_retries INTEGER DEFAULT 2,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Agent state (from herdr)
CREATE TABLE agents (
  name TEXT PRIMARY KEY,
  harness TEXT NOT NULL,  -- pi, claude, opencode
  pane_id TEXT,
  status TEXT DEFAULT 'idle',  -- idle, working, blocked, done, crashed
  current_task TEXT,
  last_heartbeat DATETIME,
  FOREIGN KEY (current_task) REFERENCES tasks(id)
);

-- Completion reports (structured IPC)
CREATE TABLE completions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  status TEXT NOT NULL,  -- done, failed, blocked
  tests_passed BOOLEAN,
  files_changed TEXT,  -- JSON array
  summary TEXT,
  error TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- Alerts (replaces comm/topics/alerts)
CREATE TABLE alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  severity TEXT NOT NULL,  -- info, warning, error, critical
  source TEXT NOT NULL,
  message TEXT NOT NULL,
  resolved BOOLEAN DEFAULT FALSE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Access pattern:

```typescript
import Database from 'better-sqlite3';
const db = new Database('coordination.db', { wal: true });

// Send message
db.prepare('INSERT INTO messages (from_agent, to_agent, subject, body) VALUES (?, ?, ?, ?)')
  .run('dave', 'laura', 'F13 fixed', 'bd32694 committed');

// Read unread
const unread = db.prepare('SELECT * FROM messages WHERE to_agent = ? AND status = ?')
  .all('laura', 'unread');

// Get ready tasks
const ready = db.prepare(`
  SELECT * FROM tasks 
  WHERE status = 'pending' 
  AND id NOT IN (SELECT json_each.value FROM json_each(tasks.blocked_by))
  ORDER BY priority DESC
`).all();

// Report completion
db.prepare('INSERT INTO completions (task_id, agent_name, status, tests_passed, files_changed) VALUES (?, ?, ?, ?, ?)')
  .run('abc123', 'laura', 'done', true, '["src/main.py"]');
```

---

## 6. Implementation Plan (v2 — post-Qwen review)

### Phase 1: Foundation (Week 1)

| Task | Description | Owner |
|---|---|---|
| Install herdr | ✅ Done (v0.8.0) | — |
| Setup SQLite coordination DB | Schema, indexes, WAL mode | Framework |
| Setup git worktree isolation | Script to create/remove worktrees per agent | Framework |
| Create pi coordination extension | `before_agent_start` (state diff injection), failure hooks | Framework |
| Test herdr integration | Workspace with 4 agent panes | Framework |
| Migrate dave from opencode → pi | Reduce harness fragmentation | Human |

### Phase 2: Dispatcher (Week 2)

| Task | Description | Owner |
|---|---|---|
| Build dispatcher core | Parallel task assignment, worktree creation | Framework |
| Add failure detection | Structured IPC + herdr state + infinite loop detection | Framework |
| Add failure recovery | 2 retries then escalate, compaction trigger | Framework |
| Add completion merging | Worktree → main branch merge/PR | Framework |
| Test parallel dispatch | 4 agents working simultaneously | Framework |

### Phase 3: Voice (Week 3)

| Task | Description | Owner |
|---|---|---|
| Install whisper.cpp | STT pipeline | Framework |
| Install piper | TTS pipeline | Framework |
| Build summarizer | Fast LLM (haiku/flash) for voice summaries | Framework |
| Build voice extension | `voice_listen` + `voice_speak` + `summarize_for_voice` | Framework |
| Test voice commands | Status, start, retry, stop | Framework |

### Phase 4: Hardening (Week 4)

| Task | Description | Owner |
|---|---|---|
| Claude Code adapter | Hook integration, structured IPC | Framework |
| Cost tracking | LLM spend per agent per session | Framework |
| Monitoring dashboard | herdr TUI + SQLite queries | Framework |
| Document runbooks | Failure scenarios, recovery procedures | Human |
| Drop opencode adapter | Remove best-effort code, simplify | Framework |

---

## 7. Tool Inventory

| Tool | Version | Location | Purpose |
|---|---|---|---|
| herdr | v0.8.0 | `~/.local/bin/herdr` | Terminal multiplexer, agent runtime |
| seeds | v0.5.9 | global install | Git-native issue tracker |
| pi | latest | running | Agent harness with extensions (PRIMARY) |
| SQLite | 3.x | system | Coordination DB (WAL mode) |
| whisper.cpp | TBD | `veritx-research/whisper/` | Speech-to-text (local) |
| piper | TBD | `veritx-research/piper/` | Text-to-speech (local) |
| claude-haiku | API | cloud | Voice summarizer (fast + cheap) |
| comm/ | custom | `veritx-research/comm/` | Human-readable logs (kept for debugging) |

---

## 8. Open Questions (answered — Qwen review)

| Question | Answer |
|---|---|
| Harness-agnostic vs pi deep? | **Keep adapter interface (20 LOC, insurance), but pi + claude are primary. OpenCode is best-effort, plan to drop.** |
| comm/ + seeds vs message broker? | **Replace comm/ with SQLite WAL. Keep seeds for task tracking. SQLite gets you ACID without a daemon.** |
| Orchestrator: pi extension or standalone? | **Standalone process. Connects to pi via RPC for hooks. Resilient to pi crashes.** |
| Voice: local vs cloud? | **Local STT/TTS (whisper + piper). Cloud summarizer only (haiku/flash, ~$0.001/summary).** |
| Failure recovery: retry or escalate? | **2 retries max. Escalate on 3rd failure. Exception: rate limits use backoff, context overflow uses compact.** |
| Guardrails: what requires human approval? | **Auto-approve: reads, tests, local commits, whitelisted searches. Human approval: git push, rm, sudo, network, financial.** |

---

## 9. Qwen Review Summary

### Adopted (critical fixes):

| Issue | Fix |
|---|---|
| Serial orchestrator bottleneck | Parallel dispatch with pull model + git worktree isolation |
| Context window pollution | Inject state diffs, not full mail content |
| Terminal scraping brittleness | Structured IPC (JSON heartbeats) instead of stdout parsing |
| File-based IPC race conditions | Migrate comm/ to SQLite WAL |
| Prompt generation waste | Seed title+description IS the prompt (no LLM paraphrase) |
| Voice pipeline too slow for long output | Add fast LLM summarizer before TTS |
| Infinite tool loops | Track tool call history, force compact after 3 similar calls |

### Partially adopted:

| Issue | Decision |
|---|---|
| Drop opencode entirely | Keep as best-effort for 1 sprint, then drop. Migrate dave to pi first. |
| Orchestrator as standalone | Yes, but keep thin pi RPC bridge for hooks. Not fully decoupled. |
| comm/ → SQLite | Yes, but keep comm/ as human-readable log layer on top. |

### Rejected:

| Issue | Reason |
|---|---|
| Drop harness-agnostic adapter | Interface is 20 LOC. It's insurance, not complexity. Keep it. |

---

## 10. References

- herdr: https://github.com/herdrdev/herdr (30k stars)
- cmux: https://github.com/manaflow-ai/cmux (26k stars, macOS only)
- warren: https://github.com/jayminwest/warren (319 stars)
- seeds: https://github.com/jayminwest/seeds (127 stars)
- pi: @earendil-works/pi-coding-agent (current harness)
- whisper.cpp: https://github.com/ggerganov/whisper.cpp
- piper: https://github.com/rhasspy/piper
- SQLite WAL: https://www.sqlite.org/wal.html

---

*This document is v2 — incorporating Qwen's Staff Engineer review. Ready for implementation.*
