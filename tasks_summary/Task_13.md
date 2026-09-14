# Task 13: группировка application layer

Дата: 2026-09-14

## Что сделали

Разделили плоскую папку `application/` на подпакеты по ответственности:

```text
application/
  branches/
  chat/
  facts/
  llm/
  memory/
  summary/
```

## Новая структура

- `application/chat/` — основной use case чата, ошибки, стратегия контекста и порт истории сообщений.
- `application/llm/` — порт LLM-агента.
- `application/summary/` — summary-порты.
- `application/facts/` — sticky facts-порты.
- `application/memory/` — рабочая и долговременная память.
- `application/branches/` — порт веток диалога.

Импорты в `main.py`, `agent.py`, `web/`, `ui/` и `infrastructure/` обновлены на новые пути.

## Важно

В `.gitignore` правило `memory` заменено на `/memory`, чтобы runtime-папка
`memory/` в корне проекта игнорировалась, но Python-пакет
`application/memory/` попадал в git.
