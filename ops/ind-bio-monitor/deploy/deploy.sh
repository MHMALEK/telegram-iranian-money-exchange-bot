#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-ubuntu@134.98.131.207}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/gha_exchange_money_bot}"
SSH_OPTS=(-o ConnectTimeout=30 -o IdentitiesOnly=yes -i "$SSH_KEY")
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Deploying to $HOST with key $(basename "$SSH_KEY") ..."
rsync -az --delete \
  -e "ssh ${SSH_OPTS[*]}" \
  --exclude '.venv/' \
  --exclude 'logs/' \
  --exclude '.env' \
  --exclude '__pycache__/' \
  "$ROOT/" "$HOST:~/ind-bio-monitor/"

scp "${SSH_OPTS[@]}" "$ROOT/.env" "$HOST:~/ind-bio-monitor/.env"

ssh "${SSH_OPTS[@]}" "$HOST" bash -s <<'REMOTE'
set -euo pipefail
cd ~/ind-bio-monitor
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
mkdir -p logs state
sudo cp deploy/ind-bio-monitor.service /etc/systemd/system/ind-bio-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable ind-bio-monitor
sudo systemctl restart ind-bio-monitor
sleep 2
sudo systemctl status ind-bio-monitor --no-pager -l
echo "--- last log lines ---"
tail -n 8 logs/check.log 2>/dev/null || true
REMOTE

echo "Done."
