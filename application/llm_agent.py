from dataclasses import dataclass
from typing import Protocol, Sequence

from domain.message import Message


@dataclass(frozen=True)
class LlmAnswer:
    text: str
    response_tokens: int


class LlmAgent(Protocol):
    def count_tokens(self, messages: Sequence[Message]) -> int:
        ...

    def ask(self, messages: Sequence[Message]) -> LlmAnswer:
        ...
