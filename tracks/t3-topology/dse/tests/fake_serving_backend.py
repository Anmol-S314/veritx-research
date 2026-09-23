#!/usr/bin/env python3
"""Fake LLMServingSim backend — PR 5 protocol fixture (a REAL process).

One script, mode-selected via argv[1], NPU count via argv[2] (default 2).
Speaks the exact protocol traced in docs/protocols/llmservingsim-backend.md
so tests exercise real OS pipes, real EOF, real process death — no
subprocess mocks (handoff §26 Level 3).

Normal behavior mirrors the BookSim frontend (booksim2/main.cc:301-487):
  * startup: one [workload] completion line per NPU + "Waiting" (unsolicited)
  * every command gets exactly one Waiting-terminated reply
  * bare-path / "run" rounds: [plat] line + one completion per NPU,
    clock += 1000
  * "pass": echo round, clock unchanged; "pass <t>": clock jumps to t
  * "done": Waiting-only reply; "exit": break -> EOF, exit 0
  * "load <p>": silent ack, queued (no reply) — traced fact

Failure modes (deterministic, one per test):
  startup_hang          never emits the startup burst
  startup_eof           EOF before any output
  startup_exit_nonzero  exit code 3 before any output
  stderr_flood          correct startup, then floods stderr forever
  waiting_without_progress  THE livelock shape: Waiting forever, no clock
  delayed_waiting       0.3s pause before each reply
  multi_line_bursts     3 completion bursts before one Waiting
  missing_waiting       emits completion, never Waiting (stall)
  partial_line          "Waiting" without newline/flush (framing stall)
  protocol_garbage      non-protocol lines, then a Waiting-ish line
  eof_before_waiting    data line then EOF (death mid-reply)
  crash_after_cmd       exit 7 on first command
  ignore_exit           answers normally but never exits on 'exit'
  late_stderr           replies on stdout FIRST, then writes the ledger to
                        stderr after a delay (the drain-lag shape: reading
                        evidence at reply time loses measured statistics)

Observable state: env FAKE_BACKEND_STATE (a JSON file) records
{clock, rounds, loads, dones, exit_seen} after each command, so tests
assert multi-command sequences without parsing protocol lines.
"""
from __future__ import annotations

import json
import os
import sys
import time


# ---- protocol emit helpers (traced wire format) ----------------------------

def emit_completion(npu: int, cycle: int, exposed: int = 0) -> None:
    print(f"[workload] sys[{npu}] finished, {cycle} cycles, "
          f"exposed communication {exposed} cycles.", flush=True)


def emit_plat(cycle: int) -> None:
    print(f"[plat] packets=8 avg={cycle // 2} min=1 p50=2 p95=3 p99=4 "
          f"max={cycle} hops_avg=2.0 hops_min=1 hops_max=3", flush=True)


def emit_waiting() -> None:
    print("Waiting", flush=True)


# ---- observable state file --------------------------------------------------

def _state_path() -> str | None:
    return os.environ.get("FAKE_BACKEND_STATE")


def read_state() -> dict:
    path = _state_path()
    if not path:
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def update_state(**updates) -> None:
    path = _state_path()
    if not path:
        return
    state = read_state()
    state.update(updates)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)  # atomic; tests may read concurrently


# ---- main --------------------------------------------------------------------

def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    npus = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    clock = 0
    loads: list[str] = []
    state = read_state()
    rounds = int(state.get("rounds", 0))
    dones = int(state.get("dones", 0))
    exit_seen = bool(state.get("exit_seen", False))

    # startup: the backend runs the argv event-handler round unsolicited
    # (traced fact: main.cc:225-262 / congestion_aware/main.cc:139-147).
    if mode == "startup_hang":
        while True:
            time.sleep(3600)  # never bursts; startup timeout must fire
    if mode == "startup_eof":
        return 0
    if mode == "startup_exit_nonzero":
        return 3

    for i in range(npus):
        emit_completion(i, clock)
    emit_waiting()

    if mode == "stderr_flood":
        import threading

        def _flood() -> None:
            while True:
                sys.stderr.write("x" * (1024 * 1024) + "\n")
                sys.stderr.flush()

        # background: the main loop must keep speaking the protocol while
        # stderr floods — that is the real hazard being tested
        # (an undrained stderr pipe filling at ~round 1500).
        threading.Thread(target=_flood, daemon=True).start()

    while True:
        line = sys.stdin.readline()
        if line == "":
            return 0  # parent closed stdin without 'exit'
        cmd = line.strip()

        if cmd == "exit":
            exit_seen = True
            update_state(exit_seen=True)
            if mode == "ignore_exit":
                time.sleep(3600)  # parent must escalate TERM->KILL
            return 0

        if mode == "crash_after_cmd":
            return 7
        if mode == "eof_before_waiting":
            print("some data", flush=True)
            return 0
        if mode == "missing_waiting":
            emit_completion(0, clock)
            sys.stdout.flush()
            continue  # stall: no Waiting, keeps reading
        if mode == "partial_line":
            sys.stdout.write("Waiting")  # no newline
            sys.stdout.flush()
            continue  # stall: terminator never completes
        if mode == "protocol_garbage":
            print("this is not protocol", flush=True)
            print("Total Waiting Time: 42 units", flush=True)  # substring term
            continue
        if mode == "waiting_without_progress":
            emit_waiting()  # clock unchanged, no completions — livelock shape
            continue
        if mode == "legacy_checking":
            # legacy terminator: accepted by read_wait, produced by NO
            # vendored binary — fixture emits it only for this mode.
            emit_completion(0, clock)
            print("Checking Non-Exited Systems ...", flush=True)
            continue
        if mode == "delayed_waiting":
            time.sleep(0.3)
            for i in range(npus):
                emit_completion(i, clock)
            emit_waiting()
            continue
        if mode == "multi_line_bursts":
            for rep in range(3):
                for i in range(npus):
                    emit_completion(i, clock + rep)
            emit_waiting()
            rounds += 1
            update_state(rounds=rounds)
            continue

        # ---- normal protocol handling ----
        if cmd == "done":
            dones += 1
            update_state(dones=dones)
            emit_waiting()  # Waiting-only reply (traced: main.cc:336-343)
            continue
        if cmd.startswith("pass"):
            target: int | None = None
            if len(cmd) > 4:
                try:
                    target = int(cmd.split()[1])
                except (IndexError, ValueError):
                    target = None
            if target is not None and target > clock:
                clock = target
                update_state(clock=clock)
            for i in range(npus):
                emit_completion(i, clock)  # pass echo: clock may be unchanged
            emit_waiting()
            rounds += 1
            update_state(rounds=rounds)
            continue
        if cmd.startswith("load "):
            loads.append(cmd[5:])
            update_state(loads=loads)
            continue  # silent ack — no reply (traced: main.cc:345-349)
        if cmd == "run":
            if mode == "late_stderr":
                # the reply lands while the ledger is still in flight: this is
                # the measured shape where reading evidence too early drops
                # statistics (stdout and stderr are separate pipes)
                clock += 1000
                rounds += 1
                update_state(clock=clock, rounds=rounds, loads=loads)
                emit_plat(clock)
                for i in range(npus):
                    emit_completion(i, clock)
                emit_waiting()
                time.sleep(0.4)
                for i in range(npus):
                    for rep in range(2):
                        sys.stderr.write(
                            f"[LEDGER][COLL_SUBMIT] rank={i} astra_node=9 "
                            f"comm_type=0 comm_size=4096 priority=0 "
                            f"involved_dims=[1,1,1,1] group_members=[0,1] "
                            f"tick={rep}\n")
                sys.stderr.flush()
                continue
            pass  # apply queued loads (empty queue = re-report round)
        else:
            loads = [cmd]  # legacy single-load round
        clock += 1000
        rounds += 1
        update_state(clock=clock, rounds=rounds, loads=loads)
        emit_plat(clock)
        for i in range(npus):
            emit_completion(i, clock)
        emit_waiting()
    return 0


if __name__ == "__main__":
    sys.exit(main())
