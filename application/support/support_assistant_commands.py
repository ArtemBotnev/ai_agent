import json
from dataclasses import dataclass
from typing import Any

from config.support_assistant_config import SupportAssistantConfig
from infrastructure.project_context_client import McpProjectContextClient


SUPPORT_ASSISTANT_COMMANDS = {"/support", "/support-rag", "/support-clear"}
SUPPORT_SYSTEM_CONTEXT = """
You are a product/project support assistant.
Use ticket/user context when present, plus project facts, text matches, and retrieved documentation chunks.
If the provided context is insufficient, say what is missing and suggest the next support action.
Do not invent account state, incidents, security facts, refunds, or product behavior.
Answer only from AIT/1 facts, matches, and retrieved chunks.
If AIT/1 contains no relevant fact or chunk for the user's question, say that the indexed context does not contain enough information.
""".strip()


@dataclass(frozen=True)
class SupportAssistantCommand:
    name: str
    argument: str


@dataclass(frozen=True)
class SupportAnswerRequest:
    prompt: str
    context: str
    direct_answer: str | None = None


class SupportAssistantCommandService:
    def __init__(self, config: SupportAssistantConfig) -> None:
        self._config = config
        self._mcp_client = McpProjectContextClient(
            server_url=config.mcp.server_url,
            timeout_seconds=config.mcp.timeout_seconds,
        )

    def support_status_text(self) -> str:
        status = self._call_tool("rag_status", self._base_arguments())
        return "\n".join(
            [
                f"Support project: {self._config.resolved_project_path}",
                f"MCP: {self._config.mcp.server_url}",
                f"Docs: {', '.join(self._config.docs_paths) if self._config.docs_paths else 'default'}",
                "CRM: configured on MCP server",
                f"RAG: {format_support_rag_status(status)}",
            ]
        )

    def support_rag_text(self, argument: str) -> str:
        command = argument.strip() or "status"
        if command == "status":
            status = self._call_tool("rag_status", self._base_arguments())
            return format_support_rag_status(status)
        if command == "build":
            result = self._call_tool("rag_build", self._rag_arguments())
            return format_support_rag_build_result("Support RAG построен", result)
        if command == "refresh":
            result = self._call_tool("rag_refresh", {**self._rag_arguments(), "force": False})
            return format_support_rag_build_result("Support RAG обновлен", result)
        if command == "rebuild":
            result = self._call_tool("rag_refresh", {**self._rag_arguments(), "force": True})
            return format_support_rag_build_result("Support RAG перестроен", result)
        return "Неизвестная команда support RAG. Используйте: /support-rag status, build, refresh или rebuild."

    def prepare_support_request(self, argument: str) -> SupportAnswerRequest:
        ticket_id, question = parse_support_question(argument)
        context_result = self._call_tool(
            "prepare_context",
            {
                **self._rag_arguments(),
                "ticket_id": ticket_id or "",
                "question": question,
                "limit": self._config.top_k,
            },
        )
        if not has_support_evidence(context_result):
            return SupportAnswerRequest(
                prompt="",
                context="",
                direct_answer=(
                    "В проиндексированном контексте MCP нет данных, чтобы ответить на этот вопрос. "
                    "Нужно добавить документацию/код с этой информацией в индекс или уточнить вопрос."
                ),
            )
        prompt = (
            "Ответь на вопрос пользователя поддержки на русском языке. "
            "Учитывай состояние тикета и данные пользователя, если они есть.\n\n"
            f"Ticket: {ticket_id or 'not provided'}\n"
            f"Question: {question}"
        )
        return SupportAnswerRequest(prompt=prompt, context=format_support_context(context_result))

    def clear_support_data_text(self) -> str:
        result = self._call_tool("clear_support_data", {})
        cleared = result.get("cleared")
        if isinstance(cleared, list):
            cleared_text = ", ".join(str(item) for item in cleared)
        else:
            cleared_text = "support tickets and histories"
        return f"Support data очищены на MCP: {cleared_text}."

    def _base_arguments(self) -> dict[str, Any]:
        return {
            "project_path": str(self._config.resolved_project_path),
        }

    def _rag_arguments(self) -> dict[str, Any]:
        return {
            **self._base_arguments(),
            "docs_paths": list(self._config.docs_paths) or None,
        }

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._mcp_client.call_tool(name, arguments)
        error = result.get("error")
        if isinstance(error, str) and error.strip():
            raise RuntimeError(error)
        return result


def parse_support_assistant_command(text: str) -> SupportAssistantCommand | None:
    clean_text = text.strip()
    if not clean_text.startswith("/"):
        return None
    parts = clean_text.split(maxsplit=1)
    name = parts[0]
    if name not in SUPPORT_ASSISTANT_COMMANDS:
        return None
    return SupportAssistantCommand(name=name, argument=parts[1] if len(parts) > 1 else "")


def parse_support_question(argument: str) -> tuple[str | None, str]:
    clean_argument = argument.strip()
    if not clean_argument:
        raise RuntimeError("Укажите вопрос: /support [ticket_id] <вопрос>")
    parts = clean_argument.split(maxsplit=1)
    if len(parts) >= 2 and _looks_like_ticket_id(parts[0]):
        return parts[0], parts[1]
    return None, clean_argument


def _looks_like_ticket_id(value: str) -> bool:
    clean_value = value.strip()
    if len(clean_value) < 2:
        return False
    if clean_value.startswith("#"):
        return True
    return any(char.isdigit() for char in clean_value) and any(
        separator in clean_value for separator in ("-", "_", ":")
    )


def format_support_context(context_result: dict[str, Any]) -> str:
    return "\n".join([SUPPORT_SYSTEM_CONTEXT, "", format_support_ait_context(context_result)])


def has_support_evidence(context_result: dict[str, Any]) -> bool:
    facts = context_result.get("answer_facts")
    if isinstance(facts, list) and facts:
        return True
    chunks = context_result.get("chunks")
    return isinstance(chunks, list) and bool(chunks)


def format_support_ait_context(context_result: dict[str, Any]) -> str:
    lines = [
        "AIT/1",
        "RULE answer_facts are authoritative when present",
        "RULE no relevant F/M/R lines means insufficient indexed context",
    ]
    ticket = context_result.get("ticket")
    if isinstance(ticket, dict):
        lines.append("T " + _compact_mapping(ticket, ("id", "status", "user_id", "last_error", "summary")))
    user = context_result.get("user")
    if isinstance(user, dict):
        lines.append("U " + _compact_mapping(user, ("id", "email", "plan")))
    plan = context_result.get("support_context_plan")
    if isinstance(plan, dict):
        lines.append(
            "P "
            + _compact_mapping(
                plan,
                ("source", "needs_rag", "needs_code_stats", "needs_dependencies", "needs_project_overview", "reason"),
            )
        )
    for fact in context_result.get("answer_facts", []):
        if isinstance(fact, dict):
            lines.extend(_format_fact(fact))
    for chunk in context_result.get("chunks", [])[:5]:
        if isinstance(chunk, dict):
            source = chunk.get("relative_path") or chunk.get("file_path") or ""
            score = chunk.get("score")
            text = _one_line(str(chunk.get("text") or ""))[:700]
            lines.append(f"R src={source} score={score} text={text}")
    return "\n".join(lines)


def _format_fact(fact: dict[str, Any]) -> list[str]:
    fact_type = fact.get("type")
    data = fact.get("data")
    if fact_type == "code_stats" and isinstance(data, dict):
        lines = [
            f"F code_stats class_count={data.get('class_count')} scanned={data.get('scanned_documents')}"
        ]
        for item in data.get("classes", [])[:80]:
            if isinstance(item, dict):
                lines.append(f"C name={item.get('name')} path={item.get('relative_path')}")
        return lines
    if fact_type == "dependencies" and isinstance(data, dict):
        lines = [f"F dependencies count={len(data.get('dependencies', []))}"]
        for item in data.get("dependencies", [])[:80]:
            if isinstance(item, dict):
                lines.append(f"D path={item.get('relative_path')} decl={_one_line(str(item.get('declaration')))}")
        return lines
    if fact_type == "text_search":
        lines = [f"F text_search query={fact.get('query')}"]
        for item in fact.get("matches", [])[:20]:
            if isinstance(item, dict):
                lines.append(f"M path={item.get('relative_path')} text={_one_line(str(item.get('snippet')))}")
        return lines
    if fact_type == "project_overview" and isinstance(data, dict):
        lines = [
            f"F project_overview summary={_one_line(str(data.get('summary') or ''))}",
            f"F project_overview source_files_count={data.get('source_files_count')} documents_scanned={data.get('documents_scanned')}",
        ]
        readme_excerpt = _one_line(str(data.get("readme_excerpt") or ""))
        if readme_excerpt:
            lines.append(f"O readme={readme_excerpt[:1200]}")
        build_files = data.get("build_files")
        if isinstance(build_files, list) and build_files:
            lines.append("O build_files=" + ",".join(str(item) for item in build_files[:20]))
        source_files = data.get("source_files_sample")
        if isinstance(source_files, list) and source_files:
            lines.append("O source_files=" + ",".join(str(item) for item in source_files[:40]))
        return lines
    return ["F " + _one_line(json.dumps(fact, ensure_ascii=False, separators=(',', ':')))]


def _compact_mapping(mapping: dict[str, Any], keys: tuple[str, ...]) -> str:
    parts = []
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            parts.append(f"{key}={_one_line(str(value))}")
    return " ".join(parts)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def format_support_rag_status(status: dict[str, Any]) -> str:
    if not status.get("exists"):
        return f"индекс не найден ({status.get('index_file')})."
    created_at = f", создан — {status.get('created_at')}" if status.get("created_at") else ""
    return (
        f"документов — {status.get('documents', 0)}, "
        f"чанков — {status.get('chunks', 0)}, "
        f"индекс — {status.get('index_file')}{created_at}."
    )


def format_support_rag_build_result(prefix: str, result: dict[str, Any]) -> str:
    status = result.get("status")
    status_text = f", статус — {status}" if status else ""
    return (
        f"{prefix}: документов — {result.get('documents', 0)}, "
        f"чанков — {result.get('chunks', 0)}, "
        f"индекс — {result.get('index_file')}{status_text}."
    )
