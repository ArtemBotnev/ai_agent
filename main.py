import os
import sys
from collections.abc import Callable
from pathlib import Path

from agent import (
    AVAILABLE_OPENAI_MODELS,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    OLLAMA_MODEL_ENV,
    OLLAMA_MODELS_ENV,
    OLLAMA_BASE_URL_ENV,
    OPENAI_API_KEY_ENV,
    OPENAI_MODEL_ENV,
    PLANNING_ANALYST_SYSTEM_PROMPT,
    LONG_TERM_MEMORY_SYSTEM_PROMPT,
    DONE_AGENT_SYSTEM_PROMPT,
    DebatingPlanningAgent,
    OllamaLlmAgent,
    PLANNING_DEVELOPER_SYSTEM_PROMPT,
    PLANNING_DESIGNER_SYSTEM_PROMPT,
    EXECUTION_AGENT_SYSTEM_PROMPT,
    PLANNING_AGENT_SYSTEM_PROMPT,
    PLANNING_SYNTHESIZER_SYSTEM_PROMPT,
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
from application.memory.invariants_repository import InvariantsRepository
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
from infrastructure.markdown_invariants_repository import MarkdownInvariantsRepository
from infrastructure.markdown_user_profile_repository import MarkdownUserProfileRepository

DEFAULT_SUMMARY_FILE = Path("history/summary.json")
DEFAULT_FACTS_FILE = Path("history/facts.json")
DEFAULT_BRANCHES_FILE = Path("history/branches.json")
DEFAULT_USER_ID = "1"
DEFAULT_MEMORY_DIR = Path("memory/users")
DEFAULT_PROFILES_DIR = Path("profiles/users")
DEFAULT_INVARIANTS_DIR = Path("invariants/users")
AGENT_HISTORY_FILE_ENV = "AGENT_HISTORY_FILE"
AGENT_SUMMARY_FILE_ENV = "AGENT_SUMMARY_FILE"
AGENT_FACTS_FILE_ENV = "AGENT_FACTS_FILE"
AGENT_BRANCHES_FILE_ENV = "AGENT_BRANCHES_FILE"
AGENT_WORKING_MEMORY_FILE_ENV = "AGENT_WORKING_MEMORY_FILE"
AGENT_LONG_TERM_MEMORY_FILE_ENV = "AGENT_LONG_TERM_MEMORY_FILE"
AGENT_USER_PROFILE_FILE_ENV = "AGENT_USER_PROFILE_FILE"
AGENT_INVARIANTS_FILE_ENV = "AGENT_INVARIANTS_FILE"
AGENT_USER_ID_ENV = "AGENT_USER_ID"
AGENT_RECENT_MESSAGES_LIMIT_ENV = "AGENT_RECENT_MESSAGES_LIMIT"
AGENT_CONTEXT_STRATEGY_ENV = "AGENT_CONTEXT_STRATEGY"
AGENT_PLANNING_MODE_ENV = "AGENT_PLANNING_MODE"
AGENT_LLM_PROVIDER_ENV = "AGENT_LLM_PROVIDER"
LLM_PROVIDER_OPENAI = "openai"
LLM_PROVIDER_OLLAMA = "ollama"
LLM_PROVIDERS = (LLM_PROVIDER_OPENAI, LLM_PROVIDER_OLLAMA)
PLANNING_MODE_SINGLE = "single"
PLANNING_MODE_DEBATE = "debate"
PLANNING_MODES = (PLANNING_MODE_SINGLE, PLANNING_MODE_DEBATE)


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


def build_llm_agent(
    model_name: str | None = None,
    *,
    provider: str | None = None,
    system_prompt: str | None = None,
) -> SimpleLlmAgent | OllamaLlmAgent:
    selected_provider = get_llm_provider(provider)
    selected_model_name = get_model_name(model_name, selected_provider)
    if selected_provider == LLM_PROVIDER_OLLAMA:
        return OllamaLlmAgent(
            model=selected_model_name,
            base_url=get_ollama_base_url(),
            system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        )

    return SimpleLlmAgent(
        api_key=get_api_key(),
        model=selected_model_name,
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
    )


def build_agent(model_name: str | None = None, provider: str | None = None) -> SimpleLlmAgent | OllamaLlmAgent:
    return build_llm_agent(model_name, provider=provider)


def build_summarizer(model_name: str | None = None, provider: str | None = None) -> ConversationSummarizer:
    summary_agent = build_llm_agent(
        model_name,
        provider=provider,
        system_prompt=SUMMARY_SYSTEM_PROMPT,
    )
    return SimpleConversationSummarizer(summary_agent)


def build_facts_extractor(model_name: str | None = None, provider: str | None = None) -> StickyFactsExtractor:
    facts_agent = build_llm_agent(
        model_name,
        provider=provider,
        system_prompt=STICKY_FACTS_SYSTEM_PROMPT,
    )
    return SimpleStickyFactsExtractor(facts_agent)


def build_working_memory_extractor(model_name: str | None = None, provider: str | None = None) -> WorkingMemoryExtractor:
    working_memory_agent = build_llm_agent(
        model_name,
        provider=provider,
        system_prompt=WORKING_MEMORY_SYSTEM_PROMPT,
    )
    return SimpleWorkingMemoryExtractor(working_memory_agent)


def build_long_term_memory_extractor(model_name: str | None = None, provider: str | None = None) -> LongTermMemoryExtractor:
    long_term_memory_agent = build_llm_agent(
        model_name,
        provider=provider,
        system_prompt=LONG_TERM_MEMORY_SYSTEM_PROMPT,
    )
    return SimpleLongTermMemoryExtractor(long_term_memory_agent)


def build_planning_agent(model_name: str | None = None, provider: str | None = None) -> PlanningAgent:
    selected_provider = get_llm_provider(provider)
    selected_model_name = get_model_name(model_name, selected_provider)
    single_planning_agent = SimplePlanningAgent(
        build_llm_agent(
            selected_model_name,
            provider=selected_provider,
            system_prompt=PLANNING_AGENT_SYSTEM_PROMPT,
        )
    )
    if get_planning_mode() == PLANNING_MODE_SINGLE:
        return single_planning_agent

    analyst_agent = build_llm_agent(
        selected_model_name,
        provider=selected_provider,
        system_prompt=PLANNING_ANALYST_SYSTEM_PROMPT,
    )
    developer_agent = build_llm_agent(
        selected_model_name,
        provider=selected_provider,
        system_prompt=PLANNING_DEVELOPER_SYSTEM_PROMPT,
    )
    designer_agent = build_llm_agent(
        selected_model_name,
        provider=selected_provider,
        system_prompt=PLANNING_DESIGNER_SYSTEM_PROMPT,
    )
    synthesizer_agent = build_llm_agent(
        selected_model_name,
        provider=selected_provider,
        system_prompt=PLANNING_SYNTHESIZER_SYSTEM_PROMPT,
    )
    return DebatingPlanningAgent(
        analyst_agent=analyst_agent,
        developer_agent=developer_agent,
        designer_agent=designer_agent,
        synthesizer_agent=synthesizer_agent,
        fallback_agent=single_planning_agent,
    )


def build_execution_agent(model_name: str | None = None, provider: str | None = None) -> ExecutionAgent:
    execution_agent = build_llm_agent(
        model_name,
        provider=provider,
        system_prompt=EXECUTION_AGENT_SYSTEM_PROMPT,
    )
    return SimpleExecutionAgent(execution_agent)


def build_validation_agent(model_name: str | None = None, provider: str | None = None) -> ValidationAgent:
    validation_agent = build_llm_agent(
        model_name,
        provider=provider,
        system_prompt=VALIDATION_AGENT_SYSTEM_PROMPT,
    )
    return SimpleValidationAgent(validation_agent)


def build_done_agent(model_name: str | None = None, provider: str | None = None) -> DoneAgent:
    done_agent = build_llm_agent(
        model_name,
        provider=provider,
        system_prompt=DONE_AGENT_SYSTEM_PROMPT,
    )
    return SimpleDoneAgent(done_agent)


def get_api_key() -> str:
    api_key = os.getenv(OPENAI_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"Перед запуском чата задайте переменную окружения {OPENAI_API_KEY_ENV}.")

    return api_key


def get_llm_provider(provider: str | None = None) -> str:
    selected_provider = (provider or os.getenv(AGENT_LLM_PROVIDER_ENV, LLM_PROVIDER_OPENAI)).strip().lower()
    if selected_provider not in LLM_PROVIDERS:
        available_providers = ", ".join(LLM_PROVIDERS)
        raise RuntimeError(f"Переменная {AGENT_LLM_PROVIDER_ENV} должна быть одной из: {available_providers}.")

    return selected_provider


def get_ollama_base_url() -> str:
    base_url = os.getenv(OLLAMA_BASE_URL_ENV, DEFAULT_OLLAMA_BASE_URL).strip()
    if not base_url:
        raise RuntimeError(f"Переменная {OLLAMA_BASE_URL_ENV} не должна быть пустой.")

    return base_url


def get_available_model_names(provider: str | None = None) -> list[str]:
    selected_provider = get_llm_provider(provider)
    if selected_provider == LLM_PROVIDER_OLLAMA:
        raw_models = os.getenv(OLLAMA_MODELS_ENV, "").strip()
        model_names = [model.strip() for model in raw_models.split(",") if model.strip()]
        selected_model = os.getenv(OLLAMA_MODEL_ENV, "").strip()
        if selected_model and selected_model not in model_names:
            model_names.insert(0, selected_model)

        return model_names or [DEFAULT_OLLAMA_MODEL]

    return list(AVAILABLE_OPENAI_MODELS)


def get_model_name(model_name: str | None = None, provider: str | None = None) -> str:
    selected_provider = get_llm_provider(provider)
    available_model_names = get_available_model_names(selected_provider)
    default_model = (
        os.getenv(OLLAMA_MODEL_ENV, available_model_names[0])
        if selected_provider == LLM_PROVIDER_OLLAMA
        else os.getenv(OPENAI_MODEL_ENV, DEFAULT_OPENAI_MODEL)
    )
    selected_model = (model_name or default_model).strip()
    if not selected_model:
        model_env = OLLAMA_MODEL_ENV if selected_provider == LLM_PROVIDER_OLLAMA else OPENAI_MODEL_ENV
        raise RuntimeError(f"Переменная {model_env} не должна быть пустой.")

    if selected_model not in available_model_names:
        available_models = ", ".join(available_model_names)
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
    for users_dir in (DEFAULT_MEMORY_DIR, DEFAULT_PROFILES_DIR, DEFAULT_INVARIANTS_DIR):
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


def build_user_invariants_file(user_id: str | None = None) -> Path:
    return DEFAULT_INVARIANTS_DIR / get_user_id(user_id) / "invariants.md"


def build_user_profile_repository(user_id: str | None = None) -> UserProfileRepository:
    profile_file = Path(
        os.getenv(
            AGENT_USER_PROFILE_FILE_ENV,
            str(build_user_profile_file(user_id)),
        )
    )
    return MarkdownUserProfileRepository(profile_file)


def build_invariants_repository(user_id: str | None = None) -> InvariantsRepository:
    invariants_file = Path(
        os.getenv(
            AGENT_INVARIANTS_FILE_ENV,
            str(build_user_invariants_file(user_id)),
        )
    )
    return MarkdownInvariantsRepository(invariants_file)


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


def get_context_strategy(provider: str | None = None) -> ContextStrategy:
    if AGENT_CONTEXT_STRATEGY_ENV in os.environ:
        raw_strategy = os.getenv(AGENT_CONTEXT_STRATEGY_ENV, ContextStrategy.MEMORY.value)
    elif get_llm_provider(provider) == LLM_PROVIDER_OLLAMA:
        raw_strategy = ContextStrategy.SUMMARY.value
    else:
        raw_strategy = ContextStrategy.MEMORY.value

    try:
        return ContextStrategy.from_value(raw_strategy)
    except ValueError as error:
        supported_values = ", ".join(get_context_strategy_values())
        raise RuntimeError(
            f"Переменная {AGENT_CONTEXT_STRATEGY_ENV} должна быть одной из: {supported_values}."
        ) from error


def get_planning_mode() -> str:
    planning_mode = os.getenv(AGENT_PLANNING_MODE_ENV, PLANNING_MODE_DEBATE).strip().lower()
    if planning_mode not in PLANNING_MODES:
        available_modes = ", ".join(PLANNING_MODES)
        raise RuntimeError(f"Переменная {AGENT_PLANNING_MODE_ENV} должна быть одной из: {available_modes}.")

    return planning_mode


def build_chat_service(
    context_strategy: ContextStrategy | None = None,
    model_name: str | None = None,
    user_id: str | None = None,
    on_task_stage_changed: Callable[[WorkingMemory], None] | None = None,
    provider: str | None = None,
) -> ChatService:
    selected_provider = get_llm_provider(provider)
    selected_model_name = get_model_name(model_name, selected_provider)
    selected_user_id = get_user_id(user_id)
    selected_context_strategy = context_strategy or get_context_strategy(selected_provider)
    return ChatService(
        agent=build_agent(selected_model_name, selected_provider),
        history_repository=build_history_repository(selected_user_id),
        summary_repository=build_summary_repository(),
        summarizer=build_summarizer(selected_model_name, selected_provider),
        facts_repository=build_facts_repository(),
        facts_extractor=build_facts_extractor(selected_model_name, selected_provider),
        branch_repository=build_branch_repository(),
        working_memory_repository=build_working_memory_repository(selected_user_id),
        working_memory_extractor=build_working_memory_extractor(selected_model_name, selected_provider),
        long_term_memory_repository=build_long_term_memory_repository(selected_user_id),
        long_term_memory_extractor=build_long_term_memory_extractor(selected_model_name, selected_provider),
        user_profile_repository=build_user_profile_repository(selected_user_id),
        invariants_repository=build_invariants_repository(selected_user_id),
        recent_messages_limit=get_recent_messages_limit(),
        context_strategy=selected_context_strategy,
        on_task_stage_changed=on_task_stage_changed,
        planning_agent=build_planning_agent(selected_model_name, selected_provider),
        execution_agent=build_execution_agent(selected_model_name, selected_provider),
        validation_agent=build_validation_agent(selected_model_name, selected_provider),
        done_agent=build_done_agent(selected_model_name, selected_provider),
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
    print("Команды: /provider, /model, /strategy, /clear, /branch, /checkpoint, /new-branch <name>.")

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

    if command_name == "/provider":
        return handle_provider_command(chat_service, command_argument)

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
    provider = get_chat_service_provider(chat_service)
    if not argument:
        models = ", ".join(get_available_model_names(provider))
        print(f"Текущая модель: {chat_service.get_model_name()}.")
        print(f"Текущий provider: {provider}.")
        print(f"Доступные модели: {models}.")
        return chat_service

    try:
        model_name = get_model_name(argument, provider)
    except RuntimeError as error:
        print(f"Ошибка модели: {error}")
        return chat_service

    updated_chat_service = build_chat_service(
        context_strategy=chat_service.get_context_strategy(),
        model_name=model_name,
        provider=provider,
    )
    print(f"Модель переключена на {model_name}.")
    return updated_chat_service


def handle_provider_command(chat_service: ChatService, argument: str) -> ChatService:
    if not argument:
        providers = ", ".join(LLM_PROVIDERS)
        print(f"Текущий provider: {get_chat_service_provider(chat_service)}.")
        print(f"Доступные provider: {providers}.")
        return chat_service

    try:
        provider = get_llm_provider(argument)
        model_name = get_model_name(provider=provider)
    except RuntimeError as error:
        print(f"Ошибка provider: {error}")
        return chat_service

    context_strategy = chat_service.get_context_strategy()
    if provider == LLM_PROVIDER_OLLAMA and AGENT_CONTEXT_STRATEGY_ENV not in os.environ:
        context_strategy = ContextStrategy.SUMMARY

    updated_chat_service = build_chat_service(
        context_strategy=context_strategy,
        model_name=model_name,
        provider=provider,
    )
    print(f"Provider переключен на {provider}. Модель: {model_name}.")
    if provider == LLM_PROVIDER_OLLAMA:
        print(f"Ollama URL: {get_ollama_base_url()}.")
    return updated_chat_service


def get_chat_service_provider(chat_service: ChatService) -> str:
    agent = getattr(chat_service, "_agent", None)
    if isinstance(agent, OllamaLlmAgent):
        return LLM_PROVIDER_OLLAMA

    return LLM_PROVIDER_OPENAI


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
