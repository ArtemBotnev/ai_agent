from typing import Protocol

from domain.sticky_facts import StickyFacts


class StickyFactsRepository(Protocol):
    def load(self) -> StickyFacts:
        ...

    def save(self, facts: StickyFacts) -> None:
        ...
