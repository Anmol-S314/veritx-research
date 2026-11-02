#!/usr/bin/env bash
# Host Python drives HTTP tests; the installed app container has no Python/Node
# installation and receives no repository mount. Not a full desktop UI test.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
prototype=$(dirname "$here")
bundle="$prototype/src-tauri/target/release/bundle/deb"
image=localhost/srota-clean-ubuntu:acceptance
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp "$bundle/Srota Studio_0.1.0_amd64.deb" "$work/app.deb"
cat > "$work/Containerfile" <<'EOF'
FROM docker.io/library/ubuntu:24.04
COPY app.deb /tmp/app.deb
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends /tmp/app.deb && rm /tmp/app.deb && rm -rf /var/lib/apt/lists/*
RUN if command -v python3 || command -v node; then echo 'Unexpected external runtime'; exit 1; fi
EOF
podman build -t "$image" "$work"
# The shell launches the gateway from the bundled resource tree
# (`ResourceDir/gateway/srota-gateway`), so the gate must exercise that exact
# installed path rather than a legacy /usr/bin entry point.
gateway_path=$(podman run --rm localhost/srota-clean-ubuntu:acceptance \
    bash -c "dpkg -L srota-studio | grep -m1 '/gateway/srota-gateway$'")
test -n "$gateway_path"
cat > "$work/gateway" <<EOF
#!/usr/bin/env bash
set -euo pipefail
mount=()
if [[ \${1:-} == --data-dir ]]; then
    mkdir -p "\$2"
    mount=(-v "\$2:\$2")
fi
exec podman run --rm -i --network=host "\${mount[@]}" localhost/srota-clean-ubuntu:acceptance "$gateway_path" "\$@"
EOF
chmod +x "$work/gateway"
SROTA_SIDECAR="$work/gateway" python3 "$here/test_gateway.py"
