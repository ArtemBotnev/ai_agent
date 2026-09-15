from dataclasses import dataclass


@dataclass(frozen=True)
class UserProfile:
    content: str = ""

    def to_context(self) -> str:
        clean_content = self.content.strip()
        if not clean_content:
            return ""

        return "\n".join(
            [
                "User profile and preferences:",
                clean_content,
            ]
        )
