import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from application.agent_error import AgentError, AgentErrorCode
from domain.message import Message

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_MODEL_ENV = "OPENAI_MODEL"
DEFAULT_OPENAI_MODEL = "gpt-5"
OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Answer clearly and concisely."


class AgentEvent(Enum):
    REQUEST_STARTED = "request_started"
    REQUEST_FINISHED = "request_finished"


AgentEventCallback = Callable[[AgentEvent], None]


@dataclass
class SimpleLlmAgent:
    api_key: str
    model: str = DEFAULT_OPENAI_MODEL
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    api_url: str = OPENAI_RESPONSES_API_URL
    on_event: AgentEventCallback | None = None

    def ask(self, messages: Sequence[Message]) -> str:
        if not messages:
            raise AgentError(AgentErrorCode.EMPTY_MESSAGE)

        payload = {
            "model": self.model,
            "instructions": self.system_prompt,
            "input": [message.to_dict() for message in messages],
        }

        self._emit(AgentEvent.REQUEST_STARTED)
        try:
            response_data = self._post_json(payload)
            return self._extract_text(response_data)
        finally:
            self._emit(AgentEvent.REQUEST_FINISHED)

    def _emit(self, event: AgentEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=60) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise AgentError(
                AgentErrorCode.HTTP_ERROR,
                details=details,
                status_code=error.code,
            ) from error
        except URLError as error:
            raise AgentError(
                AgentErrorCode.CONNECTION_ERROR,
                details=str(error.reason),
            ) from error
        except TimeoutError as error:
            raise AgentError(AgentErrorCode.TIMEOUT) from error

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as error:
            raise AgentError(AgentErrorCode.INVALID_JSON) from error

    def _extract_text(self, response_data: dict[str, Any]) -> str:
        direct_output_text = response_data.get("output_text")
        if isinstance(direct_output_text, str) and direct_output_text.strip():
            return direct_output_text.strip()

        output_parts = self._extract_text_parts_from_output(response_data)
        if output_parts:
            return "\n".join(output_parts)

        status = response_data.get("status")
        if isinstance(status, str) and status != "completed":
            raise AgentError(
                AgentErrorCode.INCOMPLETE_RESPONSE,
                response_status=status,
            )

        raise AgentError(AgentErrorCode.MISSING_OUTPUT_TEXT)

    def _extract_text_parts_from_output(self, response_data: dict[str, Any]) -> list[str]:
        output = response_data.get("output")
        if not isinstance(output, list):
            return []

        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue

            content = item.get("content")
            if not isinstance(content, list):
                continue

            for content_item in content:
                if not isinstance(content_item, dict):
                    continue

                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())

        return text_parts
