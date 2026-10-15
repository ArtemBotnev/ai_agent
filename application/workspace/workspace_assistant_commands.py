from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.project_assistant_config import ProjectAssistantConfig
from infrastructure.project_context_client import McpProjectContextClient


WORKSPACE_ASSISTANT_COMMANDS = {
    "/workspace",
    "/workspace-diff",
    "/workspace-edit",
    "/workspace-apply",
    "/workspace-clear-patch",
}
WORKSPACE_MODES = {"plan", "draft", "report", "apply"}
PENDING_PATCH_FILE = Path("history/workspace_pending.patch")


@dataclass(frozen=True)
class WorkspaceAssistantCommand:
    name: str
    argument: str


@dataclass(frozen=True)
class WorkspaceIntent:
    command: str
    display_prefix: str


@dataclass(frozen=True)
class WorkspaceAnswerRequest:
    prompt: str
    context: str
    direct_answer: str | None = None
    history_message: str | None = None


class WorkspaceAssistantCommandService:
    def __init__(self, config: ProjectAssistantConfig) -> None:
        self._config = config
        self._mcp_client = McpProjectContextClient(
            server_url=config.mcp.server_url,
            timeout_seconds=config.mcp.timeout_seconds,
        )

    def workspace_status_text(self) -> str:
        return "\n".join(
            [
                f"Workspace project: {self._config.resolved_project_path}",
                f"MCP: {self._config.mcp.server_url}",
                "Mode: draft by default; answers are returned in chat",
                "Commands: /workspace <goal>, /workspace-edit <goal>, /workspace-apply, /workspace-diff",
            ]
        )

    def workspace_text(self, argument: str) -> str:
        if not argument.strip():
            return self.workspace_status_text()

        request = self.prepare_workspace_request(argument)
        if request.direct_answer is not None:
            return request.direct_answer
        return request.prompt

    def prepare_workspace_request(self, argument: str) -> WorkspaceAnswerRequest:
        if not argument.strip():
            return WorkspaceAnswerRequest(prompt="", context="", direct_answer=self.workspace_status_text())

        mode, goal = parse_workspace_goal(argument)
        result = self._call_tool(
            "workspace_run",
            {
                "project_path": str(self._config.resolved_project_path),
                "goal": goal,
                "mode": mode,
            },
        )
        if mode == "report":
            return WorkspaceAnswerRequest(prompt="", context="", direct_answer=format_workspace_result(result))
        return WorkspaceAnswerRequest(
            prompt=goal,
            context=format_workspace_context(result)
            + "\n\n"
            + (
                "Assistant behavior:\n"
                "Ответь как инженерный ассистент по проекту. Отвечай сразу по сути вопроса. "
                "Если текущая реплика короткая и подтверждающая, например 'да', 'давай', 'начинай', "
                "продолжай последнюю обсуждавшуюся задачу из истории диалога. "
                "Не начинай с фраз про MCP, evidence, контекст, прочитанные файлы или анализ. "
                "Не перечисляй файлы и служебные поля вроде workflow/files_read, если пользователь прямо не просит. "
                "Если пользователь просит написать код, предложи конкретный код или план изменений; "
                "не утверждай, что файлы изменены, пока apply/edit не выполнен."
            ),
        )

    def workspace_diff_text(self) -> str:
        result = self._call_tool(
            "workspace_diff",
            {
                "project_path": str(self._config.resolved_project_path),
            },
        )
        return format_workspace_diff(result)

    def prepare_workspace_edit_request(self, argument: str) -> WorkspaceAnswerRequest:
        clean_argument = argument.strip()
        if not clean_argument:
            raise RuntimeError("Укажите цель: /workspace-edit <цель>")

        result = self._call_tool(
            "workspace_run",
            {
                "project_path": str(self._config.resolved_project_path),
                "goal": clean_argument,
                "mode": "draft",
            },
        )
        return WorkspaceAnswerRequest(
            prompt=build_workspace_edit_prompt(clean_argument),
            context=format_workspace_context(result)
            + "\n\n"
            + (
                "Patch generation rules:\n"
                "- The user is asking for a real source edit, not a plan or explanation.\n"
                "- Create a minimal unified diff patch for the user's requested change.\n"
                "- Return only the unified diff starting with 'diff --git a/<path> b/<path>'.\n"
                "- Every file header must use a/ and b/ prefixes.\n"
                "- Use only relative paths that exist in project_files, unless creating a clearly necessary new file.\n"
                "- Do not wrap the patch in Markdown. Do not include explanations outside the diff.\n"
                "- Do not invent files, packages, modules, screens, dependencies, or APIs unsupported by evidence or conversation history.\n"
                "- If the user refers to 'this' or 'these changes', resolve it from the previous conversation.\n"
                "- If there is not enough context to make a safe patch, return a short Russian explanation instead of a diff.\n"
            ),
            history_message=clean_argument,
        )

    def save_pending_patch_text(self, text: str) -> str:
        patch = extract_unified_diff(text)
        if not patch:
            return "LLM не вернула unified diff. Изменения не сохранены как pending patch."
        patch_error = validate_unified_diff_headers(patch)
        if patch_error:
            return f"LLM вернула некорректный unified diff: {patch_error}. Изменения не сохранены как pending patch."

        try:
            check_result = self._call_tool(
                "workspace_apply_patch",
                {
                    "project_path": str(self._config.resolved_project_path),
                    "patch": patch,
                    "dry_run": True,
                },
            )
        except RuntimeError as error:
            if PENDING_PATCH_FILE.exists():
                PENDING_PATCH_FILE.unlink()
            return f"LLM вернула patch, но git apply --check его отклонил: {error}. Pending patch не сохранен."
        PENDING_PATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_PATCH_FILE.write_text(patch + "\n", encoding="utf-8")
        touched = check_result.get("touched_files")
        touched_text = ", ".join(str(item) for item in touched) if isinstance(touched, list) else "unknown"
        return f"Pending patch сохранен: {PENDING_PATCH_FILE}. Файлы: {touched_text}."

    def workspace_apply_text(self) -> str:
        if not PENDING_PATCH_FILE.exists():
            return "Pending patch не найден. Сначала выполните /workspace-edit <цель>."
        patch = PENDING_PATCH_FILE.read_text(encoding="utf-8")
        result = self._call_tool(
            "workspace_apply_patch",
            {
                "project_path": str(self._config.resolved_project_path),
                "patch": patch,
                "dry_run": False,
            },
        )
        touched = result.get("touched_files")
        touched_text = ", ".join(str(item) for item in touched) if isinstance(touched, list) else "unknown"
        return f"Patch применен. Измененные файлы: {touched_text}."

    def clear_pending_patch_text(self) -> str:
        if not PENDING_PATCH_FILE.exists():
            return "Pending patch не найден."
        PENDING_PATCH_FILE.unlink()
        return "Pending patch сброшен."

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._mcp_client.call_tool(name, arguments)
        error = result.get("error")
        if isinstance(error, str) and error.strip():
            raise RuntimeError(error)
        return result


def parse_workspace_assistant_command(text: str) -> WorkspaceAssistantCommand | None:
    clean_text = text.strip()
    if not clean_text.startswith("/"):
        return None
    parts = clean_text.split(maxsplit=1)
    name = parts[0]
    if name not in WORKSPACE_ASSISTANT_COMMANDS:
        return None
    return WorkspaceAssistantCommand(name=name, argument=parts[1] if len(parts) > 1 else "")


def parse_workspace_goal(argument: str) -> tuple[str, str]:
    clean_argument = argument.strip()
    if not clean_argument:
        raise RuntimeError("Укажите цель: /workspace <цель>")

    parts = clean_argument.split(maxsplit=1)
    if len(parts) == 2 and parts[0].casefold() in WORKSPACE_MODES:
        return parts[0].casefold(), parts[1].strip()
    return "draft", clean_argument


def workspace_intent_for_text(text: str) -> WorkspaceIntent:
    clean_text = text.strip()
    folded = clean_text.casefold()
    if _contains_any(
        folded,
        (
            "покажи diff",
            "покажи дифф",
            "покажи изменения",
            "что изменилось",
            "какие изменения",
            "текущий diff",
            "git diff",
            "show diff",
        ),
    ):
        return WorkspaceIntent(command="/workspace-diff", display_prefix="[Workspace diff]")

    if _contains_any(
        folded,
        (
            "примени",
            "применяй",
            "давай внесём",
            "давай внесем",
            "внеси эти изменения",
            "apply",
            "apply patch",
        ),
    ):
        if not PENDING_PATCH_FILE.exists():
            return WorkspaceIntent(command=f"/workspace-edit {clean_text}", display_prefix="[Workspace edit]")
        return WorkspaceIntent(command="/workspace-apply", display_prefix="[Workspace apply]")

    if _is_short_confirmation(folded):
        return WorkspaceIntent(command=f"/workspace-edit {clean_text}", display_prefix="[Workspace edit]")

    if _contains_any(
        folded,
        (
            "пиши код",
            "напиши код",
            "внеси изменения",
            "вноси изменения",
            "начинай вносить",
            "можешь вносить",
            "измени файл",
            "измени код",
            "добавь ",
            "создай ",
            "реализуй",
            "исправь",
            "почини",
            "сделай ",
            "перепиши",
            "удали ",
            "generate code",
            "write code",
            "implement",
            "fix ",
            "add ",
            "create ",
        ),
    ):
        return WorkspaceIntent(command=f"/workspace-edit {clean_text}", display_prefix="[Workspace edit]")

    return WorkspaceIntent(command=f"/workspace {clean_text}", display_prefix="[Workspace]")


def build_workspace_edit_prompt(user_goal: str) -> str:
    return (
        "Режим редактирования проекта.\n"
        "Нужно подготовить реальные изменения в файлах проекта.\n"
        "Верни только unified diff, без объяснений, без Markdown, без плана.\n"
        "Diff должен начинаться с строки вида:\n"
        "diff --git a/<relative-path> b/<relative-path>\n"
        "Используй реальные относительные пути из контекста проекта. "
        "Если текущая просьба короткая, например 'внеси изменения', продолжи предыдущую задачу из истории диалога.\n\n"
        f"Задача пользователя: {user_goal.strip()}"
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_short_confirmation(text: str) -> bool:
    normalized = " ".join(text.replace(",", " ").replace(".", " ").split())
    return normalized in {
        "да",
        "да начинай",
        "да давай",
        "да делай",
        "да пиши",
        "ок",
        "ок начинай",
        "ок давай",
        "ок делай",
        "хорошо",
        "начинай",
        "давай",
        "делай",
        "пиши",
    }


def format_workspace_result(result: dict[str, Any]) -> str:
    answer = result.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()

    lines = [str(result.get("summary") or "Workspace-задача выполнена.")]

    files_written = result.get("files_written")
    if isinstance(files_written, list) and files_written:
        lines.append("Files written:")
        lines.extend(f"- {item}" for item in files_written)

    artifact = result.get("artifact")
    if isinstance(artifact, str) and artifact:
        lines.append(f"Artifact: {artifact}")

    return "\n".join(lines)


def format_workspace_context(result: dict[str, Any]) -> str:
    safe_result = {
        "goal": result.get("goal"),
        "workflow": result.get("workflow"),
        "summary": result.get("summary"),
        "answer_draft": result.get("answer"),
        "project_files": result.get("project_files"),
        "files_read": result.get("files_read"),
        "findings": result.get("findings"),
        "file_excerpts": result.get("file_excerpts"),
    }
    return (
        "WORKSPACE_EVIDENCE_JSON\n"
        + json.dumps(safe_result, ensure_ascii=False, indent=2)
        + "\n\n"
        "Rules:\n"
        "- Answer the user's actual question in natural language.\n"
        "- If the current user message is a short confirmation, continue the previous task from conversation history.\n"
        "- Start with the answer. Do not mention MCP, evidence, context collection, read files, or internal analysis.\n"
        "- Use project_files as the project map, and file_excerpts/findings as evidence.\n"
        "- Do not list files unless the user explicitly asks which files were inspected or changed.\n"
        "- If evidence is incomplete, say what is missing and ask for confirmation before edits.\n"
        "- Do not dump internal workflow metadata unless asked.\n"
        "- For diffs, tell the user to use /workspace-diff unless diff evidence is present.\n"
        "- For source edits, provide code/patch proposal only; do not claim it was applied.\n"
    )


def format_workspace_diff(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "").strip()
    diff = str(result.get("diff") or "").strip()
    if not status and not diff:
        return "Workspace diff: изменений нет."

    lines = ["Workspace diff:"]
    if status:
        lines.extend(["", "Status:", status])
    if diff:
        lines.extend(["", "Diff:", diff[:12000]])
        if len(diff) > 12000:
            lines.append("[diff truncated]")
    return "\n".join(lines)


def extract_unified_diff(text: str) -> str:
    clean_text = text.strip()
    if "```" in clean_text:
        blocks = clean_text.split("```")
        for block in blocks:
            clean_block = block.strip()
            if clean_block.startswith("diff\n"):
                clean_block = clean_block.removeprefix("diff").strip()
            if clean_block.startswith("diff --git "):
                return clean_block
    start = clean_text.find("diff --git ")
    if start < 0:
        return ""
    return clean_text[start:].strip()


def validate_unified_diff_headers(patch: str) -> str:
    has_diff_header = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            has_diff_header = True
            parts = line.split()
            if len(parts) < 4:
                return f"неполный заголовок: {line}"
            if not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                return f"заголовок должен быть 'diff --git a/<path> b/<path>': {line}"
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            path = line[4:].strip()
            if path != "/dev/null" and not path.startswith(("a/", "b/")):
                return f"заголовок файла должен использовать a/ или b/: {line}"

    if not has_diff_header:
        return "нет заголовка diff --git"
    return ""
