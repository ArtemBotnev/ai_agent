from typing import Protocol, Sequence

from domain.long_term_memory import LongTermMemory
from domain.message import Message


class LongTermMemoryExtractor(Protocol):
    def update(self, memory: LongTermMemory, messages: Sequence[Message]) -> LongTermMemory:
        ...
