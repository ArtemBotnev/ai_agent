from typing import Protocol

from domain.message import Message


class MessageHistoryRepository(Protocol):
    def load(self) -> list[Message]:
        ...

    def save(self, messages: list[Message]) -> None:
        ...
