import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from application.chat.agent_error import AgentError, AgentErrorCode
from application.facts.sticky_facts_extractor import StickyFactsExtractor
from application.llm.llm_agent import LlmAnswer
from application.memory.long_term_memory_extractor import LongTermMemoryExtractor
from application.memory.working_memory_extractor import WorkingMemoryExtractor
from application.summary.conversation_summarizer import ConversationSummarizer
from domain.long_term_memory import LONG_TERM_MEMORY_SECTIONS, LongTermMemory
from domain.message import USER_ROLE, Message
from domain.sticky_facts import StickyFacts
from domain.working_memory import WorkingMemory

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_MODEL_ENV = "OPENAI_MODEL"
DEFAULT_OPENAI_MODEL = "gpt-3.5-turbo-0125"
AVAILABLE_OPENAI_MODELS = (
    DEFAULT_OPENAI_MODEL,
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-5",
)
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
WORKING_MEMORY_SYSTEM_PROMPT = (
    "You update working memory for the agent's current task. "
    "Keep only active task data and a formal task state machine. "
    "The task stage may change only through the allowed state machine transitions. "
    "Planning is for requirements and plan, execution is for implementation, "
    "validation is for checks, and done is for completed validated work. "
    "Only planning is conversational with the user; execution and validation should produce concise work results. "
    "Pause can happen at any stage and does not change the stage. "
    "Remove stale task data."
)
LONG_TERM_MEMORY_SYSTEM_PROMPT = (
    "You update long-term memory for a chat agent. "
    "Save only durable information that should help future sessions. "
    "Separate it into profile, decisions, and knowledge. Do not store transient chat text."
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


@dataclass
class SimpleWorkingMemoryExtractor(WorkingMemoryExtractor):
    agent: SimpleLlmAgent

    def update(self, memory: WorkingMemory, messages: Sequence[Message]) -> WorkingMemory:
        if not messages:
            return memory

        prompt = self._build_prompt(memory, messages)
        answer = self.agent.ask([Message(role=USER_ROLE, content=prompt)])
        raw_memory = _parse_json_object(answer.text)
        if raw_memory is None:
            return memory

        return self._merge_memory(memory, raw_memory, messages)

    def _merge_memory(
        self,
        memory: WorkingMemory,
        raw_memory: dict[str, object],
        messages: Sequence[Message],
    ) -> WorkingMemory:
        raw_items = raw_memory.get("items")
        if not isinstance(raw_items, dict):
            raw_items = raw_memory

        task_state = memory.task_state
        raw_task_state = raw_memory.get("task_state")
        if isinstance(raw_task_state, dict):
            user_text, assistant_text = _last_user_and_assistant_text(messages)
            task_state = task_state.apply_update(
                raw_task_state,
                user_text=user_text,
                assistant_text=assistant_text,
            )

        return WorkingMemory(
            items=_merge_string_items(memory.items, raw_items),
            task_state=task_state,
        )

    def _build_prompt(self, memory: WorkingMemory, messages: Sequence[Message]) -> str:
        memory_json = json.dumps(memory.to_dict(), ensure_ascii=False, indent=2)
        messages_text = _format_messages_for_memory(messages)

        return (
            "Update working memory for the current task.\n"
            "Return only one JSON object with exactly these top-level objects: "
            "items and task_state.\n"
            "items keys must be strings. items values must be strings, empty strings, or null.\n"
            "Save only short-lived task state: current_goal, requirements, constraints, "
            "selected_approach, files, commands, status, open_questions, next_steps.\n"
            "Do not save user profile, durable decisions, or general knowledge here.\n"
            "Use null or an empty string to delete stale item data.\n"
            "task_state must contain task, stage, step, total, plan, done, current, and paused.\n"
            "stage must be one of planning, execution, validation, done.\n"
            "planning means requirements, clarification, and a sequential plan; no code; "
            "this is the only conversational stage with the user.\n"
            "execution means writing code or creating the concrete artifact; "
            "do not keep discussing with the user unless requirements are missing.\n"
            "validation means tests, review, and checking the result against the plan; "
            "show only the validation result.\n"
            "done means the validated task is complete and the result is fixed.\n"
            "Allowed transitions are strict: planning -> execution; "
            "execution -> validation or planning; validation -> done or execution; done -> no transition.\n"
            "If the task changed, return the new task with stage planning, step 0, empty done.\n"
            "Only use planning -> execution when the plan is ready and the user explicitly asks "
            "to implement, write code, create a class/function/file, or apply changes.\n"
            "Use execution -> planning only when the assistant needs clarification.\n"
            "Use execution -> validation after the assistant creates implementation artifacts.\n"
            "Use validation -> execution when validation failed.\n"
            "Use validation -> done when validation passed.\n"
            "plan must be the real sequential work plan, not options or alternatives.\n"
            "Create or refine plan only during planning. After the task leaves planning, "
            "preserve the existing plan and update only current, done, paused, and stage.\n"
            "done must contain completed items from plan.\n"
            "current must be the active step or current action.\n"
            "Set paused to true when the task is paused at any stage. "
            "When the user asks to continue, keep the same stage unless the normal transition "
            "rules apply and use the saved task_state to continue without asking for repeated explanation.\n\n"
            f"Current working memory:\n{memory_json}\n\n"
            f"Recent messages:\n{messages_text}"
        )


@dataclass
class SimpleLongTermMemoryExtractor(LongTermMemoryExtractor):
    agent: SimpleLlmAgent

    def update(self, memory: LongTermMemory, messages: Sequence[Message]) -> LongTermMemory:
        if not messages:
            return memory

        prompt = self._build_prompt(memory, messages)
        answer = self.agent.ask([Message(role=USER_ROLE, content=prompt)])
        raw_sections = _parse_json_object(answer.text)
        if raw_sections is None:
            return memory

        return self._merge_memory(memory, raw_sections)

    def _merge_memory(
        self,
        memory: LongTermMemory,
        raw_sections: dict[str, object],
    ) -> LongTermMemory:
        current_sections = {
            "profile": dict(memory.profile),
            "decisions": dict(memory.decisions),
            "knowledge": dict(memory.knowledge),
        }

        for section_name in LONG_TERM_MEMORY_SECTIONS:
            raw_updates = raw_sections.get(section_name)
            if not isinstance(raw_updates, dict):
                continue

            current_sections[section_name] = _merge_string_items(
                current_sections[section_name],
                raw_updates,
            )

        return LongTermMemory(
            profile=current_sections["profile"],
            decisions=current_sections["decisions"],
            knowledge=current_sections["knowledge"],
        )

    def _build_prompt(self, memory: LongTermMemory, messages: Sequence[Message]) -> str:
        memory_json = json.dumps(memory.to_dict(), ensure_ascii=False, indent=2)
        messages_text = _format_messages_for_memory(messages)

        return (
            "Update long-term memory.\n"
            "Return only one JSON object with exactly these top-level objects: "
            "profile, decisions, knowledge. Keys must be strings. Values must be "
            "strings, empty strings, or null.\n"
            "profile stores stable user/project profile details and preferences.\n"
            "decisions stores durable decisions and agreements.\n"
            "knowledge stores reusable domain or project knowledge.\n"
            "Do not save current-task status, temporary plans, or raw chat history here.\n"
            "Use null or an empty string to delete obsolete entries.\n\n"
            f"Current long-term memory:\n{memory_json}\n\n"
            f"Recent messages:\n{messages_text}"
        )


def _format_messages_for_memory(messages: Sequence[Message]) -> str:
    return "\n".join(
        f"{index}. {message.role}: {message.content}"
        for index, message in enumerate(messages, start=1)
    )


def _last_user_and_assistant_text(messages: Sequence[Message]) -> tuple[str, str]:
    user_text = ""
    assistant_text = ""
    for message in messages:
        if message.role == USER_ROLE:
            user_text = message.content
        elif message.role == "assistant":
            assistant_text = message.content

    return user_text, assistant_text


def _parse_json_object(text: str) -> dict[str, object] | None:
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

    return parsed


def _merge_string_items(
    current_items: dict[str, str],
    raw_updates: dict[str, object],
) -> dict[str, str]:
    updated_items = dict(current_items)

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

    return updated_items
