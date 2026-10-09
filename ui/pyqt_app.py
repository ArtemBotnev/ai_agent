import html
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from application.chat.agent_error import AgentError
from application.chat.chat_service import ChatResponse
from application.chat.context_strategy import ContextStrategy
from domain.conversation_branch import ConversationBranch, ConversationBranches
from domain.conversation_summary import ConversationSummary
from domain.long_term_memory import LongTermMemory
from domain.message import Message
from domain.sticky_facts import StickyFacts
from domain.task_state import TASK_STATE_MARKERS
from domain.working_memory import WorkingMemory
from main import build_chat_service, build_history_repository, format_agent_error, get_context_strategy
from main import (
    AGENT_CONTEXT_STRATEGY_ENV,
    build_branch_repository,
    build_facts_repository,
    get_cloud_base_url,
    get_ollama_base_url,
    get_llm_provider,
    get_available_model_names,
    get_available_user_ids,
    get_model_name,
    get_user_id,
    LLM_PROVIDER_OLLAMA,
    LLM_PROVIDER_CLOUD,
    LLM_PROVIDERS,
    build_long_term_memory_repository,
    build_summary_repository,
    build_working_memory_repository,
)
from ui.message_html import AGENT_AUTHOR, ERROR_AUTHOR, USER_AUTHOR, render_message_html
from ui import colors
from ui.pyqt_theme import COMPOSER_HEIGHT, WINDOW_STYLESHEET


TASK_STAGE_COLORS = {
    "planning": colors.TASK_STAGE_PLANNING,
    "execution": colors.TASK_STAGE_EXECUTION,
    "validation": colors.TASK_STAGE_VALIDATION,
    "done": colors.TASK_STAGE_DONE,
}


def main() -> None:
    try:
        from PyQt6.QtCore import Qt, QThread, pyqtSignal
        from PyQt6.QtWidgets import (
            QApplication,
            QComboBox,
            QHBoxLayout,
            QInputDialog,
            QLabel,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QTextBrowser,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print("PyQt UI requires PyQt6. Install it with: python3 -m pip install PyQt6", file=sys.stderr)
        sys.exit(1)

    class MessageInput(QTextEdit):
        submit_requested = pyqtSignal()

        def keyPressEvent(self, event: Any) -> None:
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    super().keyPressEvent(event)
                    return

                self.submit_requested.emit()
                return

            super().keyPressEvent(event)

    class ChatWorker(QThread):
        answered = pyqtSignal(object)
        failed = pyqtSignal(str)
        task_stage_changed = pyqtSignal(object)

        def __init__(
            self,
            message: str,
            context_strategy: ContextStrategy,
            model_name: str,
            user_id: str,
            provider: str,
        ) -> None:
            super().__init__()
            self._message = message
            self._context_strategy = context_strategy
            self._model_name = model_name
            self._user_id = user_id
            self._provider = provider

        def run(self) -> None:
            try:
                response = build_chat_service(
                    self._context_strategy,
                    self._model_name,
                    self._user_id,
                    self.task_stage_changed.emit,
                    self._provider,
                ).answer(self._message)
            except RuntimeError as error:
                self.failed.emit(str(error))
            except AgentError as error:
                self.failed.emit(format_agent_error(error))
            else:
                self.answered.emit(response)

    class OllamaWorker(QThread):
        progress = pyqtSignal(str)
        completed = pyqtSignal(str, object)
        failed = pyqtSignal(str)

        def __init__(self, base_url: str, model_name: str) -> None:
            super().__init__()
            self._base_url = base_url.rstrip("/")
            self._model_name = model_name

        def run(self) -> None:
            if shutil.which("ollama") is None:
                self.failed.emit("Команда ollama не найдена в PATH.")
                return

            ollama_process = None
            if self._is_ready():
                self.progress.emit(f"Ollama уже запущен: {self._base_url}")
            else:
                self.progress.emit(f"Запуск Ollama: {self._base_url}")
                try:
                    ollama_process = self._start_server()
                    self._wait_until_ready()
                except (OSError, TimeoutError) as error:
                    if ollama_process is not None:
                        ollama_process.terminate()
                    self.failed.emit(f"Не удалось запустить Ollama: {error}")
                    return

            try:
                if self._has_model():
                    self.completed.emit(f"Модель уже доступна: {self._model_name}", ollama_process)
                    return

                self.progress.emit(f"Загрузка модели: {self._model_name}")
                self._pull_model()
            except RuntimeError as error:
                if ollama_process is not None:
                    ollama_process.terminate()
                self.failed.emit(str(error))
                return

            self.completed.emit(f"Ollama готов. Модель: {self._model_name}", ollama_process)

        def _start_server(self) -> subprocess.Popen[Any]:
            env = os.environ.copy()
            env["OLLAMA_HOST"] = self._host_for_env()
            return subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )

        def _host_for_env(self) -> str:
            host = self._base_url.removeprefix("http://").removeprefix("https://")
            return host.rstrip("/")

        def _wait_until_ready(self) -> None:
            for _ in range(30):
                if self._is_ready():
                    return
                time.sleep(1)

            raise TimeoutError("сервер не ответил за 30 секунд")

        def _is_ready(self) -> bool:
            try:
                with urlopen(f"{self._base_url}/api/tags", timeout=2) as response:
                    return 200 <= response.status < 300
            except (OSError, URLError, TimeoutError):
                return False

        def _has_model(self) -> bool:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"Не удалось получить список моделей Ollama. {details}".strip())

            for line in result.stdout.splitlines()[1:]:
                columns = line.split()
                if columns and columns[0] == self._model_name:
                    return True

            return False

        def _pull_model(self) -> None:
            result = subprocess.run(
                ["ollama", "pull", self._model_name],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"Не удалось загрузить модель {self._model_name}. {details}".strip())

    class CloudCheckWorker(QThread):
        completed = pyqtSignal(str)
        failed = pyqtSignal(str)

        def __init__(self, base_url: str, model_name: str) -> None:
            super().__init__()
            self._base_url = base_url.rstrip("/")
            self._model_name = model_name

        def run(self) -> None:
            payload = {
                "model": self._model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with OK.",
                    }
                ],
                "stream": False,
                "options": {
                    "num_predict": 8,
                },
            }
            request = Request(
                f"{self._base_url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urlopen(request, timeout=30) as response:
                    raw_body = response.read().decode("utf-8")
            except HTTPError as error:
                details = error.read().decode("utf-8", errors="replace").strip()
                self.failed.emit(f"Облачная LLM вернула HTTP {error.code}. {details}".strip())
                return
            except (OSError, URLError, TimeoutError) as error:
                self.failed.emit(f"Не удалось подключиться к облачной LLM: {error}")
                return

            try:
                response_data = json.loads(raw_body)
            except json.JSONDecodeError:
                self.failed.emit("Облачная LLM вернула некорректный JSON.")
                return

            if self._has_text_response(response_data):
                self.completed.emit(f"Облако доступно. Модель: {self._model_name}")
                return

            self.failed.emit("Облачная LLM ответила, но текст ответа не найден.")

        def _has_text_response(self, response_data: object) -> bool:
            if not isinstance(response_data, dict):
                return False

            message = response_data.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return True

            response = response_data.get("response")
            return isinstance(response, str) and bool(response.strip())

    class ChatWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self._worker: ChatWorker | None = None
            self._ollama_worker: OllamaWorker | None = None
            self._cloud_worker: CloudCheckWorker | None = None
            self._ollama_process: subprocess.Popen[Any] | None = None
            self._is_loading_branches = False

            self.setWindowTitle("LLM Агент")
            self.resize(920, 720)

            self._user_label = QLabel("Пользователь:")
            self._user_combo = QComboBox()
            self._provider_combo = QComboBox()
            self._model_combo = QComboBox()
            self._status_label = QLabel("Готов")
            self._task_state_label = QLabel()
            self._strategy_combo = QComboBox()
            self._branch_combo = QComboBox()
            self._ollama_button = QPushButton("Запустить Ollama")
            self._cloud_button = QPushButton("Проверить облако")
            self._checkpoint_button = QPushButton("Checkpoint")
            self._new_branch_button = QPushButton("Новая ветка")
            self._clear_button = QPushButton("Очистить")
            self._messages = QTextBrowser()
            self._input = MessageInput()
            self._send_button = QPushButton("Отправить")

            self._setup_ui()
            self._load_history()

        def _setup_ui(self) -> None:
            self._messages.setOpenExternalLinks(False)
            self._input.setPlaceholderText("Введите сообщение")
            self._input.setFixedHeight(COMPOSER_HEIGHT)
            self._task_state_label.setObjectName("TaskStateLabel")
            self._task_state_label.setWordWrap(True)
            self._send_button.setFixedHeight(COMPOSER_HEIGHT)
            self._send_button.setFixedWidth(140)
            self._clear_button.setFixedHeight(36)
            self._ollama_button.setFixedHeight(36)
            self._cloud_button.setFixedHeight(36)
            self._checkpoint_button.setFixedHeight(36)
            self._new_branch_button.setFixedHeight(36)

            user_ids = get_available_user_ids()
            for user_id in user_ids:
                self._user_combo.addItem(user_id, user_id)
            user_index = self._user_combo.findData(get_user_id())
            if user_index >= 0:
                self._user_combo.setCurrentIndex(user_index)
            show_user_selector = len(user_ids) > 1
            self._user_label.setVisible(show_user_selector)
            self._user_combo.setVisible(show_user_selector)

            for provider in LLM_PROVIDERS:
                self._provider_combo.addItem(provider, provider)
            provider_index = self._provider_combo.findData(get_llm_provider())
            if provider_index >= 0:
                self._provider_combo.setCurrentIndex(provider_index)

            for strategy in ContextStrategy:
                self._strategy_combo.addItem(strategy.display_name, strategy.value)
            strategy_index = self._strategy_combo.findData(get_context_strategy(self._selected_provider()).value)
            if strategy_index >= 0:
                self._strategy_combo.setCurrentIndex(strategy_index)

            self._refresh_model_combo()

            self._input.submit_requested.connect(self._send_message)
            self._send_button.clicked.connect(self._send_message)
            self._clear_button.clicked.connect(self._clear_context)
            self._user_combo.currentIndexChanged.connect(self._handle_user_changed)
            self._provider_combo.currentIndexChanged.connect(self._handle_provider_changed)
            self._strategy_combo.currentIndexChanged.connect(self._handle_strategy_changed)
            self._branch_combo.currentIndexChanged.connect(self._handle_branch_changed)
            self._ollama_button.clicked.connect(self._start_ollama)
            self._cloud_button.clicked.connect(self._check_cloud)
            self._checkpoint_button.clicked.connect(self._save_checkpoint)
            self._new_branch_button.clicked.connect(self._create_branch)

            header_layout = QHBoxLayout()
            if show_user_selector:
                header_layout.addWidget(self._user_label)
                header_layout.addWidget(self._user_combo)
                header_layout.addSpacing(16)
            header_layout.addWidget(QLabel("Provider:"))
            header_layout.addWidget(self._provider_combo)
            header_layout.addSpacing(16)
            header_layout.addWidget(QLabel("Модель:"))
            header_layout.addWidget(self._model_combo)
            header_layout.addWidget(self._ollama_button)
            header_layout.addWidget(self._cloud_button)
            header_layout.addSpacing(16)
            header_layout.addWidget(QLabel("Стратегия:"))
            header_layout.addWidget(self._strategy_combo)
            header_layout.addWidget(self._branch_combo)
            header_layout.addWidget(self._checkpoint_button)
            header_layout.addWidget(self._new_branch_button)
            header_layout.addStretch()
            header_layout.addWidget(self._status_label)
            header_layout.addWidget(self._clear_button)

            composer_layout = QHBoxLayout()
            composer_layout.addWidget(self._input)
            composer_layout.addWidget(self._send_button, alignment=Qt.AlignmentFlag.AlignBottom)

            root_layout = QVBoxLayout()
            root_layout.addLayout(header_layout)
            root_layout.addWidget(self._task_state_label)
            root_layout.addWidget(self._messages, stretch=1)
            root_layout.addLayout(composer_layout)

            root = QWidget()
            root.setLayout(root_layout)
            self.setCentralWidget(root)
            self.setStyleSheet(WINDOW_STYLESHEET)
            self._update_ollama_controls()
            self._update_cloud_controls()
            self._update_branch_controls()
            self._update_task_state()

        def _load_history(self) -> None:
            try:
                messages = self._load_messages_for_current_strategy()
            except OSError as error:
                QMessageBox.warning(self, "История", f"Не удалось загрузить историю: {error}")
                return

            self._messages.clear()
            self._update_task_state()
            if not messages:
                self._append_message(AGENT_AUTHOR, "Здравствуйте. Напишите запрос, и я отправлю его в LLM через агента.")
                return

            for message in messages:
                self._append_message(self._message_author(message), message.content)

        def _send_message(self) -> None:
            text = self._input.toPlainText().strip()
            if not text:
                self._append_message(ERROR_AUTHOR, "Введите непустое сообщение.")
                return

            self._send_text(text)
            self._input.clear()

        def _send_text(self, text: str) -> None:
            self._append_message(USER_AUTHOR, text)
            self._set_loading(True)

            self._worker = ChatWorker(
                text,
                self._selected_strategy(),
                self._selected_model_name(),
                self._selected_user_id(),
                self._selected_provider(),
            )
            self._worker.answered.connect(self._handle_answer)
            self._worker.failed.connect(self._handle_error)
            self._worker.task_stage_changed.connect(self._handle_task_stage_changed)
            self._worker.finished.connect(lambda: self._set_loading(False))
            self._worker.start()

        def _handle_answer(self, response: Any) -> None:
            chat_response = response
            if not isinstance(chat_response, ChatResponse):
                self._append_message(ERROR_AUTHOR, "Агент вернул некорректный ответ.")
                return

            tokens = chat_response.tokens
            meta = (
                f"Токены: запрос {tokens.current_request}, "
                f"история {tokens.history}, ответ {tokens.response}; "
                f"время {chat_response.duration_seconds:.2f} с"
            )
            self._append_message(AGENT_AUTHOR, chat_response.text, meta)
            self._update_task_state()

        def _handle_error(self, error: str) -> None:
            self._append_message(ERROR_AUTHOR, error)

        def _handle_task_stage_changed(self, memory: Any) -> None:
            if not isinstance(memory, WorkingMemory):
                return

            self._set_task_state_text(memory)

        def _set_loading(self, is_loading: bool) -> None:
            self._send_button.setDisabled(is_loading)
            self._input.setDisabled(is_loading)
            self._user_combo.setDisabled(is_loading)
            self._provider_combo.setDisabled(is_loading)
            self._model_combo.setDisabled(is_loading)
            self._ollama_button.setDisabled(is_loading or self._selected_provider() != LLM_PROVIDER_OLLAMA)
            self._cloud_button.setDisabled(is_loading or self._selected_provider() != LLM_PROVIDER_CLOUD)
            self._strategy_combo.setDisabled(is_loading)
            self._branch_combo.setDisabled(is_loading)
            self._checkpoint_button.setDisabled(is_loading)
            self._new_branch_button.setDisabled(is_loading)
            self._clear_button.setDisabled(is_loading)
            self._status_label.setText("Запрос..." if is_loading else "Готов")
            if not is_loading:
                self._update_ollama_controls()
                self._update_cloud_controls()
                self._update_branch_controls()
                self._update_task_state()

        def _append_message(self, author: str, text: str, meta: str = "") -> None:
            self._messages.append(render_message_html(author, text, meta))
            scrollbar = self._messages.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        def _message_author(self, message: Message) -> str:
            if message.role == "user":
                return USER_AUTHOR

            return AGENT_AUTHOR

        def _selected_strategy(self) -> ContextStrategy:
            strategy_value = self._strategy_combo.currentData()
            if not isinstance(strategy_value, str):
                return ContextStrategy.MEMORY

            try:
                return ContextStrategy.from_value(strategy_value)
            except ValueError:
                return ContextStrategy.MEMORY

        def _selected_model_name(self) -> str:
            model_name = self._model_combo.currentData()
            if isinstance(model_name, str):
                return model_name

            return get_model_name(provider=self._selected_provider())

        def _selected_provider(self) -> str:
            provider = self._provider_combo.currentData()
            if isinstance(provider, str):
                return provider

            return get_llm_provider()

        def _selected_user_id(self) -> str:
            user_id = self._user_combo.currentData()
            if isinstance(user_id, str):
                return user_id

            return get_user_id()

        def _load_messages_for_current_strategy(self) -> list[Message]:
            if self._selected_strategy() == ContextStrategy.BRANCHING:
                return build_branch_repository().load().active_branch.messages

            return build_history_repository(self._selected_user_id()).load()

        def _handle_strategy_changed(self, *_args: Any) -> None:
            self._update_branch_controls()
            self._update_task_state()
            self._load_history()

        def _handle_user_changed(self, *_args: Any) -> None:
            self._update_branch_controls()
            self._update_task_state()
            self._load_history()

        def _handle_provider_changed(self, *_args: Any) -> None:
            self._refresh_model_combo()
            if (
                self._selected_provider() in {LLM_PROVIDER_OLLAMA, LLM_PROVIDER_CLOUD}
                and AGENT_CONTEXT_STRATEGY_ENV not in os.environ
            ):
                strategy_index = self._strategy_combo.findData(ContextStrategy.SUMMARY.value)
                if strategy_index >= 0:
                    self._strategy_combo.setCurrentIndex(strategy_index)
            self._update_ollama_controls()
            self._update_cloud_controls()
            self._update_branch_controls()
            self._update_task_state()

        def _refresh_model_combo(self) -> None:
            provider = self._selected_provider()
            self._model_combo.clear()
            for model_name in get_available_model_names(provider):
                self._model_combo.addItem(model_name, model_name)
            model_index = self._model_combo.findData(get_model_name(provider=provider))
            if model_index >= 0:
                self._model_combo.setCurrentIndex(model_index)

        def _update_ollama_controls(self) -> None:
            is_ollama = self._selected_provider() == LLM_PROVIDER_OLLAMA
            self._ollama_button.setVisible(is_ollama)
            self._ollama_button.setDisabled(not is_ollama or self._ollama_worker is not None)

        def _update_cloud_controls(self) -> None:
            is_cloud = self._selected_provider() == LLM_PROVIDER_CLOUD
            self._cloud_button.setVisible(is_cloud)
            self._cloud_button.setDisabled(not is_cloud or self._cloud_worker is not None)

        def _start_ollama(self) -> None:
            if self._selected_provider() != LLM_PROVIDER_OLLAMA:
                return

            try:
                base_url = get_ollama_base_url()
            except RuntimeError as error:
                self._append_message(ERROR_AUTHOR, str(error))
                return

            self._ollama_button.setDisabled(True)
            self._status_label.setText("Ollama...")
            self._ollama_worker = OllamaWorker(base_url, self._selected_model_name())
            self._ollama_worker.progress.connect(self._handle_ollama_progress)
            self._ollama_worker.completed.connect(self._handle_ollama_ready)
            self._ollama_worker.failed.connect(self._handle_ollama_error)
            self._ollama_worker.finished.connect(self._handle_ollama_finished)
            self._ollama_worker.start()

        def _check_cloud(self) -> None:
            if self._selected_provider() != LLM_PROVIDER_CLOUD:
                return

            try:
                base_url = get_cloud_base_url()
            except RuntimeError as error:
                self._append_message(ERROR_AUTHOR, str(error))
                return

            self._cloud_button.setDisabled(True)
            self._status_label.setText("Проверка облака...")
            self._cloud_worker = CloudCheckWorker(base_url, self._selected_model_name())
            self._cloud_worker.completed.connect(self._handle_cloud_ready)
            self._cloud_worker.failed.connect(self._handle_cloud_error)
            self._cloud_worker.finished.connect(self._handle_cloud_finished)
            self._cloud_worker.start()

        def _handle_ollama_progress(self, message: str) -> None:
            self._status_label.setText(message)

        def _handle_ollama_ready(self, message: str, process: object) -> None:
            if isinstance(process, subprocess.Popen):
                self._ollama_process = process
            self._status_label.setText("Готов")
            self._append_message(AGENT_AUTHOR, message)

        def _handle_ollama_error(self, error: str) -> None:
            self._status_label.setText("Готов")
            self._append_message(ERROR_AUTHOR, error)

        def _handle_ollama_finished(self) -> None:
            self._ollama_worker = None
            self._update_ollama_controls()

        def _handle_cloud_ready(self, message: str) -> None:
            self._status_label.setText("Готов")
            self._append_message(AGENT_AUTHOR, message)

        def _handle_cloud_error(self, error: str) -> None:
            self._status_label.setText("Готов")
            self._append_message(ERROR_AUTHOR, error)

        def _handle_cloud_finished(self) -> None:
            self._cloud_worker = None
            self._update_cloud_controls()

        def _update_branch_controls(self) -> None:
            is_branching = self._selected_strategy() == ContextStrategy.BRANCHING
            self._branch_combo.setVisible(is_branching)
            self._checkpoint_button.setVisible(is_branching)
            self._new_branch_button.setVisible(is_branching)
            if is_branching:
                self._refresh_branch_combo()

        def _update_task_state(self) -> None:
            if self._selected_strategy() != ContextStrategy.MEMORY:
                self._task_state_label.setVisible(False)
                return

            self._set_task_state_text(build_working_memory_repository(self._selected_user_id()).load())

        def _set_task_state_text(self, memory: WorkingMemory) -> None:
            task_state = memory.task_state
            paused_text = "да" if task_state.paused else "нет"
            task = task_state.task or "не задана"
            stage_marker = TASK_STATE_MARKERS[task_state.stage]
            stage_color = TASK_STAGE_COLORS[task_state.stage]
            self._task_state_label.setText(
                '<div style="font-size:16px;font-weight:700;margin-bottom:4px;">Состояние задачи</div>'
                f"<div>Задача: {html.escape(task)}</div>"
                f'<div>Этап: <span style="color:{stage_color};font-weight:700;">'
                f"{html.escape(stage_marker)}</span> ({html.escape(task_state.stage)})</div>"
                f"<div>Пауза: {html.escape(paused_text)}</div>"
            )
            self._task_state_label.setVisible(True)

        def _refresh_branch_combo(self) -> None:
            branches = build_branch_repository().load()
            self._is_loading_branches = True
            self._branch_combo.clear()
            for branch_id, branch in branches.branches.items():
                self._branch_combo.addItem(branch.name, branch_id)

            active_index = self._branch_combo.findData(branches.active_branch_id)
            if active_index >= 0:
                self._branch_combo.setCurrentIndex(active_index)
            self._is_loading_branches = False

        def _handle_branch_changed(self, *_args: Any) -> None:
            if self._is_loading_branches:
                return

            branch_id = self._branch_combo.currentData()
            if not isinstance(branch_id, str):
                return

            branches = build_branch_repository().load()
            if branch_id not in branches.branches:
                return

            updated_branches = ConversationBranches(
                active_branch_id=branch_id,
                checkpoint_messages=branches.checkpoint_messages,
                branches=branches.branches,
            )
            build_branch_repository().save(updated_branches)
            self._load_history()

        def _save_checkpoint(self) -> None:
            branches = build_branch_repository().load()
            updated_branches = ConversationBranches(
                active_branch_id=branches.active_branch_id,
                checkpoint_messages=list(branches.active_branch.messages),
                branches=branches.branches,
            )
            build_branch_repository().save(updated_branches)
            self._status_label.setText(f"Checkpoint: {len(updated_branches.checkpoint_messages)} сообщений")

        def _create_branch(self) -> None:
            branch_id, accepted = QInputDialog.getText(self, "Новая ветка", "Имя ветки:")
            if not accepted:
                return

            clean_branch_id = branch_id.strip()
            if not clean_branch_id:
                QMessageBox.warning(self, "Ветка", "Введите непустое имя ветки.")
                return

            branches = build_branch_repository().load()
            if clean_branch_id in branches.branches:
                QMessageBox.warning(self, "Ветка", "Такая ветка уже существует.")
                return

            updated_branches = ConversationBranches(
                active_branch_id=clean_branch_id,
                checkpoint_messages=branches.checkpoint_messages,
                branches={
                    **branches.branches,
                    clean_branch_id: ConversationBranch(
                        name=clean_branch_id,
                        messages=list(branches.checkpoint_messages),
                    ),
                },
            )
            build_branch_repository().save(updated_branches)
            self._refresh_branch_combo()
            self._load_history()

        def _clear_context(self) -> None:
            strategy = self._selected_strategy()
            if strategy == ContextStrategy.SUMMARY:
                build_history_repository(self._selected_user_id()).save([])
                build_summary_repository().save(ConversationSummary())
            elif strategy == ContextStrategy.STICKY_FACTS:
                build_history_repository(self._selected_user_id()).save([])
                build_facts_repository().save(StickyFacts())
            elif strategy == ContextStrategy.BRANCHING:
                build_branch_repository().save(ConversationBranches.empty())
                self._refresh_branch_combo()
            elif strategy == ContextStrategy.MEMORY:
                build_history_repository(self._selected_user_id()).save([])
                build_working_memory_repository(self._selected_user_id()).save(WorkingMemory())
                build_long_term_memory_repository(self._selected_user_id()).save(LongTermMemory())
            else:
                build_history_repository(self._selected_user_id()).save([])

            self._load_history()
            self._update_task_state()

        def closeEvent(self, event: Any) -> None:
            if self._ollama_process is not None and self._ollama_process.poll() is None:
                self._ollama_process.terminate()
            super().closeEvent(event)

    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
