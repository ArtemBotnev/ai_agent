from dataclasses import dataclass, field


TASK_STATE_STAGES = ("planning", "execution", "validation", "done")
TASK_STATE_STAGE_STEPS = {
    "planning": 1,
    "execution": 2,
    "validation": 3,
    "done": 4,
}
TASK_STATE_TOTAL_STEPS = len(TASK_STATE_STAGES)
TASK_STATE_DESCRIPTIONS = {
    "planning": "сбор требований, уточнения и предложение плана без реализации",
    "execution": "выполнение согласованного решения и создание артефактов",
    "validation": "проверка выполненного решения, тесты и сверка с планом",
    "done": "задача завершена, результат зафиксирован",
}
TASK_STATE_MARKERS = {
    "planning": "ПЛАНИРОВАНИЕ",
    "execution": "ВЫПОЛНЕНИЕ",
    "validation": "ПРОВЕРКА",
    "done": "ГОТОВО",
}
TASK_STATE_INSTRUCTIONS = {
    "planning": (
        "Ты находишься на этапе planning. Обсуждай задачу, уточняй требования "
        "и предлагай последовательный план решения. Не пиши код, diff, patch "
        "или другие артефакты реализации. Это единственный этап, где нужно "
        "вести уточняющий диалог с пользователем."
    ),
    "execution": (
        "Ты находишься на этапе execution. Выполняй согласованное решение: "
        "пиши код, diff, patch, файлы или другой конкретный артефакт. Не веди "
        "обсуждение с пользователем на этом этапе. Если для выполнения не хватает "
        "требований, явно укажи, что нужно уточнить, чтобы state machine вернула "
        "задачу в planning."
    ),
    "validation": (
        "Ты находишься на этапе validation. Проверяй выполненное решение: "
        "запускай релевантные проверки, сверяй результат с планом и фиксируй "
        "ошибки. Не веди обсуждение с пользователем на этом этапе. Покажи только "
        "результат проверки. Если проверка провалилась, state machine вернет "
        "задачу в execution; если прошла, переведет в done."
    ),
    "done": (
        "Ты находишься на этапе done. Задача завершена. Дай краткий итог и "
        "не продолжай planning, execution или validation, пока пользователь "
        "не начнет новую задачу."
    ),
}
ALLOWED_TRANSITIONS = {
    "planning": {"execution"},
    "execution": {"validation", "planning"},
    "validation": {"done", "execution"},
    "done": set(),
}

_IMPLEMENTATION_MARKERS = (
    "можно писать",
    "можно писать код",
    "можно вносить",
    "можешь писать",
    "можешь писать код",
    "можешь вносить",
    "можете писать",
    "можете писать код",
    "можете вносить",
    "могут писать",
    "могут писать код",
    "реализуй",
    "реализовывай",
    "приступай",
    "приступи",
    "переходи к выполнению",
    "переходите к выполнению",
    "можешь переходить к выполнению",
    "можете переходить к выполнению",
    "пиши код",
    "напиши код",
    "сделай реализацию",
    "делай реализацию",
    "выполни реализацию",
    "внеси изменения",
    "создай файл",
    "создай класс",
    "создай функцию",
    "на твое усмотрение",
    "на твоё усмотрение",
    "на ваше усмотрение",
    "все на твое усмотрение",
    "всё на твоё усмотрение",
    "все на ваше усмотрение",
    "всё на ваше усмотрение",
    "разрешаю",
    "подтверждаю",
    "go ahead",
    "do it",
    "proceed",
    "implement",
    "start implementation",
    "write code",
    "write the code",
)
_CLARIFICATION_MARKERS = (
    "уточн",
    "нужно уточнить",
    "не хватает",
    "нужна информация",
    "нужны данные",
    "подскажи",
    "какие",
    "какой",
    "какая",
    "как именно",
)
_VALIDATION_FAILURE_MARKERS = (
    "не проходит",
    "не прошел",
    "падает тест",
    "ошибка",
    "ошибки",
    "нужно исправить",
    "не соответствует",
    "провалилась проверка",
    "failed",
    "error",
)
_VALIDATION_SUCCESS_MARKERS = (
    "проверка пройдена",
    "валидация пройдена",
    "тесты прошли",
    "ошибок нет",
    "без ошибок",
    "явных ошибок не найдено",
    "успешно",
    "готово",
    "результат готов",
    "passed",
)
_NEW_TASK_MARKERS = (
    "новая задача",
    "другая задача",
    "следующая задача",
    "у нас новая задача",
    "теперь новая задача",
)


@dataclass(frozen=True)
class TaskState:
    task: str = ""
    stage: str = "planning"
    step: int = 0
    total: int = 0
    plan_step: int = 0
    plan_total: int = 0
    plan: tuple[str, ...] = field(default_factory=tuple)
    done: tuple[str, ...] = field(default_factory=tuple)
    current: str = ""
    paused: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "task": self.task,
            "stage": self.stage,
            "step": self.step,
            "total": self.total,
            "plan_step": self.plan_step,
            "plan_total": self.plan_total,
            "plan": list(self.plan),
            "done": list(self.done),
            "current": self.current,
            "paused": self.paused,
        }

    def to_context(self) -> str:
        lines = [
            "Task state:",
            f"- task: {self.task or 'not set'}",
            f"- stage: {self.stage}",
            f"- stage_marker: {TASK_STATE_MARKERS[self.stage]}",
            f"- stage_meaning: {TASK_STATE_DESCRIPTIONS[self.stage]}",
            f"- stage_instruction: {TASK_STATE_INSTRUCTIONS[self.stage]}",
            f"- workflow_step: {self.step}/{self.total}",
            f"- plan_step: {self.plan_step}/{self.plan_total}",
            f"- current: {self.current or 'not set'}",
            f"- paused: {str(self.paused).lower()}",
            "- allowed_transitions: planning->execution; execution->validation|planning; "
            "validation->done|execution; done has no transition except a new task reset",
        ]
        if self.plan:
            lines.append("- plan:")
            lines.extend(f"  {index}. {item}" for index, item in enumerate(self.plan, start=1))
        if self.done:
            lines.append("- done:")
            lines.extend(f"  - {item}" for item in self.done)

        return "\n".join(lines)

    def apply_update(
        self,
        data: dict[str, object],
        *,
        user_text: str = "",
        assistant_text: str = "",
    ) -> "TaskState":
        proposed = TaskState.from_dict(data)
        if not proposed.task:
            proposed = proposed._copy(task=self.task or _sanitize_task(user_text))

        if self._is_new_task(proposed, user_text):
            return proposed._copy(stage="planning", done=())._normalize()

        adjusted_stage = self._adjust_stage(proposed.stage, user_text, assistant_text)
        proposed = proposed._copy(task=self.task or proposed.task, stage=adjusted_stage)
        if self.stage != "planning":
            proposed_done = proposed.done if proposed.done else self.done
            proposed = proposed._copy(
                plan=self.plan,
                done=proposed_done,
            )

        return proposed._normalize()

    def prepare_for_user_message(self, user_text: str) -> "TaskState":
        if not self.task:
            return TaskState.start(user_text)

        if _contains_any(user_text.lower(), _NEW_TASK_MARKERS):
            return TaskState.start(user_text)

        if self.stage == "done" and _is_standalone_request(user_text) and _has_task_changed(self.task, user_text):
            return TaskState.start(user_text)

        if self.paused and _contains_any(user_text.lower(), ("продолж", "дальше", "resume", "continue")):
            return self._copy(paused=False)._normalize()

        if self.stage == "planning" and self._has_plan() and _contains_any(user_text.lower(), _IMPLEMENTATION_MARKERS):
            return self._copy(stage="execution", paused=False)._normalize()

        return self

    def apply_planning_result(
        self,
        *,
        task: str,
        plan: list[str],
        current: str,
        ready_for_execution: bool,
    ) -> "TaskState":
        updated = self._copy(
            task=task or self.task,
            stage="planning",
            plan=tuple(plan),
            done=(),
            current=current,
            paused=False,
        )._normalize()
        if ready_for_execution and updated._has_plan():
            return updated._copy(stage="execution")._normalize()

        return updated

    def apply_execution_result(
        self,
        *,
        needs_clarification: bool,
        completed_steps: list[str],
        current: str,
    ) -> "TaskState":
        stage = "planning" if needs_clarification else "validation"
        done = tuple(dict.fromkeys((*self.done, *completed_steps)))
        return self._copy(
            stage=stage,
            done=done,
            current=current,
            paused=False,
        )._normalize()

    def apply_validation_result(self, *, valid: bool, current: str = "") -> "TaskState":
        done = self.plan if valid and self.plan else self.done
        return self._copy(
            stage="done" if valid else "execution",
            done=done,
            current=current,
            paused=False,
        )._normalize()

    @classmethod
    def start(cls, task: str) -> "TaskState":
        return cls(
            task=_sanitize_task(task),
            stage="planning",
            current="Собрать требования и подготовить план",
        )._normalize()

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TaskState":
        raw_stage = data.get("stage")
        stage = raw_stage.strip().lower() if isinstance(raw_stage, str) else "planning"
        if stage not in TASK_STATE_STAGES:
            stage = "planning"

        current = _read_optional_string(data.get("current"))
        if not current:
            current = _read_optional_string(data.get("current_step"))

        return cls(
            task=_read_optional_string(data.get("task")),
            stage=stage,
            step=_read_int(data.get("step")),
            total=_read_int(data.get("total")),
            plan_step=_read_int(data.get("plan_step")),
            plan_total=_read_int(data.get("plan_total")),
            plan=tuple(_read_string_list(data.get("plan"))),
            done=tuple(_read_string_list(data.get("done"))),
            current=current,
            paused=data.get("paused") if isinstance(data.get("paused"), bool) else False,
        )._normalize()

    def _adjust_stage(self, proposed_stage: str, user_text: str, assistant_text: str) -> str:
        if self.paused and proposed_stage != self.stage:
            return self.stage

        normalized_user = user_text.lower()
        normalized_assistant = assistant_text.lower()

        if self.stage == "planning":
            if proposed_stage == "execution" and self._has_plan() and _contains_any(normalized_user, _IMPLEMENTATION_MARKERS):
                return "execution"
            return "planning"

        if self.stage == "execution":
            if _contains_any(normalized_assistant, _CLARIFICATION_MARKERS):
                return "planning"
            if proposed_stage == "planning":
                return "planning"
            if _contains_implementation_artifact(assistant_text) or proposed_stage == "validation":
                return "validation"
            return "execution"

        if self.stage == "validation":
            if _contains_any(normalized_assistant, _VALIDATION_SUCCESS_MARKERS):
                return "done"
            if _contains_any(normalized_assistant, _VALIDATION_FAILURE_MARKERS):
                return "execution"
            if proposed_stage == "execution":
                return "execution"
            if proposed_stage == "done":
                return "done"
            return "validation"

        return "done"

    def _is_new_task(self, proposed: "TaskState", user_text: str) -> bool:
        if _contains_any(user_text.lower(), _NEW_TASK_MARKERS):
            return True
        if self.stage != "done":
            return False
        if not proposed.task:
            return False
        return _has_task_changed(self.task, proposed.task)

    def _has_plan(self) -> bool:
        return bool(self.plan) and self.plan_total > 0

    def _normalize(self) -> "TaskState":
        plan = tuple(_sanitize_item(item) for item in self.plan if _sanitize_item(item))
        done = tuple(_sanitize_item(item) for item in self.done if _sanitize_item(item))
        plan = tuple(dict.fromkeys(plan))[:12]
        done = tuple(dict.fromkeys(done))[:12]
        stage = self.stage if self.stage in TASK_STATE_STAGES else "planning"
        total = TASK_STATE_TOTAL_STEPS
        step = TASK_STATE_STAGE_STEPS[stage]
        plan_total = len(plan)
        if plan_total == 0:
            plan_step = 0
        elif stage == "done":
            plan_step = plan_total
        else:
            plan_step = min(max(1, len(done) + 1), plan_total)

        current = _sanitize_item(self.current)
        if not current:
            current = _default_current(stage, plan, plan_step)

        return self._copy(
            task=_sanitize_task(self.task),
            stage=stage,
            step=step,
            total=total,
            plan_step=plan_step,
            plan_total=plan_total,
            plan=plan,
            done=done,
            current=current,
        )

    def _copy(self, **changes: object) -> "TaskState":
        data = self.to_dict()
        data.update(changes)
        return TaskState(
            task=data["task"] if isinstance(data["task"], str) else "",
            stage=data["stage"] if isinstance(data["stage"], str) else "planning",
            step=data["step"] if isinstance(data["step"], int) else 0,
            total=data["total"] if isinstance(data["total"], int) else 0,
            plan_step=data["plan_step"] if isinstance(data.get("plan_step"), int) else 0,
            plan_total=data["plan_total"] if isinstance(data.get("plan_total"), int) else 0,
            plan=tuple(data["plan"]) if isinstance(data["plan"], (list, tuple)) else (),
            done=tuple(data["done"]) if isinstance(data["done"], (list, tuple)) else (),
            current=data["current"] if isinstance(data["current"], str) else "",
            paused=data["paused"] if isinstance(data["paused"], bool) else False,
        )


def _read_optional_string(value: object) -> str:
    if value is None or not isinstance(value, str):
        return ""
    return value.strip()


def _read_int(value: object) -> int:
    if isinstance(value, int):
        return max(0, value)
    return 0


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_sanitize_item(item) for item in value if isinstance(item, str) and _sanitize_item(item)]


def _sanitize_task(value: str) -> str:
    return _sanitize_words(value, 18)


def _sanitize_item(value: str) -> str:
    return _sanitize_words(value, 18)


def _sanitize_words(value: str, limit: int) -> str:
    compact = " ".join(value.replace("\n", " ").split()).strip().rstrip(".;: ")
    if not compact:
        return ""
    return " ".join(compact.split(" ")[:limit])


def _default_current(stage: str, plan: tuple[str, ...], step: int) -> str:
    current_plan_step = plan[step - 1] if step > 0 and step <= len(plan) else ""
    defaults = {
        "planning": current_plan_step or "Собрать требования и подготовить план",
        "execution": current_plan_step or "Выполнить текущий шаг плана",
        "validation": "Проверить результат по плану",
        "done": "Зафиксировать итоговый результат",
    }
    return defaults[stage]


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _contains_implementation_artifact(text: str) -> bool:
    normalized = text.lower()
    return (
        "```" in text
        or "diff --git" in normalized
        or "def " in normalized
        or "class " in normalized
        or "import " in normalized
        or "from " in normalized
        or "fun " in normalized
        or "val " in normalized
    )


def _has_task_changed(current_task: str, proposed_task: str) -> bool:
    current = _normalize_text(current_task)
    proposed = _normalize_text(proposed_task)
    if not proposed:
        return False
    if not current:
        return True
    if current == proposed or current in proposed or proposed in current:
        return False

    current_tokens = _tokenize(current)
    proposed_tokens = _tokenize(proposed)
    if not current_tokens or not proposed_tokens:
        return True

    overlap = len(current_tokens.intersection(proposed_tokens))
    similarity = overlap / max(len(current_tokens), len(proposed_tokens))
    return similarity < 0.55


def _is_standalone_request(text: str) -> bool:
    normalized = text.strip().lower()
    if len(normalized) < 12:
        return False

    continuation_markers = (
        "продолж",
        "дальше",
        "покажи",
        "объясни",
        "исправь",
        "добавь",
        "еще",
        "ещё",
        "давай",
        "ок",
        "хорошо",
        "да",
        "нет",
    )
    return not any(normalized.startswith(marker) for marker in continuation_markers)


def _normalize_text(value: str) -> str:
    return value.strip().rstrip(". ").lower()


def _tokenize(value: str) -> set[str]:
    return {token for token in value.replace("_", " ").split() if len(token) >= 3}
