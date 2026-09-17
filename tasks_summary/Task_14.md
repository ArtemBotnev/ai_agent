# Task 14: инварианты ассистента

Дата: 2026-09-17

## Что сделали

Добавили ассистенту инварианты — правила, которые он обязан учитывать и не
имеет права нарушать при планировании, выполнении и проверке решения.

Инварианты хранятся отдельно от диалога и runtime-памяти в markdown-файле:

```text
invariants/users/<user_id>/invariants.md
```

Путь можно переопределить через переменную окружения:

```text
AGENT_INVARIANTS_FILE
```

Инварианты редактируются вручную. Автоматического извлечения, merge или очистки
для них нет.

## Формат

Добавлен пример:

```text
invariants/example/invariants.md
```

Ожидаемый формат — обычный markdown с секциями:

```text
## Architecture
## Technical Decisions
## Stack Constraints
## Business Rules
```

Для пользователя `1` инварианты лежат в:

```text
invariants/users/1/invariants.md
```

Текущие правила включают:

- использовать MVVM и Kotlin;
- использовать Jetpack Compose для UI и только его;
- использовать Ktor для сетевых запросов и только его;
- не использовать красный цвет в приложении.

Runtime-директория пользовательских инвариантов добавлена в `.gitignore`:

```text
/invariants/users/
```

## Архитектура

Добавлены:

- `domain/invariants.py` — доменная сущность `Invariants`;
- `application/memory/invariants_repository.py` — порт чтения инвариантов;
- `infrastructure/markdown_invariants_repository.py` — markdown-реализация.

`Invariants.to_context()` рендерит markdown-файл отдельным блоком:

```text
Invariants that must not be violated:
...
```

В контекст добавлены правила интерпретации:

- каждый пункт в каждой секции обязателен;
- `Architecture`, `Technical Decisions`, `Stack Constraints` и `Business Rules`
  имеют одинаковый приоритет;
- при нарушении нужно называть ближайший релевантный пункт;
- архитектурный конфликт должен ссылаться на архитектурный инвариант, а не на
  нерелевантные ограничения стека.

`AgentMemorySnapshot` теперь содержит:

- краткосрочную память;
- профиль пользователя;
- инварианты;
- рабочую память;
- долговременную память.

Инварианты стоят в контексте выше рабочей и долговременной памяти.

## Подключение

В `main.py` добавлены:

- `DEFAULT_INVARIANTS_DIR`;
- `AGENT_INVARIANTS_FILE_ENV`;
- `build_user_invariants_file(user_id=None)`;
- `build_invariants_repository(user_id=None)`.

`get_available_user_ids()` теперь учитывает пользователей из:

```text
memory/users/
profiles/users/
invariants/users/
```

`build_chat_service()` прокидывает `invariants_repository` в `ChatService`.

Инварианты добавляются в контекст всех стратегий:

- `memory`;
- `sliding_window`;
- `summary`;
- `sticky_facts`;
- `branching`.

Команда `/clear` и очистка контекста в PyQt UI не удаляют инварианты.

## Поведение workflow

Для `PlanningAgentResult` добавлены поля:

```text
invariant_check
violates_invariants
violated_invariants
```

Если planning обнаружил нарушение инварианта, `ChatService` программно блокирует
переход в `execution`:

```text
ready_for_execution = result.ready_for_execution and not result.violates_invariants
```

Даже если LLM ошибочно вернет `ready_for_execution=true`, задача не перейдет к
выполнению при `violates_invariants=true`.

Для `ValidationAgentResult` добавлены поля:

```text
invariant_violations
artifact_is_concrete
```

Validation теперь считает результат невалидным, если:

- artifact нарушает инварианты;
- artifact является сводкой вместо конкретного решения;
- есть обычные validation issues.

Это исправляет проблему, когда artifact мог содержать текст вроде
`реализовано с Retrofit`, хотя инварианты требуют использовать Ktor и только его.

## Prompts

Системные prompts обновлены для:

- основного агента;
- `PlanningAgent`;
- `ExecutionAgent`;
- `ValidationAgent`;
- `DoneAgent`.

Общее правило:

```text
если запрос пользователя или предлагаемое решение нарушает инвариант,
ассистент должен отказаться от такого решения, назвать нарушенный инвариант
и предложить совместимую альтернативу.
```

`ExecutionAgent` дополнительно получил требование возвращать конкретный artifact
— код, patch, документ или другой результат задачи, а не текстовую сводку.

`ValidationAgent` проверяет artifact против задачи, плана и инвариантов.

После проверки поведения усилены prompts: если пользователь предлагает другой
архитектурный подход, например MVI при инварианте `только MVVM`, агент должен
отказаться именно по архитектурному инварианту и не подменять причину
ограничениями про Jetpack Compose или Ktor.

После этого уточнены правила перехода из planning: короткие фразы вроде `давай`,
`делай`, `пиши`, `ок`, `окей`, `согласен`, `начинай` и `начни` считаются
неоднозначными. На них агент должен явно переспросить, приступать ли к
выполнению. Переход в `execution` происходит только по недвусмысленной команде
выполнения, например `приступай`, `можешь писать код`, `реализуй`,
`внеси изменения`, `создай файл`.

## Проверки

Выполнены проверки:

```text
python3 -m py_compile main.py agent.py application/chat/chat_service.py application/workflow/task_stage_agents.py domain/agent_memory.py domain/invariants.py application/memory/invariants_repository.py infrastructure/markdown_invariants_repository.py ui/pyqt_app.py
python3 -c "import agent, main, web.server, ui.pyqt_app; print('imports ok')"
```

Дополнительно проверены fake-сценарии без реального API:

- markdown-инварианты попадают в context обычных стратегий;
- `memory` workflow не запускает execution при нарушении инварианта на planning;
- `ValidationAgent` делает результат invalid при `invariant_violations`;
- `ValidationAgent` делает результат invalid, если artifact является сводкой,
  а не конкретным решением.
- planning prompt содержит MVVM-инвариант и инструкцию ссылаться на архитектурный
  инвариант при архитектурном конфликте.
- state machine не переводит planning в execution по коротким неоднозначным
  фразам вроде `давай`, `пиши`, `окей`, но переводит по явным командам
  выполнения вроде `приступай`, `можешь писать код`, `реализуй`.
