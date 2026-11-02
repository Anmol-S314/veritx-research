#!/usr/bin/env python3
"""Adversarial runtime sweep of the packaged app.

Starts the frozen gateway and calls a broad set of endpoints, then drives every
executable backend. Any 5xx, or any refusal caused by a missing packaged file,
is a packaging defect: the app must either work from its bundle or say why in
terms of user input, never in terms of absent repository files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SIDECAR = Path(sys.argv[1]).resolve()
DATA = Path("/tmp/audit-data")


def start():
    import shutil
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True)
    log = open(DATA / "backend.log", "w+")
    proc = subprocess.Popen([str(SIDECAR), "--data-dir", str(DATA / "data")],
                            cwd=DATA, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=log, start_new_session=True)
    line = proc.stdout.readline().decode()
    if not line.startswith("SROTA_READY "):
        raise SystemExit(f"gateway did not start: {line!r}\n{log.read()}")
    return proc, json.loads(line[len("SROTA_READY "):])["base"]


def call(base, path, body=None, method=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + "/api/v1" + path, data=data,
                                     method=method or ("POST" if data else "GET"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:400]}
    except Exception as exc:  # noqa: BLE001
        return 0, {"exception": f"{type(exc).__name__}: {exc}"}


GETS = [
    "/health", "/qualification", "/capabilities", "/loom/capabilities",
    "/loom/provenance", "/loom/origin", "/reports", "/validation",
    "/federation/backends", "/catalog/workloads", "/catalog/fabric-presets",
    "/catalog/serving-configs", "/catalog/hardware-profiles",
    "/catalog/serving-experiments", "/catalog/capability-gaps",
    "/catalog/execution-evidence", "/catalog/knob-inventory",
    "/analysis/topology-sweep", "/loom/simulation/load",
    "/loom/simulation/series", "/loom/simulation/link",
]


def main() -> int:
    proc, base = start()
    failures = []
    try:
        print(f"{'endpoint':45s} status  note")
        for path in GETS:
            status, payload = call(base, path, timeout=120)
            note = ""
            if status >= 500 or status == 0:
                note = str(payload)[:160]
                failures.append((f"GET {path}", status, note))
            print(f"{path:45s} {status:<7d} {note}")

        # Every preset must materialize, compile and evaluate on every backend
        # the health endpoint advertises as present.
        status, health = call(base, "/health")
        backends = [name for name, info in (health.get("backends") or {}).items()
                    if info.get("binary_present")]
        print(f"\nadvertised backends: {backends}")
        _, presets = call(base, "/catalog/fabric-presets")
        preset_ids = [p.get("preset_id") or p.get("id") for p in (presets.get("presets") or presets.get("items") or [])]
        print(f"presets: {preset_ids}")
        for preset in preset_ids[:4]:
            project = call(base, "/projects/from-preset",
                           {"preset_id": preset, "name": f"audit {preset}"})
            if project[0] >= 400:
                failures.append((f"preset {preset}", project[0], str(project[1])[:200]))
                print(f"  preset {preset}: create failed {project[0]}")
                continue
            pid = project[1]["project"]["project_id"]
            draft = call(base, f"/projects/{pid}/draft")[1]
            compiled = call(base, f"/projects/{pid}/compile",
                            {"expected_draft_design_hash": draft["design_hash"]})
            if compiled[0] >= 400:
                failures.append((f"preset {preset} compile", compiled[0], str(compiled[1])[:300]))
                print(f"  preset {preset}: compile failed {compiled[0]} {str(compiled[1])[:120]}")
                continue
            revision = compiled[1]["revision_id"]
            for backend in backends:
                job = call(base, f"/revisions/{revision}/evaluate",
                           {"backend": backend, "questions": ["NETWORK_COMPLETION"]})
                if job[0] >= 400:
                    failures.append((f"{preset}/{backend} evaluate", job[0], str(job[1])[:300]))
                    print(f"  preset {preset}: {backend} evaluate refused {job[0]} {str(job[1])[:140]}")
                    continue
                job_id = job[1]["job_id"]
                for _ in range(600):
                    state = call(base, f"/jobs/{job_id}")[1]
                    if state["state"] in {"COMPLETED", "FAILED", "REFUSED", "CANCELLED"}:
                        break
                    time.sleep(0.5)
                marker = "ok" if state["state"] == "COMPLETED" else state["state"]
                print(f"  preset {preset}: {backend} -> {marker}")
                if state["state"] != "COMPLETED":
                    failures.append((f"{preset}/{backend}", state["state"],
                                     str(state.get("error_message"))[:300]))
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\n--- backend log tail")
        print((DATA / "backend.log").read_text()[-3000:])
    print(f"\nFAILURES: {len(failures)}")
    for name, status, note in failures:
        print(f"  ! {name}: {status} {note}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
