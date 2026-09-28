from dataclasses import dataclass, field

from domain.message import Message

DEFAULT_BRANCH_ID = "main"


@dataclass(frozen=True)
class ConversationBranch:
    name: str
    messages: list[Message] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "messages": [message.to_dict() for message in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ConversationBranch":
        name = data.get("name")
        raw_messages = data.get("messages", [])
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Conversation branch name must be a non-empty string.")

        if not isinstance(raw_messages, list):
            raise ValueError("Conversation branch messages must be a list.")

        messages: list[Message] = []
        for raw_message in raw_messages:
            if not isinstance(raw_message, dict):
                continue

            try:
                messages.append(Message.from_dict(raw_message))
            except ValueError:
                continue

        return cls(name=name.strip(), messages=messages)


@dataclass(frozen=True)
class ConversationBranches:
    active_branch_id: str = DEFAULT_BRANCH_ID
    checkpoint_messages: list[Message] = field(default_factory=list)
    branches: dict[str, ConversationBranch] = field(
        default_factory=lambda: {
            DEFAULT_BRANCH_ID: ConversationBranch(name="Main"),
        }
    )

    @property
    def active_branch(self) -> ConversationBranch:
        return self.branches[self.active_branch_id]

    def to_dict(self) -> dict[str, object]:
        return {
            "active_branch_id": self.active_branch_id,
            "checkpoint_messages": [
                message.to_dict() for message in self.checkpoint_messages
            ],
            "branches": {
                branch_id: branch.to_dict()
                for branch_id, branch in sorted(self.branches.items())
            },
        }

    @classmethod
    def empty(cls) -> "ConversationBranches":
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ConversationBranches":
        active_branch_id = data.get("active_branch_id", DEFAULT_BRANCH_ID)
        raw_checkpoint_messages = data.get("checkpoint_messages", [])
        raw_branches = data.get("branches", {})
        if not isinstance(active_branch_id, str) or not active_branch_id.strip():
            raise ValueError("Active branch id must be a non-empty string.")

        if not isinstance(raw_checkpoint_messages, list):
            raise ValueError("Checkpoint messages must be a list.")

        if not isinstance(raw_branches, dict):
            raise ValueError("Branches must be an object.")

        checkpoint_messages: list[Message] = []
        for raw_message in raw_checkpoint_messages:
            if not isinstance(raw_message, dict):
                continue

            try:
                checkpoint_messages.append(Message.from_dict(raw_message))
            except ValueError:
                continue

        branches: dict[str, ConversationBranch] = {}
        for branch_id, raw_branch in raw_branches.items():
            if not isinstance(branch_id, str) or not isinstance(raw_branch, dict):
                continue

            clean_branch_id = branch_id.strip()
            if not clean_branch_id:
                continue

            try:
                branches[clean_branch_id] = ConversationBranch.from_dict(raw_branch)
            except ValueError:
                continue

        if not branches:
            branches = {DEFAULT_BRANCH_ID: ConversationBranch(name="Main")}

        if active_branch_id not in branches:
            active_branch_id = next(iter(branches))

        return cls(
            active_branch_id=active_branch_id,
            checkpoint_messages=checkpoint_messages,
            branches=branches,
        )
