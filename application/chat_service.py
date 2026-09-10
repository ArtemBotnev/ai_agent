from dataclasses import dataclass

from application.agent_error import AgentError, AgentErrorCode
from application.conversation_summarizer import ConversationSummarizer
from application.conversation_summary_repository import ConversationSummaryRepository
from application.llm_agent import LlmAgent
from application.message_history_repository import MessageHistoryRepository
from domain.conversation_summary import ConversationSummary
from domain.message import ASSISTANT_ROLE, USER_ROLE, Message

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
        recent_messages_limit: int = DEFAULT_RECENT_MESSAGES_LIMIT,
    ) -> None:
        self._agent = agent
        self._history_repository = history_repository
        self._summary_repository = summary_repository
        self._summarizer = summarizer
        self._recent_messages_limit = recent_messages_limit
        if self._recent_messages_limit < 1:
            raise ValueError("recent_messages_limit must be greater than 0.")

    def answer(self, user_message: str) -> ChatResponse:
        clean_message = user_message.strip()
        if not clean_message:
            raise AgentError(AgentErrorCode.EMPTY_MESSAGE)

        current_message = Message(role=USER_ROLE, content=clean_message)
        summary = self._summary_repository.load()
        messages = self._history_repository.load()
        should_save_compacted_history = len(messages) > self._recent_messages_limit
        summary, messages = self._compact_history(summary, messages)
        if should_save_compacted_history:
            self._summary_repository.save(summary)
            self._history_repository.save(messages)

        messages.append(current_message)

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages, summary=summary.content)

        answer = self._agent.ask(messages, summary=summary.content)
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

    def get_history(self) -> list[Message]:
        return self._history_repository.load()

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
