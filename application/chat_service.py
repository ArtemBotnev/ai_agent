from dataclasses import dataclass

from application.agent_error import AgentError, AgentErrorCode
from application.branch_repository import BranchRepository
from application.conversation_summarizer import ConversationSummarizer
from application.conversation_summary_repository import ConversationSummaryRepository
from application.context_strategy import ContextStrategy
from application.llm_agent import LlmAgent
from application.message_history_repository import MessageHistoryRepository
from application.sticky_facts_extractor import StickyFactsExtractor
from application.sticky_facts_repository import StickyFactsRepository
from domain.conversation_branch import (
    ConversationBranch,
    ConversationBranches,
)
from domain.conversation_summary import ConversationSummary
from domain.message import ASSISTANT_ROLE, USER_ROLE, Message
from domain.sticky_facts import StickyFacts

DEFAULT_RECENT_MESSAGES_LIMIT = 6


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
        recent_messages_limit: int = DEFAULT_RECENT_MESSAGES_LIMIT,
        context_strategy: ContextStrategy = ContextStrategy.SUMMARY,
    ) -> None:
        self._agent = agent
        self._history_repository = history_repository
        self._summary_repository = summary_repository
        self._summarizer = summarizer
        self._facts_repository = facts_repository
        self._facts_extractor = facts_extractor
        self._branch_repository = branch_repository
        self._recent_messages_limit = recent_messages_limit
        self._context_strategy = context_strategy
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

        return self._answer_with_summary(current_message)

    def get_context_strategy(self) -> ContextStrategy:
        return self._context_strategy

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

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages, context=summary.content)

        answer = self._agent.ask(messages, context=summary.content)
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

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages)
        answer = self._agent.ask(messages)

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
        context = facts.to_context()

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

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages)
        answer = self._agent.ask(messages)

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
