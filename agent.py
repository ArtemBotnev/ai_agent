import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from application.agent_error import AgentError, AgentErrorCode
from application.conversation_summarizer import ConversationSummarizer
from application.llm_agent import LlmAnswer
from application.sticky_facts_extractor import StickyFactsExtractor
from domain.message import USER_ROLE, Message
from domain.sticky_facts import StickyFacts

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_MODEL_ENV = "OPENAI_MODEL"
# DEFAULT_OPENAI_MODEL = "gpt-5"
DEFAULT_OPENAI_MODEL = "gpt-3.5-turbo-0125"
OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
OPENAI_RESPONSES_INPUT_TOKENS_API_URL = "https://api.openai.com/v1/responses/input_tokens"
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Answer clearly and concisely."
SUMMARY_SYSTEM_PROMPT = (
    "You summarize earlier chat messages for future context. "
    "Keep stable facts, user preferences, decisions, constraints, open tasks, "
    "and important technical details. Do not invent details."
)
ADDITIONAL_CONTEXT_LABEL = "Additional conversation context:"
STICKY_FACTS_SYSTEM_PROMPT = (
    "You update durable key-value memory for a chat agent. "
    "Keep only stable facts that will help future replies: goals, constraints, "
    "preferences, decisions, agreements, user profile, project details, and open tasks. "
    "Preserve useful existing facts unless the new messages contradict them. "
    "Remove obsolete facts."
)


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
    input_tokens_api_url: str = OPENAI_RESPONSES_INPUT_TOKENS_API_URL
    on_event: AgentEventCallback | None = None

    def count_tokens(self, messages: Sequence[Message], *, context: str = "") -> int:
        if not messages:
            return 0

        payload = {
            "model": self.model,
            "input": [message.to_dict() for message in messages],
        }
        if context.strip():
            payload["instructions"] = self._build_instructions(context)

        response_data = self._post_json(payload, self.input_tokens_api_url)
        return self._extract_input_tokens(response_data)

    def ask(self, messages: Sequence[Message], *, context: str = "") -> LlmAnswer:
        if not messages:
            raise AgentError(AgentErrorCode.EMPTY_MESSAGE)

        payload = {
            "model": self.model,
            "instructions": self._build_instructions(context),
            "input": [message.to_dict() for message in messages],
        }

        self._emit(AgentEvent.REQUEST_STARTED)
        try:
            response_data = self._post_json(payload, self.api_url)
            return LlmAnswer(
                text=self._extract_text(response_data),
                response_tokens=self._extract_output_tokens(response_data),
            )
        finally:
            self._emit(AgentEvent.REQUEST_FINISHED)

    def _emit(self, event: AgentEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _build_instructions(self, context: str = "") -> str:
        clean_context = context.strip()
        if not clean_context:
            return self.system_prompt

        return f"{self.system_prompt}\n\n{ADDITIONAL_CONTEXT_LABEL}\n{clean_context}"

    def _post_json(self, payload: dict[str, Any], api_url: str) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            api_url,
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

    def _extract_input_tokens(self, response_data: dict[str, Any]) -> int:
        input_tokens = response_data.get("input_tokens")
        if isinstance(input_tokens, int) and input_tokens >= 0:
            return input_tokens

        raise AgentError(AgentErrorCode.MISSING_TOKEN_USAGE)

    def _extract_output_tokens(self, response_data: dict[str, Any]) -> int:
        usage = response_data.get("usage")
        if not isinstance(usage, dict):
            return 0

        output_tokens = usage.get("output_tokens")
        if isinstance(output_tokens, int) and output_tokens >= 0:
            return output_tokens

        return 0

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


@dataclass
class SimpleConversationSummarizer(ConversationSummarizer):
    agent: SimpleLlmAgent

    def summarize(self, previous_summary: str, messages: Sequence[Message]) -> str:
        if not messages:
            return previous_summary.strip()

        prompt = self._build_prompt(previous_summary, messages)
        answer = self.agent.ask([Message(role=USER_ROLE, content=prompt)])
        return answer.text

    def _build_prompt(self, previous_summary: str, messages: Sequence[Message]) -> str:
        messages_text = "\n".join(
            f"{index}. {message.role}: {message.content}"
            for index, message in enumerate(messages, start=1)
        )

        clean_previous_summary = previous_summary.strip() or "No previous summary."
        return (
            "Update the conversation summary using the previous summary and the new messages.\n\n"
            f"Previous summary:\n{clean_previous_summary}\n\n"
            f"New messages to summarize:\n{messages_text}\n\n"
            "Return only the updated summary."
        )


@dataclass
class SimpleStickyFactsExtractor(StickyFactsExtractor):
    agent: SimpleLlmAgent

    def update(self, facts: StickyFacts, messages: Sequence[Message]) -> StickyFacts:
        if not messages:
            return facts

        prompt = self._build_prompt(facts, messages)
        answer = self.agent.ask([Message(role=USER_ROLE, content=prompt)])

        raw_facts = self._parse_json_object(answer.text)
        if raw_facts is None:
            return facts

        return self._merge_facts(facts, raw_facts)

    def _parse_json_object(self, text: str) -> dict[str, object] | None:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start_index = text.find("{")
            end_index = text.rfind("}")
            if start_index < 0 or end_index <= start_index:
                return None

            try:
                parsed = json.loads(text[start_index : end_index + 1])
            except json.JSONDecodeError:
                return None

        if not isinstance(parsed, dict):
            return None

        raw_items = parsed.get("items")
        if isinstance(raw_items, dict):
            return raw_items

        return parsed

    def _merge_facts(self, current_facts: StickyFacts, raw_updates: dict[str, object]) -> StickyFacts:
        updated_items = dict(current_facts.items)

        for key, value in raw_updates.items():
            if not isinstance(key, str):
                continue

            clean_key = key.strip()
            if not clean_key:
                continue

            if value is None:
                updated_items.pop(clean_key, None)
                continue

            if not isinstance(value, str):
                continue

            clean_value = value.strip()
            if clean_value:
                updated_items[clean_key] = clean_value
            else:
                updated_items.pop(clean_key, None)

        return StickyFacts(updated_items)

    def _build_prompt(self, facts: StickyFacts, messages: Sequence[Message]) -> str:
        facts_json = json.dumps(facts.items, ensure_ascii=False, indent=2)
        messages_text = "\n".join(
            f"{index}. {message.role}: {message.content}"
            for index, message in enumerate(messages, start=1)
        )

        return (
            "Update key-value memory using the current facts and recent messages.\n"
            "Return only one JSON object. Keys must be strings. Values must be strings, "
            "empty strings, or null.\n"
            "Return every new or changed durable fact. Use null or an empty string to delete "
            "a fact that became obsolete.\n"
            "Keep separate facts as separate keys instead of compressing everything into one item.\n"
            "Use concise keys such as goal, constraints, preferences, decisions, agreements, "
            "user_profile, project_details, open_tasks, current_topic.\n"
            "Do not repeat facts that are unchanged unless they help clarify the update.\n\n"
            f"Current facts:\n{facts_json}\n\n"
            f"Recent messages:\n{messages_text}"
        )
