import os
import sys
from typing import Any

from agent import DEFAULT_OPENAI_MODEL, OPENAI_MODEL_ENV
from application.agent_error import AgentError
from application.chat_service import ChatResponse
from application.context_strategy import ContextStrategy
from domain.conversation_branch import ConversationBranch, ConversationBranches
from domain.conversation_summary import ConversationSummary
from domain.message import Message
from domain.sticky_facts import StickyFacts
from main import build_chat_service, build_history_repository, format_agent_error, get_context_strategy
from main import build_branch_repository, build_facts_repository, build_summary_repository
from ui.message_html import AGENT_AUTHOR, ERROR_AUTHOR, USER_AUTHOR, render_message_html
from ui.pyqt_theme import COMPOSER_HEIGHT, WINDOW_STYLESHEET


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

        def __init__(self, message: str, context_strategy: ContextStrategy) -> None:
            super().__init__()
            self._message = message
            self._context_strategy = context_strategy

        def run(self) -> None:
            try:
                response = build_chat_service(self._context_strategy).answer(self._message)
            except RuntimeError as error:
                self.failed.emit(str(error))
            except AgentError as error:
                self.failed.emit(format_agent_error(error))
            else:
                self.answered.emit(response)

    class ChatWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self._worker: ChatWorker | None = None
            self._is_loading_branches = False

            self.setWindowTitle("LLM Агент")
            self.resize(920, 720)

            self._model_label = QLabel(f"Модель: {os.getenv(OPENAI_MODEL_ENV, DEFAULT_OPENAI_MODEL)}")
            self._status_label = QLabel("Готов")
            self._strategy_combo = QComboBox()
            self._branch_combo = QComboBox()
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
            self._send_button.setFixedHeight(COMPOSER_HEIGHT)
            self._send_button.setFixedWidth(140)
            self._clear_button.setFixedHeight(36)
            self._checkpoint_button.setFixedHeight(36)
            self._new_branch_button.setFixedHeight(36)

            for strategy in ContextStrategy:
                self._strategy_combo.addItem(strategy.display_name, strategy.value)
            strategy_index = self._strategy_combo.findData(get_context_strategy().value)
            if strategy_index >= 0:
                self._strategy_combo.setCurrentIndex(strategy_index)

            self._input.submit_requested.connect(self._send_message)
            self._send_button.clicked.connect(self._send_message)
            self._clear_button.clicked.connect(self._clear_context)
            self._strategy_combo.currentIndexChanged.connect(self._handle_strategy_changed)
            self._branch_combo.currentIndexChanged.connect(self._handle_branch_changed)
            self._checkpoint_button.clicked.connect(self._save_checkpoint)
            self._new_branch_button.clicked.connect(self._create_branch)

            header_layout = QHBoxLayout()
            header_layout.addWidget(self._model_label)
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
            root_layout.addWidget(self._messages, stretch=1)
            root_layout.addLayout(composer_layout)

            root = QWidget()
            root.setLayout(root_layout)
            self.setCentralWidget(root)
            self.setStyleSheet(WINDOW_STYLESHEET)
            self._update_branch_controls()

        def _load_history(self) -> None:
            try:
                messages = self._load_messages_for_current_strategy()
            except OSError as error:
                QMessageBox.warning(self, "История", f"Не удалось загрузить историю: {error}")
                return

            self._messages.clear()
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

            self._append_message(USER_AUTHOR, text)
            self._input.clear()
            self._set_loading(True)

            self._worker = ChatWorker(text, self._selected_strategy())
            self._worker.answered.connect(self._handle_answer)
            self._worker.failed.connect(self._handle_error)
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
                f"история {tokens.history}, ответ {tokens.response}"
            )
            self._append_message(AGENT_AUTHOR, chat_response.text, meta)

        def _handle_error(self, error: str) -> None:
            self._append_message(ERROR_AUTHOR, error)

        def _set_loading(self, is_loading: bool) -> None:
            self._send_button.setDisabled(is_loading)
            self._input.setDisabled(is_loading)
            self._strategy_combo.setDisabled(is_loading)
            self._branch_combo.setDisabled(is_loading)
            self._checkpoint_button.setDisabled(is_loading)
            self._new_branch_button.setDisabled(is_loading)
            self._clear_button.setDisabled(is_loading)
            self._status_label.setText("Запрос..." if is_loading else "Готов")
            if not is_loading:
                self._update_branch_controls()

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
                return ContextStrategy.SUMMARY

            try:
                return ContextStrategy.from_value(strategy_value)
            except ValueError:
                return ContextStrategy.SUMMARY

        def _load_messages_for_current_strategy(self) -> list[Message]:
            if self._selected_strategy() == ContextStrategy.BRANCHING:
                return build_branch_repository().load().active_branch.messages

            return build_history_repository().load()

        def _handle_strategy_changed(self, *_args: Any) -> None:
            self._update_branch_controls()
            self._load_history()

        def _update_branch_controls(self) -> None:
            is_branching = self._selected_strategy() == ContextStrategy.BRANCHING
            self._branch_combo.setVisible(is_branching)
            self._checkpoint_button.setVisible(is_branching)
            self._new_branch_button.setVisible(is_branching)
            if is_branching:
                self._refresh_branch_combo()

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
                build_history_repository().save([])
                build_summary_repository().save(ConversationSummary())
            elif strategy == ContextStrategy.STICKY_FACTS:
                build_history_repository().save([])
                build_facts_repository().save(StickyFacts())
            elif strategy == ContextStrategy.BRANCHING:
                build_branch_repository().save(ConversationBranches.empty())
                self._refresh_branch_combo()
            else:
                build_history_repository().save([])

            self._load_history()

    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
