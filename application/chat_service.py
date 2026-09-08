from application.agent_error import AgentError, AgentErrorCode
from application.llm_agent import LlmAgent
from application.message_history_repository import MessageHistoryRepository
from domain.message import ASSISTANT_ROLE, USER_ROLE, Message


class ChatService:
    def __init__(
        self,
        agent: LlmAgent,
        history_repository: MessageHistoryRepository,
    ) -> None:
        self._agent = agent
        self._history_repository = history_repository

    def answer(self, user_message: str) -> str:
        clean_message = user_message.strip()
        if not clean_message:
            raise AgentError(AgentErrorCode.EMPTY_MESSAGE)

        messages = self._history_repository.load()
        messages.append(Message(role=USER_ROLE, content=clean_message))

        answer = self._agent.ask(messages)
        messages.append(Message(role=ASSISTANT_ROLE, content=answer))
        self._history_repository.save(messages)

        return answer

    def get_history(self) -> list[Message]:
        return self._history_repository.load()
