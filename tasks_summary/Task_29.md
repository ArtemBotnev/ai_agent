# Task 29: конфигурация агента через agent_config

Дата: 2026-10-08

## Что сделали

Вынесли основные настройки LLM, prompt-файлы и пользовательские пути в
конфигурационную директорию:

```text
agent_config/
  llm.yaml
  prompts/
  profiles/
  invariants/
```

`agent_config/llm.yaml` стал основным YAML-файлом для выбора provider,
моделей, Ollama runtime options, system prompt markdown-файлов и директорий
memory/profile/invariants.

## Загрузка конфигурации

Добавлен модуль:

```text
config/agent_config.py
```

Он читает `AGENT_CONFIG_FILE` или дефолтный `agent_config/llm.yaml`, валидирует
базовые типы и параметры Ollama, а также поддерживает fallback-парсер простого
YAML-формата, если `PyYAML` недоступен.

Приоритет настроек сохранён совместимым:

```text
явный аргумент
env override
yaml config
старый дефолт
```

## System prompts

System prompts вынесены в markdown-файлы:

```text
agent_config/prompts/example/ollama_system.md
agent_config/prompts/example/openai_system.md
```

Provider-specific prompt используется при создании OpenAI и Ollama LLM-agent.
Внутренние workflow-агенты продолжают использовать свои специализированные
system prompts из кода.

## Profiles and invariants

Профили и invariants перенесены в новую структуру:

```text
agent_config/profiles/
agent_config/invariants/
```

Пользовательские директории внутри `agent_config` добавлены в `.gitignore`, как
и пользовательские prompt-файлы. Примерные prompt-файлы оставлены в git через
исключение для `agent_config/prompts/example`.

## Ollama options

Добавлена dataclass-конфигурация `OllamaOptions` и передача runtime options в
Ollama `/api/chat` через поле `options`:

```json
{
  "options": {
    "temperature": 0.2,
    "num_predict": 1024,
    "num_ctx": 4096
  }
}
```

Поддержаны параметры:

```text
temperature
num_predict
num_ctx
top_k
top_p
repeat_penalty
seed
```

Для каждого параметра добавлена базовая валидация диапазонов.

## Response duration

В application-level ответ добавлено поле:

```text
duration_seconds
```

Для OpenAI время считается по wall-clock вокруг HTTP-запроса. Для Ollama сначала
используется `total_duration` из API-ответа, а если его нет, применяется
wall-clock fallback.

CLI, PyQt UI, web API и web UI показывают время ответа рядом с токенами.

## Запуск Ollama

`start_ollama_llm.sh` теперь читает модель, список моделей и base URL из
`agent_config/llm.yaml`, если они не переопределены через env.

В PyQt UI добавлена кнопка:

```text
Запустить Ollama
```

Она проверяет наличие `ollama`, запускает `ollama serve` при необходимости,
ждёт готовности `/api/tags`, проверяет наличие выбранной модели и выполняет
`ollama pull`, если модель не установлена.

## Проверки

В summary-файл восстановлены итоги по уже сделанному коммиту. Дополнительные
runtime-проверки при восстановлении этого описания не запускались.
