#!/usr/bin/env bash
# Smart full-stack deploy (run on the EC2 box, or by CI/CD over SSH).
# Pulls latest, then ONLY rebuilds/restarts the parts that changed:
#   requirements.txt -> pip install
#   src/ change       -> restart worker + api
#   dashboard/ change -> npm install + build + restart dashboard
set -euo pipefail
cd "$HOME/diigoo"

BEFORE=$(git rev-parse HEAD 2>/dev/null || echo none)
git pull --ff-only
AFTER=$(git rev-parse HEAD)
if [ "$BEFORE" = "$AFTER" ]; then echo "Already up to date — nothing to deploy."; exit 0; fi
CHANGED=$(git diff --name-only "$BEFORE" "$AFTER")
echo "Changed files:"; echo "$CHANGED" | sed 's/^/  /'

if echo "$CHANGED" | grep -q '^requirements.txt'; then
  echo "==> deps changed -> pip install"
  .venv/bin/pip install -r requirements.txt -q
fi

if echo "$CHANGED" | grep -qE '^src/|^conftest|^requirements.txt'; then
  echo "==> backend changed -> restart worker + api (in-flight calls drop)"
  sudo systemctl restart diigoo-worker diigoo-api
fi

if echo "$CHANGED" | grep -q '^dashboard/'; then
  echo "==> dashboard changed -> npm install + build + restart"
  cd dashboard && npm install && npm run build && cd ..
  sudo systemctl restart diigoo-dashboard
fi

sleep 4
echo "==> deploy done. service states:"
systemctl is-active diigoo-worker diigoo-api diigoo-dashboard redis-server | tr '\n' ' '; echo
grep -a 'registered worker' "$HOME/diigoo/worker.err.log" 2>/dev/null | tail -1 || true
