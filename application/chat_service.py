from dataclasses import dataclass

from application.agent_error import AgentError, AgentErrorCode
from application.llm_agent import LlmAgent
from application.message_history_repository import MessageHistoryRepository
from domain.message import ASSISTANT_ROLE, USER_ROLE, Message


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
    ) -> None:
        self._agent = agent
        self._history_repository = history_repository

    def answer(self, user_message: str) -> ChatResponse:
        clean_message = user_message.strip()
        if not clean_message:
            raise AgentError(AgentErrorCode.EMPTY_MESSAGE)

        current_message = Message(role=USER_ROLE, content=clean_message)
        messages = self._history_repository.load()
        messages.append(current_message)

        current_request_tokens = self._agent.count_tokens([current_message])
        history_tokens = self._agent.count_tokens(messages)

        answer = self._agent.ask(messages)
        messages.append(Message(role=ASSISTANT_ROLE, content=answer.text))
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
