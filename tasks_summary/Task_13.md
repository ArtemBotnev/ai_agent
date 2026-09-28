# Task 13: состояние задачи как конечный автомат

Дата: 2026-09-16

## Что сделали

Добавили формализованное состояние задачи поверх стратегии `memory`.

Состояние хранится в рабочей памяти пользователя:

```text
memory/users/<user_id>/working_memory.json
```

Основные этапы автомата:

```text
planning -> execution -> validation -> done
```

Этапы означают:

- `planning` — обсуждение требований, уточнения и подготовка плана;
- `execution` — выполнение согласованного решения и создание артефакта;
- `validation` — проверка результата по задаче и плану;
- `done` — зафиксированный финальный результат.

## Правила переходов

Переходы ограничены явно:

```text
planning -> execution
execution -> validation | planning
validation -> done | execution
done -> planning только при новой задаче
```

Логика переходов:

- из `planning` можно перейти только в `execution`, когда план готов и пользователь просит выполнять;
- из `execution` можно перейти в `validation`, если артефакт создан;
- из `execution` можно вернуться в `planning`, если нужны уточнения;
- из `validation` можно перейти в `done`, если проверка прошла;
- из `validation` можно вернуться в `execution`, если проверка провалилась;
- из `done` новая самостоятельная задача начинает новый цикл с `planning`.

## Шаги и восстановление после прерывания

`step/total` теперь описывает шаг workflow, а не количество пунктов плана:

```text
planning   = 1/4
execution  = 2/4
validation = 3/4
done       = 4/4
```

Для прогресса внутри плана добавлены отдельные поля:

```text
plan_step
plan_total
```

Это нужно, чтобы после перезапуска программы агент мог понять:

- какой этап выполнялся последним;
- какого subagent нужно запустить дальше;
- какой план уже был сохранён;
- какие пункты плана уже закрыты;
- какой артефакт нужно проверять или дорабатывать.

В `done` состояние теперь выглядит как завершённый workflow, например:

```json
{
  "stage": "done",
  "step": 4,
  "total": 4,
  "plan_step": 2,
  "plan_total": 2
}
```

## Subagent workflow

Добавлены отдельные subagent-интерфейсы для этапов:

```text
application/workflow/task_stage_agents.py
```

Subagent-ы:

- `PlanningAgent` — готовит план и решает, можно ли переходить к выполнению;
- `ExecutionAgent` — создаёт конкретный артефакт решения;
- `ValidationAgent` — проверяет артефакт и возвращает результат проверки;
- `DoneAgent` — формирует финальный пользовательский ответ.

Реализации на базе LLM добавлены в `agent.py`:

- `SimplePlanningAgent`;
- `SimpleExecutionAgent`;
- `SimpleValidationAgent`;
- `SimpleDoneAgent`.

`ChatService` теперь оркестрирует эти subagent-ы внутри стратегии `memory`.
Пользователь видит обсуждение на этапе планирования и финальный результат, а
внутренние этапы выполнения и проверки отражаются через состояние задачи.

## Финальный ответ в done

`done` теперь содержит не только краткую сводку.

Финальный ответ гарантированно включает:

- итог выполненной задачи;
- результат проверки;
- финальное решение или артефакт.

Если `DoneAgent` вернул только сводку, `ChatService` добавляет сохранённый
`last_artifact` и `last_validation_summary` из рабочей памяти.

## UI

PyQt UI показывает состояние задачи для стратегии `memory`.

Отображаются:

- название задачи;
- текущий этап;
- признак паузы.

Для этапов добавлены цветовые маркеры:

- `ПЛАНИРОВАНИЕ`;
- `ВЫПОЛНЕНИЕ`;
- `ПРОВЕРКА`;
- `ГОТОВО`.

Лишняя кнопка ручного перехода между этапами убрана. Этап определяется текущим
subagent workflow и обновляется в UI через callback из `ChatService`.

## Изменённые файлы

Основные изменения:

```text
domain/task_state.py
domain/working_memory.py
application/workflow/task_stage_agents.py
application/chat/chat_service.py
agent.py
main.py
ui/pyqt_app.py
ui/colors.py
ui/pyqt_theme.py
```

## Проверки

Выполнены проверки:

```text
python3 -m py_compile domain/task_state.py agent.py application/chat/chat_service.py domain/working_memory.py ui/pyqt_app.py main.py application/workflow/task_stage_agents.py
python3 -c "import agent, main, web.server, ui.pyqt_app; print('imports ok')"
```

Дополнительно проверены fake-сценарии без реального API:

- `planning -> execution -> validation -> done`;
- восстановление из сохранённого `execution` без повторного planning;
- `validation -> execution -> validation -> done` после проваленной проверки;
- финальный ответ содержит артефакт и итог проверки;
- в `done` сохраняется `step: 4`, `total: 4`.
