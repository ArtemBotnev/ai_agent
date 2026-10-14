# Task 33: Support assistant through MCP context service

Дата: 2026-10-14

## Что сделали

Добавлен support-режим для AI-ассистента. Он отвечает на вопросы о продукте
и подключенном проекте, получает контекст через MCP и может учитывать данные
тикета, если тикет указан.

Основной сценарий:

```text
Support mode в UI
  -> вопрос пользователя
  -> MCP prepare_context
  -> project/support evidence pack
  -> ответ текущим LLM provider
```

Тикет теперь является дополнительным контекстом, а не обязательным параметром.
Можно спрашивать как общие вопросы о проекте, так и вопросы по конкретному
тикету:

```text
/support О чём проект?
/support T-1 Почему не работает авторизация?
```

## Клиентская часть ai_second

Добавлен пакет:

```text
application/support/
  support_assistant_commands.py
```

Он отвечает за:

- slash-команды support-режима;
- загрузку контекста через MCP;
- подготовку AIT/1-контекста для LLM;
- форматирование статуса и результатов RAG;
- очистку support runtime-данных на MCP.

Поддержаны команды:

```text
/support
/support [ticket_id] <вопрос>
/support-rag status
/support-rag build
/support-rag refresh
/support-rag rebuild
/support-clear
```

Команда `/support` без аргументов показывает статус подключения, путь проекта,
настройки docs paths и состояние RAG-индекса.

## Конфигурация

Добавлен конфиг:

```text
agent_config/support_assistant.example.yaml
agent_config/support_assistant.local.yaml
```

Публичный example хранится в git, local-файл добавлен в `.gitignore`.

Основные настройки:

```yaml
support_assistant:
  project_path: /absolute/path/to/product-or-support-project
  docs_paths:
    - "."
  top_k: 5

  mcp:
    server_url: http://127.0.0.1:8000
    timeout_seconds: 10
```

Клиент не хранит support CRM, tickets, histories и RAG runtime-данные. Всё это
находится на стороне MCP.

## UI

В PyQt UI добавлен режим:

```text
Support
```

В этом режиме обычные сообщения автоматически отправляются как `/support`.
Поле тикета опциональное:

- пустое поле: общий вопрос о проекте или продукте;
- заполненное поле: вопрос с привязкой к тикету.

Добавлена кнопка:

```text
Support RAG
```

Она запускает `/support-rag refresh`.

## MCP integration

Клиент использует общий MCP tool:

```text
prepare_context
```

Запрос содержит:

```text
project_path
docs_paths
question
ticket_id, если указан
limit
```

В ответ клиент получает evidence pack и передает его в LLM в компактном AIT/1
формате:

```text
T - ticket context
U - user context
P - context plan
F - structured facts
M - text matches
R - retrieved RAG chunks
```

## Проверки

Запускались:

```bash
python -m py_compile application/support/support_assistant_commands.py ui/pyqt_app.py main.py
```

Дополнительно проверено:

- `/support <вопрос>` парсится без тикета;
- `/support T-1 <вопрос>` сохраняет старый сценарий с тикетом;
- UI в support-режиме отправляет вопрос без ошибки при пустом поле тикета.
