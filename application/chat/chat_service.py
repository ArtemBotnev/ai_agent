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
from application.memory.user_profile_repository import UserProfileRepository
from application.memory.working_memory_extractor import WorkingMemoryExtractor
from application.memory.working_memory_repository import WorkingMemoryRepository
from application.summary.conversation_summarizer import ConversationSummarizer
from application.summary.conversation_summary_repository import ConversationSummaryRepository
from domain.agent_memory import AgentMemorySnapshot
from domain.conversation_branch import (
    ConversationBranch,
    ConversationBranches,
)
from domain.conversation_summary import ConversationSummary
from domain.long_term_memory import LongTermMemory
from domain.message import ASSISTANT_ROLE, USER_ROLE, Message
from domain.sticky_facts import StickyFacts
from domain.task_state import TASK_STATE_INSTRUCTIONS, TASK_STATE_MARKERS
from domain.working_memory import WorkingMemory

DEFAULT_RECENT_MESSAGES_LIMIT = 6
MEMORY_STAGE_TURN_LIMIT = 4


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
        recent_messages_limit: int = DEFAULT_RECENT_MESSAGES_LIMIT,
        context_strategy: ContextStrategy = ContextStrategy.MEMORY,
        on_task_stage_changed: Callable[[WorkingMemory], None] | None = None,
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
        self._recent_messages_limit = recent_messages_limit
        self._context_strategy = context_strategy
        self._on_task_stage_changed = on_task_stage_changed
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
            working_memory_extractor,
            long_term_memory_repository,
            long_term_memory_extractor,
            user_profile_repository,
        ) = self._require_memory_components()

        short_term_messages = self._load_short_term_memory()
        saved_short_term_messages = list(short_term_messages)
        user_profile = user_profile_repository.load()
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
        visible_outputs: list[str] = []
        short_term_messages.append(current_message)
        short_term_messages = short_term_messages[-self._recent_messages_limit :]

        for _turn_index in range(MEMORY_STAGE_TURN_LIMIT):
            stage = working_memory.task_state.stage
            memory_snapshot = AgentMemorySnapshot(
                short_term=short_term_messages,
                user_profile=user_profile,
                working=working_memory,
                long_term=long_term_memory,
            )
            context = self._build_memory_stage_context(memory_snapshot, stage)

            history_tokens += self._agent.count_tokens(short_term_messages, context=context)
            answer = self._agent.ask(short_term_messages, context=context)
            response_tokens += answer.response_tokens

            assistant_message = Message(role=ASSISTANT_ROLE, content=answer.text)
            completed_turn_messages = [current_message, assistant_message]
            visible_outputs.append(self._format_stage_output(stage, answer.text))
            short_term_messages.append(assistant_message)
            short_term_messages = short_term_messages[-self._recent_messages_limit :]

            previous_stage = working_memory.task_state.stage
            working_memory = working_memory_extractor.update(
                working_memory,
                completed_turn_messages,
            )
            long_term_memory = long_term_memory_extractor.update(
                long_term_memory,
                completed_turn_messages,
            )
            next_stage = working_memory.task_state.stage
            if next_stage != previous_stage:
                self._notify_task_stage_changed(working_memory)

            if previous_stage == "planning":
                break

            if next_stage in {"planning", "done"}:
                break

            if next_stage == previous_stage:
                break

        response_text = self._format_memory_response(visible_outputs, working_memory)
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

    def _build_memory_stage_context(
        self,
        memory_snapshot: AgentMemorySnapshot,
        stage: str,
    ) -> str:
        context = memory_snapshot.to_context()
        if stage == "execution":
            stage_instruction = (
                "Internal stage runner: execute now. Do not write that you are starting. "
                "Produce the concrete implementation artifact in this reply: code, patch, "
                "file content, or the requested concrete result. "
                f"Stage rule: {TASK_STATE_INSTRUCTIONS[stage]}"
            )
        elif stage == "validation":
            stage_instruction = (
                "Internal stage runner: validate the implementation from the previous assistant reply now. "
                "Run or describe the relevant checks based on the available project context. "
                "If validation passes, explicitly include 'Проверка пройдена' or 'ошибок нет'. "
                "If validation fails, explicitly include what failed and that it needs fixing. "
                f"Stage rule: {TASK_STATE_INSTRUCTIONS[stage]}"
            )
        else:
            stage_instruction = TASK_STATE_INSTRUCTIONS[stage]

        return "\n\n".join(part for part in (context, stage_instruction) if part)

    def _format_stage_output(self, stage: str, text: str) -> str:
        marker = TASK_STATE_MARKERS[stage]
        return f"[{marker}]\n{text.strip()}"

    def _format_memory_response(
        self,
        visible_outputs: list[str],
        working_memory: WorkingMemory,
    ) -> str:
        response = "\n\n".join(output for output in visible_outputs if output.strip())
        if working_memory.task_state.stage == "done" and "[ГОТОВО]" not in response:
            return f"{response}\n\n[ГОТОВО]\nЗадача завершена.".strip()

        return response

    def _notify_task_stage_changed(self, working_memory: WorkingMemory) -> None:
        if self._on_task_stage_changed is not None:
            self._on_task_stage_changed(working_memory)

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
        ) = self._require_memory_components()
        long_term_memory_repository.save(memory)

    def _build_context(self, *parts: str) -> str:
        profile_context = ""
        if self._user_profile_repository is not None:
            profile_context = self._user_profile_repository.load().to_context()

        return "\n\n".join(part.strip() for part in (profile_context, *parts) if part.strip())

    def _require_memory_components(
        self,
    ) -> tuple[
        WorkingMemoryRepository,
        WorkingMemoryExtractor,
        LongTermMemoryRepository,
        LongTermMemoryExtractor,
        UserProfileRepository,
    ]:
        if (
            self._working_memory_repository is None
            or self._working_memory_extractor is None
            or self._long_term_memory_repository is None
            or self._long_term_memory_extractor is None
            or self._user_profile_repository is None
        ):
            raise RuntimeError("Memory strategy requires user profile, working, and long-term memory components.")

        return (
            self._working_memory_repository,
            self._working_memory_extractor,
            self._long_term_memory_repository,
            self._long_term_memory_extractor,
            self._user_profile_repository,
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
