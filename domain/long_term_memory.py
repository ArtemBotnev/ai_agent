from dataclasses import dataclass, field


LONG_TERM_MEMORY_SECTIONS = ("profile", "decisions", "knowledge")


@dataclass(frozen=True)
class LongTermMemory:
    profile: dict[str, str] = field(default_factory=dict)
    decisions: dict[str, str] = field(default_factory=dict)
    knowledge: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            "profile": dict(sorted(self.profile.items())),
            "decisions": dict(sorted(self.decisions.items())),
            "knowledge": dict(sorted(self.knowledge.items())),
        }

    def to_context(self) -> str:
        section_lines = []
        for section_name, section_title, items in (
            ("profile", "Profile", self.profile),
            ("decisions", "Decisions", self.decisions),
            ("knowledge", "Knowledge", self.knowledge),
        ):
            if not items:
                continue

            section_lines.append(f"{section_title}:")
            for key, value in sorted(items.items()):
                section_lines.append(f"- {key}: {value}")

        if not section_lines:
            return ""

        return "\n".join(["Long-term memory:"] + section_lines)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "LongTermMemory":
        return cls(
            profile=_read_section(data, "profile"),
            decisions=_read_section(data, "decisions"),
            knowledge=_read_section(data, "knowledge"),
        )


def _read_section(data: dict[str, object], section_name: str) -> dict[str, str]:
    raw_section = data.get(section_name, {})
    if not isinstance(raw_section, dict):
        raise ValueError(f"Long-term memory section must be an object: {section_name}")

    section: dict[str, str] = {}
    for key, value in raw_section.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue

        clean_key = key.strip()
        clean_value = value.strip()
        if clean_key and clean_value:
            section[clean_key] = clean_value

    return section
