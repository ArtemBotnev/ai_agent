# Task 30: cloud provider для Ollama-compatible LLM

Дата: 2026-10-09

## Что сделали

Добавили третий LLM provider:

```text
openai
ollama
cloud
```

`cloud` использует тот же Ollama-compatible `/api/chat` контракт, что и
локальная Ollama-интеграция, но берёт base URL, модель и список моделей из
отдельной cloud-конфигурации.

## Конфигурация

В `agent_config/llm.yaml` добавлена секция:

```text
cloud
```

Она содержит:

- ссылку на приватный config-файл;
- fallback-модель;
- список моделей для CLI/UI;
- Ollama-compatible runtime options;
- system prompt file.

Добавлен пример приватного конфига:

```text
agent_config/llm.local.example.yaml
```

Реальный файл:

```text
agent_config/llm.local.yaml
```

добавлен в `.gitignore`, как и остальные `*.local.yaml` внутри
`agent_config`.

## Private config merge

`config/agent_config.py` теперь умеет читать приватный cloud-конфиг из поля:

```text
cloud.config_file
```

Если файл существует, его секция `cloud` накладывается поверх публичной секции
из `agent_config/llm.yaml`. Это позволяет хранить настоящий cloud endpoint вне
git, а публичный YAML оставлять с безопасными placeholder-значениями.

## Runtime support

В `main.py` добавлены cloud-specific env overrides:

```text
AGENT_CLOUD_URL
AGENT_CLOUD_MODEL
AGENT_CLOUD_MODELS
```

Создан общий путь для Ollama-compatible providers:

```text
uses_ollama_chat_api(provider)
get_ollama_compatible_base_url(provider)
get_ollama_compatible_options(provider)
```

`build_llm_agent(...)` теперь создаёт `OllamaLlmAgent` и для локального
`ollama`, и для `cloud`.

Для `cloud`, как и для `ollama`, стратегия по умолчанию переключается на
`summary`, если `AGENT_CONTEXT_STRATEGY` явно не задан.

## CLI and service state

`ChatService` теперь хранит выбранный provider, чтобы команды CLI могли
корректно отличать локальную Ollama-интеграцию от cloud-интеграции, хотя обе
используют один `OllamaLlmAgent`.

Команда `/provider cloud` пересобирает сервис с cloud provider и summary
strategy по умолчанию.

## PyQt UI

В PyQt UI добавлена кнопка:

```text
Проверить облако
```

Кнопка видна только для provider `cloud`.

Проверка выполняет короткий non-streaming запрос в endpoint:

```text
POST /api/chat
```

Если endpoint возвращает текстовый ответ в формате Ollama-compatible API, UI
показывает сообщение, что облако доступно и какая модель используется.

## Проверки

В summary-файл восстановлены итоги по уже сделанному коммиту. Дополнительные
runtime-проверки при восстановлении этого описания не запускались.
