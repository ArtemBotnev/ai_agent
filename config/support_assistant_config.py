import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.project_assistant_config import _load_config_mapping, _optional_mapping, _optional_path, _optional_str, _path_tuple


SUPPORT_ASSISTANT_CONFIG_FILE_ENV = "AGENT_SUPPORT_ASSISTANT_CONFIG_FILE"
DEFAULT_SUPPORT_ASSISTANT_CONFIG_FILE = Path("agent_config/support_assistant.local.yaml")
EXAMPLE_SUPPORT_ASSISTANT_CONFIG_FILE = Path("agent_config/support_assistant.example.yaml")


@dataclass(frozen=True)
class SupportMcpConfig:
    server_url: str = "http://localhost:8000"
    timeout_seconds: int = 10


@dataclass(frozen=True)
class SupportAssistantConfig:
    config_file: Path
    project_path: Path | None = None
    docs_paths: tuple[str, ...] = ()
    top_k: int = 5
    mcp: SupportMcpConfig = SupportMcpConfig()

    @property
    def resolved_project_path(self) -> Path:
        if self.project_path is None:
            raise RuntimeError(
                "Support assistant is not configured. Create agent_config/support_assistant.local.yaml."
            )
        return self.project_path.expanduser().resolve()


def load_support_assistant_config() -> SupportAssistantConfig:
    config_file = Path(os.getenv(SUPPORT_ASSISTANT_CONFIG_FILE_ENV, str(DEFAULT_SUPPORT_ASSISTANT_CONFIG_FILE)))
    if not config_file.exists():
        if SUPPORT_ASSISTANT_CONFIG_FILE_ENV in os.environ:
            raise RuntimeError(f"Файл конфигурации {config_file} не найден.")
        config_file = EXAMPLE_SUPPORT_ASSISTANT_CONFIG_FILE

    if not config_file.exists():
        return SupportAssistantConfig(config_file=config_file)

    raw_config = _load_config_mapping(config_file)
    support_assistant = _optional_mapping(raw_config.get("support_assistant"), "support_assistant")
    if support_assistant is None:
        return SupportAssistantConfig(config_file=config_file)

    return SupportAssistantConfig(
        config_file=config_file,
        project_path=_optional_path(support_assistant, "project_path"),
        docs_paths=tuple(path.as_posix() for path in _path_tuple(support_assistant.get("docs_paths"), "support_assistant.docs_paths")),
        top_k=_int_option(support_assistant, "top_k", default=5, minimum=1),
        mcp=_read_mcp_config(support_assistant.get("mcp")),
    )


def _read_mcp_config(raw_mcp: object) -> SupportMcpConfig:
    mcp = _optional_mapping(raw_mcp, "support_assistant.mcp")
    if mcp is None:
        return SupportMcpConfig()
    return SupportMcpConfig(
        server_url=_optional_str(mcp, "server_url") or "http://localhost:8000",
        timeout_seconds=_int_option(mcp, "timeout_seconds", default=10, minimum=1),
    )


def _int_option(mapping: dict[str, Any], key: str, *, default: int, minimum: int) -> int:
    value = mapping.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"Параметр {key} должен быть целым числом.")
    if value < minimum:
        raise RuntimeError(f"Параметр {key} должен быть >= {minimum}.")
    return value
