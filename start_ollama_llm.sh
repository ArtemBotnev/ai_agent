#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${AGENT_CONFIG_FILE:-agent_config/llm.yaml}"

yaml_value() {
  python3 - "${CONFIG_FILE}" "$1" <<'PY'
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(0)

config_file = Path(sys.argv[1])
if not config_file.exists():
    sys.exit(0)

try:
    data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
except Exception:
    sys.exit(0)

value = data
for part in sys.argv[2].split("."):
    if not isinstance(value, dict) or part not in value:
        sys.exit(0)
    value = value[part]

if isinstance(value, list):
    print(",".join(str(item).strip() for item in value if str(item).strip()))
elif value is not None:
    print(str(value).strip())
PY
}

CONFIG_MODEL="$(yaml_value ollama.model)"
CONFIG_MODELS="$(yaml_value ollama.models)"
CONFIG_BASE_URL="$(yaml_value ollama.base_url)"

MODEL="${AGENT_OLLAMA_MODEL:-${OLLAMA_LLM_MODEL:-${CONFIG_MODEL:-llama3.1:8b}}}"
if [[ -n "${AGENT_OLLAMA_URL:-}" ]]; then
  BASE_URL="${AGENT_OLLAMA_URL}"
elif [[ -n "${OLLAMA_HOST:-}" ]]; then
  BASE_URL="http://${OLLAMA_HOST}"
else
  BASE_URL="${CONFIG_BASE_URL:-http://127.0.0.1:11434}"
fi
BASE_URL="${BASE_URL%/}"
HOST="${BASE_URL#http://}"
HOST="${HOST#https://}"
export OLLAMA_HOST="${HOST}"
export AGENT_LLM_PROVIDER="ollama"
export AGENT_CONFIG_FILE="${CONFIG_FILE}"
export AGENT_OLLAMA_URL="${BASE_URL}"
export AGENT_OLLAMA_MODEL="${MODEL}"
export AGENT_OLLAMA_MODELS="${AGENT_OLLAMA_MODELS:-${CONFIG_MODELS:-${MODEL}}}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Error: ollama command not found."
  echo
  echo "Install Ollama system-wide on Linux:"
  echo "curl -fsSL https://ollama.com/install.sh | sh"
  echo
  echo "Then restart the terminal or make sure ollama is available in PATH."
  exit 1
fi

echo "Using agent config: ${CONFIG_FILE}"
echo "Using Ollama LLM model: ${MODEL}"

if curl -fsS "${BASE_URL}/api/tags" >/dev/null 2>&1; then
  echo "Ollama is already running at ${BASE_URL}"
else
  echo "Starting Ollama server at ${BASE_URL}..."
  ollama serve &
  OLLAMA_PID=$!

  for _ in $(seq 1 30); do
    if curl -fsS "${BASE_URL}/api/tags" >/dev/null 2>&1; then
      echo "Ollama server is ready"
      break
    fi
    sleep 1
  done

  if ! curl -fsS "${BASE_URL}/api/tags" >/dev/null 2>&1; then
    echo "Error: Ollama server did not become ready in time"
    kill "${OLLAMA_PID}" >/dev/null 2>&1 || true
    exit 1
  fi
fi

if ollama list | awk '{print $1}' | grep -Fxq "${MODEL}"; then
  echo "Model is already available: ${MODEL}"
else
  echo "Pulling model: ${MODEL}"
  ollama pull "${MODEL}"
fi

echo
echo "Ollama LLM model is ready. Use these env values for this project:"
echo "export AGENT_CONFIG_FILE=${CONFIG_FILE}"
echo "export AGENT_LLM_PROVIDER=ollama"
echo "export AGENT_OLLAMA_URL=${BASE_URL}"
echo "export AGENT_OLLAMA_MODEL=${MODEL}"
echo "export AGENT_OLLAMA_MODELS=${AGENT_OLLAMA_MODELS}"
echo
echo "Ollama runtime options are configured in ${CONFIG_FILE} under ollama.options."

if [[ -n "${OLLAMA_PID:-}" ]]; then
  echo
  echo "Keeping Ollama server attached to this terminal. Press Ctrl+C to stop it."
  wait "${OLLAMA_PID}"
fi
