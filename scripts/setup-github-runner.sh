#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# VeritX Self-Hosted GitHub Actions Runner Setup (Ubuntu 22.04)
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="${REPO:-Anmol-S314/veritx-research}"
GITHUB_URL="${GITHUB_URL:-https://github.com/Anmol-S314/veritx-research}"
RUNNER_TOKEN="${RUNNER_TOKEN:?Must set RUNNER_TOKEN — generate at: $GITHUB_URL/settings/actions/runners/new}"
RUNNER_NAME="${RUNNER_NAME:-veritx-runner-1}"
RUNNER_LABELS="${RUNNER_LABELS:-veritx-runner,docker}"

echo "[1/5] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | bash
    sudo usermod -aG docker "$USER"
    echo "  → Docker installed. Log out/in for group changes."
fi

echo "[2/5] Creating runner user..."
sudo id -u actions 2>/dev/null || sudo useradd -m -s /bin/bash actions
sudo usermod -aG docker actions

echo "[3/5] Downloading and configuring GitHub Actions runner..."
cd /opt
sudo rm -rf actions-runner
sudo mkdir actions-runner
sudo chown actions:actions actions-runner
cd actions-runner
sudo -u actions bash -c "
    curl -o actions-runner-linux-x64.tar.gz -L https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64-2.320.0.tar.gz
    tar xzf actions-runner-linux-x64.tar.gz
    ./config.sh --url https://github.com/${REPO} --token ${RUNNER_TOKEN} --name ${RUNNER_NAME} --labels ${RUNNER_LABELS} --unattended
"

echo "[4/5] Installing runner as service..."
sudo ./svc.sh install
sudo ./svc.sh start

echo "[5/5] Verifying runner status..."
sudo ./svc.sh status

echo ""
echo "✅ GitHub Actions runner setup complete!"
echo "   Check it at: https://github.com/${REPO}/settings/actions/runners"
echo ""
echo "Next step:"
echo "  1. Build and push the Docker image (via GitHub Actions manually):"
echo "     gh workflow run rebuild-docker"
echo "     OR trigger from the GitHub web UI → Actions → Rebuild Docker Image"
