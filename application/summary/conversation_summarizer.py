from typing import Protocol, Sequence

from domain.message import Message


class ConversationSummarizer(Protocol):
    def summarize(self, previous_summary: str, messages: Sequence[Message]) -> str:
        ...
