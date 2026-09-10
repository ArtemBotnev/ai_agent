from typing import Protocol

from domain.conversation_summary import ConversationSummary


class ConversationSummaryRepository(Protocol):
    def load(self) -> ConversationSummary:
        ...

    def save(self, summary: ConversationSummary) -> None:
        ...
