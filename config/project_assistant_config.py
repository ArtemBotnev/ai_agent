import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as error:  # pragma: no cover - exercised only in a broken environment.
    yaml = None
    YAML_IMPORT_ERROR = error
else:
    YAML_IMPORT_ERROR = None


PROJECT_ASSISTANT_CONFIG_FILE_ENV = "AGENT_PROJECT_ASSISTANT_CONFIG_FILE"
DEFAULT_PROJECT_ASSISTANT_CONFIG_FILE = Path("agent_config/project_assistant.local.yaml")
EXAMPLE_PROJECT_ASSISTANT_CONFIG_FILE = Path("agent_config/project_assistant.example.yaml")


@dataclass(frozen=True)
class ProjectEmbeddingConfig:
    provider: str = "ollama"
    model: str = "nomic-embed-text"
    base_url: str = "http://127.0.0.1:11434"
    batch_size: int = 16
    timeout_seconds: int = 120


@dataclass(frozen=True)
class ProjectChunkingConfig:
    target_tokens: int = 500
    overlap_tokens: int = 60
    min_tokens: int = 40


@dataclass(frozen=True)
class ProjectRetrievalConfig:
    top_k: int = 5


@dataclass(frozen=True)
class ProjectMcpConfig:
    enabled: bool = False
    server_url: str = "http://localhost:8000"
    timeout_seconds: int = 10


@dataclass(frozen=True)
class ProjectAssistantConfig:
    config_file: Path
    project_path: Path | None = None
    docs_paths: tuple[Path, ...] = ()
    index_file: Path = Path("rag/project_rag_index.sqlite")
    embedding: ProjectEmbeddingConfig = ProjectEmbeddingConfig()
    chunking: ProjectChunkingConfig = ProjectChunkingConfig()
    retrieval: ProjectRetrievalConfig = ProjectRetrievalConfig()
    mcp: ProjectMcpConfig = ProjectMcpConfig()

    @property
    def resolved_project_path(self) -> Path:
        if self.project_path is None:
            raise RuntimeError(
                "Project assistant is not configured. Create agent_config/project_assistant.local.yaml."
            )
        return self.project_path.expanduser().resolve()

    @property
    def resolved_index_file(self) -> Path:
        return self.index_file.expanduser().resolve()


def load_project_assistant_config() -> ProjectAssistantConfig:
    config_file = Path(os.getenv(PROJECT_ASSISTANT_CONFIG_FILE_ENV, str(DEFAULT_PROJECT_ASSISTANT_CONFIG_FILE)))
    if not config_file.exists():
        if PROJECT_ASSISTANT_CONFIG_FILE_ENV in os.environ:
            raise RuntimeError(f"Файл конфигурации {config_file} не найден.")
        config_file = EXAMPLE_PROJECT_ASSISTANT_CONFIG_FILE

    if not config_file.exists():
        return ProjectAssistantConfig(config_file=config_file)

    raw_config = _load_config_mapping(config_file)
    project_assistant = _optional_mapping(raw_config.get("project_assistant"), "project_assistant")
    if project_assistant is None:
        return ProjectAssistantConfig(config_file=config_file)

    return ProjectAssistantConfig(
        config_file=config_file,
        project_path=_optional_path(project_assistant, "project_path"),
        docs_paths=_path_tuple(project_assistant.get("docs_paths"), "project_assistant.docs_paths"),
        index_file=_optional_path(project_assistant, "index_file") or Path("rag/project_rag_index.sqlite"),
        embedding=_read_embedding_config(project_assistant.get("embedding")),
        chunking=_read_chunking_config(project_assistant.get("chunking")),
        retrieval=_read_retrieval_config(project_assistant.get("retrieval")),
        mcp=_read_mcp_config(project_assistant.get("mcp")),
    )


def _load_config_mapping(config_file: Path) -> dict[str, Any]:
    config_text = config_file.read_text(encoding="utf-8")
    raw_config = yaml.safe_load(config_text) if yaml is not None else _parse_simple_yaml(config_text)

    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise RuntimeError(f"Файл конфигурации {config_file} должен содержать YAML-объект.")
    return raw_config


def _read_embedding_config(raw_embedding: object) -> ProjectEmbeddingConfig:
    embedding = _optional_mapping(raw_embedding, "project_assistant.embedding")
    if embedding is None:
        return ProjectEmbeddingConfig()

    provider = _optional_str(embedding, "provider") or "ollama"
    if provider not in {"ollama", "hashing"}:
        raise RuntimeError("project_assistant.embedding.provider должен быть ollama или hashing.")

    batch_size = _int_option(embedding, "batch_size", minimum=1)
    timeout_seconds = _int_option(embedding, "timeout_seconds", minimum=1)
    return ProjectEmbeddingConfig(
        provider=provider,
        model=_optional_str(embedding, "model") or "nomic-embed-text",
        base_url=_optional_str(embedding, "base_url") or "http://127.0.0.1:11434",
        batch_size=batch_size if batch_size is not None else 16,
        timeout_seconds=timeout_seconds if timeout_seconds is not None else 120,
    )


def _read_chunking_config(raw_chunking: object) -> ProjectChunkingConfig:
    chunking = _optional_mapping(raw_chunking, "project_assistant.chunking")
    if chunking is None:
        return ProjectChunkingConfig()

    target_tokens = _int_option(chunking, "target_tokens", minimum=50)
    overlap_tokens = _int_option(chunking, "overlap_tokens", minimum=0)
    min_tokens = _int_option(chunking, "min_tokens", minimum=1)
    return ProjectChunkingConfig(
        target_tokens=target_tokens if target_tokens is not None else 500,
        overlap_tokens=overlap_tokens if overlap_tokens is not None else 60,
        min_tokens=min_tokens if min_tokens is not None else 40,
    )


def _read_retrieval_config(raw_retrieval: object) -> ProjectRetrievalConfig:
    retrieval = _optional_mapping(raw_retrieval, "project_assistant.retrieval")
    if retrieval is None:
        return ProjectRetrievalConfig()

    top_k = _int_option(retrieval, "top_k", minimum=1)
    return ProjectRetrievalConfig(
        top_k=top_k if top_k is not None else 5,
    )


def _read_mcp_config(raw_mcp: object) -> ProjectMcpConfig:
    mcp = _optional_mapping(raw_mcp, "project_assistant.mcp")
    if mcp is None:
        return ProjectMcpConfig()

    timeout_seconds = _int_option(mcp, "timeout_seconds", minimum=1)
    return ProjectMcpConfig(
        enabled=_bool_option(mcp, "enabled") if _bool_option(mcp, "enabled") is not None else False,
        server_url=_optional_str(mcp, "server_url") or "http://localhost:8000",
        timeout_seconds=timeout_seconds if timeout_seconds is not None else 10,
    )


def _optional_mapping(value: object, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError(f"Секция {name} в YAML-конфигурации должна быть объектом.")
    return value


def _optional_str(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Значение {key} в YAML-конфигурации должно быть строкой.")
    clean_value = value.strip()
    return clean_value or None


def _optional_path(mapping: dict[str, Any], key: str) -> Path | None:
    raw_path = _optional_str(mapping, key)
    if raw_path is None:
        return None
    return Path(raw_path)


def _path_tuple(value: object, key: str) -> tuple[Path, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = []
        for item in value:
            if not isinstance(item, str):
                raise RuntimeError(f"Список {key} должен содержать только строки.")
            items.append(item.strip())
    else:
        raise RuntimeError(f"Значение {key} должно быть списком строк.")

    return tuple(Path(item) for item in items if item)


def _int_option(mapping: dict[str, Any], key: str, *, minimum: int | None = None) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"Параметр {key} должен быть целым числом.")
    if minimum is not None and value < minimum:
        raise RuntimeError(f"Параметр {key} должен быть >= {minimum}.")
    return value


def _bool_option(mapping: dict[str, Any], key: str) -> bool | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise RuntimeError(f"Параметр {key} должен быть boolean.")
    return value


def _parse_simple_yaml(config_text: str) -> dict[str, Any]:
    lines = []
    for raw_line in config_text.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if line_without_comment.strip():
            indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
            lines.append((indent, line_without_comment.strip()))

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any] | list[Any]]] = [(-1, root)]
    for index, (indent, text) in enumerate(lines):
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if text.startswith("- "):
            if not isinstance(parent, list):
                raise RuntimeError("YAML-конфигурация содержит список без родительского ключа.")
            parent.append(_parse_yaml_scalar(text[2:].strip()))
            continue

        key, separator, raw_value = text.partition(":")
        if not separator or not isinstance(parent, dict):
            raise RuntimeError(f"Некорректная строка YAML-конфигурации: {text}")
        clean_value = raw_value.strip()
        if clean_value:
            parent[key.strip()] = _parse_yaml_scalar(clean_value)
            continue

        next_line = next((line for line in lines[index + 1 :] if line[0] > indent), None)
        child: dict[str, Any] | list[Any] = [] if next_line is not None and next_line[1].startswith("- ") else {}
        parent[key.strip()] = child
        stack.append((indent, child))

    return root


def _parse_yaml_scalar(raw_value: str) -> str | int | float | bool | None:
    value = raw_value.strip().strip('"').strip("'")
    normalized_value = value.lower()
    if normalized_value == "true":
        return True
    if normalized_value == "false":
        return False
    if normalized_value in {"null", "none", "~"}:
        return None

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value
