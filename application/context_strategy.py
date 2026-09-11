from enum import Enum


class ContextStrategy(Enum):
    SLIDING_WINDOW = "sliding_window"
    SUMMARY = "summary"
    STICKY_FACTS = "sticky_facts"
    BRANCHING = "branching"

    @property
    def display_name(self) -> str:
        return {
            ContextStrategy.SLIDING_WINDOW: "Sliding Window",
            ContextStrategy.SUMMARY: "Summary",
            ContextStrategy.STICKY_FACTS: "Sticky Facts",
            ContextStrategy.BRANCHING: "Branching",
        }[self]

    @classmethod
    def from_value(cls, value: str) -> "ContextStrategy":
        normalized_value = value.strip().lower()
        for strategy in cls:
            if strategy.value == normalized_value:
                return strategy

        raise ValueError(f"Unsupported context strategy: {value}")


def get_context_strategy_values() -> list[str]:
    return [strategy.value for strategy in ContextStrategy]
