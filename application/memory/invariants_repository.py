from typing import Protocol

from domain.invariants import Invariants


class InvariantsRepository(Protocol):
    def load(self) -> Invariants:
        pass
