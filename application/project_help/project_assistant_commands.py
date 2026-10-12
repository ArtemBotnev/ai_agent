from dataclasses import dataclass

from application.project_help.project_help_service import ProjectHelpRequest, ProjectHelpService
from application.project_help.rag_index import ProjectRagStatus


PROJECT_ASSISTANT_COMMANDS = {"/project", "/project-rag", "/help"}


@dataclass(frozen=True)
class ProjectAssistantCommand:
    name: str
    argument: str


class ProjectAssistantCommandService:
    def __init__(self, project_help_service: ProjectHelpService) -> None:
        self._project_help_service = project_help_service

    def project_status_text(self) -> str:
        config = self._project_help_service.config
        project_path = config.resolved_project_path
        context = self._project_help_service.project_context_client.get_context(project_path)
        status = self._project_help_service.rag_status()
        return "\n".join(
            [
                f"Проект: {project_path}",
                f"Git-ветка: {context.git_branch}",
                format_mcp_status(config.mcp.enabled, config.mcp.server_url),
                f"Конфиг: {config.config_file}",
                format_project_rag_status(status),
            ]
        )

    def project_rag_text(self, argument: str) -> str:
        command = argument.strip() or "status"
        if command == "build":
            result = self._project_help_service.build_rag()
            return (
                "Project RAG построен: "
                f"документов — {result.documents}, чанков — {result.chunks}, индекс — {result.index_file}."
            )
        if command == "status":
            return format_project_rag_status(self._project_help_service.rag_status())

        return "Неизвестная команда project RAG. Используйте: /project-rag build или /project-rag status."

    def prepare_help_request(self, question: str) -> ProjectHelpRequest:
        return self._project_help_service.prepare_request(question)


def parse_project_assistant_command(text: str) -> ProjectAssistantCommand | None:
    clean_text = text.strip()
    if not clean_text.startswith("/"):
        return None

    parts = clean_text.split(maxsplit=1)
    name = parts[0]
    if name not in PROJECT_ASSISTANT_COMMANDS:
        return None

    return ProjectAssistantCommand(name=name, argument=parts[1] if len(parts) > 1 else "")


def format_project_rag_status(status: ProjectRagStatus) -> str:
    if not status.exists:
        return f"Project RAG: индекс не найден ({status.index_file})."

    created_at = f", создан — {status.created_at}" if status.created_at else ""
    return (
        "Project RAG: "
        f"документов — {status.documents}, чанков — {status.chunks}, индекс — {status.index_file}{created_at}."
    )


def format_mcp_status(enabled: bool, server_url: str) -> str:
    if enabled:
        return f"MCP: включен ({server_url})"
    return "MCP: выключен, используется локальный project adapter"
