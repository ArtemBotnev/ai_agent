# Task 10: стратегии управления контекстом

Дата: 2026-09-11

## Что сделали

Добавили четыре стратегии управления контекстом агента и переключение между ними:

- `sliding_window` — хранит и отправляет только последние N сообщений.
- `summary` — сворачивает старые сообщения в `summary.json` и отправляет summary + последние N сообщений.
- `sticky_facts` — хранит key-value факты в `facts.json` и отправляет facts + последние N сообщений.
- `branching` — хранит независимые ветки диалога в `branches.json`.

Для `sticky_facts` обновление работает как merge: модель возвращает новые или измененные факты, они добавляются к существующим, а `null` или пустая строка удаляют устаревший факт.

Стратегию по умолчанию можно задать переменной окружения:

```text
AGENT_CONTEXT_STRATEGY
```

Допустимые значения:

```text
sliding_window
summary
sticky_facts
branching
```

## Новые файлы хранения

```text
history/facts.json
history/branches.json
```

Пути можно переопределить:

```text
AGENT_FACTS_FILE
AGENT_BRANCHES_FILE
```

## CLI

Добавлены команды:

```text
/strategy
/strategy sliding_window
/strategy summary
/strategy sticky_facts
/strategy branching
/clear
/branch
/branch <name>
/checkpoint
/new-branch <name>
```

## PyQt

В `ui/pyqt_app.py` добавлены:

- переключатель стратегии;
- кнопка очистки контекста;
- для `branching`: выбор ветки, checkpoint и создание новой ветки.

## Проверки

Были выполнены проверки:

```text
python3 -m py_compile ...
поведенческий тест ChatService с fake-agent, fake-summarizer и fake-facts-extractor
```

Реальные запросы к OpenAI API не запускались, чтобы не расходовать внешний API.
