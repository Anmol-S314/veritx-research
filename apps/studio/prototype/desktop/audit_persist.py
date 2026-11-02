#!/usr/bin/env python3
"""Adversarial persistence audit: do evaluation artifacts survive a restart?

The frozen app extracts to a temporary directory. Anything written there is
lost when it exits, so every artifact a user can download must live under the
data directory and remain downloadable after a restart.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SIDECAR = Path(sys.argv[1]).resolve()
DATA = Path("/tmp/persist-data")


def start():
    log = open(DATA / "backend.log", "a+")
    proc = subprocess.Popen([str(SIDECAR), "--data-dir", str(DATA / "data")], cwd=DATA,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=log, start_new_session=True)
    line = proc.stdout.readline().decode()
    if not line.startswith("SROTA_READY "):
        raise SystemExit(f"gateway did not start: {line!r}")
    return proc, json.loads(line[len("SROTA_READY "):])["base"]


def stop(proc):
    proc.stdin.close()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def call(base, path, body=None, raw=False, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + "/api/v1" + path, data=data,
                                     method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return response.status, payload if raw else json.loads(payload)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:300] if raw else {"error": exc.read()[:300].decode("utf-8", "replace")}


def main() -> int:
    import shutil
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True)
    proc, base = start()
    failures = []
    try:
        project = call(base, "/projects/from-preset", {"preset_id": "torus25", "name": "persist"})[1]
        pid = project["project"]["project_id"]
        draft = call(base, f"/projects/{pid}/draft")[1]
        compiled = call(base, f"/projects/{pid}/compile",
                        {"expected_draft_design_hash": draft["design_hash"]})[1]
        job = call(base, f"/revisions/{compiled['revision_id']}/evaluate",
                   {"backend": "BOOKSIM_STANDALONE", "questions": ["NETWORK_COMPLETION"]})[1]
        for _ in range(600):
            state = call(base, f"/jobs/{job['job_id']}")[1]
            if state["state"] in {"COMPLETED", "FAILED", "REFUSED", "CANCELLED"}:
                break
            time.sleep(0.5)
        if state["state"] != "COMPLETED":
            return fail(f"evaluation {state['state']}: {state.get('error_message')}")
        run_id = state.get("result", {}).get("run_id") or state.get("run_id")
        status, listing = call(base, f"/runs/{run_id}/artifacts")
        names = [a.get("name") or a.get("artifact_id") or a.get("path") for a in
                 (listing.get("artifacts") if isinstance(listing, dict) else listing) or []]
        print(f"artifacts before restart ({status}): {len(names)} {names[:6]}")
        before = {}
        for name in names:
            code, blob = call(base, f"/runs/{run_id}/artifact?name={name}", raw=True)
            if code != 200:
                failures.append(f"download {name} -> {code}")
                continue
            before[name] = hashlib.sha256(blob).hexdigest()
            print(f"  {name}: {len(blob)} bytes")
        status, evidence = call(base, f"/runs/{run_id}/evidence")
        print(f"evidence endpoint: {status}")
        if status >= 400:
            failures.append(f"/runs/{run_id}/evidence -> {status}")
    finally:
        stop(proc)

    # Restart against the same data directory; everything must still be there.
    proc, base = start()
    try:
        runs = call(base, "/runs")[1]["runs"]
        print(f"runs after restart: {[r['run_id'] for r in runs]}")
        if not runs:
            failures.append("no runs survived restart")
        for name, digest in before.items():
            code, blob = call(base, f"/runs/{run_id}/artifact?name={name}", raw=True)
            if code != 200:
                failures.append(f"after restart {name} -> {code}")
                continue
            if hashlib.sha256(blob).hexdigest() != digest:
                failures.append(f"after restart {name} content changed")
        print(f"re-downloaded {len(before)} artifact(s) after restart")
    finally:
        stop(proc)
    written = sorted(p.relative_to(DATA).parts[0] for p in (DATA / "data").iterdir())
    print(f"data dir top level: {written}")
    print(f"FAILURES: {len(failures)}")
    for item in failures:
        print(f"  ! {item}")
    return 1 if failures else 0


def fail(message: str) -> int:
    print(f"FAILED: {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
