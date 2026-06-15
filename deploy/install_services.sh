#!/usr/bin/env bash
# Install + start the systemd services (run once, after setup.sh + .env).
set -euo pipefail
cd "$HOME/diigoo"

echo "==> Installing systemd units..."
sudo cp deploy/diigoo-worker.service /etc/systemd/system/
sudo cp deploy/diigoo-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable diigoo-worker diigoo-api
sudo systemctl restart diigoo-worker diigoo-api

sleep 4
echo "==> Status:"
systemctl --no-pager --lines=3 status diigoo-worker || true
systemctl --no-pager --lines=3 status diigoo-api || true
echo ""
echo "Logs: journalctl -u diigoo-worker -f   (or tail worker.err.log)"
echo "Look for: 'registered worker' = healthy."
