from dataclasses import dataclass

ASSISTANT_ROLE = "assistant"
USER_ROLE = "user"
SUPPORTED_MESSAGE_ROLES = {ASSISTANT_ROLE, USER_ROLE}


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in SUPPORTED_MESSAGE_ROLES:
            raise ValueError(f"Unsupported message role: {self.role}")

        if not self.content.strip():
            raise ValueError("Message content cannot be empty.")

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Message":
        role = data.get("role")
        content = data.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError("Message data must contain string role and content.")

        return cls(role=role, content=content)
