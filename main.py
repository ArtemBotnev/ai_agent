import os
import sys
from pathlib import Path

from agent import (
    DEFAULT_OPENAI_MODEL,
    OPENAI_API_KEY_ENV,
    OPENAI_MODEL_ENV,
    STICKY_FACTS_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    SimpleConversationSummarizer,
    SimpleLlmAgent,
    SimpleStickyFactsExtractor,
)
from application.agent_error import AgentError, AgentErrorCode
from application.branch_repository import BranchRepository
from application.chat_service import DEFAULT_RECENT_MESSAGES_LIMIT, ChatService
from application.context_strategy import ContextStrategy, get_context_strategy_values
from application.conversation_summary_repository import ConversationSummaryRepository
from application.conversation_summarizer import ConversationSummarizer
from application.message_history_repository import MessageHistoryRepository
from application.sticky_facts_extractor import StickyFactsExtractor
from application.sticky_facts_repository import StickyFactsRepository
from infrastructure.json_branch_repository import JsonBranchRepository
from infrastructure.json_conversation_summary_repository import JsonConversationSummaryRepository
from infrastructure.json_message_history_repository import JsonMessageHistoryRepository
from infrastructure.json_sticky_facts_repository import JsonStickyFactsRepository

DEFAULT_HISTORY_FILE = Path("history/messages.json")
DEFAULT_SUMMARY_FILE = Path("history/summary.json")
DEFAULT_FACTS_FILE = Path("history/facts.json")
DEFAULT_BRANCHES_FILE = Path("history/branches.json")
AGENT_HISTORY_FILE_ENV = "AGENT_HISTORY_FILE"
AGENT_SUMMARY_FILE_ENV = "AGENT_SUMMARY_FILE"
AGENT_FACTS_FILE_ENV = "AGENT_FACTS_FILE"
AGENT_BRANCHES_FILE_ENV = "AGENT_BRANCHES_FILE"
AGENT_RECENT_MESSAGES_LIMIT_ENV = "AGENT_RECENT_MESSAGES_LIMIT"
AGENT_CONTEXT_STRATEGY_ENV = "AGENT_CONTEXT_STRATEGY"


AGENT_ERROR_MESSAGES = {
    AgentErrorCode.EMPTY_MESSAGE: "Введите непустое сообщение.",
    AgentErrorCode.HTTP_ERROR: "LLM API вернул HTTP-ошибку.",
    AgentErrorCode.CONNECTION_ERROR: "Не удалось подключиться к LLM API.",
    AgentErrorCode.TIMEOUT: "Истекло время ожидания ответа от LLM API.",
    AgentErrorCode.INVALID_JSON: "LLM API вернул некорректный JSON.",
    AgentErrorCode.MISSING_OUTPUT_TEXT: "В ответе LLM API не найден текст ответа.",
    AgentErrorCode.MISSING_TOKEN_USAGE: "LLM API не вернул данные о токенах.",
    AgentErrorCode.INCOMPLETE_RESPONSE: "LLM API вернул незавершенный ответ без текста.",
}


def build_agent() -> SimpleLlmAgent:
    return SimpleLlmAgent(api_key=get_api_key(), model=get_model_name())


def build_summarizer() -> ConversationSummarizer:
    summary_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(),
        system_prompt=SUMMARY_SYSTEM_PROMPT,
    )
    return SimpleConversationSummarizer(summary_agent)


def build_facts_extractor() -> StickyFactsExtractor:
    facts_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(),
        system_prompt=STICKY_FACTS_SYSTEM_PROMPT,
    )
    return SimpleStickyFactsExtractor(facts_agent)


def get_api_key() -> str:
    api_key = os.getenv(OPENAI_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"Перед запуском чата задайте переменную окружения {OPENAI_API_KEY_ENV}.")

    return api_key


def get_model_name() -> str:
    return os.getenv(OPENAI_MODEL_ENV, DEFAULT_OPENAI_MODEL)


def build_history_repository() -> MessageHistoryRepository:
    history_file = Path(os.getenv(AGENT_HISTORY_FILE_ENV, str(DEFAULT_HISTORY_FILE)))
    return JsonMessageHistoryRepository(history_file)


def build_summary_repository() -> ConversationSummaryRepository:
    summary_file = Path(os.getenv(AGENT_SUMMARY_FILE_ENV, str(DEFAULT_SUMMARY_FILE)))
    return JsonConversationSummaryRepository(summary_file)


def build_facts_repository() -> StickyFactsRepository:
    facts_file = Path(os.getenv(AGENT_FACTS_FILE_ENV, str(DEFAULT_FACTS_FILE)))
    return JsonStickyFactsRepository(facts_file)


def build_branch_repository() -> BranchRepository:
    branches_file = Path(os.getenv(AGENT_BRANCHES_FILE_ENV, str(DEFAULT_BRANCHES_FILE)))
    return JsonBranchRepository(branches_file)


def get_recent_messages_limit() -> int:
    raw_limit = os.getenv(AGENT_RECENT_MESSAGES_LIMIT_ENV, str(DEFAULT_RECENT_MESSAGES_LIMIT))

    try:
        limit = int(raw_limit)
    except ValueError as error:
        raise RuntimeError(f"Переменная {AGENT_RECENT_MESSAGES_LIMIT_ENV} должна быть числом.") from error

    if limit < 1:
        raise RuntimeError(f"Переменная {AGENT_RECENT_MESSAGES_LIMIT_ENV} должна быть больше 0.")

    return limit


def get_context_strategy() -> ContextStrategy:
    raw_strategy = os.getenv(AGENT_CONTEXT_STRATEGY_ENV, ContextStrategy.SUMMARY.value)
    try:
        return ContextStrategy.from_value(raw_strategy)
    except ValueError as error:
        supported_values = ", ".join(get_context_strategy_values())
        raise RuntimeError(
            f"Переменная {AGENT_CONTEXT_STRATEGY_ENV} должна быть одной из: {supported_values}."
        ) from error


def build_chat_service(context_strategy: ContextStrategy | None = None) -> ChatService:
    return ChatService(
        agent=build_agent(),
        history_repository=build_history_repository(),
        summary_repository=build_summary_repository(),
        summarizer=build_summarizer(),
        facts_repository=build_facts_repository(),
        facts_extractor=build_facts_extractor(),
        branch_repository=build_branch_repository(),
        recent_messages_limit=get_recent_messages_limit(),
        context_strategy=context_strategy or get_context_strategy(),
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
    print("Команды: /strategy, /clear, /branch, /checkpoint, /new-branch <name>.")

    while True:
        try:
            user_message = input("\nВы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nДо свидания!")
            return

        if user_message.lower() in {"exit", "quit"}:
            print("До свидания!")
            return

        if user_message.startswith("/"):
            handle_command(chat_service, user_message)
            continue

        if not user_message:
            print(f"Агент: {AGENT_ERROR_MESSAGES[AgentErrorCode.EMPTY_MESSAGE]}")
            continue

        try:
            response = chat_service.answer(user_message)
        except AgentError as error:
            print(f"Ошибка агента: {format_agent_error(error)}", file=sys.stderr)
            continue

        print(f"Агент: {response.text}")
        print(
            "Токены: "
            f"текущий запрос — {response.tokens.current_request}, "
            f"история — {response.tokens.history}, "
            f"ответ — {response.tokens.response}"
        )


def handle_command(chat_service: ChatService, command: str) -> None:
    command_parts = command.split(maxsplit=1)
    command_name = command_parts[0]
    command_argument = command_parts[1] if len(command_parts) > 1 else ""

    if command_name == "/strategy":
        handle_strategy_command(chat_service, command_argument)
        return

    if command_name == "/clear":
        chat_service.clear_context()
        print(f"Контекст очищен для стратегии {chat_service.get_context_strategy().value}.")
        return

    if command_name == "/branch":
        handle_branch_command(chat_service, command_argument)
        return

    if command_name == "/checkpoint":
        branches = chat_service.save_checkpoint()
        print(
            "Checkpoint сохранен: "
            f"{len(branches.checkpoint_messages)} сообщений из ветки {branches.active_branch_id}."
        )
        return

    if command_name == "/new-branch":
        if not command_argument:
            print("Укажите имя ветки: /new-branch branch_a")
            return

        try:
            branches = chat_service.create_branch(command_argument)
        except ValueError as error:
            print(f"Ошибка ветки: {error}")
            return

        print(f"Создана и активирована ветка {branches.active_branch_id}.")
        return

    print("Неизвестная команда.")


def handle_strategy_command(chat_service: ChatService, argument: str) -> None:
    if not argument:
        strategies = ", ".join(get_context_strategy_values())
        print(f"Текущая стратегия: {chat_service.get_context_strategy().value}.")
        print(f"Доступные стратегии: {strategies}.")
        return

    try:
        strategy = ContextStrategy.from_value(argument)
    except ValueError:
        strategies = ", ".join(get_context_strategy_values())
        print(f"Неизвестная стратегия. Доступные стратегии: {strategies}.")
        return

    chat_service.set_context_strategy(strategy)
    print(f"Стратегия переключена на {strategy.value}.")


def handle_branch_command(chat_service: ChatService, argument: str) -> None:
    branches = chat_service.get_branches()
    if not argument:
        branch_names = ", ".join(
            f"{branch_id}{' *' if branch_id == branches.active_branch_id else ''}"
            for branch_id in branches.branches
        )
        print(f"Ветки: {branch_names}.")
        return

    try:
        branches = chat_service.switch_branch(argument)
    except ValueError as error:
        print(f"Ошибка ветки: {error}")
        return

    print(f"Активная ветка: {branches.active_branch_id}.")


def main() -> None:
    try:
        chat_service = build_chat_service()
    except RuntimeError as error:
        print(f"Ошибка конфигурации: {error}", file=sys.stderr)
        sys.exit(1)

    run_chat(chat_service)


if __name__ == "__main__":
    main()
