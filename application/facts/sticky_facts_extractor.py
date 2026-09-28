from typing import Protocol, Sequence

from domain.message import Message
from domain.sticky_facts import StickyFacts


class StickyFactsExtractor(Protocol):
    def update(self, facts: StickyFacts, messages: Sequence[Message]) -> StickyFacts:
        ...
