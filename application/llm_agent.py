from typing import Protocol, Sequence

from domain.message import Message


class LlmAgent(Protocol):
    def ask(self, messages: Sequence[Message]) -> str:
        ...
