from dataclasses import dataclass, field
from typing import Protocol

from domain.agent_memory import AgentMemorySnapshot
from domain.message import Message


@dataclass(frozen=True)
class TaskAgentContext:
    user_message: Message
    memory_snapshot: AgentMemorySnapshot


@dataclass(frozen=True)
class TaskAgentUsage:
    prompt_tokens: int = 0
    response_tokens: int = 0


@dataclass(frozen=True)
class PlanningAgentResult:
    reply: str
    task: str
    plan: list[str] = field(default_factory=list)
    current: str = ""
    awaiting_confirmation: bool = False
    ready_for_execution: bool = False
    usage: TaskAgentUsage = field(default_factory=TaskAgentUsage)


@dataclass(frozen=True)
class ExecutionAgentResult:
    reply: str
    needs_clarification: bool = False
    completed_steps: list[str] = field(default_factory=list)
    current: str = ""
    artifact: str = ""
    usage: TaskAgentUsage = field(default_factory=TaskAgentUsage)


@dataclass(frozen=True)
class ValidationAgentResult:
    reply: str
    valid: bool = False
    issues: list[str] = field(default_factory=list)
    revision_request: str = ""
    usage: TaskAgentUsage = field(default_factory=TaskAgentUsage)


@dataclass(frozen=True)
class DoneAgentResult:
    reply: str
    usage: TaskAgentUsage = field(default_factory=TaskAgentUsage)


class PlanningAgent(Protocol):
    def run(self, context: TaskAgentContext) -> PlanningAgentResult:
        ...


class ExecutionAgent(Protocol):
    def run(self, context: TaskAgentContext, revision_request: str = "") -> ExecutionAgentResult:
        ...


class ValidationAgent(Protocol):
    def run(self, context: TaskAgentContext, artifact: str) -> ValidationAgentResult:
        ...


class DoneAgent(Protocol):
    def run(self, context: TaskAgentContext, artifact: str, validation_summary: str) -> DoneAgentResult:
        ...
