#!/usr/bin/env bash
set -euo pipefail

WEB_HOST_VALUE="${WEB_HOST:-127.0.0.1}"
WEB_PORT_VALUE="${WEB_PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_FILE="${APP_FILE:-app.py}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$PROJECT_DIR"

find_server_pid() {
  ss -ltnp "sport = :${WEB_PORT_VALUE}" 2>/dev/null     | sed -n 's/.*pid=\([0-9]\+\).*/\1/p'     | head -n 1
}

PID="$(find_server_pid || true)"

if [[ -n "$PID" ]]; then
  PROCESS_COMMAND="$(ps -p "$PID" -o args= || true)"

  if [[ "$PROCESS_COMMAND" != *"$APP_FILE"* ]]; then
    echo "Порт ${WEB_PORT_VALUE} занят другим процессом:"
    echo "$PROCESS_COMMAND"
    echo "Сервер не перезапущен. Укажите другой порт: WEB_PORT=8001 ./restart_server.sh"
    exit 1
  fi

  echo "Останавливаю web-сервер на ${WEB_HOST_VALUE}:${WEB_PORT_VALUE} (PID ${PID})..."
  kill "$PID"

  for _ in {1..25}; do
    if ! kill -0 "$PID" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done

  if kill -0 "$PID" 2>/dev/null; then
    echo "Процесс ${PID} не остановился вовремя. Остановите его вручную и повторите запуск."
    exit 1
  fi
else
  echo "Запущенный web-сервер на порту ${WEB_PORT_VALUE} не найден."
fi

echo "Запускаю web-интерфейс: http://${WEB_HOST_VALUE}:${WEB_PORT_VALUE}"
exec "$PYTHON_BIN" "$APP_FILE"
