import os
import sys
from collections.abc import Callable
from pathlib import Path

from agent import (
    AVAILABLE_OPENAI_MODELS,
    DEFAULT_OPENAI_MODEL,
    OPENAI_API_KEY_ENV,
    OPENAI_MODEL_ENV,
    LONG_TERM_MEMORY_SYSTEM_PROMPT,
    DONE_AGENT_SYSTEM_PROMPT,
    EXECUTION_AGENT_SYSTEM_PROMPT,
    PLANNING_AGENT_SYSTEM_PROMPT,
    STICKY_FACTS_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    SimpleDoneAgent,
    SimpleConversationSummarizer,
    SimpleExecutionAgent,
    SimpleLlmAgent,
    SimpleLongTermMemoryExtractor,
    SimplePlanningAgent,
    SimpleStickyFactsExtractor,
    SimpleValidationAgent,
    SimpleWorkingMemoryExtractor,
    VALIDATION_AGENT_SYSTEM_PROMPT,
    WORKING_MEMORY_SYSTEM_PROMPT,
)
from application.branches.branch_repository import BranchRepository
from application.chat.agent_error import AgentError, AgentErrorCode
from application.chat.chat_service import DEFAULT_RECENT_MESSAGES_LIMIT, ChatService
from application.chat.context_strategy import ContextStrategy, get_context_strategy_values
from application.chat.message_history_repository import MessageHistoryRepository
from application.facts.sticky_facts_extractor import StickyFactsExtractor
from application.facts.sticky_facts_repository import StickyFactsRepository
from application.memory.long_term_memory_extractor import LongTermMemoryExtractor
from application.memory.long_term_memory_repository import LongTermMemoryRepository
from application.memory.user_profile_repository import UserProfileRepository
from application.memory.working_memory_extractor import WorkingMemoryExtractor
from application.memory.working_memory_repository import WorkingMemoryRepository
from application.summary.conversation_summarizer import ConversationSummarizer
from application.summary.conversation_summary_repository import ConversationSummaryRepository
from application.workflow.task_stage_agents import DoneAgent, ExecutionAgent, PlanningAgent, ValidationAgent
from domain.working_memory import WorkingMemory
from infrastructure.json_branch_repository import JsonBranchRepository
from infrastructure.json_conversation_summary_repository import JsonConversationSummaryRepository
from infrastructure.json_long_term_memory_repository import JsonLongTermMemoryRepository
from infrastructure.json_message_history_repository import JsonMessageHistoryRepository
from infrastructure.json_sticky_facts_repository import JsonStickyFactsRepository
from infrastructure.json_working_memory_repository import JsonWorkingMemoryRepository
from infrastructure.markdown_user_profile_repository import MarkdownUserProfileRepository

DEFAULT_SUMMARY_FILE = Path("history/summary.json")
DEFAULT_FACTS_FILE = Path("history/facts.json")
DEFAULT_BRANCHES_FILE = Path("history/branches.json")
DEFAULT_USER_ID = "1"
DEFAULT_MEMORY_DIR = Path("memory/users")
DEFAULT_PROFILES_DIR = Path("profiles/users")
AGENT_HISTORY_FILE_ENV = "AGENT_HISTORY_FILE"
AGENT_SUMMARY_FILE_ENV = "AGENT_SUMMARY_FILE"
AGENT_FACTS_FILE_ENV = "AGENT_FACTS_FILE"
AGENT_BRANCHES_FILE_ENV = "AGENT_BRANCHES_FILE"
AGENT_WORKING_MEMORY_FILE_ENV = "AGENT_WORKING_MEMORY_FILE"
AGENT_LONG_TERM_MEMORY_FILE_ENV = "AGENT_LONG_TERM_MEMORY_FILE"
AGENT_USER_PROFILE_FILE_ENV = "AGENT_USER_PROFILE_FILE"
AGENT_USER_ID_ENV = "AGENT_USER_ID"
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


def build_agent(model_name: str | None = None) -> SimpleLlmAgent:
    return SimpleLlmAgent(api_key=get_api_key(), model=get_model_name(model_name))


def build_summarizer(model_name: str | None = None) -> ConversationSummarizer:
    summary_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(model_name),
        system_prompt=SUMMARY_SYSTEM_PROMPT,
    )
    return SimpleConversationSummarizer(summary_agent)


def build_facts_extractor(model_name: str | None = None) -> StickyFactsExtractor:
    facts_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(model_name),
        system_prompt=STICKY_FACTS_SYSTEM_PROMPT,
    )
    return SimpleStickyFactsExtractor(facts_agent)


def build_working_memory_extractor(model_name: str | None = None) -> WorkingMemoryExtractor:
    working_memory_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(model_name),
        system_prompt=WORKING_MEMORY_SYSTEM_PROMPT,
    )
    return SimpleWorkingMemoryExtractor(working_memory_agent)


def build_long_term_memory_extractor(model_name: str | None = None) -> LongTermMemoryExtractor:
    long_term_memory_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(model_name),
        system_prompt=LONG_TERM_MEMORY_SYSTEM_PROMPT,
    )
    return SimpleLongTermMemoryExtractor(long_term_memory_agent)


def build_planning_agent(model_name: str | None = None) -> PlanningAgent:
    planning_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(model_name),
        system_prompt=PLANNING_AGENT_SYSTEM_PROMPT,
    )
    return SimplePlanningAgent(planning_agent)


def build_execution_agent(model_name: str | None = None) -> ExecutionAgent:
    execution_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(model_name),
        system_prompt=EXECUTION_AGENT_SYSTEM_PROMPT,
    )
    return SimpleExecutionAgent(execution_agent)


def build_validation_agent(model_name: str | None = None) -> ValidationAgent:
    validation_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(model_name),
        system_prompt=VALIDATION_AGENT_SYSTEM_PROMPT,
    )
    return SimpleValidationAgent(validation_agent)


def build_done_agent(model_name: str | None = None) -> DoneAgent:
    done_agent = SimpleLlmAgent(
        api_key=get_api_key(),
        model=get_model_name(model_name),
        system_prompt=DONE_AGENT_SYSTEM_PROMPT,
    )
    return SimpleDoneAgent(done_agent)


def get_api_key() -> str:
    api_key = os.getenv(OPENAI_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"Перед запуском чата задайте переменную окружения {OPENAI_API_KEY_ENV}.")

    return api_key


def get_available_model_names() -> list[str]:
    return list(AVAILABLE_OPENAI_MODELS)


def get_model_name(model_name: str | None = None) -> str:
    selected_model = (model_name or os.getenv(OPENAI_MODEL_ENV, DEFAULT_OPENAI_MODEL)).strip()
    if not selected_model:
        raise RuntimeError(f"Переменная {OPENAI_MODEL_ENV} не должна быть пустой.")

    if selected_model not in AVAILABLE_OPENAI_MODELS:
        available_models = ", ".join(get_available_model_names())
        raise RuntimeError(f"Модель должна быть одной из: {available_models}.")

    return selected_model


def build_history_repository(user_id: str | None = None) -> MessageHistoryRepository:
    history_file = Path(
        os.getenv(
            AGENT_HISTORY_FILE_ENV,
            str(build_user_memory_file("messages.json", user_id)),
        )
    )
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


def get_user_id(user_id: str | None = None) -> str:
    selected_user_id = user_id if user_id is not None else os.getenv(AGENT_USER_ID_ENV, DEFAULT_USER_ID)
    user_id = selected_user_id.strip()
    if not user_id:
        raise RuntimeError(f"Переменная {AGENT_USER_ID_ENV} не должна быть пустой.")

    if user_id in {".", ".."} or "/" in user_id or "\\" in user_id:
        raise RuntimeError(
            f"Переменная {AGENT_USER_ID_ENV} не должна содержать разделители пути."
        )

    return user_id


def get_available_user_ids() -> list[str]:
    user_ids = {get_user_id()}
    for users_dir in (DEFAULT_MEMORY_DIR, DEFAULT_PROFILES_DIR):
        if not users_dir.exists():
            continue

        for user_dir in users_dir.iterdir():
            if not user_dir.is_dir():
                continue

            try:
                user_ids.add(get_user_id(user_dir.name))
            except RuntimeError:
                continue

    return sorted(user_ids)


def build_user_memory_file(file_name: str, user_id: str | None = None) -> Path:
    return DEFAULT_MEMORY_DIR / get_user_id(user_id) / file_name


def build_user_profile_file(user_id: str | None = None) -> Path:
    return DEFAULT_PROFILES_DIR / get_user_id(user_id) / "profile.md"


def build_user_profile_repository(user_id: str | None = None) -> UserProfileRepository:
    profile_file = Path(
        os.getenv(
            AGENT_USER_PROFILE_FILE_ENV,
            str(build_user_profile_file(user_id)),
        )
    )
    return MarkdownUserProfileRepository(profile_file)


def build_working_memory_repository(user_id: str | None = None) -> WorkingMemoryRepository:
    memory_file = Path(
        os.getenv(
            AGENT_WORKING_MEMORY_FILE_ENV,
            str(build_user_memory_file("working_memory.json", user_id)),
        )
    )
    return JsonWorkingMemoryRepository(memory_file)


def build_long_term_memory_repository(user_id: str | None = None) -> LongTermMemoryRepository:
    memory_file = Path(
        os.getenv(
            AGENT_LONG_TERM_MEMORY_FILE_ENV,
            str(build_user_memory_file("long_term_memory.json", user_id)),
        )
    )
    return JsonLongTermMemoryRepository(memory_file)


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
    raw_strategy = os.getenv(AGENT_CONTEXT_STRATEGY_ENV, ContextStrategy.MEMORY.value)
    try:
        return ContextStrategy.from_value(raw_strategy)
    except ValueError as error:
        supported_values = ", ".join(get_context_strategy_values())
        raise RuntimeError(
            f"Переменная {AGENT_CONTEXT_STRATEGY_ENV} должна быть одной из: {supported_values}."
        ) from error


def build_chat_service(
    context_strategy: ContextStrategy | None = None,
    model_name: str | None = None,
    user_id: str | None = None,
    on_task_stage_changed: Callable[[WorkingMemory], None] | None = None,
) -> ChatService:
    selected_model_name = get_model_name(model_name)
    selected_user_id = get_user_id(user_id)
    return ChatService(
        agent=build_agent(selected_model_name),
        history_repository=build_history_repository(selected_user_id),
        summary_repository=build_summary_repository(),
        summarizer=build_summarizer(selected_model_name),
        facts_repository=build_facts_repository(),
        facts_extractor=build_facts_extractor(selected_model_name),
        branch_repository=build_branch_repository(),
        working_memory_repository=build_working_memory_repository(selected_user_id),
        working_memory_extractor=build_working_memory_extractor(selected_model_name),
        long_term_memory_repository=build_long_term_memory_repository(selected_user_id),
        long_term_memory_extractor=build_long_term_memory_extractor(selected_model_name),
        user_profile_repository=build_user_profile_repository(selected_user_id),
        recent_messages_limit=get_recent_messages_limit(),
        context_strategy=context_strategy or get_context_strategy(),
        on_task_stage_changed=on_task_stage_changed,
        planning_agent=build_planning_agent(selected_model_name),
        execution_agent=build_execution_agent(selected_model_name),
        validation_agent=build_validation_agent(selected_model_name),
        done_agent=build_done_agent(selected_model_name),
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
    print("Команды: /model, /strategy, /clear, /branch, /checkpoint, /new-branch <name>.")

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
            chat_service = handle_command(chat_service, user_message)
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


def handle_command(chat_service: ChatService, command: str) -> ChatService:
    command_parts = command.split(maxsplit=1)
    command_name = command_parts[0]
    command_argument = command_parts[1] if len(command_parts) > 1 else ""

    if command_name == "/model":
        return handle_model_command(chat_service, command_argument)

    if command_name == "/strategy":
        handle_strategy_command(chat_service, command_argument)
        return chat_service

    if command_name == "/clear":
        chat_service.clear_context()
        print(f"Контекст очищен для стратегии {chat_service.get_context_strategy().value}.")
        return chat_service

    if command_name == "/branch":
        handle_branch_command(chat_service, command_argument)
        return chat_service

    if command_name == "/checkpoint":
        branches = chat_service.save_checkpoint()
        print(
            "Checkpoint сохранен: "
            f"{len(branches.checkpoint_messages)} сообщений из ветки {branches.active_branch_id}."
        )
        return chat_service

    if command_name == "/new-branch":
        if not command_argument:
            print("Укажите имя ветки: /new-branch branch_a")
            return chat_service

        try:
            branches = chat_service.create_branch(command_argument)
        except ValueError as error:
            print(f"Ошибка ветки: {error}")
            return chat_service

        print(f"Создана и активирована ветка {branches.active_branch_id}.")
        return chat_service

    print("Неизвестная команда.")
    return chat_service


def handle_model_command(chat_service: ChatService, argument: str) -> ChatService:
    if not argument:
        models = ", ".join(get_available_model_names())
        print(f"Текущая модель: {chat_service.get_model_name()}.")
        print(f"Доступные модели: {models}.")
        return chat_service

    try:
        model_name = get_model_name(argument)
    except RuntimeError as error:
        print(f"Ошибка модели: {error}")
        return chat_service

    updated_chat_service = build_chat_service(
        context_strategy=chat_service.get_context_strategy(),
        model_name=model_name,
    )
    print(f"Модель переключена на {model_name}.")
    return updated_chat_service


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
