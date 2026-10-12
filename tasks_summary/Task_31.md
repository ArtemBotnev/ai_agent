# Task 31: developer assistant с RAG и MCP project context

Дата: 2026-10-12

## Что сделали

Добавили project assistant для ответов на вопросы о подключенном локальном
проекте. Ассистент использует:

```text
README.md
project/docs
MCP project context
SQLite RAG index
Ollama embeddings
```

Основной пользовательский сценарий:

```text
/project-rag build
/help какая структура проекта?
```

Команда `/help` ищет релевантную документацию в RAG-индексе, добавляет контекст
проекта через MCP и отвечает через текущий выбранный LLM provider.

## Конфигурация project assistant

Добавлен отдельный конфиг:

```text
agent_config/project_assistant.example.yaml
agent_config/project_assistant.local.yaml
```

Публичный файл `project_assistant.example.yaml` хранится в git как шаблон.
Реальный `project_assistant.local.yaml` содержит локальный путь к выбранному
проекту и скрывается уже существующим правилом:

```text
/agent_config/*.local.yaml
```

Основные настройки:

```yaml
project_assistant:
  project_path: /path/to/project
  docs_paths:
    - README.md
    - project/docs
  index_file: rag/project_rag_index.sqlite

  mcp:
    enabled: true
    server_url: <mcp-server-url>
    timeout_seconds: 10

  embedding:
    provider: ollama
    base_url: <ollama-base-url>
    model: nomic-embed-text
```

RAG-индекс вынесен из `history` в отдельную runtime-папку:

```text
rag/project_rag_index.sqlite
```

Папка `/rag` добавлена в `.gitignore`.

## Загрузка конфигурации

Добавлен модуль:

```text
config/project_assistant_config.py
```

Он читает `AGENT_PROJECT_ASSISTANT_CONFIG_FILE` или дефолтный
`agent_config/project_assistant.local.yaml`, валидирует типы и поддерживает
fallback-парсер простого YAML-формата, если `PyYAML` недоступен.

Fallback YAML-парсер теперь умеет читать:

```text
bool
int
float
null
строки
списки
вложенные объекты
```

Это исправило запуск `scripts/start_project_ollama.sh` в окружениях, где
`PyYAML` не установлен.

## RAG

Добавлен пакет:

```text
application/project_help/
```

Ключевые компоненты:

```text
embeddings.py
rag_index.py
project_help_service.py
project_assistant_commands.py
tokenizer.py
```

RAG реализован на стороне агента:

1. Загружаются `README.md` и файлы из `project/docs` выбранного проекта.
2. Документы режутся на чанки с overlap.
3. Embeddings строятся через Ollama `/api/embed`.
4. Чанки и embeddings сохраняются в SQLite.
5. `/help` embedding-ит вопрос, ищет похожие чанки и отправляет их в LLM.

Поддержан fallback embedding provider:

```text
hashing
```

Он нужен для локальной проверки RAG-логики без Ollama.

## MCP project context

Добавлен adapter:

```text
infrastructure/project_context_client.py
```

Поддержаны два режима:

```text
LocalProjectContextClient
McpProjectContextClient
```

Если `project_assistant.mcp.enabled: false`, используется локальный read-only
adapter, который получает ветку через:

```bash
git branch --show-current
git rev-parse --abbrev-ref HEAD
```

Если `project_assistant.mcp.enabled: true`, используется MCP Streamable HTTP
server. Реализована поддержка:

```text
POST /mcp
initialize
notifications/initialized
mcp-session-id
text/event-stream responses
tools/call
```

Сейчас используется tool:

```text
get_git_branch
```

Через MCP проверено получение ветки для локального тестового проекта:

```text
Git-ветка получена через MCP
MCP: включен
```

## Команды CLI

В `main.py` добавлены команды:

```text
/project
/project-rag build
/project-rag status
/help <вопрос>
```

Команда `/project` показывает:

```text
project_path
git branch
MCP status
config file
RAG index status
```

Команда `/project-rag build` собирает SQLite RAG-индекс.

Команда `/project-rag status` показывает количество документов и чанков.

Команда `/help <вопрос>` делает одноразовый LLM-запрос через:

```text
ChatService.answer_once(...)
```

Такой запрос не записывается в обычную историю диалога.

## Общий command service

Project-assistant slash-команды вынесены в application layer:

```text
ProjectAssistantCommandService
```

CLI и PyQt UI используют один и тот же сервис, чтобы логика `/project`,
`/project-rag` и `/help` не дублировалась между интерфейсами.

## PyQt UI

В PyQt UI добавлена поддержка project-assistant команд в обычном поле ввода:

```text
/project
/project-rag build
/project-rag status
/help какая структура проекта?
```

Добавлена кнопка:

```text
Собрать RAG
```

Она запускает тот же путь, что и команда:

```text
/project-rag build
```

Также исправлен lifecycle `ChatWorker`: ссылка на worker очищается после
завершения, чтобы кнопки UI корректно включались обратно.

## Запуск Ollama для embeddings

Добавлен скрипт:

```text
scripts/start_project_ollama.sh
```

Он читает `project_assistant.local.yaml`, берет:

```text
embedding.base_url
embedding.model
```

запускает `ollama serve`, если Ollama еще не отвечает, и выполняет:

```bash
ollama pull <embedding.model>
```

По умолчанию используется:

```text
nomic-embed-text
```

## Документация

Добавлены:

```text
README.md
README.ru.md
project/docs/architecture.md
project/docs/configuration.md
```

Английский README оставлен как основной. Русский README добавлен отдельным
файлом рядом:

```text
README.ru.md
```

Документация описывает:

- структуру проекта;
- запуск CLI и PyQt UI;
- команды project assistant;
- сборку RAG;
- MCP-настройки;
- расположение SQLite RAG-индекса;
- отличие MCP от RAG.

## Проверки

Запускались проверки:

```bash
python -m compileall config application infrastructure main.py ui/pyqt_app.py
bash -n scripts/start_project_ollama.sh
```

Проверялся fallback YAML parser без `PyYAML`.

Проверялся RAG build через `hashing` embedding provider во временный SQLite.

Проверялась подготовка `/help`:

```text
MCP branch context
retrieved documentation chunks
LLM prompt/context
```

Полный `/help` был проверен на локальном тестовом проекте с текущим provider:

```text
provider: ollama
model: llama3.1:8b
```

Ответ пришел примерно за 75 секунд, что подтвердило работоспособность
RAG+MCP+LLM цепочки, но показало, что локальная модель отвечает медленно без
streaming.
