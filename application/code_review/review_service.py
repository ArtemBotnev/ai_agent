from dataclasses import dataclass
from pathlib import Path

from application.code_review.diff_loader import ChangedFile, PullRequestDiff
from application.project_help.project_help_service import build_embedding_client, build_project_context_client
from application.project_help.rag_index import RetrievedProjectChunk, ProjectRagIndex
from config.project_assistant_config import ProjectAssistantConfig, ProjectSourceConfig


CODE_REVIEW_SYSTEM_CONTEXT = """
You are a senior software engineer reviewing a pull request.
Review only the supplied diff, changed files, and retrieved project context.
Prioritize correctness bugs, regressions, missing tests, security risks, and architectural issues.
Do not invent files, APIs, or requirements that are not present in the context.
If there are no substantial issues, say that clearly.
Return a concise Markdown review with these sections:
## Potential Bugs
## Architecture Concerns
## Recommendations
""".strip()


@dataclass(frozen=True)
class CodeReviewRequest:
    prompt: str
    context: str


class CodeReviewService:
    def __init__(
        self,
        config: ProjectAssistantConfig,
        project_context_client: object | None = None,
    ) -> None:
        self.config = config
        self.project_context_client = project_context_client or build_project_context_client(config)
        self.rag_index = ProjectRagIndex(config, build_embedding_client(config))

    def build_rag(self) -> None:
        self.rag_index.build()

    def prepare_request(self, pull_request_diff: PullRequestDiff) -> CodeReviewRequest:
        project_context = self.project_context_client.get_context(pull_request_diff.project_path)
        review_query = _build_review_query(pull_request_diff)
        chunks = self.rag_index.search(review_query, self.config.review.top_k)
        context = "\n\n".join(
            [
                CODE_REVIEW_SYSTEM_CONTEXT,
                f"Project path: {project_context.project_path}",
                f"Current git branch: {project_context.git_branch}",
                f"Base ref: {pull_request_diff.base_ref}",
                f"Head ref: {pull_request_diff.head_ref}",
                "Changed files:\n" + _format_changed_files(pull_request_diff.changed_files),
                "Retrieved project context:\n" + _format_retrieved_chunks(chunks),
                "Changed file snapshots:\n" + _format_changed_file_snapshots(pull_request_diff.changed_files),
                "Pull request diff:\n" + pull_request_diff.diff,
            ]
        )
        prompt = (
            f"Write the pull request code review in {self.config.review.language}. "
            "Focus on potential bugs, architectural problems, and actionable recommendations. "
            "Reference file paths when useful.\n"
        )
        return CodeReviewRequest(prompt=prompt, context=context)


def _build_review_query(pull_request_diff: PullRequestDiff) -> str:
    changed_paths = ", ".join(changed_file.path for changed_file in pull_request_diff.changed_files)
    return (
        "Code review pull request. "
        f"Changed files: {changed_paths}. "
        f"Diff:\n{pull_request_diff.diff[:8000]}"
    )


def _format_changed_files(changed_files: tuple[ChangedFile, ...]) -> str:
    if not changed_files:
        return "- No changed files detected."
    lines = []
    for changed_file in changed_files:
        if changed_file.previous_path:
            lines.append(f"- {changed_file.status}: {changed_file.previous_path} -> {changed_file.path}")
        else:
            lines.append(f"- {changed_file.status}: {changed_file.path}")
    return "\n".join(lines)


def _format_retrieved_chunks(chunks: list[RetrievedProjectChunk]) -> str:
    if not chunks:
        return "No RAG chunks retrieved."
    return "\n\n".join(
        (
            f"Source: {chunk.file_path}"
            f"\nTitle: {chunk.title}"
            f"\nSimilarity: {chunk.score:.3f}"
            f"\nContent:\n{chunk.text}"
        )
        for chunk in chunks
    )


def _format_changed_file_snapshots(changed_files: tuple[ChangedFile, ...]) -> str:
    snapshots = []
    for changed_file in changed_files:
        if not changed_file.content:
            continue
        snapshots.append(
            f"File: {changed_file.path}\n"
            "```text\n"
            f"{changed_file.content}\n"
            "```"
        )
    if not snapshots:
        return "No text snapshots available."
    return "\n\n".join(snapshots)


def with_project_path(
    config: ProjectAssistantConfig,
    project_path: Path,
    index_file: Path | None = None,
    source: ProjectSourceConfig | None = None,
) -> ProjectAssistantConfig:
    return ProjectAssistantConfig(
        config_file=config.config_file,
        project_path=project_path,
        docs_paths=config.docs_paths,
        index_file=index_file or config.index_file,
        embedding=config.embedding,
        chunking=config.chunking,
        retrieval=config.retrieval,
        review=config.review,
        source=source or config.source,
        mcp=config.mcp,
        github=config.github,
    )
