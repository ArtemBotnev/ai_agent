import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from application.branch_repository import BranchRepository
from domain.conversation_branch import ConversationBranches


class JsonBranchRepository(BranchRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def load(self) -> ConversationBranches:
        if not self._file_path.exists():
            return ConversationBranches.empty()

        try:
            raw_branches = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return ConversationBranches.empty()

        if not isinstance(raw_branches, dict):
            return ConversationBranches.empty()

        try:
            return ConversationBranches.from_dict(raw_branches)
        except ValueError:
            return ConversationBranches.empty()

    def save(self, branches: ConversationBranches) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._file_path.parent,
            delete=False,
        ) as temp_file:
            json.dump(branches.to_dict(), temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)

        temp_path.replace(self._file_path)
