# Настройка GitHub AI Code Review

Этот документ описывает, как ревьюить pull request в другом GitHub-репозитории с помощью `ai_second`.

Есть два разных репозитория:

```text
ai_second
  Репозиторий с агентом-ревьюером. Здесь лежат агент, RAG, prompts и review workflow.

target_repo
  Репозиторий, который нужно ревьюить. В него добавляется только маленький workflow.
```

Ревьюится `target_repo`. `ai_second` используется только как инструмент ревью.

## Результат

Когда в `target_repo` создается или обновляется pull request, GitHub Actions отправляет job на твой self-hosted runner. Runner скачивает оба репозитория, строит временный RAG-индекс по `target_repo`, обращается к локальной Ollama для embeddings и текста ревью, а затем публикует результат обратно в pull request.

Ревью будет видно:

- в conversation pull request как комментарий от bot;
- в GitHub Actions job summary.

## Требования

На машине, где будет запущен self-hosted runner, должны быть:

```text
git
Python 3.12
Ollama
доступ в интернет к GitHub
```

Статический IP не нужен. Runner сам открывает исходящее соединение к GitHub и ждет jobs.

Скачай модели, которые использует reviewer:

```bash
ollama pull nomic-embed-text
ollama pull llama3.1:8b
```

Chat-модель настраивается в `ai_second/agent_config/llm.yaml`. По умолчанию используется provider `ollama`.

## Шаг 1: Опубликовать ai_second

Запушь `ai_second` на GitHub, например:

```text
github.com/YOUR_USER/ai_second
```

В этом репозитории должны быть:

```text
.github/workflows/ai-code-review.yml
scripts/review_pr.py
application/code_review/
application/project_help/
agent_config/project_assistant.example.yaml
```

Если `ai_second` приватный, убедись, что `target_repo` может вызывать reusable workflows и checkout-ить этот репозиторий.

## Шаг 2: Добавить workflow в target_repo

В репозитории, который нужно ревьюить, добавь файл:

```text
.github/workflows/ai-review.yml
```

Готовый пример лежит в `project/examples/target_repo_ai_review.yml`. Его содержимое:

```yaml
name: AI Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  ai-review:
    uses: ArtemBotnev/ai_agent/.github/workflows/ai-code-review.yml@task-32
    with:
      reviewer_repository: ArtemBotnev/ai_agent
      reviewer_ref: task-32
```

`uses` должен быть полноценной ссылкой вида `owner/repository/.github/workflows/file.yml@ref`.
Для текущей ветки разработки это `ArtemBotnev/ai_agent/.github/workflows/ai-code-review.yml@task-32`.
`reviewer_ref` должен указывать на ту же ветку или tag, из которого нужно checkout-ить код агента.
После merge в основную ветку замени `@task-32` и `reviewer_ref: task-32` на `@main` / `reviewer_ref: main` или `@master` / `reviewer_ref: master`.

Больше ничего из `ai_second` в `target_repo` копировать не нужно.

## Шаг 3: Создать self-hosted runner

Открой `target_repo` на GitHub:

```text
Settings -> Actions -> Runners -> New self-hosted runner
```

Выбери OS и архитектуру. GitHub покажет команды примерно такого вида:

```bash
mkdir actions-runner
cd actions-runner
curl -o actions-runner-linux-x64.tar.gz -L https://github.com/actions/runner/releases/download/...
tar xzf ./actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/YOUR_USER/target_repo --token YOUR_TOKEN
```

Запусти runner интерактивно:

```bash
./run.sh
```

Когда runner запущен, GitHub должен показывать его как `Idle`.

Для постоянного фонового режима на Linux:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

Локальная машина должна быть включена, а runner должен быть online в момент запуска PR review jobs.

## Шаг 4: Проверить локальную Ollama

На той же машине, где работает runner:

```bash
ollama list
```

Проверь, что есть модели:

```text
nomic-embed-text
llama3.1:8b
```

Workflow также запускает:

```bash
bash scripts/start_project_ollama.sh
```

из checkout-а `ai_second`. Этот скрипт запускает Ollama, если она еще не отвечает, и скачивает настроенную embedding-модель.

## Шаг 5: Открыть Pull Request

В `target_repo`:

1. создай branch;
2. измени код;
3. сделай push;
4. открой pull request.

GitHub запустит workflow:

```text
AI Review
```

Reusable workflow из `ai_second`:

1. checkout-ит `target_repo` в папку `target-repo`;
2. checkout-ит `ai_second` в папку `ai-reviewer`;
3. устанавливает Python dependencies из `ai_second/requirements.txt`;
4. запускает Ollama embeddings;
5. запускает `ai_second/scripts/review_pr.py` против `target_repo`;
6. записывает `pr_review.md`;
7. публикует review как PR comment и job summary.

## Что выполняется на локальной машине

Runner выполняет job локально. Во время job создается временный SQLite RAG-индекс:

```text
project_rag_index.sqlite
```

в workspace runner-а. Этот файл не коммитится и не сохраняется в GitHub.

RAG-индекс строится по `target_repo`, не по `ai_second`.

Review script использует:

```bash
git diff BASE_SHA...HEAD_SHA
```

внутри `target_repo`, извлекает релевантные текстовые чанки через RAG, затем вызывает настроенную Ollama chat-модель.

## Где читать ревью

Открой pull request в `target_repo`.

Ревью появится как PR comment с секциями:

```markdown
## Potential Bugs
## Architecture Concerns
## Recommendations
```

Workflow использует marker:

```text
<!-- ai-second-code-review -->
```

Если PR обновляется, workflow обновляет существующий AI review comment вместо создания нового.

Также ревью можно открыть здесь:

```text
Actions -> AI Review -> job summary
```

## Локальная отладка

Локальная отладка необязательна. Она полезна, если GitHub workflow падает или нужно проверить изменения prompt-ов до открытия PR.

Из репозитория `ai_second`:

```bash
python scripts/review_pr.py \
  --project-path /path/to/target_repo \
  --base-ref origin/main \
  --head-ref HEAD \
  --index-file /tmp/target_review_rag.sqlite \
  --output /tmp/target_ai_review.md
```

Затем прочитай:

```bash
cat /tmp/target_ai_review.md
```

## Troubleshooting

Если GitHub job долго ждет runner, проверь, что self-hosted runner online:

```text
target_repo -> Settings -> Actions -> Runners
```

Если job не находит Ollama, установи Ollama на машине runner-а и убедись, что команда `ollama` доступна в `PATH`.

Если не загружаются модели, скачай их вручную:

```bash
ollama pull nomic-embed-text
ollama pull llama3.1:8b
```

Если `ai_second` приватный и checkout падает, настрой доступ между репозиториями для reusable workflows или сделай reviewer repository публичным.

Если review comment не создается, проверь permissions workflow:

```yaml
permissions:
  contents: read
  pull-requests: write
```
