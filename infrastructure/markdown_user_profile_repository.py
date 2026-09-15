from pathlib import Path

from application.memory.user_profile_repository import UserProfileRepository
from domain.user_profile import UserProfile


class MarkdownUserProfileRepository(UserProfileRepository):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def load(self) -> UserProfile:
        if not self._file_path.exists():
            return UserProfile()

        try:
            return UserProfile(self._file_path.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeDecodeError):
            return UserProfile()
