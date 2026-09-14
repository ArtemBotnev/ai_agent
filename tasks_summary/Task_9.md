# Task 9: управление контекстом через summary

Дата: 2026-09-10

## Что сделали

Добавили механизм компактного хранения контекста:

- последние сообщения диалога сохраняются как есть;
- все сообщения сверх лимита сворачиваются в summary;
- summary хранится отдельно и подставляется в LLM-запрос как контекст прошлой беседы.

По умолчанию сохраняются последние 5 сообщений:

```text
AGENT_RECENT_MESSAGES_LIMIT=5
```

История сообщений по-прежнему хранится в:

```text
history/messages.json
```

Summary хранится отдельно:

```text
history/summary.json
```

Путь к summary можно переопределить:

```text
AGENT_SUMMARY_FILE
```

## Архитектура

Реализация сохранена в стиле чистой архитектуры:

- `domain/conversation_summary.py` — доменная сущность `ConversationSummary`.
- `application/conversation_summary_repository.py` — порт хранения summary.
- `application/conversation_summarizer.py` — порт специального агента для выжимки старых сообщений.
- `infrastructure/json_conversation_summary_repository.py` — JSON-хранилище summary.
- `application/chat_service.py` — use case управляет компактизацией истории.
- `agent.py` — обычный агент принимает summary как дополнительный контекст, а `SimpleConversationSummarizer` обновляет summary через LLM.

## Поведение

При новом сообщении:

1. `ChatService` загружает summary и сохраненные сообщения.
2. Если в старом `messages.json` уже больше лимита, лишние старые сообщения сразу сворачиваются в summary.
3. Новое сообщение пользователя добавляется к живой истории.
4. Обычный агент получает summary и живые сообщения.
5. После ответа ассистента история снова проверяется на лимит.
6. Все сообщения сверх последних 5 отправляются summarizer-агенту.
7. В `history/messages.json` сохраняются только последние 5 сообщений.
8. В `history/summary.json` сохраняется обновленная выжимка.

UI через `/api/messages` показывает только последние сохраненные сообщения. Summary пользователю не показывается.

## Проверки

Были выполнены проверки:

```text
python3 -m py_compile ...
node --check web/static/app.js
import agent, main, web.server, ui.pyqt_app
поведенческий тест ChatService с fake-agent и fake-summarizer
```

Реальные запросы к OpenAI API не запускались, чтобы не расходовать внешний API.
