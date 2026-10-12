import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from application.project_help.embeddings import EmbeddingClient, cosine_similarity
from application.project_help.tokenizer import slice_by_token_range, token_count
from config.project_assistant_config import ProjectAssistantConfig


SUPPORTED_DOC_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".proto",
}
EXCLUDED_DIR_NAMES = {".git", ".idea", ".venv", "__pycache__", "node_modules", "build", "dist"}
EXCLUDED_FILE_SUFFIXES = {".local.yaml", ".local.yml", ".env"}
MAX_TEXT_FILE_BYTES = 1_000_000


@dataclass(frozen=True)
class SourceDocument:
    file_path: str
    title: str
    content_type: str
    text: str


@dataclass(frozen=True)
class ProjectChunk:
    chunk_id: str
    file_path: str
    title: str
    section: str
    content_type: str
    start_offset: int
    end_offset: int
    token_count: int
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class RetrievedProjectChunk:
    chunk_id: str
    file_path: str
    title: str
    section: str
    score: float
    text: str


@dataclass(frozen=True)
class ProjectRagBuildResult:
    documents: int
    chunks: int
    index_file: Path


@dataclass(frozen=True)
class ProjectRagStatus:
    exists: bool
    documents: int = 0
    chunks: int = 0
    index_file: Path | None = None
    created_at: str | None = None


class ProjectRagIndex:
    def __init__(self, config: ProjectAssistantConfig, embedding_client: EmbeddingClient) -> None:
        self.config = config
        self.embedding_client = embedding_client

    def build(self) -> ProjectRagBuildResult:
        project_path = self.config.resolved_project_path
        if not project_path.exists() or not project_path.is_dir():
            raise RuntimeError(f"Project path does not exist or is not a directory: {project_path}")

        documents = load_project_documents(project_path, self.config.docs_paths)
        if not documents:
            raise RuntimeError(f"No supported documentation files found for project: {project_path}")

        chunks = [
            chunk
            for document in documents
            for chunk in chunk_document(document, self.config.chunking.target_tokens, self.config.chunking.overlap_tokens)
            if chunk.token_count >= self.config.chunking.min_tokens
        ]
        if not chunks:
            raise RuntimeError("Documentation files were found, but no chunks were produced.")

        embeddings = self.embedding_client.embed_all(chunk.text for chunk in chunks)
        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding client returned an unexpected number of embeddings.")

        embedded_chunks = [
            ProjectChunk(
                chunk_id=chunk.chunk_id,
                file_path=chunk.file_path,
                title=chunk.title,
                section=chunk.section,
                content_type=chunk.content_type,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                token_count=chunk.token_count,
                text=chunk.text,
                embedding=embedding,
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
        write_index(self.config.resolved_index_file, documents, embedded_chunks)
        return ProjectRagBuildResult(
            documents=len(documents),
            chunks=len(embedded_chunks),
            index_file=self.config.resolved_index_file,
        )

    def status(self) -> ProjectRagStatus:
        return read_status(self.config.resolved_index_file)

    def search(self, question: str, limit: int) -> list[RetrievedProjectChunk]:
        clean_question = question.strip()
        if not clean_question:
            raise RuntimeError("Question must not be blank.")

        chunks = load_chunks(self.config.resolved_index_file)
        if not chunks:
            raise RuntimeError("Project RAG index is empty. Run /project-rag build first.")

        query_embedding = self.embedding_client.embed_all([clean_question])[0]
        scored = sorted(
            (
                RetrievedProjectChunk(
                    chunk_id=chunk.chunk_id,
                    file_path=chunk.file_path,
                    title=chunk.title,
                    section=chunk.section,
                    score=cosine_similarity(query_embedding, chunk.embedding),
                    text=chunk.text,
                )
                for chunk in chunks
            ),
            key=lambda item: item.score,
            reverse=True,
        )
        return scored[:limit]


def load_project_documents(project_path: Path, docs_paths: tuple[Path, ...]) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    for configured_path in docs_paths or (Path("README.md"), Path("project/docs")):
        absolute_path = _resolve_inside_project(project_path, configured_path)
        if absolute_path.is_file():
            document = load_document(absolute_path, project_path)
            if document is not None:
                documents.append(document)
            continue
        if absolute_path.is_dir():
            for path in sorted(absolute_path.rglob("*")):
                if path.is_file() and should_include(path, project_path):
                    document = load_document(path, project_path)
                    if document is not None:
                        documents.append(document)
    return documents


def should_include(path: Path, project_path: Path) -> bool:
    try:
        relative_parts = path.relative_to(project_path).parts
    except ValueError:
        return False
    if any(part in EXCLUDED_DIR_NAMES for part in relative_parts):
        return False
    name = path.name.lower()
    if any(name.endswith(suffix) for suffix in EXCLUDED_FILE_SUFFIXES):
        return False
    if path.suffix.lower() not in SUPPORTED_DOC_SUFFIXES:
        return False
    return path.stat().st_size <= MAX_TEXT_FILE_BYTES


def load_document(path: Path, project_path: Path) -> SourceDocument | None:
    if not should_include(path, project_path):
        return None
    text = path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    return SourceDocument(
        file_path=path.relative_to(project_path).as_posix(),
        title=extract_title(path, text),
        content_type=content_type_for(path),
        text=text,
    )


def chunk_document(document: SourceDocument, target_tokens: int, overlap_tokens: int) -> list[ProjectChunk]:
    total_tokens = token_count(document.text)
    if total_tokens == 0:
        return []

    chunks: list[ProjectChunk] = []
    step = max(1, target_tokens - overlap_tokens)
    start = 0
    index = 0
    while start < total_tokens:
        end = min(start + target_tokens, total_tokens)
        text, start_offset, end_offset, actual_tokens = slice_by_token_range(document.text, start, end)
        if text:
            chunks.append(
                ProjectChunk(
                    chunk_id=f"{document.file_path}:{index:05d}",
                    file_path=document.file_path,
                    title=document.title,
                    section=document.title,
                    content_type=document.content_type,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    token_count=actual_tokens,
                    text=text,
                    embedding=[],
                )
            )
            index += 1
        if end >= total_tokens:
            break
        start += step
    return chunks


def write_index(index_file: Path, documents: list[SourceDocument], chunks: list[ProjectChunk]) -> None:
    index_file.parent.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(index_file) as connection:
        connection.execute(
            """
            create table if not exists chunks (
                id integer primary key autoincrement,
                chunk_id text not null,
                file_path text not null,
                title text not null,
                section text not null,
                content_type text not null,
                start_offset integer not null,
                end_offset integer not null,
                token_count integer not null,
                embedding_blob blob not null,
                text_content text not null,
                created_at text not null
            )
            """
        )
        connection.execute(
            """
            create table if not exists metadata (
                key text primary key,
                value text not null
            )
            """
        )
        connection.execute("delete from chunks")
        connection.execute("delete from metadata")
        connection.executemany(
            """
            insert into chunks (
                chunk_id, file_path, title, section, content_type, start_offset,
                end_offset, token_count, embedding_blob, text_content, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.file_path,
                    chunk.title,
                    chunk.section,
                    chunk.content_type,
                    chunk.start_offset,
                    chunk.end_offset,
                    chunk.token_count,
                    encode_embedding(chunk.embedding),
                    chunk.text,
                    created_at,
                )
                for chunk in chunks
            ],
        )
        connection.executemany(
            "insert into metadata (key, value) values (?, ?)",
            [
                ("created_at", created_at),
                ("documents", str(len(documents))),
                ("chunks", str(len(chunks))),
            ],
        )


def read_status(index_file: Path) -> ProjectRagStatus:
    if not index_file.exists():
        return ProjectRagStatus(exists=False, index_file=index_file)
    with sqlite3.connect(index_file) as connection:
        metadata = dict(connection.execute("select key, value from metadata").fetchall())
        chunk_count = connection.execute("select count(*) from chunks").fetchone()[0]
    return ProjectRagStatus(
        exists=True,
        documents=int(metadata.get("documents", "0")),
        chunks=int(metadata.get("chunks", str(chunk_count))),
        index_file=index_file,
        created_at=metadata.get("created_at"),
    )


def load_chunks(index_file: Path) -> list[ProjectChunk]:
    if not index_file.exists():
        return []
    with sqlite3.connect(index_file) as connection:
        rows = connection.execute(
            """
            select chunk_id, file_path, title, section, content_type, start_offset,
                   end_offset, token_count, embedding_blob, text_content
            from chunks
            order by id
            """
        ).fetchall()
    return [
        ProjectChunk(
            chunk_id=row[0],
            file_path=row[1],
            title=row[2],
            section=row[3],
            content_type=row[4],
            start_offset=row[5],
            end_offset=row[6],
            token_count=row[7],
            embedding=decode_embedding(row[8]),
            text=row[9],
        )
        for row in rows
    ]


def encode_embedding(embedding: list[float]) -> bytes:
    return struct.pack(f"<{len(embedding)}f", *embedding)


def decode_embedding(blob: bytes) -> list[float]:
    if not blob:
        return []
    dimensions = len(blob) // 4
    return list(struct.unpack(f"<{dimensions}f", blob))


def extract_title(path: Path, text: str) -> str:
    if path.suffix.lower() in {".md", ".markdown"}:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title:
                    return title
    return path.name


def content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "MARKDOWN"
    if suffix in {".yaml", ".yml"}:
        return "YAML"
    if suffix == ".json":
        return "JSON"
    if suffix == ".toml":
        return "TOML"
    if suffix == ".proto":
        return "PROTO"
    return "TEXT"


def _resolve_inside_project(project_path: Path, configured_path: Path) -> Path:
    absolute_path = configured_path.expanduser()
    if not absolute_path.is_absolute():
        absolute_path = project_path / absolute_path
    resolved_path = absolute_path.resolve()
    try:
        resolved_path.relative_to(project_path)
    except ValueError as error:
        raise RuntimeError(f"Documentation path is outside project: {configured_path}") from error
    return resolved_path
