# Task 32: Automatic AI code review for GitHub PRs

Дата: 2026-10-13

## Что сделали

Добавлен первый рабочий контур автоматического AI-review для pull request:

```text
GitHub pull_request
  -> GitHub Actions self-hosted runner
  -> scripts/review_pr.py
  -> git diff + changed files
  -> project RAG
  -> Ollama LLM
  -> Markdown review в PR comment и job summary
```

## Архитектура

Review-логика вынесена в отдельный application package:

```text
application/code_review/
  diff_loader.py
  review_service.py
```

`diff_loader.py` получает:

- unified diff;
- список измененных файлов через `git diff --name-status`;
- snapshots текущего содержимого измененных текстовых файлов.

`CodeReviewService` переиспользует существующие компоненты Task 31:

- `ProjectRagIndex`;
- Ollama embeddings;
- project context adapter / MCP;
- `ChatService.answer_once(...)`.

Обычная история чата при review-запросах не изменяется.

## RAG для любого проекта

Project RAG расширен с документации на любой текстовый проект.

Добавлена конфигурация:

```yaml
project_assistant:
  source:
    paths:
      - .
    exclude_dirs:
      - .git
      - .idea
      - .venv
      - __pycache__
      - node_modules
      - build
      - dist
      - rag
      - history
    exclude_globs:
      - "*.local.yaml"
      - "*.env"
      - "*.sqlite"
      - "*.png"
      - "*.jpg"
      - "*.pdf"
    max_file_bytes: 1000000
```

Файлы включаются не по whitelist расширений, а по признаку текстовости:

- файл внутри `project_path`;
- не находится в excluded dirs;
- не совпадает с excluded globs;
- меньше лимита;
- не содержит `NUL`;
- декодируется как UTF-8.

Для `/project-rag build` старые `docs_paths` остаются fallback-ом, если
`source.paths` не задан. Для `scripts/review_pr.py` принудительно используется
`source.paths: [.]`, чтобы ревью видело код проверяемого проекта.

## MCP

Старый local project MCP сохранен без замены:

```yaml
project_assistant:
  mcp:
    enabled: false
    server_url: http://localhost:8000
```

Добавлена отдельная GitHub-секция под будущий GitHub MCP/API context:

```yaml
project_assistant:
  github:
    enabled: true
    repository: owner/repo
    token_env: GITHUB_TOKEN
    mcp:
      enabled: false
      server_url: http://localhost:8001
      timeout_seconds: 10
```

Она не влияет на старый `/project` и `/help`.

## Entry Point

Добавлен CI-friendly скрипт:

```bash
python scripts/review_pr.py \
  --project-path /path/to/target-repo \
  --base-ref origin/main \
  --head-ref HEAD \
  --output pr_review.md
```

Для GitHub Actions можно передавать SHA:

```bash
python scripts/review_pr.py \
  --project-path ../target-repo \
  --base-sha "$BASE_SHA" \
  --head-sha "$HEAD_SHA" \
  --index-file ../project_rag_index.sqlite \
  --output ../pr_review.md
```

## GitHub Action

Добавлен workflow:

```text
.github/workflows/ai-code-review.yml
```

Он рассчитан на self-hosted runner с Ollama и может:

- запускаться напрямую на PR в этом репозитории;
- использоваться как reusable workflow из другого GitHub repository.

Проверяемый репозиторий может вызвать reviewer так:

```yaml
jobs:
  ai-review:
    uses: your-org/ai_second/.github/workflows/ai-code-review.yml@main
    with:
      reviewer_repository: your-org/ai_second
```

Workflow:

1. checkout-ит target repository;
2. checkout-ит `ai_second` как reviewer repository;
3. ставит зависимости;
4. запускает `scripts/start_project_ollama.sh`;
5. запускает `scripts/review_pr.py`;
6. публикует Markdown review в `$GITHUB_STEP_SUMMARY`;
7. создает или обновляет PR comment.

## Проверки

Запускались:

```bash
python -m compileall config application infrastructure main.py scripts/review_pr.py
bash -n scripts/start_project_ollama.sh
python scripts/review_pr.py --help
```

Также проверено:

- `source_paths: [.]` индексирует текстовые файлы проекта и не заходит в `.git`;
- hashing RAG build во временный SQLite;
- diff loader на диапазоне `HEAD...HEAD`.
