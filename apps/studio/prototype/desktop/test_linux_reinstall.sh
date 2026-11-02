#!/usr/bin/env bash
# Install -> real workflow -> uninstall -> reinstall in ONE machine (container),
# proving binaries are removed while per-user data survives.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
prototype=$(dirname "$here")
bundle="$prototype/src-tauri/target/release/bundle/deb"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp "$bundle/Srota Studio_0.1.0_amd64.deb" "$work/app.deb"
cat > "$work/probe.sh" <<'EOF'
set -euo pipefail
export HOME=/home/studio XDG_DATA_HOME=/home/studio/.local/share
# The sidecar exits when its stdin closes; keep a parent pipe open.
# Filter from a file: `dpkg -L ... | grep -m1` makes dpkg take SIGPIPE, and
# under `set -o pipefail` that aborts the probe before the gateway starts.
dpkg -L srota-studio > /tmp/studio-files.txt
gateway=$(grep -m1 '/gateway/srota-gateway$' /tmp/studio-files.txt)
# The sidecar exits when its stdin closes, so hold stdin open with a FIFO
# writer. A plain `producer | gateway` pipeline trips `pipefail` on SIGPIPE
# when the gateway is stopped.
# A backgrounded pipeline does not decide this shell's status, and the
# teardown tolerates the producer's SIGPIPE.
tail -f /dev/null | "$gateway" --data-dir "$XDG_DATA_HOME/com.srota.studio" > /tmp/gw.out 2>/tmp/gw.err &
gw=$!
trap 'kill "$gw" 2>/dev/null || true; pkill -f "tail -f /dev/null" 2>/dev/null || true' EXIT
for _ in $(seq 1 120); do
    grep -q SROTA_READY /tmp/gw.out 2>/dev/null && break
    kill -0 $gw
    sleep 0.5
done
python3 - "/tmp/gw.out" "$1" <<'PY'
import json, sys, time, urllib.error, urllib.request
line = next(l for l in open(sys.argv[1]) if l.startswith("SROTA_READY "))
base = json.loads(line.split(" ", 1)[1])["base"]
mode = sys.argv[2]
def call(path, body=None):
    request = urllib.request.Request(base + "/api/v1" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)
if mode == "first":
    project = call("/projects/from-preset", {"preset_id": "torus25", "name": "Reinstall probe"})
    pid = project["project"]["project_id"]
    draft = call(f"/projects/{pid}/draft")
    compiled = call(f"/projects/{pid}/compile", {"expected_draft_design_hash": draft["design_hash"]})
    job = call(f"/revisions/{compiled['revision_id']}/evaluate",
               {"backend": "BOOKSIM_STANDALONE", "questions": ["NETWORK_COMPLETION"]})
    while True:
        job = call(f"/jobs/{job['job_id']}")
        if job["state"] == "COMPLETED":
            break
        if job["state"] in {"FAILED", "REFUSED", "CANCELLED"}:
            raise SystemExit(f"evaluation {job['state']}: {job.get('error_message')}")
        time.sleep(0.5)
    print("PASS: first install completed create -> compile -> evaluate")
else:
    projects = call("/projects")["projects"]
    runs = call("/runs")["runs"]
    name = projects[0]["project"]["name"] if projects else None
    assert name == "Reinstall probe", projects
    assert runs, "no runs survived reinstall"
    print(f"PASS: reinstall preserved project {name!r} and {len(runs)} run(s), "
          f"status={runs[0]['status']}")
PY
EOF
cat > "$work/Containerfile" <<'EOF'
FROM docker.io/library/ubuntu:24.04
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY app.deb /tmp/app.deb
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends /tmp/app.deb \
    && cp /tmp/app.deb /opt/app.deb && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home studio
COPY probe.sh /opt/probe.sh
CMD ["bash", "-euc", "su studio -c 'bash /opt/probe.sh first' && dpkg --remove srota-studio && ! test -e /usr/bin/srota-studio && ! test -e /usr/bin/srota-gateway && echo 'PASS: uninstall removed application binaries' && apt-get install -y --no-install-recommends /opt/app.deb >/dev/null && rm -rf /var/lib/apt/lists/* && su studio -c 'bash /opt/probe.sh second'"]
EOF
podman build -t localhost/srota-reinstall:acceptance "$work"
podman run --rm localhost/srota-reinstall:acceptance
podman image rm -f localhost/srota-reinstall:acceptance >/dev/null 2>&1 || true
