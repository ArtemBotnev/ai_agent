# Task 15: multi-agent planning debate

Дата: 2026-09-18

## Что сделали

Заменили одиночное планирование на multi-agent planning debate для стратегии
`memory`.

Внешний workflow не изменился:

```text
planning -> execution -> validation -> done
```

`ChatService` по-прежнему работает через один контракт:

```text
PlanningAgent.run(context) -> PlanningAgentResult
```

Но внутри planning теперь используется несколько ролей:

- `analyst` — проверяет требования, scope, риски и недостающую информацию;
- `dev` — проверяет архитектуру, реализуемость, state machine и тестируемость;
- `design` — проверяет UX/UI-аспекты, визуальные ограничения и продуктовую
  согласованность;
- `synthesizer` — собирает финальный результат planning.

## Внутренний протокол

Для общения ролей не используется JSON, чтобы не тратить лишние токены на
кавычки, скобки и повторяющиеся ключи.

Внутренние роли отвечают компактным KQML-like S-expression форматом:

```text
(propose :r dev :p POSITION :q QUESTIONS :risk RISKS :plan PLAN :v VIOLATIONS :ready yes|no)
(challenge :r design :target dev :p POSITION :risk RISKS :v VIOLATIONS)
(block :r analyst :v VIOLATION :why REASON)
```

Строгий JSON оставлен только на внешней границе planning, где его читает код:

```json
{
  "reply": "сообщение пользователю",
  "task": "краткое название задачи",
  "plan": ["шаг 1", "шаг 2"],
  "current": "текущий ближайший шаг",
  "awaiting_confirmation": true,
  "ready_for_execution": false,
  "invariant_check": "как план учитывает инварианты",
  "violates_invariants": false,
  "violated_invariants": []
}
```

## Архитектура

Добавлен `DebatingPlanningAgent` в `agent.py`.

Он реализует тот же application-level protocol `PlanningAgent`, что и старый
`SimplePlanningAgent`, поэтому не потребовалось менять:

- `application/workflow/task_stage_agents.py`;
- `application/chat/chat_service.py`;
- `domain/task_state.py` в части основного workflow;
- web API;
- UI.

Внутренний алгоритм:

```text
1. analyst/dev/design дают первичные compact notes.
2. analyst/dev/design видят notes друг друга и дают review/challenge/revise.
3. synthesizer читает debate transcript.
4. synthesizer возвращает обычный PlanningAgentResult JSON.
```

Если одна роль упала или вернула неудачный ответ, вместо нее в transcript
попадает короткая форма:

```text
(fail :r ROLE :err ERROR_CODE)
```

Если synthesizer упал или вернул неполный planning result, используется fallback
на старый `SimplePlanningAgent`.

Внутренние notes дополнительно ограничены по длине, чтобы сорванный формат не
раздувал synthesis-запрос.

## Подключение

В `main.py` добавлен режим планирования:

```text
AGENT_PLANNING_MODE=debate
AGENT_PLANNING_MODE=single
```

По умолчанию используется:

```text
debate
```

`single` оставлен как быстрый откат к прежнему поведению.

Для debate создаются отдельные `SimpleLlmAgent`-экземпляры с разными system
prompts:

- `PLANNING_ANALYST_SYSTEM_PROMPT`;
- `PLANNING_DEVELOPER_SYSTEM_PROMPT`;
- `PLANNING_DESIGNER_SYSTEM_PROMPT`;
- `PLANNING_SYNTHESIZER_SYSTEM_PROMPT`.

## Инварианты

Инварианты продолжают читаться через существующий repository flow:

```text
invariants/users/<user_id>/invariants.md
```

Для пользователя по умолчанию используется user `1`:

```text
invariants/users/1/invariants.md
```

`invariants/example/invariants.md` не используется по умолчанию. Он может быть
подключен только явным переопределением `AGENT_INVARIANTS_FILE`.

Все роли получают общий task context, где инварианты уже включены в prompt.
Synthesizer обязан блокировать execution, если любая роль нашла реальное
нарушение инвариантов.

## Переход к выполнению

После внедрения debate planning агенты оказались слишком консервативными и могли
не переходить к `execution`, даже когда пользователь явно делегировал решение и
разрешил писать код.

Исправлено на двух уровнях.

В `domain/task_state.py` расширены `_IMPLEMENTATION_MARKERS`. Добавлены варианты:

- `можно писать код`;
- `можете писать код`;
- `могут писать код`;
- `можно вносить`;
- `переходи к выполнению`;
- `на твое усмотрение`;
- `на твоё усмотрение`;
- `на ваше усмотрение`;
- `start implementation`;
- `write the code`.

В `agent.py` обновлены planning-инструкции: delegation-фразы вроде
`всё на твоё усмотрение, можешь писать код` считаются явным разрешением на
execution.

Также добавлен deterministic guard:

```text
если пользователь явно разрешил выполнение,
и план есть,
и инварианты не нарушены,
то ready_for_execution=true
```

Простой `ок` по-прежнему не считается явным разрешением.

## Изменённые файлы

Основные изменения:

```text
agent.py
main.py
domain/task_state.py
```

Добавлен summary-файл:

```text
tasks_summary/Task_15.md
```

## Проверки

Выполнены проверки:

```text
python3 -m py_compile agent.py main.py application/workflow/task_stage_agents.py application/chat/chat_service.py
python3 -c 'from agent import DebatingPlanningAgent, PLANNING_SYNTHESIZER_SYSTEM_PROMPT; from main import PLANNING_MODE_DEBATE, PLANNING_MODE_SINGLE; print(PLANNING_MODE_DEBATE, PLANNING_MODE_SINGLE)'
python3 -m py_compile agent.py main.py domain/task_state.py application/chat/chat_service.py
```

Дополнительно проверены сценарии без реального API:

- default path инвариантов указывает на `invariants/users/1/invariants.md`;
- repository фактически загружает инварианты user `1`, а не example;
- сохраненный planning state переходит в `execution` по фразе
  `всё на твое усмотрение, можете писать код`;
- `_has_explicit_execution_approval(...)` возвращает `true` для явного
  разрешения писать код;
- `_has_explicit_execution_approval("ок")` возвращает `false`.
