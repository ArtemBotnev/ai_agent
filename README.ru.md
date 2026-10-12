# AI Second Developer Assistant

AI Second — Python-проект ассистента разработчика с CLI и PyQt-интерфейсом. Он поддерживает OpenAI, локальную Ollama и Ollama-compatible cloud provider. Ассистент хранит историю диалога, summary, sticky facts, working memory, long-term memory, профиль пользователя, invariants и ветки диалога.

## Основные Папки

- `main.py` собирает `ChatService` и обрабатывает CLI-команды.
- `agent.py` содержит OpenAI и Ollama-compatible LLM-клиенты, а также простые workflow-агенты.
- `domain` содержит доменные модели: сообщения, ветки, память, summary, профиль пользователя и invariants.
- `application` содержит сценарии приложения: чат, память, summary, project help и workflow.
- `infrastructure` содержит JSON/Markdown-репозитории и adapter доступа к контексту проекта.
- `config` загружает YAML-конфиги.
- `agent_config` хранит публичные примеры и безопасные настройки.
- `ui` содержит PyQt-приложение.
- `web` содержит web server entry point.
- `project/docs` содержит документацию, которая входит в RAG.

## Быстрый Запуск

Установить зависимости:

```bash
pip install -r requirements.txt
```

Запустить CLI:

```bash
python main.py
```

Запустить PyQt UI:

```bash
python -m ui.pyqt_app
```

Перед сборкой project RAG запустить Ollama и скачать embedding-модель:

```bash
./scripts/start_project_ollama.sh
```

После этого в CLI или UI:

```text
/project-rag build
/help какая структура проекта?
```

## Команды CLI

- `/provider` показывает или переключает LLM provider.
- `/model` показывает или переключает модель текущего provider.
- `/strategy` показывает или переключает стратегию контекста.
- `/clear` очищает контекст активной стратегии.
- `/branch`, `/checkpoint`, `/new-branch <name>` управляют ветками диалога.
- `/project` показывает подключенный проект, git-ветку, MCP-статус и RAG-статус.
- `/project-rag build` собирает SQLite RAG-индекс по документации проекта.
- `/project-rag status` показывает статус RAG-индекса.
- `/help <вопрос>` отвечает на вопросы о подключенном проекте через RAG и project context.

## PyQt UI

В UI можно писать project-assistant команды прямо в обычное поле ввода:

```text
/project
/project-rag build
/project-rag status
/help какая структура проекта?
```

Также в UI есть кнопка `Собрать RAG`. Она запускает тот же путь, что и команда:

```text
/project-rag build
```

## Project Assistant

Project assistant настраивается через приватный файл:

```text
agent_config/project_assistant.local.yaml
```

Публичный пример:

```text
agent_config/project_assistant.example.yaml
```

Основные поля:

- `project_path` — путь к локальному репозиторию, про который ассистент должен отвечать.
- `docs_paths` — список файлов или папок документации относительно `project_path`.
- `index_file` — путь к SQLite RAG-индексу.
- `mcp.enabled` — включает получение project context через MCP.
- `mcp.server_url` — адрес MCP Streamable HTTP server.
- `embedding.provider` — provider для embeddings, обычно `ollama`.
- `embedding.model` — embedding-модель Ollama, например `nomic-embed-text`.
- `retrieval.top_k` — сколько чанков документации передавать в `/help`.

По умолчанию RAG-индекс хранится отдельно от истории чата:

```text
rag/project_rag_index.sqlite
```

Папка `rag` игнорируется git.

## MCP

Если в `project_assistant.local.yaml` включено:

```yaml
mcp:
  enabled: true
  server_url: http://localhost:8000
  timeout_seconds: 10
```

то ассистент получает project context через MCP. Сейчас используется tool `get_git_branch`, чтобы показать текущую git-ветку в `/project` и добавить ее в контекст `/help`.

Если `mcp.enabled: false`, используется локальный adapter, который получает ветку через read-only git-команды.

## RAG

Сборка RAG:

```text
/project-rag build
```

Что происходит:

1. Ассистент читает `README.md` и `project/docs` выбранного проекта.
2. Документы режутся на чанки.
3. Чанки отправляются в Ollama embedding API.
4. Embeddings и тексты сохраняются в SQLite.
5. Команда `/help` ищет релевантные чанки и передает их выбранной LLM.

RAG находится на стороне агента. MCP не строит embeddings и не вызывает LLM.

## Конфиги

LLM provider настраивается здесь:

```text
agent_config/llm.yaml
```

Приватные cloud-настройки:

```text
agent_config/llm.local.yaml
```

Project assistant:

```text
agent_config/project_assistant.local.yaml
```

Файлы `*.local.yaml` внутри `agent_config` игнорируются git.
