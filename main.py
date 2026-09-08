import os
import sys
from pathlib import Path

from agent import (
    DEFAULT_OPENAI_MODEL,
    OPENAI_API_KEY_ENV,
    OPENAI_MODEL_ENV,
    SimpleLlmAgent,
)
from application.agent_error import AgentError, AgentErrorCode
from application.chat_service import ChatService
from application.message_history_repository import MessageHistoryRepository
from infrastructure.json_message_history_repository import JsonMessageHistoryRepository

DEFAULT_HISTORY_FILE = Path("history/messages.json")
AGENT_HISTORY_FILE_ENV = "AGENT_HISTORY_FILE"


AGENT_ERROR_MESSAGES = {
    AgentErrorCode.EMPTY_MESSAGE: "Введите непустое сообщение.",
    AgentErrorCode.HTTP_ERROR: "LLM API вернул HTTP-ошибку.",
    AgentErrorCode.CONNECTION_ERROR: "Не удалось подключиться к LLM API.",
    AgentErrorCode.TIMEOUT: "Истекло время ожидания ответа от LLM API.",
    AgentErrorCode.INVALID_JSON: "LLM API вернул некорректный JSON.",
    AgentErrorCode.MISSING_OUTPUT_TEXT: "В ответе LLM API не найден текст ответа.",
    AgentErrorCode.INCOMPLETE_RESPONSE: "LLM API вернул незавершенный ответ без текста.",
}


def build_agent() -> SimpleLlmAgent:
    api_key = os.getenv(OPENAI_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"Перед запуском чата задайте переменную окружения {OPENAI_API_KEY_ENV}.")

    model = os.getenv(OPENAI_MODEL_ENV, DEFAULT_OPENAI_MODEL)
    return SimpleLlmAgent(api_key=api_key, model=model)


def build_history_repository() -> MessageHistoryRepository:
    history_file = Path(os.getenv(AGENT_HISTORY_FILE_ENV, str(DEFAULT_HISTORY_FILE)))
    return JsonMessageHistoryRepository(history_file)


def build_chat_service() -> ChatService:
    return ChatService(
        agent=build_agent(),
        history_repository=build_history_repository(),
    )


def format_agent_error(error: AgentError) -> str:
    message = AGENT_ERROR_MESSAGES.get(error.code, "Произошла неизвестная ошибка агента.")

    if error.status_code is not None:
        message = f"{message} Код HTTP: {error.status_code}."

    if error.response_status is not None:
        message = f"{message} Статус ответа: {error.response_status}."

    if error.details:
        message = f"{message} Подробности: {error.details}"

    return message


def run_chat(chat_service: ChatService) -> None:
    print("Простой CLI-чат с LLM-агентом")
    print("Введите сообщение и нажмите Enter. Для выхода напишите 'exit' или 'quit'.")

    while True:
        try:
            user_message = input("\nВы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nДо свидания!")
            return

        if user_message.lower() in {"exit", "quit"}:
            print("До свидания!")
            return

        if not user_message:
            print(f"Агент: {AGENT_ERROR_MESSAGES[AgentErrorCode.EMPTY_MESSAGE]}")
            continue

        try:
            answer = chat_service.answer(user_message)
        except AgentError as error:
            print(f"Ошибка агента: {format_agent_error(error)}", file=sys.stderr)
            continue

        print(f"Агент: {answer}")


def main() -> None:
    try:
        chat_service = build_chat_service()
    except RuntimeError as error:
        print(f"Ошибка конфигурации: {error}", file=sys.stderr)
        sys.exit(1)

    run_chat(chat_service)


if __name__ == "__main__":
    main()
