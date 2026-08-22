#!/usr/bin/env bash
# poll-kaggle-runner.sh — опрашивает статус kernel'а до тех пор, пока
# он не перейдёт в RUNNING (или complete/error). Возвращает 0 при
# успехе, 1 при ошибке, 2 при timeout.
#
# Использование:
#   bin/poll-kaggle-runner.sh                       # ждать до 15 мин
#   TIMEOUT_SEC=600 bin/poll-kaggle-runner.sh       # ждать 10 мин
#   INTERVAL=15 bin/poll-kaggle-runner.sh           # опрос каждые 15 с

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KERNEL_ID="$(python3 -c "import json; print(json.load(open('$REPO_ROOT/colab/kaggle-runner/kernel-metadata.json'))['id'])")"
TIMEOUT_SEC="${TIMEOUT_SEC:-900}"
INTERVAL="${INTERVAL:-20}"

if [ -n "${KAE_KAGGLE_CLI:-}" ]; then
  KAG="$KAE_KAGGLE_CLI"
else
  KAG="$REPO_ROOT/.scratchpad/kag-venv/bin/kaggle"
fi

DEADLINE=$(( $(date +%s) + TIMEOUT_SEC ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  status_line="$("$KAG" kernels status "$KERNEL_ID" 2>&1 || true)"
  echo "$(date -u +%H:%M:%S) $status_line"
  case "$status_line" in
    *RUNNING*) exit 0 ;;
    *COMPLETE*) exit 0 ;;
    *ERROR*|*CANCEL*) exit 1 ;;
  esac
  sleep "$INTERVAL"
done
echo "timeout waiting for $KERNEL_ID"
exit 2
