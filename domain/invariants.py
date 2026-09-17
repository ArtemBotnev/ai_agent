from dataclasses import dataclass


@dataclass(frozen=True)
class Invariants:
    content: str = ""

    def to_context(self) -> str:
        clean_content = self.content.strip()
        if not clean_content:
            return ""

        return "\n".join(
            [
                "Invariants that must not be violated:",
                "Every bullet in every section is mandatory. Architecture, technical decisions, "
                "stack constraints, and business rules have equal priority. When a user request "
                "conflicts with an invariant, identify the closest matching violated bullet from "
                "the relevant section and do not replace it with unrelated invariants.",
                clean_content,
            ]
        )
