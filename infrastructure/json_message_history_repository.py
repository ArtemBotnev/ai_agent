import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from application.chat.message_history_repository import MessageHistoryRepository
from domain.message import Message


class JsonMessageHistoryRepository(MessageHistoryRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def load(self) -> list[Message]:
        if not self._file_path.exists():
            return []

        try:
            raw_messages = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return []

        if not isinstance(raw_messages, list):
            return []

        messages: list[Message] = []
        for raw_message in raw_messages:
            if not isinstance(raw_message, dict):
                continue

            try:
                messages.append(Message.from_dict(raw_message))
            except ValueError:
                continue

        return messages

    def save(self, messages: list[Message]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [message.to_dict() for message in messages]

        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._file_path.parent,
            delete=False,
        ) as temp_file:
            json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)

        temp_path.replace(self._file_path)
