#!/usr/bin/env bash
# push-kaggle-runner.sh — заливает colab/kaggle-runner/ в Kaggle с
# подстановкой секретов из env vars. НИЧЕГО не пишет в git.
#
# Требует:
#   KAE_MANAGER_URL   — публичный URL Manager'а
#   KAE_RUNNER_TOKEN  — Bearer-токен Manager↔Runner
# Опционально:
#   KAE_KAGGLE_CLI    — путь к kaggle CLI (по умолчанию — одноразовый
#                       venv в scratchpad)
#
# Использование:
#   KAE_MANAGER_URL=https://... KAE_RUNNER_TOKEN=xxx \
#     bin/push-kaggle-runner.sh
#
# Скрипт не сохраняет модифицированный ноутбук — только заливает
# в приватный Kaggle kernel (id из colab/kaggle-runner/kernel-metadata.json).

set -euo pipefail

: "${KAE_MANAGER_URL:?set KAE_MANAGER_URL}"
: "${KAE_RUNNER_TOKEN:?set KAE_RUNNER_TOKEN}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_ROOT/colab/kaggle-runner"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -R "$SRC_DIR"/. "$STAGE"/

# sed-подстановка placeholder'ов только в notebook — kernel-metadata.json
# трогать не нужно (id/title там уже финальные).
python3 - "$STAGE/runner.ipynb" "$KAE_MANAGER_URL" "$KAE_RUNNER_TOKEN" <<'PY'
import json, sys, pathlib
nb_path = pathlib.Path(sys.argv[1])
url, token = sys.argv[2], sys.argv[3]
data = json.loads(nb_path.read_text())
for cell in data.get("cells", []):
    src = cell.get("source")
    if isinstance(src, list):
        cell["source"] = [
            s.replace("__KAE_MANAGER_URL__", url)
             .replace("__KAE_RUNNER_TOKEN__", token)
            for s in src
        ]
    elif isinstance(src, str):
        cell["source"] = (
            src.replace("__KAE_MANAGER_URL__", url)
               .replace("__KAE_RUNNER_TOKEN__", token)
        )
nb_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
PY

# Kaggle CLI — из env или одноразовый venv в scratchpad (правило
# feedback_no_local_install: ничего не ставим в проект).
if [ -n "${KAE_KAGGLE_CLI:-}" ]; then
  KAG="$KAE_KAGGLE_CLI"
else
  VENV="$REPO_ROOT/.scratchpad/kag-venv"
  if [ ! -x "$VENV/bin/kaggle" ]; then
    mkdir -p "$(dirname "$VENV")"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --disable-pip-version-check kaggle
  fi
  KAG="$VENV/bin/kaggle"
fi

echo "→ kaggle kernels push $STAGE"
"$KAG" kernels push -p "$STAGE"
