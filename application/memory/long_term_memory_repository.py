from typing import Protocol

from domain.long_term_memory import LongTermMemory


class LongTermMemoryRepository(Protocol):
    def load(self) -> LongTermMemory:
        ...

    def save(self, memory: LongTermMemory) -> None:
        ...
