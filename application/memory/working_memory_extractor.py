from typing import Protocol, Sequence

from domain.message import Message
from domain.working_memory import WorkingMemory


class WorkingMemoryExtractor(Protocol):
    def update(self, memory: WorkingMemory, messages: Sequence[Message]) -> WorkingMemory:
        ...
