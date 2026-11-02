#!/usr/bin/env python3
"""Preset x backend matrix for the packaged app.

Establishes, for a chosen set of fabric presets, whether create -> compile ->
evaluate works against every advertised backend. Run it against the source
gateway (expected behaviour) and the frozen bundle; any difference is a
packaging defect, and any failure at all is a user-visible defect.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Each certified backend answers only its own question set; asking the wrong one
# is a caller error, not a defect.
QUESTIONS = {
    "BOOKSIM_STANDALONE": ["NETWORK_COMPLETION"],
    "ASTRA2_EMBEDDED_BOOKSIM": ["SYSTEM_MAKESPAN"],
    "RAMULATOR2_HBM3_V1": ["DRAM_TIMING"],
}
PRESETS: list[str] = []  # filled from the catalog when --all is passed
DATA = Path("/tmp/matrix-data")


def start(command: list[str]):
    import shutil
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True)
    log = open(DATA / "backend.log", "w+")
    proc = subprocess.Popen([*command, "--data-dir", str(DATA / "data")], cwd=DATA,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=log, start_new_session=True)
    line = proc.stdout.readline().decode()
    if not line.startswith("SROTA_READY "):
        raise SystemExit(f"gateway did not start: {line!r}")
    return proc, json.loads(line[len("SROTA_READY "):])["base"]


def call(base, path, body=None, method=None, timeout=900):
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
            return exc.code, {"raw": raw[:300]}
    except Exception as exc:  # noqa: BLE001
        return 0, {"exception": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    command = [str(Path(part).resolve()) if Path(part).exists() else part
               for part in sys.argv[1:]]
    proc, base = start(command)
    failures = []
    try:
        status, health = call(base, "/health")
        backends = [n for n, i in (health.get("backends") or {}).items()
                    if i.get("binary_present")]
        print(f"backends: {backends}")
        presets = list(PRESETS)
        if not presets:
            catalog = call(base, "/catalog/fabric-presets")[1]
            items = catalog.get("presets") or catalog.get("items") or []
            presets = [p.get("preset_id") or p.get("id") for p in items]
        for preset in presets:
            created = call(base, "/projects/from-preset", {"preset_id": preset,
                                                           "name": f"m {preset}"})
            if created[0] >= 400:
                print(f"{preset:15s} create {created[0]} {str(created[1])[:120]}")
                failures.append((preset, "create", created[0], str(created[1])[:200]))
                continue
            pid = created[1]["project"]["project_id"]
            draft = call(base, f"/projects/{pid}/draft")[1]
            compiled = call(base, f"/projects/{pid}/compile",
                            {"expected_draft_design_hash": draft["design_hash"]})
            if compiled[0] >= 400:
                print(f"{preset:15s} compile {compiled[0]} {str(compiled[1])[:120]}")
                failures.append((preset, "compile", compiled[0], str(compiled[1])[:200]))
                continue
            revision = compiled[1]["revision_id"]
            for backend in backends:
                status, job = call(base, f"/revisions/{revision}/evaluate",
                                   {"backend": backend,
                                    "questions": QUESTIONS.get(backend, ["NETWORK_COMPLETION"])})
                if status >= 400:
                    print(f"{preset:15s} {backend:26s} refused {status} {str(job)[:110]}")
                    failures.append((preset, backend, status, str(job)[:200]))
                    continue
                for _ in range(1200):
                    state = call(base, f"/jobs/{job['job_id']}")[1]
                    if state["state"] in {"COMPLETED", "FAILED", "REFUSED", "CANCELLED"}:
                        break
                    time.sleep(0.5)
                ok = state["state"] == "COMPLETED"
                print(f"{preset:15s} {backend:26s} {state['state']}")
                if not ok:
                    failures.append((preset, backend, state["state"],
                                     str(state.get("error_message"))[:400]))
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        tail = (DATA / "backend.log").read_text()
        if "Traceback" in tail or "Error" in tail:
            print("--- log tail\n" + tail[-2500:])
    print(f"\nFAILURES: {len(failures)}")
    for preset, what, status, note in failures:
        print(f"  ! {preset}/{what}: {status} {note}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
