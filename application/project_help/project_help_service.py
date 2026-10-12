from dataclasses import dataclass

from application.project_help.embeddings import HashingEmbeddingClient, OllamaEmbeddingClient
from application.project_help.rag_index import ProjectRagBuildResult, ProjectRagIndex, ProjectRagStatus
from config.project_assistant_config import ProjectAssistantConfig
from infrastructure.project_context_client import LocalProjectContextClient, McpProjectContextClient


PROJECT_HELP_SYSTEM_CONTEXT = """
You are a developer assistant for the connected software project.
Answer questions only from the provided project documentation and project context.
If the documentation is insufficient, say what is missing and avoid inventing details.
Mention relevant file paths when they help the developer navigate the project.
""".strip()


@dataclass(frozen=True)
class ProjectHelpRequest:
    prompt: str
    context: str


class ProjectHelpService:
    def __init__(
        self,
        config: ProjectAssistantConfig,
        project_context_client: object | None = None,
    ) -> None:
        self.config = config
        self.project_context_client = project_context_client or build_project_context_client(config)
        self.rag_index = ProjectRagIndex(config, build_embedding_client(config))

    def build_rag(self) -> ProjectRagBuildResult:
        return self.rag_index.build()

    def rag_status(self) -> ProjectRagStatus:
        return self.rag_index.status()

    def prepare_request(self, question: str) -> ProjectHelpRequest:
        clean_question = question.strip()
        if not clean_question:
            raise RuntimeError("Укажите вопрос: /help <вопрос о проекте>")

        project_path = self.config.resolved_project_path
        project_context = self.project_context_client.get_context(project_path)
        chunks = self.rag_index.search(clean_question, self.config.retrieval.top_k)
        docs_context = "\n\n".join(
            (
                f"Source: {chunk.file_path}"
                f"\nTitle: {chunk.title}"
                f"\nSimilarity: {chunk.score:.3f}"
                f"\nContent:\n{chunk.text}"
            )
            for chunk in chunks
        )
        context = (
            f"{PROJECT_HELP_SYSTEM_CONTEXT}\n\n"
            f"Project path: {project_context.project_path}\n"
            f"Current git branch: {project_context.git_branch}\n\n"
            f"Retrieved project documentation:\n{docs_context}"
        )
        prompt = (
            "Answer this project question in Russian. "
            "Use the retrieved documentation and project context.\n\n"
            f"Question: {clean_question}"
        )
        return ProjectHelpRequest(prompt=prompt, context=context)


def build_embedding_client(config: ProjectAssistantConfig):
    embedding = config.embedding
    if embedding.provider == "hashing":
        return HashingEmbeddingClient()
    return OllamaEmbeddingClient(
        base_url=embedding.base_url,
        model=embedding.model,
        batch_size=embedding.batch_size,
        timeout_seconds=embedding.timeout_seconds,
    )


def build_project_context_client(config: ProjectAssistantConfig):
    if config.mcp.enabled:
        return McpProjectContextClient(
            server_url=config.mcp.server_url,
            timeout_seconds=config.mcp.timeout_seconds,
        )
    return LocalProjectContextClient()
