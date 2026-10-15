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
- `/workspace <цель>` запускает MCP workspace assistant: он анализирует файлы проекта и отвечает в чат.
- `/workspace plan <цель>` строит план без записи файлов; `/workspace-diff` показывает текущий git status/diff.
- `/workspace-edit <цель>` просит LLM сгенерировать unified diff и сохраняет его как pending patch.
- `/workspace-apply` применяет сохраненный pending patch через MCP после серверных проверок.
- `/workspace-clear-patch` удаляет сохраненный pending patch без изменения файлов проекта.
- `scripts/review_pr.py` делает AI-ревью PR diff через RAG и текущий LLM provider.

## PyQt UI

В UI можно писать project-assistant команды прямо в обычное поле ввода:

```text
/project
/project-rag build
/project-rag status
/help какая структура проекта?
/workspace подготовь changelog по текущим изменениям
/workspace-edit реализуй UI на Compose
/workspace-apply
/workspace-clear-patch
/workspace-diff
```

В режиме `Workspace` можно писать обычными фразами без явной команды: вопросы превращаются в `/workspace <цель>`, просьбы вроде `пиши код`, `реализуй`, `внеси изменения` — в `/workspace-edit <цель>`, а просьбы `примени`/`давай внесём` применяют pending patch через `/workspace-apply`, если он уже подготовлен.

В режиме `Workspace` также появляется компактное меню `Workspace`: `Подготовить patch` генерирует pending patch из текущего текста в поле ввода, `Применить pending patch` записывает подготовленный patch в проект, `Показать diff` показывает изменения в ветке, `Сбросить pending patch` удаляет pending patch.

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
- `source.paths` — список файлов или папок, которые входят в RAG; для ревью можно указать весь проект через `.`.
- `source.exclude_dirs` и `source.exclude_globs` — исключения для runtime-папок, бинарников, артефактов и локальных секретов.
- `index_file` — путь к SQLite RAG-индексу.
- `mcp.enabled` — включает получение project context через MCP.
- `mcp.server_url` — адрес MCP Streamable HTTP server.
- `github.mcp` — отдельная секция для будущего GitHub MCP, не заменяет локальный `mcp`.
- `embedding.provider` — provider для embeddings, обычно `ollama`.
- `embedding.model` — embedding-модель Ollama, например `nomic-embed-text`.
- `retrieval.top_k` — сколько чанков документации передавать в `/help`.
- `review.*` — лимиты diff/file context и язык ответа для AI-ревью.

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

Workspace assistant тоже использует этот MCP server. Тяжелая работа с файлами выполняется на стороне сервера: он обходит разрешенные файлы, читает релевантные файлы, анализирует цель и возвращает evidence для активной LLM. Diff показывается через `/workspace-diff`. Изменения исходников идут явным двухшаговым сценарием: `/workspace-edit <цель>` генерирует и проверяет pending unified diff, затем `/workspace-apply` применяет его.

Если `mcp.enabled: false`, используется локальный adapter, который получает ветку через read-only git-команды.

## RAG

Сборка RAG:

```text
/project-rag build
```

Что происходит:

1. Ассистент читает настроенные `source.paths` выбранного проекта.
2. Документы режутся на чанки.
3. Чанки отправляются в Ollama embedding API.
4. Embeddings и тексты сохраняются в SQLite.
5. Команда `/help` ищет релевантные чанки и передает их выбранной LLM.

RAG находится на стороне агента. MCP не строит embeddings и не вызывает LLM.

## AI Code Review

Для ревью PR добавлен CI entry point:

Полная инструкция для GitHub, включая файл в проверяемом репозитории и запуск self-hosted runner, описана в `project/docs/github_ai_review_setup.ru.md`.

```bash
python scripts/review_pr.py \
  --project-path /path/to/target-repo \
  --base-ref origin/main \
  --head-ref HEAD \
  --output pr_review.md
```

Скрипт получает diff через git, строит RAG по проверяемому проекту, достает релевантный контекст и отправляет одноразовый запрос в LLM. Результат — Markdown review с потенциальными багами, архитектурными замечаниями и рекомендациями.

Для GitHub используется workflow `.github/workflows/ai-code-review.yml`. Он рассчитан на вариант, где `ai_second` живет как отдельный reviewer repository, а проверяемый репозиторий вызывает его:

```yaml
jobs:
  ai-review:
    uses: your-org/ai_second/.github/workflows/ai-code-review.yml@main
    with:
      reviewer_repository: your-org/ai_second
```

Workflow запускается на PR, checkout-ит проверяемый repo и repo ассистента, запускает Ollama embeddings, выполняет `scripts/review_pr.py`, пишет результат в job summary и обновляет комментарий в PR.

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
