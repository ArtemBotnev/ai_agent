from dataclasses import dataclass, field

from domain.task_state import TaskState


@dataclass(frozen=True)
class WorkingMemory:
    items: dict[str, str] = field(default_factory=dict)
    task_state: TaskState = field(default_factory=TaskState)

    def to_dict(self) -> dict[str, object]:
        return {
            "items": dict(sorted(self.items.items())),
            "task_state": self.task_state.to_dict(),
        }

    def to_context(self) -> str:
        lines = [self.task_state.to_context()]

        if self.items:
            lines.append("Working memory for the current task:")
            for key, value in sorted(self.items.items()):
                lines.append(f"- {key}: {value}")

        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WorkingMemory":
        raw_items = data.get("items", {})
        if not isinstance(raw_items, dict):
            raise ValueError("Working memory items must be an object.")

        items: dict[str, str] = {}
        for key, value in raw_items.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue

            clean_key = key.strip()
            clean_value = value.strip()
            if clean_key and clean_value:
                items[clean_key] = clean_value

        raw_task_state = data.get("task_state", {})
        if not isinstance(raw_task_state, dict):
            raise ValueError("Working memory task_state must be an object.")

        task_state = TaskState.from_dict(raw_task_state)
        if not task_state.task and "current_goal" in items:
            task_state = task_state.apply_update({"task": items["current_goal"]})

        return cls(
            items=items,
            task_state=task_state,
        )
