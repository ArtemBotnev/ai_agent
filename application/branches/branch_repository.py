from typing import Protocol

from domain.conversation_branch import ConversationBranches


class BranchRepository(Protocol):
    def load(self) -> ConversationBranches:
        ...

    def save(self, branches: ConversationBranches) -> None:
        ...
