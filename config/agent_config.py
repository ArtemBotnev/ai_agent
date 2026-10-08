import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as error:  # pragma: no cover - exercised only in a broken environment.
    yaml = None
    YAML_IMPORT_ERROR = error
else:
    YAML_IMPORT_ERROR = None


AGENT_CONFIG_FILE_ENV = "AGENT_CONFIG_FILE"
DEFAULT_AGENT_CONFIG_FILE = Path("agent_config/llm.yaml")


@dataclass(frozen=True)
class ProviderConfig:
    model: str | None = None
    models: tuple[str, ...] = ()
    system_prompt_file: Path | None = None


@dataclass(frozen=True)
class OllamaConfig(ProviderConfig):
    base_url: str | None = None
    options: dict[str, int | float] = field(default_factory=dict)


@dataclass(frozen=True)
class PathConfig:
    memory_dir: Path | None = None
    profiles_dir: Path | None = None
    invariants_dir: Path | None = None


@dataclass(frozen=True)
class AgentConfig:
    config_file: Path
    provider: str | None = None
    openai: ProviderConfig = field(default_factory=ProviderConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    @property
    def config_dir(self) -> Path:
        return self.config_file.parent


def load_agent_config() -> AgentConfig:
    config_file = Path(os.getenv(AGENT_CONFIG_FILE_ENV, str(DEFAULT_AGENT_CONFIG_FILE)))
    if not config_file.exists():
        if AGENT_CONFIG_FILE_ENV in os.environ:
            raise RuntimeError(f"Файл конфигурации {config_file} не найден.")
        return AgentConfig(config_file=config_file)

    config_text = config_file.read_text(encoding="utf-8")
    raw_config = yaml.safe_load(config_text) if yaml is not None else _parse_simple_yaml(config_text)

    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise RuntimeError(f"Файл конфигурации {config_file} должен содержать YAML-объект.")

    return AgentConfig(
        config_file=config_file,
        provider=_optional_str(raw_config, "provider"),
        openai=_read_provider_config(raw_config.get("openai"), config_file),
        ollama=_read_ollama_config(raw_config.get("ollama"), config_file),
        paths=_read_path_config(raw_config.get("paths")),
    )


def _parse_simple_yaml(config_text: str) -> dict[str, Any]:
    lines = _yaml_lines(config_text)
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
        if not separator:
            raise RuntimeError(f"Некорректная строка YAML-конфигурации: {text}")

        clean_key = key.strip()
        if not clean_key:
            raise RuntimeError(f"Некорректный ключ YAML-конфигурации: {text}")
        if not isinstance(parent, dict):
            raise RuntimeError(f"Ключ {clean_key} не может быть вложен в список.")

        clean_value = raw_value.strip()
        if clean_value:
            parent[clean_key] = _parse_yaml_scalar(clean_value)
            continue

        child: dict[str, Any] | list[Any]
        next_line = _next_nested_yaml_line(lines, index, indent)
        if next_line is not None and next_line[1].startswith("- "):
            child = []
        else:
            child = {}
        parent[clean_key] = child
        stack.append((indent, child))

    return root


def _yaml_lines(config_text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw_line in config_text.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue

        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        lines.append((indent, line_without_comment.strip()))

    return lines


def _next_nested_yaml_line(
    lines: list[tuple[int, str]],
    current_index: int,
    current_indent: int,
) -> tuple[int, str] | None:
    for indent, text in lines[current_index + 1 :]:
        if indent <= current_indent:
            return None
        return indent, text

    return None


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


def _read_provider_config(raw_provider: object, config_file: Path) -> ProviderConfig:
    provider = _optional_mapping(raw_provider, "provider")
    if provider is None:
        return ProviderConfig()

    return ProviderConfig(
        model=_optional_str(provider, "model"),
        models=_string_tuple(provider.get("models"), "models"),
        system_prompt_file=_optional_prompt_path(provider, "system_prompt_file", config_file),
    )


def _read_ollama_config(raw_provider: object, config_file: Path) -> OllamaConfig:
    provider = _optional_mapping(raw_provider, "ollama")
    if provider is None:
        return OllamaConfig()

    return OllamaConfig(
        model=_optional_str(provider, "model"),
        models=_string_tuple(provider.get("models"), "models"),
        system_prompt_file=_optional_prompt_path(provider, "system_prompt_file", config_file),
        base_url=_optional_str(provider, "base_url"),
        options=_read_ollama_options(provider.get("options")),
    )


def _read_path_config(raw_paths: object) -> PathConfig:
    paths = _optional_mapping(raw_paths, "paths")
    if paths is None:
        return PathConfig()

    return PathConfig(
        memory_dir=_optional_path(paths, "memory_dir"),
        profiles_dir=_optional_path(paths, "profiles_dir"),
        invariants_dir=_optional_path(paths, "invariants_dir"),
    )


def _read_ollama_options(raw_options: object) -> dict[str, int | float]:
    options = _optional_mapping(raw_options, "ollama.options")
    if options is None:
        return {}

    supported_options = {
        "temperature": _float_option(options, "temperature", minimum=0.0, maximum=2.0),
        "num_predict": _int_option(options, "num_predict", minimum=-1),
        "num_ctx": _int_option(options, "num_ctx", minimum=1),
        "top_k": _int_option(options, "top_k", minimum=1),
        "top_p": _float_option(options, "top_p", minimum=0.0, maximum=1.0),
        "repeat_penalty": _float_option(options, "repeat_penalty", minimum=0.0),
        "seed": _int_option(options, "seed", minimum=0),
    }
    return {
        key: value
        for key, value in supported_options.items()
        if value is not None
    }


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


def _string_tuple(value: object, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = []
        for item in value:
            if not isinstance(item, str):
                raise RuntimeError(f"Список {key} в YAML-конфигурации должен содержать только строки.")
            items.append(item.strip())
    else:
        raise RuntimeError(f"Значение {key} в YAML-конфигурации должно быть списком строк.")

    return tuple(item for item in items if item)


def _optional_prompt_path(mapping: dict[str, Any], key: str, config_file: Path) -> Path | None:
    raw_path = _optional_str(mapping, key)
    if raw_path is None:
        return None

    prompt_path = Path(raw_path)
    if prompt_path.is_absolute():
        return prompt_path

    return config_file.parent / prompt_path


def _optional_path(mapping: dict[str, Any], key: str) -> Path | None:
    raw_path = _optional_str(mapping, key)
    if raw_path is None:
        return None

    return Path(raw_path)


def _int_option(
    mapping: dict[str, Any],
    key: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"Параметр ollama.options.{key} должен быть целым числом.")
    if minimum is not None and value < minimum:
        raise RuntimeError(f"Параметр ollama.options.{key} должен быть >= {minimum}.")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"Параметр ollama.options.{key} должен быть <= {maximum}.")

    return value


def _float_option(
    mapping: dict[str, Any],
    key: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Параметр ollama.options.{key} должен быть числом.")

    float_value = float(value)
    if minimum is not None and float_value < minimum:
        raise RuntimeError(f"Параметр ollama.options.{key} должен быть >= {minimum}.")
    if maximum is not None and float_value > maximum:
        raise RuntimeError(f"Параметр ollama.options.{key} должен быть <= {maximum}.")

    return float_value
