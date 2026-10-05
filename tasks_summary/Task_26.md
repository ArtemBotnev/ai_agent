# Task 26: локальный LLM через Ollama

Дата: 2026-10-05

## Что сделали

Добавили возможность запускать агента на локальной LLM через Ollama.

Поддержка сделана как отдельный provider:

```text
openai
ollama
```

OpenAI остался поведением по умолчанию. Для Ollama используется упрощённый
режим через стратегию `summary`, чтобы локальная модель не зависела от
сложного `memory` workflow с multi-agent planning, JSON subagent-ответами и
валидацией артефактов.

Если выбран provider `ollama` и переменная `AGENT_CONTEXT_STRATEGY` явно не
задана, стратегия по умолчанию становится:

```text
summary
```

Web-интерфейс не меняли.

## Ollama agent

В `agent.py` добавлен `OllamaLlmAgent`.

Он реализует тот же application-level контракт, что и OpenAI agent:

```text
count_tokens(messages, context="")
ask(messages, context="") -> LlmAnswer
```

Для генерации используется Ollama chat API:

```text
POST /api/chat
```

Запрос отправляется без streaming:

```json
{
  "model": "llama3.1:8b",
  "messages": [...],
  "stream": false
}
```

System prompt и дополнительный context добавляются как первое `system`
сообщение.

Подсчёт токенов для Ollama сделан ограниченно:

- `count_tokens(...)` возвращает `0`, потому что в текущей интеграции нет
  отдельного preflight token-count endpoint как у OpenAI;
- токены ответа берутся из поля `eval_count`, если Ollama вернула его в ответе.

## Конфигурация

Добавлены env-переменные:

```text
AGENT_LLM_PROVIDER=openai|ollama
AGENT_OLLAMA_URL=http://127.0.0.1:11434
AGENT_OLLAMA_MODEL=llama3.1:8b
AGENT_OLLAMA_MODELS=llama3.1:8b,qwen2.5:7b
```

Модель Ollama по умолчанию:

```text
llama3.1:8b
```

Список доступных моделей для UI и CLI берётся только из env:

```text
AGENT_OLLAMA_MODELS
```

Если `AGENT_OLLAMA_MODEL` не задан, выбирается первая модель из
`AGENT_OLLAMA_MODELS`. Если список моделей не задан, используется дефолтная
модель `llama3.1:8b`.

## Сборка зависимостей

В `main.py` добавлены:

- `get_llm_provider(provider=None)`;
- `get_ollama_base_url()`;
- provider-aware `get_available_model_names(provider=None)`;
- provider-aware `get_model_name(model_name=None, provider=None)`;
- `build_llm_agent(...)`.

Builder-функции теперь могут создавать либо OpenAI, либо Ollama agent:

- `build_agent(...)`;
- `build_summarizer(...)`;
- `build_facts_extractor(...)`;
- `build_working_memory_extractor(...)`;
- `build_long_term_memory_extractor(...)`;
- `build_planning_agent(...)`;
- `build_execution_agent(...)`;
- `build_validation_agent(...)`;
- `build_done_agent(...)`.

Это позволяет собрать `ChatService` для Ollama без `OPENAI_API_KEY`, если
выбрана стратегия `summary`.

## CLI

Добавлена команда:

```text
/provider
/provider openai
/provider ollama
```

Команда `/model` теперь показывает и переключает модели в рамках текущего
provider.

Для Ollama команда `/provider ollama` дополнительно показывает текущий
`AGENT_OLLAMA_URL`.

## PyQt

В PyQt UI добавлен выбор provider:

```text
Provider: openai | ollama
```

При смене provider:

- список моделей пересобирается из соответствующего источника;
- для OpenAI используется статический список OpenAI-моделей;
- для Ollama используется `AGENT_OLLAMA_MODELS`;
- если выбран Ollama и `AGENT_CONTEXT_STRATEGY` явно не задан, UI переключает
  стратегию на `Summary`.

## Скрипт запуска Ollama

Добавлен корневой скрипт:

```text
start_ollama_llm.sh
```

Скрипт:

- проверяет наличие команды `ollama`;
- запускает `ollama serve`, если сервер ещё не отвечает;
- ждёт готовности `http://127.0.0.1:11434/api/tags`;
- проверяет наличие выбранной модели;
- при необходимости выполняет `ollama pull`;
- печатает env-переменные для запуска проекта с Ollama.

Модель выбирается в порядке:

```text
AGENT_OLLAMA_MODEL
OLLAMA_LLM_MODEL
llama3.1:8b
```

## Изменённые файлы

Основные изменения:

```text
agent.py
main.py
ui/pyqt_app.py
start_ollama_llm.sh
```

Добавлен summary-файл:

```text
tasks_summary/Task_26.md
```

## Проверки

Выполнены проверки:

```text
python3 -m py_compile agent.py main.py ui/pyqt_app.py application/chat/chat_service.py
python3 -c "import agent, main, web.server, ui.pyqt_app; print('imports ok')"
git diff --check
```

Дополнительно проверены сценарии без реального запроса к Ollama:

- `ChatService` собирается с `AGENT_LLM_PROVIDER=ollama` без `OPENAI_API_KEY`;
- для Ollama без явного `AGENT_CONTEXT_STRATEGY` выбирается стратегия
  `summary`;
- при пустом `AGENT_OLLAMA_MODEL` выбирается первая модель из
  `AGENT_OLLAMA_MODELS`;
- при заданном `AGENT_OLLAMA_MODEL` используется выбранная модель;
- дефолтная Ollama-модель — `llama3.1:8b`.
