import errno
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from application.chat.agent_error import AgentError, AgentErrorCode
from main import (
    AGENT_ERROR_MESSAGES,
    build_chat_service,
    build_history_repository,
    format_agent_error,
    get_available_model_names,
    get_model_name,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
WEB_HOST_ENV = "WEB_HOST"
WEB_PORT_ENV = "WEB_PORT"
WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
INDEX_FILE = WEB_DIR / "index.html"


class WebChatHandler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        self._handle_get_request(include_body=False)

    def do_GET(self) -> None:
        self._handle_get_request(include_body=True)

    def _handle_get_request(self, *, include_body: bool) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_file(INDEX_FILE, "text/html; charset=utf-8", include_body=include_body)
            return

        if path == "/api/config":
            self._send_json(
                {
                    "model": get_model_name(),
                    "models": get_available_model_names(),
                },
                HTTPStatus.OK,
                include_body=include_body,
            )
            return

        if path == "/api/messages":
            self._handle_messages_request(include_body=include_body)
            return

        if path.startswith("/static/"):
            self._send_static_file(path, include_body=include_body)
            return

        self._send_json({"error": "Страница не найдена."}, HTTPStatus.NOT_FOUND, include_body=include_body)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/chat":
            self._send_json({"error": "Endpoint не найден."}, HTTPStatus.NOT_FOUND)
            return

        payload = self._read_json_body()
        if payload is None:
            self._send_json({"error": "Некорректный JSON в запросе."}, HTTPStatus.BAD_REQUEST)
            return

        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            self._send_json(
                {"error": AGENT_ERROR_MESSAGES[AgentErrorCode.EMPTY_MESSAGE]},
                HTTPStatus.BAD_REQUEST,
            )
            return

        model_name = payload.get("model")
        try:
            selected_model_name = get_model_name(model_name if isinstance(model_name, str) else None)
        except RuntimeError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        try:
            chat_service = build_chat_service(model_name=selected_model_name)
            response = chat_service.answer(message)
        except RuntimeError as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        except AgentError as error:
            self._send_json({"error": format_agent_error(error)}, HTTPStatus.BAD_GATEWAY)
            return

        self._send_json(
            {
                "answer": response.text,
                "model": selected_model_name,
                "tokens": {
                    "current_request": response.tokens.current_request,
                    "history": response.tokens.history,
                    "response": response.tokens.response,
                },
                "duration_seconds": response.duration_seconds,
            },
            HTTPStatus.OK,
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle_messages_request(self, *, include_body: bool) -> None:
        history_repository = build_history_repository()
        messages = [message.to_dict() for message in history_repository.load()]
        self._send_json({"messages": messages}, HTTPStatus.OK, include_body=include_body)

    def _read_json_body(self) -> dict[str, Any] | None:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            return None

        try:
            raw_body = self.rfile.read(int(content_length)).decode("utf-8")
            payload = json.loads(raw_body)
        except (ValueError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        return payload

    def _send_static_file(self, request_path: str, *, include_body: bool = True) -> None:
        relative_path = unquote(request_path.removeprefix("/static/")).lstrip("/")
        file_path = (STATIC_DIR / relative_path).resolve()

        if not file_path.is_file() or not file_path.is_relative_to(STATIC_DIR):
            self._send_json({"error": "Файл не найден."}, HTTPStatus.NOT_FOUND, include_body=include_body)
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self._send_file(file_path, content_type, include_body=include_body)

    def _send_file(self, file_path: Path, content_type: str, *, include_body: bool = True) -> None:
        try:
            body = file_path.read_bytes()
        except OSError:
            self._send_json({"error": "Не удалось прочитать файл."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus,
        *,
        include_body: bool = True,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

def get_server_address() -> tuple[str, int]:
    host = os.getenv(WEB_HOST_ENV, DEFAULT_HOST)
    port_value = os.getenv(WEB_PORT_ENV, str(DEFAULT_PORT))

    try:
        port = int(port_value)
    except ValueError as error:
        raise RuntimeError(f"Переменная {WEB_PORT_ENV} должна быть числом.") from error

    return host, port


def run_server() -> None:
    try:
        host, port = get_server_address()
    except RuntimeError as error:
        print(f"Ошибка конфигурации web-сервера: {error}")
        return

    try:
        server = ThreadingHTTPServer((host, port), WebChatHandler)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(f"Порт {port} уже занят.")
            print(f"Запустите сервер на другом порту: {WEB_PORT_ENV}=8001 python3 app.py")
            return
        raise

    print(f"Web-интерфейс запущен: http://{host}:{port}")
    print("Для остановки нажмите Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb-интерфейс остановлен.")
    finally:
        server.server_close()
