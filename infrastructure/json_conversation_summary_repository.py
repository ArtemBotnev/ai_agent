import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from application.summary.conversation_summary_repository import ConversationSummaryRepository
from domain.conversation_summary import ConversationSummary


class JsonConversationSummaryRepository(ConversationSummaryRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def load(self) -> ConversationSummary:
        if not self._file_path.exists():
            return ConversationSummary()

        try:
            raw_summary = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return ConversationSummary()

        if not isinstance(raw_summary, dict):
            return ConversationSummary()

        try:
            return ConversationSummary.from_dict(raw_summary)
        except ValueError:
            return ConversationSummary()

    def save(self, summary: ConversationSummary) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._file_path.parent,
            delete=False,
        ) as temp_file:
            json.dump(summary.to_dict(), temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)

        temp_path.replace(self._file_path)
