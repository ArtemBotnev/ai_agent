import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from application.memory.working_memory_repository import WorkingMemoryRepository
from domain.working_memory import WorkingMemory


class JsonWorkingMemoryRepository(WorkingMemoryRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def load(self) -> WorkingMemory:
        if not self._file_path.exists():
            return WorkingMemory()

        try:
            raw_memory = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return WorkingMemory()

        if not isinstance(raw_memory, dict):
            return WorkingMemory()

        try:
            return WorkingMemory.from_dict(raw_memory)
        except ValueError:
            return WorkingMemory()

    def save(self, memory: WorkingMemory) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._file_path.parent,
            delete=False,
        ) as temp_file:
            json.dump(memory.to_dict(), temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)

        temp_path.replace(self._file_path)
