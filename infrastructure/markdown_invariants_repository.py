from pathlib import Path

from application.memory.invariants_repository import InvariantsRepository
from domain.invariants import Invariants


class MarkdownInvariantsRepository(InvariantsRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def load(self) -> Invariants:
        if not self._file_path.exists():
            return Invariants()

        try:
            return Invariants(self._file_path.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeDecodeError):
            return Invariants()
