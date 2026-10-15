# Task 34: Workspace assistant через MCP

Дата: 2026-10-15

## Цель

Добавить ассистента, который работает с файлами проекта на уровне цели:
читает несколько файлов, ищет релевантную информацию, анализирует содержимое
и возвращает результат в чат. Diff и изменения файлов выполняются только по
явному запросу.

## Архитектура

Основная логика находится на MCP-сервере `project_mcp_adapter`.
Клиент `ai_second` остается тонким: отправляет цель, показывает результат,
список прочитанных файлов и diff по отдельному запросу.

## MCP server

Добавлен модуль:

```text
src/local_project_mcp/workspace_tools.py
```

Новые tools:

```text
workspace_run(project_path, goal, mode="draft")
workspace_diff(project_path)
```

Поддержанные workflow:

- `usage_analysis`;
- `documentation_update`;
- `changelog`;
- `invariant_check`;
- `diff_summary`;
- `code_stats`;
- fallback `project_analysis`.

Режимы:

- `plan` - план и evidence без записи;
- `draft` - возвращает структурированный ответ без записи файлов;
- `report` - создает Markdown-отчет в `workspace_reports`;
- `apply` - зарезервирован под будущие изменения исходников и выключен
  настройкой `workspace_allow_apply: false`.

## Клиент ai_second

Добавлен пакет:

```text
application/workspace/
  workspace_assistant_commands.py
```

Команды:

```text
/workspace
/workspace <цель>
/workspace plan <цель>
/workspace-diff
/workspace-edit <цель>
/workspace-apply
```

В PyQt добавлен режим:

```text
Workspace
```

Обычное сообщение в этом режиме отправляется как `/workspace <цель>`.

## Безопасность

Workspace-agent использует существующую `ProjectSecurityPolicy` на MCP:

- `project_path` должен быть внутри `allowed_roots`;
- blocked names/suffixes/dirs не читаются;
- draft-режим не пишет файлы;
- report-режим пишет только отчет в `workspace_reports`;
- source-file edits идут через pending patch:
  `/workspace-edit <цель>` генерирует unified diff через LLM и проверяет его
  на MCP через `workspace_apply_patch(dry_run=true)`;
  `/workspace-apply` применяет pending patch через MCP.
