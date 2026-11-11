#!/usr/bin/env bash
# OpenCode spend breakdown — reads the client's per-call cost records from
# OpenCode's local database. These are the client's computed figures, not a
# provider invoice; retried or failed calls can drift, and subagent sessions
# are counted alongside chat sessions.
#
# Usage:
#   scripts/spend.sh                 # this repo, all time
#   scripts/spend.sh --all           # every project in the database
#   scripts/spend.sh --since 7d      # add-on window (1d, 12h, 3w, 2m)
#   scripts/spend.sh --project PATH  # exact directory or bare substring
#   scripts/spend.sh --session ID    # one session (default: $OPENCODE_SESSION_ID)
#
# Env: OPENCODE_DB overrides the database path.
set -euo pipefail
exec python3 - "$@" <<'PY'
import argparse, datetime, json, os, sqlite3, sys

DB = os.environ.get("OPENCODE_DB") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
    "opencode", "opencode.db",
)

p = argparse.ArgumentParser(description="OpenCode spend breakdown")
p.add_argument("--all", action="store_true", help="every project, not just this one")
p.add_argument("--project", metavar="PATH", help="directory path or substring to filter")
p.add_argument("--session", metavar="ID", help="restrict to one session id")
p.add_argument("--since", metavar="DUR", default=None, help="window, e.g. 12h 7d 3w 2m")
a = p.parse_args()

if not os.path.exists(DB):
    sys.exit(f"no OpenCode database at {DB} (set OPENCODE_DB)")
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cols = {r[1] for r in con.execute("pragma table_info(session_v2)")}
if "cost" not in cols:
    sys.exit(f"{DB}: session_v2 has no cost column")

UNITS = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 30 * 86400}
def parse_dur(s):
    try:
        n, u = float(s[:-1]), s[-1].lower()
    except (ValueError, IndexError):
        sys.exit(f"bad duration {s!r} (use 12h, 7d, 3w, 2m)")
    if u not in UNITS:
        sys.exit(f"bad duration unit {u!r} (h/d/w/m)")
    return int(n * UNITS[u] * 1000)

since_ms = parse_dur(a.since) if a.since else None

# "1 sessions" reads badly; every count in this report is a session count.
def plural(n):
    return f"{n} session" + ("" if n == 1 else "s")

def git_root(path):
    cur = os.path.realpath(path)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.realpath(path)
        cur = parent

def usd(v):
    return f"${v:,.4f}" if v < 100 else f"${v:,.0f}"

def tok(v):
    v = int(v or 0)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if v >= div:
            return f"{v / div:.1f}{suf}"
    return str(v)

def day(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")

where, params, scope = ["1=1"], [], "all projects"
if a.session:
    where.append("id = ?"); params.append(a.session); scope = f"session {a.session}"
elif a.project:
    root = git_root(a.project) if os.path.isdir(a.project) else a.project
    rows = con.execute("select count(*) from session_v2 where directory = ?", (root,)).fetchone()[0]
    if rows:
        where.append("directory = ?"); params.append(root); scope = root
    else:
        where.append("directory like ?"); params.append(f"%{a.project}%"); scope = f"directory like {a.project}"
elif not a.all:
    root = git_root(os.getcwd())
    rows = con.execute("select count(*) from session_v2 where directory = ?", (root,)).fetchone()[0]
    if rows:
        where.append("directory = ?"); params.append(root); scope = root
    else:  # same repo checked out elsewhere: fall back to its basename
        where.append("directory like ?"); params.append(f"%/{os.path.basename(root)}")
        scope = f"directory like %/{os.path.basename(root)}"
q = ("select id, directory, title, model, cost, tokens_input, tokens_output, tokens_reasoning,"
     " tokens_cache_read, tokens_cache_write, time_created, time_updated, parent_id"
     " from session_v2 where " + " and ".join(where))
rows = con.execute(q, params).fetchall()
if not rows:
    sys.exit(f"no sessions matched ({scope})")

def summarize(rs):
    t = {"cost": 0.0, "in": 0, "out": 0, "reason": 0, "crc": 0, "crw": 0}
    for r in rs:
        t["cost"] += r[4] or 0
        t["in"] += r[5] or 0; t["out"] += r[6] or 0; t["reason"] += r[7] or 0
        t["crc"] += r[8] or 0; t["crw"] += r[9] or 0
    return t

def model_name(raw):
    try:
        m = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw or "?"
    return f"{m.get('providerID', '?')}/{m.get('id', '?')}"

tot = summarize(rows)
lo = min(r[10] for r in rows); hi = max(r[11] for r in rows)
root_cost = sum(r[4] or 0 for r in rows if r[12] is None)
sub_cost = tot["cost"] - root_cost
billable = tot["in"] + tot["out"] + tot["reason"] + tot["crw"]
print(f"OpenCode spend — {scope}")
print(f"  source {DB}")
print(f"  {plural(len(rows))}, {day(lo)} → {day(hi)}")
print()
print(f"  total              {usd(tot['cost'])}")
print(f"  chat sessions      {usd(root_cost)}  ({sum(1 for r in rows if r[12] is None)})")
print(f"  subagent sessions  {usd(sub_cost)}  ({sum(1 for r in rows if r[12] is not None)})")
print(f"  tokens             in {tok(tot['in'])} · out {tok(tot['out'])} · "
      f"reasoning {tok(tot['reason'])} · cache read {tok(tot['crc'])} · cache write {tok(tot['crw'])}")
if billable:
    print(f"  effective          ${tot['cost'] / billable * 1e6:,.2f} per 1M billable tokens "
          f"(cache reads excluded from 'billable')")

now = datetime.datetime.now().timestamp() * 1000
if since_ms is not None:
    windows = [("today", now - (now % 86400000)), (f"last {a.since}", now - since_ms),
               ("all time", 0)]
else:
    windows = [("today", now - (now % 86400000)), ("7 days", now - 7 * 86400000),
               ("30 days", now - 30 * 86400000), ("all time", 0)]
print()
print("WINDOWS (by last activity)")
for label, since in windows:
    sel = [r for r in rows if r[11] >= since]
    s = summarize(sel)
    print(f"  {label:<12} {usd(s['cost']):>12}   {plural(len(sel)):>12}")

by_model = {}
for r in rows:
    by_model.setdefault(model_name(r[3]), []).append(r)
print()
print("BY MODEL")
for name, rs in sorted(by_model.items(), key=lambda kv: -summarize(kv[1])["cost"])[:10]:
    s = summarize(rs)
    share = (s["cost"] / tot["cost"] * 100) if tot["cost"] else 0
    print(f"  {name:<44} {usd(s['cost']):>11}  {share:5.1f}%  {plural(len(rs)):>12}")

daily = {}
for r in rows:
    daily.setdefault(day(r[11]), []).append(r)
days = sorted(daily)[-14:]
if len(days) > 1:
    peak = max(summarize(daily[d])["cost"] for d in days) or 1
    print()
    print("BY DAY (last 14 active)")
    for d in days:
        c = summarize(daily[d])["cost"]
        bar = "█" * max(0, round(c / peak * 28))
        print(f"  {d}  {usd(c):>10}  {bar}")

print()
print("TOP SESSIONS")
for r in sorted(rows, key=lambda r: -(r[4] or 0))[:8]:
    title = (r[2] or r[0])[:52]
    tag = "sub" if r[12] else "   "
    print(f"  {usd(r[4] or 0):>10}  {tag} {day(r[11])}  {title}")

sid = os.environ.get("OPENCODE_SESSION_ID")
if sid and not a.session and not any(r[0] == sid for r in rows):
    cur = con.execute(
        "select id, model, cost, tokens_input, tokens_output, tokens_reasoning,"
        " tokens_cache_read, tokens_cache_write, time_created from session_v2 where id = ?",
        (sid,)).fetchone()
    if cur:
        n = con.execute("select count(*) from session_message where session_id = ? and type = 'assistant'",
                        (sid,)).fetchone()[0]
        print()
        print(f"THIS SESSION {sid} ({model_name(cur[1])}, {n} API calls)")
        print(f"  cost {usd(cur[2] or 0)}   in {tok(cur[3])} · out {tok(cur[4])} · "
              f"reasoning {tok(cur[5])} · cache read {tok(cur[6])} · cache write {tok(cur[7])}")
PY
