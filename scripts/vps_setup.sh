#!/bin/bash
# One-shot VPS setup script. Run once after cloning the repo.
# Usage: bash scripts/vps_setup.sh
set -euo pipefail

echo "=== PepperBot VPS Setup ==="

# 1. Install Docker if missing
if ! command -v docker &>/dev/null; then
    echo "[1/5] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker "$USER"
    echo "Docker installed. You may need to log out and back in."
else
    echo "[1/5] Docker already installed: $(docker --version)"
fi

# 2. Install Docker Compose plugin if missing
if ! docker compose version &>/dev/null 2>&1; then
    echo "[2/5] Installing Docker Compose plugin..."
    apt-get install -y docker-compose-plugin
else
    echo "[2/5] Docker Compose already available"
fi

# 3. Create required dirs + placeholder secrets
echo "[3/5] Creating data/logs/secrets dirs..."
mkdir -p secrets data logs tmp_images

if [ ! -f secrets/secrets.env ]; then
    echo "MOONSHOT_API_KEY=sk-your-key-here" > secrets/secrets.env
    echo "  Created secrets/secrets.env — fill in your MOONSHOT_API_KEY"
fi

if [ ! -f secrets/twitter_cookies.json ]; then
    echo "  WARNING: secrets/twitter_cookies.json missing — copy from Mac before starting"
fi

# 4. Build image
echo "[4/5] Building Docker image..."
docker compose build

# 5. Done
echo "[5/5] Setup complete."
echo ""
echo "Next steps:"
echo "  1. Copy twitter_cookies.json to secrets/"
echo "  2. Fill in secrets/secrets.env with real MOONSHOT_API_KEY"
echo "  3. docker compose up -d"
echo "  4. docker compose logs -f  # watch first run"
