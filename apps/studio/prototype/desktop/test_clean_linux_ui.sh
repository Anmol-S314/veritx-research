#!/usr/bin/env bash
# Minimal offline native-window launch proof, not full UI workflow acceptance.
# Run test_clean_linux.sh first to create the installed-app image.
set -euo pipefail
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cat > "$work/Containerfile" <<'EOF'
FROM localhost/srota-clean-ubuntu:acceptance
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends xvfb xauth xdotool dbus-x11 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home studio
USER studio
ENV HOME=/home/studio LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1
COPY launch.sh /tmp/launch.sh
CMD ["dbus-run-session", "--", "xvfb-run", "-a", "bash", "/tmp/launch.sh"]
EOF
cat > "$work/launch.sh" <<'EOF'
set -euo pipefail
if command -v python3 || command -v node; then exit 1; fi
cd /tmp
/usr/bin/srota-studio > /tmp/studio.log 2>&1 &
app=$!
trap 'kill "$app" 2>/dev/null || true; wait "$app" 2>/dev/null || true; cat /tmp/studio.log' EXIT
window=
for ((i=0; i<60; i++)); do
    kill -0 "$app"
    window=$(xdotool search --onlyvisible --name 'Srota Studio' 2>/dev/null | head -n 1 || true)
    if [[ -n $window ]]; then break; fi
    sleep 1
done
[[ -n $window ]] || { echo 'FAIL: no visible native window'; exit 1; }
xdotool getwindowname "$window"
# A live window alone is insufficient if gateway startup failed.
sleep 5
kill -0 "$app"
log="$HOME/.local/share/com.srota.studio/backend.log"
[[ -f $log ]] || { echo 'FAIL: no owned gateway log'; exit 1; }
if grep -Ei 'Traceback|panic|error while loading shared libraries' "$log" /tmp/studio.log; then
    echo 'FAIL: startup error in logs'; tail -n 100 "$log"; exit 1
fi
echo 'PASS: offline non-root native window launch; full UI workflow not tested'
EOF
podman build -t localhost/srota-clean-ui:acceptance "$work"
podman run --rm --network=none --shm-size=256m localhost/srota-clean-ui:acceptance
