#!/usr/bin/env bash
# First-time EC2 provisioning for the diigoo voice worker.
# Target: Ubuntu 24.04 LTS (Python 3.12) on an ap-south-1 (Mumbai) instance.
# Run as the 'ubuntu' user from the home dir. Idempotent-ish.
set -euo pipefail

echo "==> Installing system packages..."
sudo apt-get update -y
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  redis-server \
  ffmpeg \
  git build-essential

echo "==> Enabling Redis..."
sudo systemctl enable --now redis-server

cd "$HOME/diigoo"

echo "==> Creating virtualenv + installing deps (this takes a few minutes)..."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt

echo ""
echo "==> Code + deps ready."
echo "    NEXT:"
echo "    1) Copy your .env to $HOME/diigoo/.env   (scp from your laptop)"
echo "    2) Install services:  bash deploy/install_services.sh"
echo "    3) Check:  systemctl status diigoo-worker"
