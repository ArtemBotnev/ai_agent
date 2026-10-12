import re
from dataclasses import dataclass


TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.MULTILINE)


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


def tokenize(text: str) -> list[Token]:
    return [Token(match.group(0), match.start(), match.end()) for match in TOKEN_RE.finditer(text)]


def token_count(text: str) -> int:
    return len(tokenize(text))


def slice_by_token_range(text: str, start_token_index: int, end_token_exclusive: int) -> tuple[str, int, int, int]:
    tokens = tokenize(text)
    if not tokens:
        return "", 0, 0, 0

    safe_start = max(0, min(start_token_index, len(tokens) - 1))
    safe_end = max(safe_start + 1, min(end_token_exclusive, len(tokens)))
    start_offset = tokens[safe_start].start
    end_offset = tokens[safe_end - 1].end
    sliced = text[start_offset:end_offset].strip()
    return sliced, start_offset, end_offset, safe_end - safe_start
