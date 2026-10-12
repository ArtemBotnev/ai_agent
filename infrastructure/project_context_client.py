import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ProjectContext:
    project_path: Path
    git_branch: str


class LocalProjectContextClient:
    """Read-only project context adapter. Replace this with an MCP client later."""

    def get_context(self, project_path: Path) -> ProjectContext:
        return ProjectContext(
            project_path=project_path,
            git_branch=self.get_git_branch(project_path),
        )

    def get_git_branch(self, project_path: Path) -> str:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=project_path,
            check=False,
            capture_output=True,
            text=True,
        )
        branch = result.stdout.strip()
        if branch:
            return branch

        fallback = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_path,
            check=False,
            capture_output=True,
            text=True,
        )
        return fallback.stdout.strip() or "unknown"


class McpProjectContextClient:
    def __init__(self, server_url: str, timeout_seconds: int = 10) -> None:
        self._server_url = normalize_mcp_url(server_url)
        self._timeout_seconds = timeout_seconds
        self._session_id: str | None = None
        self._next_request_id = 1

    def get_context(self, project_path: Path) -> ProjectContext:
        return ProjectContext(
            project_path=project_path,
            git_branch=self.get_git_branch(project_path),
        )

    def get_git_branch(self, project_path: Path) -> str:
        result = self._call_tool(
            "get_git_branch",
            {"project_path": str(project_path)},
        )
        branch = result.get("branch")
        if isinstance(branch, str) and branch.strip():
            return branch.strip()
        raise RuntimeError(f"MCP get_git_branch returned no branch: {result}")

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        response = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments,
                },
            },
            include_session=True,
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"MCP tool {name} returned an invalid response: {response}")
        if result.get("isError") is True:
            raise RuntimeError(f"MCP tool {name} failed: {result}")

        structured_content = result.get("structuredContent")
        if isinstance(structured_content, dict):
            return structured_content

        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    try:
                        parsed = json.loads(item["text"])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed

        raise RuntimeError(f"MCP tool {name} returned no structured content: {result}")

    def _ensure_initialized(self) -> None:
        if self._session_id is not None:
            return

        response = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "ai-second",
                        "version": "0.1.0",
                    },
                },
            },
            include_session=False,
        )
        if "result" not in response:
            raise RuntimeError(f"MCP initialize failed: {response}")
        self._post_json(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            include_session=True,
            allow_empty_response=True,
        )

    def _post_json(
        self,
        payload: dict[str, Any],
        *,
        include_session: bool,
        allow_empty_response: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if include_session:
            if self._session_id is None:
                raise RuntimeError("MCP session is not initialized.")
            headers["mcp-session-id"] = self._session_id

        request = Request(
            self._server_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
                session_id = response.headers.get("mcp-session-id")
                if session_id:
                    self._session_id = session_id
                if not raw_body.strip() and allow_empty_response:
                    return {}
                response_data = parse_mcp_response(raw_body, response.headers.get("content-type", ""))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MCP HTTP {error.code}: {details}") from error
        except (OSError, URLError, TimeoutError) as error:
            raise RuntimeError(f"MCP request failed: {error}") from error

        mcp_error = response_data.get("error")
        if isinstance(mcp_error, dict):
            raise RuntimeError(f"MCP error: {mcp_error.get('message') or mcp_error}")
        return response_data

    def _request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id


def normalize_mcp_url(server_url: str) -> str:
    clean_url = server_url.strip().rstrip("/")
    if not clean_url:
        raise RuntimeError("MCP server_url must not be empty.")
    parsed = urlparse(clean_url)
    if parsed.path in {"", "/"}:
        return f"{clean_url}/mcp"
    return clean_url


def parse_mcp_response(raw_body: str, content_type: str) -> dict[str, Any]:
    if "text/event-stream" in content_type:
        for line in raw_body.splitlines():
            if not line.startswith("data:"):
                continue
            raw_data = line.removeprefix("data:").strip()
            if not raw_data:
                continue
            parsed = json.loads(raw_data)
            if isinstance(parsed, dict):
                return parsed
        raise RuntimeError(f"MCP SSE response did not contain data: {raw_body}")

    parsed = json.loads(raw_body)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"MCP response must be a JSON object: {raw_body}")
    return parsed
