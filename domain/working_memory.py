from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkingMemory:
    items: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {"items": dict(sorted(self.items.items()))}

    def to_context(self) -> str:
        if not self.items:
            return ""

        lines = ["Working memory for the current task:"]
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

        return cls(items=items)
