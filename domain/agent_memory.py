from dataclasses import dataclass
from enum import Enum

from domain.long_term_memory import LongTermMemory
from domain.message import Message
from domain.working_memory import WorkingMemory


class MemoryType(Enum):
    SHORT_TERM = "short_term"
    WORKING = "working"
    LONG_TERM = "long_term"


@dataclass(frozen=True)
class AgentMemorySnapshot:
    short_term: list[Message]
    working: WorkingMemory
    long_term: LongTermMemory

    def to_context(self) -> str:
        context_parts = [
            self.working.to_context(),
            self.long_term.to_context(),
        ]
        return "\n\n".join(part for part in context_parts if part)
