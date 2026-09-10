from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationSummary:
    content: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ConversationSummary":
        content = data.get("content", "")
        if not isinstance(content, str):
            raise ValueError("Conversation summary content must be a string.")

        return cls(content=content.strip())
