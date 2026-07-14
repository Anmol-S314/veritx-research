#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# VeritX Self-Hosted GitLab Runner Setup (Ubuntu 22.04 / Docker executor)
# ---------------------------------------------------------------------------
set -euo pipefail

GITLAB_URL="${GITLAB_URL:-https://internal-devrepo.datavex.ai}"
REGISTRATION_TOKEN="${REGISTRATION_TOKEN:?Must set GITLAB_RUNNER_TOKEN}"
RUNNER_NAME="${RUNNER_NAME:-veritx-runner}"
DOCKER_IMAGE="${DOCKER_IMAGE:-internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest}"

echo "[1/5] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | bash
    sudo usermod -aG docker "$USER"
    echo "  → Docker installed. You may need to log out/in for group changes."
fi

echo "[2/5] Installing GitLab Runner..."
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt-get install -y gitlab-runner

echo "[3/5] Registering runner (Docker executor)..."
sudo gitlab-runner register \
    --non-interactive \
    --url "${GITLAB_URL}" \
    --registration-token "${REGISTRATION_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --executor docker \
    --docker-image "${DOCKER_IMAGE}" \
    --docker-volumes /var/run/docker.sock:/var/run/docker.sock \
    --tag-list "veritx-runner,docker" \
    --run-untagged="false" \
    --locked="false"

echo "[4/5] Configuring concurrent jobs..."
sudo sed -i 's/^concurrent = .*/concurrent = 5/' /etc/gitlab-runner/config.toml
sudo gitlab-runner restart

echo "[5/5] Verifying runner status..."
sudo gitlab-runner status

echo ""
echo "✅ GitLab runner setup complete!"
echo "   Check it at: ${GITLAB_URL}/admin/runners"
echo ""
echo "Next steps:"
echo "  1. Build and push the Docker image:"
echo "     make docker-build && make docker-push"
echo "  2. Push the monorepo to GitLab:"
echo "     git remote add origin ${GITLAB_URL}/anmol/veritx-research.git"
echo "     git push -u origin main"
