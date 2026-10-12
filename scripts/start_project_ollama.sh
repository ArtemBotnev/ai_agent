#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIG_VALUES="$(
python - <<'PY'
from config.project_assistant_config import load_project_assistant_config

config = load_project_assistant_config()
embedding = config.embedding
print(embedding.base_url)
print(embedding.model)
PY
)"

OLLAMA_BASE_URL="$(printf '%s\n' "$CONFIG_VALUES" | sed -n '1p')"
OLLAMA_MODEL="$(printf '%s\n' "$CONFIG_VALUES" | sed -n '2p')"
OLLAMA_HOST_VALUE="${OLLAMA_BASE_URL#http://}"
OLLAMA_HOST_VALUE="${OLLAMA_HOST_VALUE#https://}"
OLLAMA_HOST_VALUE="${OLLAMA_HOST_VALUE%/}"
OLLAMA_LOG="${OLLAMA_LOG:-/tmp/ai_second_ollama.log}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Команда ollama не найдена в PATH."
  echo "Установите Ollama и повторите запуск."
  exit 1
fi

is_ready() {
  python - "$OLLAMA_BASE_URL" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen

base_url = sys.argv[1].rstrip("/")
with urlopen(f"{base_url}/api/tags", timeout=2) as response:
    raise SystemExit(0 if 200 <= response.status < 300 else 1)
PY
}

echo "Ollama URL: $OLLAMA_BASE_URL"
echo "Embedding model: $OLLAMA_MODEL"

if is_ready; then
  echo "Ollama уже запущена."
else
  echo "Запускаю Ollama в фоне. Лог: $OLLAMA_LOG"
  OLLAMA_HOST="$OLLAMA_HOST_VALUE" nohup ollama serve >"$OLLAMA_LOG" 2>&1 &

  for _ in $(seq 1 30); do
    if is_ready; then
      echo "Ollama готова."
      break
    fi
    sleep 1
  done

  if ! is_ready; then
    echo "Ollama не ответила за 30 секунд. Проверьте лог: $OLLAMA_LOG"
    exit 1
  fi
fi

echo "Проверяю embedding-модель..."
ollama pull "$OLLAMA_MODEL"
echo "Готово. Теперь можно выполнить /project-rag build."
