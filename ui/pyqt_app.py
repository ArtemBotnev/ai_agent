import os
import sys
from typing import Any

from agent import DEFAULT_OPENAI_MODEL, OPENAI_MODEL_ENV
from application.agent_error import AgentError
from application.chat_service import ChatResponse
from domain.message import Message
from main import build_chat_service, build_history_repository, format_agent_error
from ui.message_html import AGENT_AUTHOR, ERROR_AUTHOR, USER_AUTHOR, render_message_html
from ui.pyqt_theme import COMPOSER_HEIGHT, WINDOW_STYLESHEET


def main() -> None:
    try:
        from PyQt6.QtCore import Qt, QThread, pyqtSignal
        from PyQt6.QtWidgets import (
            QApplication,
            QHBoxLayout,
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

        def __init__(self, message: str) -> None:
            super().__init__()
            self._message = message

        def run(self) -> None:
            try:
                response = build_chat_service().answer(self._message)
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

            self.setWindowTitle("LLM Агент")
            self.resize(920, 720)

            self._model_label = QLabel(f"Модель: {os.getenv(OPENAI_MODEL_ENV, DEFAULT_OPENAI_MODEL)}")
            self._status_label = QLabel("Готов")
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
            self._input.submit_requested.connect(self._send_message)
            self._send_button.clicked.connect(self._send_message)

            header_layout = QHBoxLayout()
            header_layout.addWidget(self._model_label)
            header_layout.addStretch()
            header_layout.addWidget(self._status_label)

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

        def _load_history(self) -> None:
            try:
                messages = build_history_repository().load()
            except OSError as error:
                QMessageBox.warning(self, "История", f"Не удалось загрузить историю: {error}")
                return

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

            self._worker = ChatWorker(text)
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
            self._status_label.setText("Запрос..." if is_loading else "Готов")

        def _append_message(self, author: str, text: str, meta: str = "") -> None:
            self._messages.append(render_message_html(author, text, meta))
            scrollbar = self._messages.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        def _message_author(self, message: Message) -> str:
            if message.role == "user":
                return USER_AUTHOR

            return AGENT_AUTHOR

    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
