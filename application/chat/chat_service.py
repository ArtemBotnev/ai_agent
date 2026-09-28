from collections.abc import Callable
from dataclasses import dataclass

from application.branches.branch_repository import BranchRepository
from application.chat.agent_error import AgentError, AgentErrorCode
from application.chat.context_strategy import ContextStrategy
from application.chat.message_history_repository import MessageHistoryRepository
from application.facts.sticky_facts_extractor import StickyFactsExtractor
from application.facts.sticky_facts_repository import StickyFactsRepository
from application.llm.llm_agent import LlmAgent
from application.memory.long_term_memory_extractor import LongTermMemoryExtractor
from application.memory.long_term_memory_repository import LongTermMemoryRepository
from application.memory.invariants_repository import InvariantsRepository
from application.memory.user_profile_repository import UserProfileRepository
from application.memory.working_memory_extractor import WorkingMemoryExtractor
from application.memory.working_memory_repository import WorkingMemoryRepository
from application.summary.conversation_summarizer import ConversationSummarizer
from application.summary.conversation_summary_repository import ConversationSummaryRepository
from application.workflow.task_stage_agents import (
    DoneAgent,
    ExecutionAgent,
    PlanningAgent,
    TaskAgentContext,
    ValidationAgent,
    ValidationAgentResult,
)
from domain.agent_memory import AgentMemorySnapshot
from domain.conversation_branch import (
    ConversationBranch,
    ConversationBranches,
)
from domain.conversation_summary import ConversationSummary
from domain.long_term_memory import LongTermMemory
from domain.message import ASSISTANT_ROLE, USER_ROLE, Message
from domain.sticky_facts import StickyFacts
from domain.working_memory import WorkingMemory

DEFAULT_RECENT_MESSAGES_LIMIT = 6
MEMORY_STAGE_TURN_LIMIT = 8


@dataclass(frozen=True)
class ChatTokenUsage:
    current_request: int
    history: int
    response: int


@dataclass(frozen=True)
class ChatResponse:
    text: str
    tokens: ChatTokenUsage


class ChatService:
    def __init__(
        self,
        agent: LlmAgent,
        history_repository: MessageHistoryRepository,
        summary_repository: ConversationSummaryRepository,
        summarizer: ConversationSummarizer,
        facts_repository: StickyFactsRepository,
        facts_extractor: StickyFactsExtractor,
        branch_repository: BranchRepository,
        working_memory_repository: WorkingMemoryRepository | None = None,
        working_memory_extractor: WorkingMemoryExtractor | None = None,
        long_term_memory_repository: LongTermMemoryRepository | None = None,
        long_term_memory_extractor: LongTermMemoryExtractor | None = None,
        user_profile_repository: UserProfileRepository | None = None,
        invariants_repository: InvariantsRepository | None = None,
        recent_messages_limit: int = DEFAULT_RECENT_MESSAGES_LIMIT,
        context_strategy: ContextStrategy = ContextStrategy.MEMORY,
        on_task_stage_changed: Callable[[WorkingMemory], None] | None = None,
        planning_agent: PlanningAgent | None = None,
        execution_agent: ExecutionAgent | None = None,
        validation_agent: ValidationAgent | None = None,
        done_agent: DoneAgent | None = None,
    ) -> None:
        self._agent = agent
        self._history_repository = history_repository
        self._summary_repository = summary_repository
        self._summarizer = summarizer
        self._facts_repository = facts_repository
        self._facts_extractor = facts_extractor
        self._branch_repository = branch_repository
        self._working_memory_repository = working_memory_repository
        self._working_memory_extractor = working_memory_extractor
        self._long_term_memory_repository = long_term_memory_repository
        self._long_term_memory_extractor = long_term_memory_extractor
        self._user_profile_repository = user_profile_repository
        self._invariants_repository = invariants_repository
        self._recent_messages_limit = recent_messages_limit
        self._context_strategy = context_strategy
        self._on_task_stage_changed = on_task_stage_changed
        self._planning_agent = planning_agent
        self._execution_agent = execution_agent
        self._validation_agent = validation_agent
        self._done_agent = done_agent
        self._last_notified_task_stage: str | None = None
        if self._recent_messages_limit < 1:
            raise ValueError("recent_messages_limit must be greater than 0.")

    def answer(self, user_message: str) -> ChatResponse:
        clean_message = user_message.strip()
        if not clean_message:
            raise AgentError(AgentErrorCode.EMPTY_MESSAGE)

        current_message = Message(role=USER_ROLE, content=clean_message)
        if self._context_strategy == ContextStrategy.SLIDING_WINDOW:
            return self._answer_with_sliding_window(current_message)

        if self._context_strategy == ContextStrategy.STICKY_FACTS:
            return self._answer_with_sticky_facts(current_message)

        if self._context_strategy == ContextStrategy.BRANCHING:
            return self._answer_with_branching(current_message)

        if self._context_strategy == ContextStrategy.MEMORY:
            return self._answer_with_memory(current_message)

        return self._answer_with_summary(current_message)

    def get_context_strategy(self) -> ContextStrategy:
        return self._context_strategy

    def get_model_name(self) -> str:
        model_name = getattr(self._agent, "model", "")
        if isinstance(model_name, str):
            return model_name

        return ""

    def set_context_strategy(self, context_strategy: ContextStrategy) -> None:
        self._context_strategy = context_strategy

    def get_history(self) -> list[Message]:
        if self._context_strategy == ContextStrategy.BRANCHING:
            return list(self._branch_repository.load().active_branch.messages)

        return self._history_repository.load()

    def clear_context(self) -> None:
        if self._context_strategy == ContextStrategy.SUMMARY:
            self._history_repository.save([])
            self._summary_repository.save(ConversationSummary())
            return

        if self._context_strategy == ContextStrategy.STICKY_FACTS:
            self._history_repository.save([])
            self._facts_repository.save(StickyFacts())
            return

        if self._context_strategy == ContextStrategy.BRANCHING:
            self._branch_repository.save(ConversationBranches.empty())
            return

        if self._context_strategy == ContextStrategy.MEMORY:
            self._require_memory_components()
            self._save_short_term_memory([])
            self._save_working_memory(WorkingMemory())
            self._save_long_term_memory(LongTermMemory())
            return

        self._history_repository.save([])

    def get_branches(self) -> ConversationBranches:
        return self._branch_repository.load()

    def switch_branch(self, branch_id: str) -> ConversationBranches:
        branches_state = self._branch_repository.load()
        clean_branch_id = branch_id.strip()
        if clean_branch_id not in branches_state.branches:
            raise ValueError(f"Branch does not exist: {branch_id}")

        updated_state = ConversationBranches(
            active_branch_id=clean_branch_id,
            checkpoint_messages=branches_state.checkpoint_messages,
            branches=branches_state.branches,
        )
        self._branch_repository.save(updated_state)
        return updated_state

    def save_checkpoint(self) -> ConversationBranches:
        branches_state = self._branch_repository.load()
        updated_state = ConversationBranches(
            active_branch_id=branches_state.active_branch_id,
            checkpoint_messages=list(branches_state.active_branch.messages),
            branches=branches_state.branches,
        )
        self._branch_repository.save(updated_state)
        return updated_state

    def create_branch(self, branch_id: str) -> ConversationBranches:
        clean_branch_id = branch_id.strip()
        if not clean_branch_id:
            raise ValueError("Branch id cannot be empty.")

        branches_state = self._branch_repository.load()
        if clean_branch_id in branches_state.branches:
            raise ValueError(f"Branch already exists: {branch_id}")

        base_messages = list(branches_state.checkpoint_messages)
        branches = dict(branches_state.branches)
        branches[clean_branch_id] = ConversationBranch(
            name=clean_branch_id,
            messages=base_messages,
        )
        updated_state = ConversationBranches(
            active_branch_id=clean_branch_id,
            checkpoint_messages=branches_state.checkpoint_messages,
            branches=branches,
        )
        self._branch_repository.save(updated_state)
        return updated_state

    def _answer_with_summary(self, current_message: Message) -> ChatResponse:
        summary = self._summary_repository.load()
        messages = self._history_repository.load()
        should_save_compacted_history = len(messages) > self._recent_messages_limit
        summary, messages = self._compact_history(summary, messages)
        if should_save_compacted_history:
            self._summary_repository.save(summary)
            self._history_repository.save(messages)

        messages.append(current_message)
        context = self._build_context(summary.content)

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages, context=context)

        answer = self._agent.ask(messages, context=context)
        messages.append(Message(role=ASSISTANT_ROLE, content=answer.text))

        summary, messages = self._compact_history(summary, messages)
        self._summary_repository.save(summary)
        self._history_repository.save(messages)

        return ChatResponse(
            text=answer.text,
            tokens=ChatTokenUsage(
                current_request=current_request_tokens,
                history=history_tokens,
                response=answer.response_tokens,
            ),
        )

    def _answer_with_sliding_window(self, current_message: Message) -> ChatResponse:
        messages = self._history_repository.load()
        messages.append(current_message)
        messages = messages[-self._recent_messages_limit :]
        context = self._build_context()

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages, context=context)
        answer = self._agent.ask(messages, context=context)

        messages.append(Message(role=ASSISTANT_ROLE, content=answer.text))
        messages = messages[-self._recent_messages_limit :]
        self._history_repository.save(messages)

        return ChatResponse(
            text=answer.text,
            tokens=ChatTokenUsage(
                current_request=current_request_tokens,
                history=history_tokens,
                response=answer.response_tokens,
            ),
        )

    def _answer_with_sticky_facts(self, current_message: Message) -> ChatResponse:
        facts = self._facts_repository.load()
        messages = self._history_repository.load()
        messages.append(current_message)
        messages = messages[-self._recent_messages_limit :]
        facts = self._facts_extractor.update(facts, messages)
        context = self._build_context(facts.to_context())

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages, context=context)
        answer = self._agent.ask(messages, context=context)

        messages.append(Message(role=ASSISTANT_ROLE, content=answer.text))
        messages = messages[-self._recent_messages_limit :]
        self._history_repository.save(messages)
        self._facts_repository.save(facts)

        return ChatResponse(
            text=answer.text,
            tokens=ChatTokenUsage(
                current_request=current_request_tokens,
                history=history_tokens,
                response=answer.response_tokens,
            ),
        )

    def _answer_with_branching(self, current_message: Message) -> ChatResponse:
        branches_state = self._branch_repository.load()
        messages = list(branches_state.active_branch.messages)
        messages.append(current_message)
        context = self._build_context()

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages, context=context)
        answer = self._agent.ask(messages, context=context)

        messages.append(Message(role=ASSISTANT_ROLE, content=answer.text))
        branches = dict(branches_state.branches)
        branches[branches_state.active_branch_id] = ConversationBranch(
            name=branches_state.active_branch.name,
            messages=messages,
        )
        self._branch_repository.save(
            ConversationBranches(
                active_branch_id=branches_state.active_branch_id,
                checkpoint_messages=branches_state.checkpoint_messages,
                branches=branches,
            )
        )

        return ChatResponse(
            text=answer.text,
            tokens=ChatTokenUsage(
                current_request=current_request_tokens,
                history=history_tokens,
                response=answer.response_tokens,
            ),
        )

    def _answer_with_memory(self, current_message: Message) -> ChatResponse:
        (
            working_memory_repository,
            _working_memory_extractor,
            long_term_memory_repository,
            long_term_memory_extractor,
            user_profile_repository,
            invariants_repository,
        ) = self._require_memory_components()
        planning_agent, execution_agent, validation_agent, done_agent = self._require_task_stage_agents()

        short_term_messages = self._load_short_term_memory()
        saved_short_term_messages = list(short_term_messages)
        user_profile = user_profile_repository.load()
        invariants = invariants_repository.load()
        working_memory = working_memory_repository.load()
        long_term_memory = long_term_memory_repository.load()
        prepared_task_state = working_memory.task_state.prepare_for_user_message(current_message.content)
        if prepared_task_state != working_memory.task_state:
            working_memory = WorkingMemory(
                items=working_memory.items,
                task_state=prepared_task_state,
            )
            working_memory_repository.save(working_memory)
            self._notify_task_stage_changed(working_memory)

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = 0
        response_tokens = 0
        final_answer = ""
        short_term_messages.append(current_message)
        short_term_messages = short_term_messages[-self._recent_messages_limit :]
        artifact = working_memory.items.get("last_artifact", "")
        validation_summary = working_memory.items.get("last_validation_summary", "")
        revision_request = working_memory.items.get("revision_request", "")
        validation_attempts = _read_int_item(working_memory.items, "validation_attempts")

        for _turn_index in range(MEMORY_STAGE_TURN_LIMIT):
            stage = working_memory.task_state.stage
            memory_snapshot = AgentMemorySnapshot(
                short_term=short_term_messages,
                user_profile=user_profile,
                invariants=invariants,
                working=working_memory,
                long_term=long_term_memory,
            )
            task_context = TaskAgentContext(
                user_message=current_message,
                memory_snapshot=memory_snapshot,
            )
            self._notify_task_stage_changed(working_memory)

            if stage == "planning":
                result = planning_agent.run(task_context)
                history_tokens += result.usage.prompt_tokens
                response_tokens += result.usage.response_tokens
                ready_for_execution = result.ready_for_execution and not result.violates_invariants
                previous_stage = working_memory.task_state.stage
                working_memory = WorkingMemory(
                    items={
                        **working_memory.items,
                        "revision_request": "",
                        "validation_attempts": "0",
                        "last_invariant_check": result.invariant_check,
                    },
                    task_state=working_memory.task_state.apply_planning_result(
                        task=result.task,
                        plan=result.plan,
                        current=result.current,
                        ready_for_execution=ready_for_execution,
                    ),
                )
                if working_memory.task_state.stage != previous_stage:
                    self._notify_task_stage_changed(working_memory)
                if result.violates_invariants:
                    final_answer = self._format_invariant_refusal(result.reply, result.violated_invariants)
                    break
                if not ready_for_execution:
                    final_answer = result.reply
                    break
                short_term_messages.append(Message(role=ASSISTANT_ROLE, content=result.reply))
                short_term_messages = short_term_messages[-self._recent_messages_limit :]
                continue

            if stage == "execution":
                result = execution_agent.run(task_context, revision_request)
                history_tokens += result.usage.prompt_tokens
                response_tokens += result.usage.response_tokens
                previous_stage = working_memory.task_state.stage
                artifact = result.artifact or artifact
                items = {
                    **working_memory.items,
                    "last_artifact": artifact,
                    "revision_request": "",
                }
                working_memory = WorkingMemory(
                    items=items,
                    task_state=working_memory.task_state.apply_execution_result(
                        needs_clarification=result.needs_clarification,
                        completed_steps=result.completed_steps,
                        current=result.current,
                    ),
                )
                if working_memory.task_state.stage != previous_stage:
                    self._notify_task_stage_changed(working_memory)
                if result.needs_clarification:
                    final_answer = result.reply or "Нужны уточнения перед выполнением."
                    break
                short_term_messages.append(Message(role=ASSISTANT_ROLE, content=result.reply or "Execution completed."))
                short_term_messages = short_term_messages[-self._recent_messages_limit :]
                continue

            if stage == "validation":
                result = validation_agent.run(task_context, artifact)
                history_tokens += result.usage.prompt_tokens
                response_tokens += result.usage.response_tokens
                validation_summary = result.reply
                validation_issues = self._build_validation_issues(result)
                previous_stage = working_memory.task_state.stage
                if result.valid:
                    revision_request = ""
                    validation_attempts = 0
                else:
                    validation_attempts += 1
                    revision_request = result.revision_request or "; ".join(validation_issues)
                working_memory = WorkingMemory(
                    items={
                        **working_memory.items,
                        "last_artifact": artifact,
                        "last_validation_summary": validation_summary,
                        "revision_request": revision_request,
                        "validation_attempts": str(validation_attempts),
                    },
                    task_state=working_memory.task_state.apply_validation_result(
                        valid=result.valid,
                        current="" if result.valid else revision_request,
                    ),
                )
                if working_memory.task_state.stage != previous_stage:
                    self._notify_task_stage_changed(working_memory)
                if not result.valid and validation_attempts >= 2:
                    final_answer = self._format_validation_failure(result.reply, validation_issues)
                    break
                short_term_messages.append(Message(role=ASSISTANT_ROLE, content=result.reply))
                short_term_messages = short_term_messages[-self._recent_messages_limit :]
                continue

            if stage == "done":
                result = done_agent.run(task_context, artifact, validation_summary)
                history_tokens += result.usage.prompt_tokens
                response_tokens += result.usage.response_tokens
                final_answer = self._format_done_answer(result.reply, artifact, validation_summary)
                break

        response_text = final_answer or "Workflow остановлен без итогового ответа."
        saved_short_term_messages.append(current_message)
        saved_short_term_messages.append(Message(role=ASSISTANT_ROLE, content=response_text))
        saved_short_term_messages = saved_short_term_messages[-self._recent_messages_limit :]

        self._save_short_term_memory(saved_short_term_messages)
        self._save_working_memory(working_memory)
        self._save_long_term_memory(long_term_memory)

        return ChatResponse(
            text=response_text,
            tokens=ChatTokenUsage(
                current_request=current_request_tokens,
                history=history_tokens,
                response=response_tokens,
            ),
        )

    def _format_validation_failure(self, reply: str, issues: list[str]) -> str:
        if not issues:
            return reply or "Решение не прошло проверку."

        issue_lines = "\n".join(f"- {issue}" for issue in issues)
        return f"{reply or 'Решение не прошло проверку.'}\n\nЧто нужно исправить:\n{issue_lines}"

    def _build_validation_issues(self, result: ValidationAgentResult) -> list[str]:
        issues = list(result.issues)
        issues.extend(result.invariant_violations)
        if not result.artifact_is_concrete:
            issues.append("Artifact должен содержать конкретное решение, а не сводку.")

        return issues

    def _format_invariant_refusal(self, reply: str, violated_invariants: list[str]) -> str:
        clean_reply = reply.strip() or "Не могу предложить это решение, потому что оно нарушает инварианты."
        if not violated_invariants:
            return clean_reply

        invariant_lines = "\n".join(f"- {invariant}" for invariant in violated_invariants)
        return f"{clean_reply}\n\nНарушенные инварианты:\n{invariant_lines}"

    def _format_done_answer(self, reply: str, artifact: str, validation_summary: str) -> str:
        clean_reply = reply.strip() or "Задача завершена."
        clean_artifact = artifact.strip()
        clean_validation_summary = validation_summary.strip()
        parts = [clean_reply]

        if clean_validation_summary and clean_validation_summary not in clean_reply:
            parts.append(f"Проверка:\n{clean_validation_summary}")

        if clean_artifact and clean_artifact not in clean_reply:
            if "```" in clean_artifact:
                parts.append(f"Решение:\n\n{clean_artifact}")
            else:
                parts.append(f"Решение:\n\n```text\n{clean_artifact}\n```")

        return "\n\n".join(parts)

    def _notify_task_stage_changed(self, working_memory: WorkingMemory) -> None:
        stage = working_memory.task_state.stage
        if stage == self._last_notified_task_stage:
            return

        self._last_notified_task_stage = stage
        if self._on_task_stage_changed is not None:
            self._on_task_stage_changed(working_memory)

    def _require_task_stage_agents(
        self,
    ) -> tuple[PlanningAgent, ExecutionAgent, ValidationAgent, DoneAgent]:
        if (
            self._planning_agent is None
            or self._execution_agent is None
            or self._validation_agent is None
            or self._done_agent is None
        ):
            raise RuntimeError("Memory strategy requires planning, execution, validation, and done agents.")

        return (
            self._planning_agent,
            self._execution_agent,
            self._validation_agent,
            self._done_agent,
        )

    def _load_short_term_memory(self) -> list[Message]:
        return self._history_repository.load()

    def _save_short_term_memory(self, messages: list[Message]) -> None:
        self._history_repository.save(messages)

    def _save_working_memory(self, memory: WorkingMemory) -> None:
        working_memory_repository, *_ = self._require_memory_components()
        working_memory_repository.save(memory)

    def _save_long_term_memory(self, memory: LongTermMemory) -> None:
        (
            _working_memory_repository,
            _working_memory_extractor,
            long_term_memory_repository,
            _long_term_memory_extractor,
            _user_profile_repository,
            _invariants_repository,
        ) = self._require_memory_components()
        long_term_memory_repository.save(memory)

    def _build_context(self, *parts: str) -> str:
        profile_context = ""
        if self._user_profile_repository is not None:
            profile_context = self._user_profile_repository.load().to_context()

        invariants_context = ""
        if self._invariants_repository is not None:
            invariants_context = self._invariants_repository.load().to_context()

        return "\n\n".join(
            part.strip()
            for part in (profile_context, invariants_context, *parts)
            if part.strip()
        )

    def _require_memory_components(
        self,
    ) -> tuple[
        WorkingMemoryRepository,
        WorkingMemoryExtractor,
        LongTermMemoryRepository,
        LongTermMemoryExtractor,
        UserProfileRepository,
        InvariantsRepository,
    ]:
        if (
            self._working_memory_repository is None
            or self._working_memory_extractor is None
            or self._long_term_memory_repository is None
            or self._long_term_memory_extractor is None
            or self._user_profile_repository is None
            or self._invariants_repository is None
        ):
            raise RuntimeError(
                "Memory strategy requires user profile, invariants, working, and long-term memory components."
            )

        return (
            self._working_memory_repository,
            self._working_memory_extractor,
            self._long_term_memory_repository,
            self._long_term_memory_extractor,
            self._user_profile_repository,
            self._invariants_repository,
        )

    def _compact_history(
        self,
        summary: ConversationSummary,
        messages: list[Message],
    ) -> tuple[ConversationSummary, list[Message]]:
        if len(messages) <= self._recent_messages_limit:
            return summary, messages

        messages_to_summarize = messages[:-self._recent_messages_limit]
        recent_messages = messages[-self._recent_messages_limit :]
        updated_summary = self._summarizer.summarize(summary.content, messages_to_summarize)

        return ConversationSummary(updated_summary), recent_messages


def _read_int_item(items: dict[str, str], key: str) -> int:
    try:
        return int(items.get(key, "0"))
    except ValueError:
        return 0
