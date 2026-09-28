from typing import Protocol

from domain.working_memory import WorkingMemory


class WorkingMemoryRepository(Protocol):
    def load(self) -> WorkingMemory:
        ...

    def save(self, memory: WorkingMemory) -> None:
        ...
