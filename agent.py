import json
import time
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
from application.workflow.task_stage_agents import (
    DoneAgentResult,
    ExecutionAgentResult,
    PlanningAgent,
    PlanningAgentResult,
    TaskAgentContext,
    TaskAgentUsage,
    ValidationAgentResult,
)
from domain.long_term_memory import LONG_TERM_MEMORY_SECTIONS, LongTermMemory
from domain.message import USER_ROLE, Message
from domain.sticky_facts import StickyFacts
from domain.working_memory import WorkingMemory

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_MODEL_ENV = "OPENAI_MODEL"
OLLAMA_BASE_URL_ENV = "AGENT_OLLAMA_URL"
OLLAMA_MODEL_ENV = "AGENT_OLLAMA_MODEL"
OLLAMA_MODELS_ENV = "AGENT_OLLAMA_MODELS"
DEFAULT_OPENAI_MODEL = "gpt-3.5-turbo-0125"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
AVAILABLE_OPENAI_MODELS = (
    DEFAULT_OPENAI_MODEL,
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-5",
)
OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
OPENAI_RESPONSES_INPUT_TOKENS_API_URL = "https://api.openai.com/v1/responses/input_tokens"
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer clearly and concisely. "
    "When invariants are provided, treat them as mandatory constraints. "
    "Refuse to propose or implement solutions that violate them, name the violated invariant, "
    "and offer a compliant alternative."
)
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
PLANNING_AGENT_SYSTEM_PROMPT = (
    "You are the planning subagent in a task state machine. "
    "Discuss requirements, clarify missing details, and produce a short sequential plan. "
    "Do not write code, diffs, patches, or implementation artifacts. "
    "You must follow all invariants. If the user's request or a possible solution violates an invariant, "
    "refuse that solution, name the violated invariant, and offer a compliant alternative. "
    "When the request is about architecture, check architecture invariants first and report those violations directly. "
    "Do not answer only with stack constraints when an architecture invariant is the relevant conflict. "
    "Do not set ready_for_execution=true when invariants are violated. "
    "Return only JSON."
)
PLANNING_ANALYST_SYSTEM_PROMPT = (
    "You are the analyst role inside a planning debate. "
    "Focus on user intent, requirements, scope, missing information, business rules, risks, "
    "and whether the task is ready to move forward. You must follow all invariants. "
    "Use only the compact internal protocol requested by the prompt."
)
PLANNING_DEVELOPER_SYSTEM_PROMPT = (
    "You are the developer role inside a planning debate. "
    "Focus on architecture, implementation feasibility, clean boundaries, state-machine impact, "
    "test strategy, and technical risks. You must follow all invariants. "
    "Use only the compact internal protocol requested by the prompt."
)
PLANNING_DESIGNER_SYSTEM_PROMPT = (
    "You are the designer role inside a planning debate. "
    "Focus on UX, UI implications, interaction clarity, visual constraints, accessibility, "
    "and product consistency. You must follow all invariants. "
    "Use only the compact internal protocol requested by the prompt."
)
PLANNING_SYNTHESIZER_SYSTEM_PROMPT = (
    "You are the synthesizer for a planning debate. "
    "Read compact internal debate notes, resolve conflicts, enforce all invariants, "
    "and produce the final planning result for the task state machine. "
    "Return only JSON."
)
EXECUTION_AGENT_SYSTEM_PROMPT = (
    "You are the execution subagent in a task state machine. "
    "Use the confirmed plan and produce the concrete requested artifact now. "
    "You must follow all invariants. Do not implement artifacts that violate invariants. "
    "If the requested artifact would violate an invariant, return needs_clarification=true and explain the violation. "
    "If the violation is architectural, name the architecture invariant that blocks the artifact. "
    "The artifact must be the final implementation, code, patch, or document requested by the task, "
    "not a summary of what should be implemented. Do not say that you are starting; perform the work. "
    "Return JSON and an artifact block."
)
VALIDATION_AGENT_SYSTEM_PROMPT = (
    "You are the validation subagent in a task state machine. "
    "Validate the artifact against the task, plan, and all invariants. "
    "Set valid=false if the artifact violates any invariant or if the artifact is only a summary "
    "instead of the concrete requested implementation. Architecture invariants must be checked explicitly. "
    "Return only JSON."
)
DONE_AGENT_SYSTEM_PROMPT = (
    "You are the done subagent in a task state machine. "
    "Write the final user-facing answer in Russian. Include the completed solution or artifact, "
    "the validation result, and a concise summary. "
    "You must follow all invariants and must not present an artifact that violates them. "
    "Do not expose internal JSON or subagent details."
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
        started_at = time.monotonic()
        try:
            response_data = self._post_json(payload, self.api_url)
            return LlmAnswer(
                text=self._extract_text(response_data),
                response_tokens=self._extract_output_tokens(response_data),
                duration_seconds=time.monotonic() - started_at,
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
class OllamaOptions:
    temperature: float | None = None
    num_predict: int | None = None
    num_ctx: int | None = None
    top_k: int | None = None
    top_p: float | None = None
    repeat_penalty: float | None = None
    seed: int | None = None

    def to_payload(self) -> dict[str, int | float]:
        return {
            key: value
            for key, value in {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
                "top_k": self.top_k,
                "top_p": self.top_p,
                "repeat_penalty": self.repeat_penalty,
                "seed": self.seed,
            }.items()
            if value is not None
        }


@dataclass
class OllamaLlmAgent:
    model: str = DEFAULT_OLLAMA_MODEL
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    options: OllamaOptions | None = None
    on_event: AgentEventCallback | None = None

    def count_tokens(self, messages: Sequence[Message], *, context: str = "") -> int:
        return 0

    def ask(self, messages: Sequence[Message], *, context: str = "") -> LlmAnswer:
        if not messages:
            raise AgentError(AgentErrorCode.EMPTY_MESSAGE)

        payload = {
            "model": self.model,
            "messages": self._build_messages(messages, context),
            "stream": False,
        }
        if self.options is not None:
            options_payload = self.options.to_payload()
            if options_payload:
                payload["options"] = options_payload

        self._emit(AgentEvent.REQUEST_STARTED)
        started_at = time.monotonic()
        try:
            response_data = self._post_json(payload, self._chat_url())
            return LlmAnswer(
                text=self._extract_text(response_data),
                response_tokens=self._extract_eval_count(response_data),
                duration_seconds=self._extract_total_duration_seconds(response_data, started_at),
            )
        finally:
            self._emit(AgentEvent.REQUEST_FINISHED)

    def _build_messages(self, messages: Sequence[Message], context: str = "") -> list[dict[str, str]]:
        chat_messages = [
            {
                "role": "system",
                "content": self._build_instructions(context),
            }
        ]
        chat_messages.extend(message.to_dict() for message in messages)
        return chat_messages

    def _build_instructions(self, context: str = "") -> str:
        clean_context = context.strip()
        if not clean_context:
            return self.system_prompt

        return f"{self.system_prompt}\n\n{ADDITIONAL_CONTEXT_LABEL}\n{clean_context}"

    def _chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/chat"

    def _post_json(self, payload: dict[str, Any], api_url: str) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            api_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=120) as response:
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
        message = response_data.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        response = response_data.get("response")
        if isinstance(response, str) and response.strip():
            return response.strip()

        done = response_data.get("done")
        if done is False:
            raise AgentError(AgentErrorCode.INCOMPLETE_RESPONSE)

        raise AgentError(AgentErrorCode.MISSING_OUTPUT_TEXT)

    def _extract_eval_count(self, response_data: dict[str, Any]) -> int:
        eval_count = response_data.get("eval_count")
        if isinstance(eval_count, int) and eval_count >= 0:
            return eval_count

        return 0

    def _extract_total_duration_seconds(self, response_data: dict[str, Any], started_at: float) -> float:
        total_duration = response_data.get("total_duration")
        if isinstance(total_duration, int) and total_duration >= 0:
            return total_duration / 1_000_000_000

        return time.monotonic() - started_at

    def _emit(self, event: AgentEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)


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
            "task_state must contain task, stage, step, total, plan_step, plan_total, plan, done, current, and paused.\n"
            "step/total is the workflow position only: planning=1/4, execution=2/4, validation=3/4, done=4/4.\n"
            "plan_step/plan_total is the progress inside the saved execution plan.\n"
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
            "If the task changed, return the new task with stage planning and empty done.\n"
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
class SimplePlanningAgent:
    agent: SimpleLlmAgent

    def run(self, context: TaskAgentContext) -> PlanningAgentResult:
        prompt = _build_task_agent_prompt(context)
        prompt += _build_final_planning_json_instructions()
        prompt_message = Message(role=USER_ROLE, content=prompt)
        prompt_tokens = self.agent.count_tokens([prompt_message])
        answer = self.agent.ask([prompt_message])
        payload = _parse_json_payload(answer.text) or {}
        result = _planning_result_from_payload(
            payload,
            context,
            TaskAgentUsage(prompt_tokens=prompt_tokens, response_tokens=answer.response_tokens),
        )
        return _apply_explicit_execution_approval(result, context)


@dataclass
class DebatingPlanningAgent:
    analyst_agent: SimpleLlmAgent
    developer_agent: SimpleLlmAgent
    designer_agent: SimpleLlmAgent
    synthesizer_agent: SimpleLlmAgent
    fallback_agent: PlanningAgent | None = None

    def run(self, context: TaskAgentContext) -> PlanningAgentResult:
        base_prompt = _build_task_agent_prompt(context)
        usage = TaskAgentUsage()
        notes: list[str] = []

        initial_notes, usage = self._collect_initial_notes(base_prompt, usage)
        notes.extend(initial_notes)

        review_notes, usage = self._collect_review_notes(base_prompt, notes, usage)
        notes.extend(review_notes)

        try:
            result, synthesis_usage = self._synthesize(context, base_prompt, notes)
        except AgentError:
            if self.fallback_agent is None:
                raise
            fallback_result = self.fallback_agent.run(context)
            return _with_added_usage(fallback_result, usage)

        usage = _add_usage(usage, synthesis_usage)
        if not _planning_result_has_required_payload(result):
            if self.fallback_agent is None:
                return result
            fallback_result = self.fallback_agent.run(context)
            return _with_added_usage(fallback_result, usage)

        result = _apply_explicit_execution_approval(result, context)
        return _with_usage(result, usage)

    def _collect_initial_notes(
        self,
        base_prompt: str,
        usage: TaskAgentUsage,
    ) -> tuple[list[str], TaskAgentUsage]:
        notes: list[str] = []
        for role, agent in self._role_agents():
            prompt = _build_debate_role_prompt(base_prompt, role)
            note, note_usage = self._ask_for_note(agent, prompt, role)
            notes.append(note)
            usage = _add_usage(usage, note_usage)

        return notes, usage

    def _collect_review_notes(
        self,
        base_prompt: str,
        previous_notes: list[str],
        usage: TaskAgentUsage,
    ) -> tuple[list[str], TaskAgentUsage]:
        notes: list[str] = []
        transcript = "\n".join(previous_notes)
        for role, agent in self._role_agents():
            prompt = _build_debate_review_prompt(base_prompt, role, transcript)
            note, note_usage = self._ask_for_note(agent, prompt, role)
            notes.append(note)
            usage = _add_usage(usage, note_usage)

        return notes, usage

    def _synthesize(
        self,
        context: TaskAgentContext,
        base_prompt: str,
        notes: list[str],
    ) -> tuple[PlanningAgentResult, TaskAgentUsage]:
        prompt = _build_debate_synthesis_prompt(base_prompt, notes)
        prompt_message = Message(role=USER_ROLE, content=prompt)
        prompt_tokens = self.synthesizer_agent.count_tokens([prompt_message])
        answer = self.synthesizer_agent.ask([prompt_message])
        payload = _parse_json_payload(answer.text) or {}
        return (
            _planning_result_from_payload(
                payload,
                context,
                TaskAgentUsage(prompt_tokens=prompt_tokens, response_tokens=answer.response_tokens),
            ),
            TaskAgentUsage(prompt_tokens=prompt_tokens, response_tokens=answer.response_tokens),
        )

    def _ask_for_note(
        self,
        agent: SimpleLlmAgent,
        prompt: str,
        role: str,
    ) -> tuple[str, TaskAgentUsage]:
        prompt_message = Message(role=USER_ROLE, content=prompt)
        try:
            prompt_tokens = agent.count_tokens([prompt_message])
            answer = agent.ask([prompt_message])
        except AgentError as error:
            return (
                f'(fail :r {role} :err "{error.code.value}")',
                TaskAgentUsage(),
            )

        return (
            _compact_internal_note(answer.text, role),
            TaskAgentUsage(prompt_tokens=prompt_tokens, response_tokens=answer.response_tokens),
        )

    def _role_agents(self) -> tuple[tuple[str, SimpleLlmAgent], ...]:
        return (
            ("analyst", self.analyst_agent),
            ("dev", self.developer_agent),
            ("design", self.designer_agent),
        )


@dataclass
class SimpleExecutionAgent:
    agent: SimpleLlmAgent

    def run(self, context: TaskAgentContext, revision_request: str = "") -> ExecutionAgentResult:
        prompt = _build_task_agent_prompt(context)
        if revision_request.strip():
            prompt += f"\n\nValidation revision request:\n{revision_request.strip()}"
        prompt += (
            "\n\nIf requirements are enough, return exactly two fenced blocks: first JSON, then artifact.\n"
            "```json\n"
            "{\n"
            '  "reply": "краткая внутренняя сводка",\n'
            '  "needs_clarification": false,\n'
            '  "completed_steps": ["что выполнено"],\n'
            '  "current": "что осталось или пустая строка"\n'
            "}\n"
            "```\n"
            "```text\n"
            "the concrete artifact, code, patch, or final implementation\n"
            "```\n"
            "If requirements are missing, return only JSON with needs_clarification=true. "
            "If producing the artifact would violate invariants, return only JSON with "
            "needs_clarification=true and explain the violated invariant in reply. "
            "For an architecture conflict, cite the architecture invariant, not unrelated stack constraints. "
            "Never put a summary like 'implemented with X' into the artifact block when code, "
            "a patch, or another concrete implementation was requested. "
            "Do not write that you are starting. Produce the artifact now."
        )
        prompt_message = Message(role=USER_ROLE, content=prompt)
        prompt_tokens = self.agent.count_tokens([prompt_message])
        answer = self.agent.ask([prompt_message])
        payload = _parse_json_payload(answer.text) or {}
        artifact = _extract_last_fenced_block(answer.text)
        needs_clarification = _read_json_bool(payload, "needs_clarification") or not artifact
        return ExecutionAgentResult(
            reply=_read_json_string(payload, "reply") or answer.text.strip(),
            needs_clarification=needs_clarification,
            completed_steps=_read_json_string_list(payload, "completed_steps"),
            current=_read_json_string(payload, "current"),
            artifact="" if needs_clarification else artifact,
            usage=TaskAgentUsage(prompt_tokens=prompt_tokens, response_tokens=answer.response_tokens),
        )


@dataclass
class SimpleValidationAgent:
    agent: SimpleLlmAgent

    def run(self, context: TaskAgentContext, artifact: str) -> ValidationAgentResult:
        prompt = _build_task_agent_prompt(context)
        prompt += (
            f"\n\nArtifact to validate:\n{artifact.strip() or 'No artifact.'}\n\n"
            "Return only JSON with this shape:\n"
            "{\n"
            '  "reply": "краткий итог проверки",\n'
            '  "valid": true,\n'
            '  "issues": ["проблема, если есть"],\n'
            '  "invariant_violations": ["нарушенный инвариант, если есть"],\n'
            '  "artifact_is_concrete": true,\n'
            '  "revision_request": "что исправить при повторном execution"\n'
            "}\n"
            "valid=true only when the artifact covers the task and plan, follows all invariants, "
            "is a concrete requested artifact rather than a summary, and has no obvious issues. "
            "If invariants say to use one technology only, any artifact using a competing technology "
            "must be invalid and listed in invariant_violations. If the artifact uses a competing "
            "architecture pattern, list the architecture invariant in invariant_violations."
        )
        prompt_message = Message(role=USER_ROLE, content=prompt)
        prompt_tokens = self.agent.count_tokens([prompt_message])
        answer = self.agent.ask([prompt_message])
        payload = _parse_json_payload(answer.text) or {}
        issues = _read_json_string_list(payload, "issues")
        invariant_violations = _read_json_string_list(payload, "invariant_violations")
        artifact_is_concrete = _read_json_bool(payload, "artifact_is_concrete")
        return ValidationAgentResult(
            reply=_read_json_string(payload, "reply") or answer.text.strip(),
            valid=_read_json_bool(payload, "valid")
            and not issues
            and not invariant_violations
            and artifact_is_concrete,
            issues=issues,
            invariant_violations=invariant_violations,
            artifact_is_concrete=artifact_is_concrete,
            revision_request=_read_json_string(payload, "revision_request"),
            usage=TaskAgentUsage(prompt_tokens=prompt_tokens, response_tokens=answer.response_tokens),
        )


@dataclass
class SimpleDoneAgent:
    agent: SimpleLlmAgent

    def run(self, context: TaskAgentContext, artifact: str, validation_summary: str) -> DoneAgentResult:
        prompt = _build_task_agent_prompt(context)
        prompt += (
            f"\n\nValidation summary:\n{validation_summary.strip() or 'Validation passed.'}\n\n"
            f"Final artifact:\n{artifact.strip() or 'No artifact.'}\n\n"
            "Write a concise final answer to the user in Russian. Include three parts: "
            "what was done, validation result, and the final solution/artifact. "
            "If the artifact is code or structured text, preserve it in a fenced block."
        )
        prompt_message = Message(role=USER_ROLE, content=prompt)
        prompt_tokens = self.agent.count_tokens([prompt_message])
        answer = self.agent.ask([prompt_message])
        return DoneAgentResult(
            reply=answer.text.strip() or "Задача завершена.",
            usage=TaskAgentUsage(prompt_tokens=prompt_tokens, response_tokens=answer.response_tokens),
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


def _build_task_agent_prompt(context: TaskAgentContext) -> str:
    task_state = context.memory_snapshot.working.task_state
    return (
        f"User message:\n{context.user_message.content}\n\n"
        f"Task state:\n{task_state.to_context()}\n\n"
        f"User profile:\n{context.memory_snapshot.user_profile.to_context() or 'No profile.'}\n\n"
        f"Invariants:\n{context.memory_snapshot.invariants.to_context() or 'No invariants.'}\n\n"
        "Invariant handling rules:\n"
        "- Check all invariant sections before planning, executing, or validating.\n"
        "- If the request conflicts with an architecture invariant, refuse because of that architecture invariant.\n"
        "- Name the closest matching violated invariant bullet instead of mentioning unrelated constraints.\n"
        "- A request to use one architecture pattern violates an invariant that says to use a different pattern only.\n\n"
        f"Working memory:\n{context.memory_snapshot.working.to_context() or 'No working memory.'}\n\n"
        f"Long-term memory:\n{context.memory_snapshot.long_term.to_context() or 'No long-term memory.'}\n\n"
        f"Recent history:\n{_format_messages_for_memory(context.memory_snapshot.short_term)}"
    )


def _build_final_planning_json_instructions() -> str:
    return (
        "\n\nReturn only JSON with this shape:\n"
        "{\n"
        '  "reply": "сообщение пользователю",\n'
        '  "task": "краткое название задачи",\n'
        '  "plan": ["шаг 1", "шаг 2"],\n'
        '  "current": "текущий ближайший шаг",\n'
        '  "awaiting_confirmation": true,\n'
        '  "ready_for_execution": false,\n'
        '  "invariant_check": "как план учитывает инварианты",\n'
        '  "violates_invariants": false,\n'
        '  "violated_invariants": []\n'
        "}\n"
        "Set ready_for_execution=true only when the user clearly asks to start implementation, "
        "write code, apply changes, create files/classes/functions, or otherwise perform the artifact work. "
        "Treat delegation phrases such as 'все на твое усмотрение', 'всё на твоё усмотрение', "
        "'на ваше усмотрение', 'можешь писать код', 'можете писать код', 'могут писать код', "
        "'переходи к выполнению', 'можно вносить изменения', 'go ahead', or 'write the code' "
        "as explicit execution approval. "
        "Short ambiguous confirmations such as 'давай', 'делай', 'ок', 'окей', or 'согласен' "
        "are not enough: ask one explicit confirmation question "
        "that says whether to start execution now. If the user gives explicit execution approval "
        "and the plan follows all invariants, set ready_for_execution=true instead of repeating the same plan. "
        "Otherwise ask for confirmation or clarification. "
        "If the user request or plan violates invariants, set violates_invariants=true, "
        "ready_for_execution=false, and explain the refusal in reply. "
        "violated_invariants must contain the exact closest violated invariant bullets, "
        "including architecture bullets when the conflict is architectural."
    )


def _build_debate_role_prompt(base_prompt: str, role: str) -> str:
    return (
        f"{base_prompt}\n\n"
        "Internal planning debate protocol:\n"
        "- Answer with compact KQML-like S-expressions only.\n"
        "- Use at most 5 lines.\n"
        "- Keep each line short.\n"
        "- Allowed forms: "
        "(propose :r ROLE :p POSITION :q QUESTIONS :risk RISKS :plan PLAN :v VIOLATIONS :ready yes|no), "
        "(block :r ROLE :v VIOLATION :why REASON), "
        "(ask :r ROLE :q QUESTION).\n"
        "- Use none when a field is empty.\n"
        "- Do not return JSON, markdown, code fences, or prose outside forms.\n\n"
        f"Your role is {role}. Produce your initial planning position."
    )


def _build_debate_review_prompt(base_prompt: str, role: str, transcript: str) -> str:
    return (
        f"{base_prompt}\n\n"
        "Internal planning debate transcript:\n"
        f"{transcript.strip() or '(empty)'}\n\n"
        "Respond with compact KQML-like S-expressions only, at most 4 lines.\n"
        "Allowed forms: "
        "(accept :r ROLE :target ROLE :why REASON), "
        "(challenge :r ROLE :target ROLE :p POSITION :risk RISKS :v VIOLATIONS), "
        "(revise :r ROLE :p POSITION :plan PLAN :ready yes|no), "
        "(block :r ROLE :v VIOLATION :why REASON).\n"
        "Use none when a field is empty. Do not return JSON, markdown, code fences, or prose outside forms.\n\n"
        f"Your role is {role}. Review the other roles and resolve disagreements from your perspective."
    )


def _build_debate_synthesis_prompt(base_prompt: str, notes: list[str]) -> str:
    transcript = "\n".join(note for note in notes if note.strip())
    return (
        f"{base_prompt}\n\n"
        "Internal compact planning debate notes:\n"
        f"{transcript.strip() or '(empty)'}\n\n"
        "Synthesize the debate into the single final planning result. "
        "Do not expose internal roles, transcript, or protocol unless the user explicitly asks. "
        "Resolve conflicts conservatively. If any role identifies a real invariant violation, "
        "the final result must block execution and name the violated invariant. "
        "If a role failed, use the available notes and the original context.\n"
        f"{_build_final_planning_json_instructions()}"
    )


def _compact_internal_note(text: str, role: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    protocol_lines = [line for line in lines if line.startswith("(") and line.endswith(")")]
    clean_lines = protocol_lines or lines
    compact = " ".join(clean_lines[:6]).strip()
    if not compact:
        return f"(fail :r {role} :err empty)"
    return compact[:1200]


def _planning_result_from_payload(
    payload: dict[str, object],
    context: TaskAgentContext,
    usage: TaskAgentUsage,
) -> PlanningAgentResult:
    return PlanningAgentResult(
        reply=_read_json_string(payload, "reply") or "Уточни требования, и я обновлю план.",
        task=_read_json_string(payload, "task") or context.memory_snapshot.working.task_state.task,
        plan=_read_json_string_list(payload, "plan"),
        current=_read_json_string(payload, "current"),
        awaiting_confirmation=_read_json_bool(payload, "awaiting_confirmation"),
        ready_for_execution=_read_json_bool(payload, "ready_for_execution"),
        invariant_check=_read_json_string(payload, "invariant_check"),
        violates_invariants=_read_json_bool(payload, "violates_invariants"),
        violated_invariants=_read_json_string_list(payload, "violated_invariants"),
        usage=usage,
    )


def _planning_result_has_required_payload(result: PlanningAgentResult) -> bool:
    if result.violates_invariants:
        return bool(result.reply and result.violated_invariants)
    return bool(result.reply and result.task and result.plan)


def _apply_explicit_execution_approval(
    result: PlanningAgentResult,
    context: TaskAgentContext,
) -> PlanningAgentResult:
    if result.violates_invariants or not result.plan:
        return result

    normalized_user_message = context.user_message.content.lower()
    if not _has_explicit_execution_approval(normalized_user_message):
        return result

    return PlanningAgentResult(
        reply=result.reply,
        task=result.task,
        plan=result.plan,
        current=result.current,
        awaiting_confirmation=False,
        ready_for_execution=True,
        invariant_check=result.invariant_check,
        violates_invariants=result.violates_invariants,
        violated_invariants=result.violated_invariants,
        usage=result.usage,
    )


def _has_explicit_execution_approval(text: str) -> bool:
    direct_markers = (
        "можно писать код",
        "можешь писать код",
        "можете писать код",
        "могут писать код",
        "пиши код",
        "напиши код",
        "реализуй",
        "реализовывай",
        "сделай реализацию",
        "делай реализацию",
        "выполни реализацию",
        "внеси изменения",
        "можно вносить",
        "можешь вносить",
        "можете вносить",
        "переходи к выполнению",
        "переходите к выполнению",
        "можешь переходить к выполнению",
        "можете переходить к выполнению",
        "go ahead",
        "do it",
        "proceed",
        "implement",
        "start implementation",
        "write code",
        "write the code",
    )
    if any(marker in text for marker in direct_markers):
        return True

    discretion_markers = (
        "на твое усмотрение",
        "на твоё усмотрение",
        "на ваше усмотрение",
        "все на твое усмотрение",
        "всё на твоё усмотрение",
        "все на ваше усмотрение",
        "всё на ваше усмотрение",
    )
    execution_words = (
        "код",
        "писать",
        "выполн",
        "реализ",
        "изменен",
        "изменён",
        "правк",
    )
    return any(marker in text for marker in discretion_markers) and any(
        word in text for word in execution_words
    )


def _add_usage(left: TaskAgentUsage, right: TaskAgentUsage) -> TaskAgentUsage:
    return TaskAgentUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        response_tokens=left.response_tokens + right.response_tokens,
    )


def _with_usage(result: PlanningAgentResult, usage: TaskAgentUsage) -> PlanningAgentResult:
    return PlanningAgentResult(
        reply=result.reply,
        task=result.task,
        plan=result.plan,
        current=result.current,
        awaiting_confirmation=result.awaiting_confirmation,
        ready_for_execution=result.ready_for_execution,
        invariant_check=result.invariant_check,
        violates_invariants=result.violates_invariants,
        violated_invariants=result.violated_invariants,
        usage=usage,
    )


def _with_added_usage(result: PlanningAgentResult, usage: TaskAgentUsage) -> PlanningAgentResult:
    return _with_usage(result, _add_usage(result.usage, usage))


def _last_user_and_assistant_text(messages: Sequence[Message]) -> tuple[str, str]:
    user_text = ""
    assistant_text = ""
    for message in messages:
        if message.role == USER_ROLE:
            user_text = message.content
        elif message.role == "assistant":
            assistant_text = message.content

    return user_text, assistant_text


def _read_json_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        return ""
    return value.strip()


def _read_json_bool(data: dict[str, object], key: str) -> bool:
    return data.get(key) is True


def _read_json_string_list(data: dict[str, object], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _extract_last_fenced_block(text: str) -> str:
    blocks = _extract_fenced_blocks(text)
    if len(blocks) >= 2:
        return blocks[-1]

    return ""


def _parse_json_payload(text: str) -> dict[str, object] | None:
    for block in _extract_fenced_blocks(text):
        parsed = _parse_json_object(block)
        if parsed is not None:
            return parsed

    return _parse_json_object(text)


def _extract_fenced_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    start = 0
    while True:
        block_start = text.find("```", start)
        if block_start < 0:
            break
        content_start = text.find("\n", block_start + 3)
        if content_start < 0:
            break
        block_end = text.find("```", content_start + 1)
        if block_end < 0:
            break
        blocks.append(text[content_start + 1 : block_end].strip())
        start = block_end + 3

    return blocks


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
