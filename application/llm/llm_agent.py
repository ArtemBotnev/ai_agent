from dataclasses import dataclass
from typing import Protocol, Sequence

from domain.message import Message


@dataclass(frozen=True)
class LlmAnswer:
    text: str
    response_tokens: int
    duration_seconds: float = 0.0


class LlmAgent(Protocol):
    def count_tokens(self, messages: Sequence[Message], *, context: str = "") -> int:
        ...

    def ask(self, messages: Sequence[Message], *, context: str = "") -> LlmAnswer:
        ...
