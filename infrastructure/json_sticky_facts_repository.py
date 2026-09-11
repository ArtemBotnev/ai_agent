import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from application.sticky_facts_repository import StickyFactsRepository
from domain.sticky_facts import StickyFacts


class JsonStickyFactsRepository(StickyFactsRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def load(self) -> StickyFacts:
        if not self._file_path.exists():
            return StickyFacts()

        try:
            raw_facts = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return StickyFacts()

        if not isinstance(raw_facts, dict):
            return StickyFacts()

        try:
            return StickyFacts.from_dict(raw_facts)
        except ValueError:
            return StickyFacts()

    def save(self, facts: StickyFacts) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._file_path.parent,
            delete=False,
        ) as temp_file:
            json.dump(facts.to_dict(), temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)

        temp_path.replace(self._file_path)
