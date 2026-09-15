from typing import Protocol

from domain.user_profile import UserProfile


class UserProfileRepository(Protocol):
    def load(self) -> UserProfile:
        pass
