import html
import os
import sys
from typing import Any

from agent import DEFAULT_OPENAI_MODEL, OPENAI_MODEL_ENV
from application.agent_error import AgentError
from application.chat_service import ChatResponse
from domain.message import Message
from main import build_chat_service, build_history_repository, format_agent_error


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
            self._input = QTextEdit()
            self._send_button = QPushButton("Отправить")

            self._setup_ui()
            self._load_history()

        def _setup_ui(self) -> None:
            self._messages.setOpenExternalLinks(False)
            self._input.setPlaceholderText("Введите сообщение")
            self._input.setFixedHeight(96)
            self._send_button.setFixedWidth(140)
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
            self.setStyleSheet(
                """
                QMainWindow {
                    background: #111827;
                }
                QLabel {
                    color: #d1d5db;
                    font-size: 14px;
                }
                QTextBrowser,
                QTextEdit {
                    border: 1px solid #374151;
                    border-radius: 8px;
                    background: #0f172a;
                    color: #f9fafb;
                    font-size: 15px;
                    padding: 10px;
                    selection-background-color: #2563eb;
                    selection-color: #ffffff;
                }
                QPushButton {
                    min-height: 42px;
                    border: 0;
                    border-radius: 8px;
                    background: #2563eb;
                    color: #ffffff;
                    font-weight: 700;
                    padding: 0 16px;
                }
                QPushButton:hover {
                    background: #1d4ed8;
                }
                QPushButton:disabled {
                    background: #4b5563;
                    color: #cbd5e1;
                }
                QScrollBar:vertical {
                    width: 12px;
                    background: #111827;
                    margin: 4px 2px 4px 2px;
                }
                QScrollBar::handle:vertical {
                    min-height: 34px;
                    border-radius: 6px;
                    background: #4b5563;
                }
                QScrollBar::handle:vertical:hover {
                    background: #64748b;
                }
                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical {
                    height: 0;
                    border: 0;
                    background: transparent;
                }
                QScrollBar::add-page:vertical,
                QScrollBar::sub-page:vertical {
                    background: transparent;
                }
                """
            )

        def _load_history(self) -> None:
            try:
                messages = build_history_repository().load()
            except OSError as error:
                QMessageBox.warning(self, "История", f"Не удалось загрузить историю: {error}")
                return

            if not messages:
                self._append_message("Агент", "Здравствуйте. Напишите запрос, и я отправлю его в LLM через агента.")
                return

            for message in messages:
                self._append_message(self._message_author(message), message.content)

        def _send_message(self) -> None:
            text = self._input.toPlainText().strip()
            if not text:
                self._append_message("Ошибка", "Введите непустое сообщение.")
                return

            self._append_message("Вы", text)
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
                self._append_message("Ошибка", "Агент вернул некорректный ответ.")
                return

            tokens = chat_response.tokens
            meta = (
                f"Токены: запрос {tokens.current_request}, "
                f"история {tokens.history}, ответ {tokens.response}"
            )
            self._append_message("Агент", chat_response.text, meta)

        def _handle_error(self, error: str) -> None:
            self._append_message("Ошибка", error)

        def _set_loading(self, is_loading: bool) -> None:
            self._send_button.setDisabled(is_loading)
            self._input.setDisabled(is_loading)
            self._status_label.setText("Запрос..." if is_loading else "Готов")

        def _append_message(self, author: str, text: str, meta: str = "") -> None:
            author_html = html.escape(author)
            text_html = html.escape(text).replace("\n", "<br>")
            author_color = "#93c5fd"
            text_color = "#f9fafb"
            if author == "Вы":
                author_color = "#5eead4"
            elif author == "Ошибка":
                author_color = "#fca5a5"
                text_color = "#fee2e2"

            meta_html = ""
            if meta:
                meta_html = f'<div style="color:#94a3b8;font-size:12px;margin-top:6px;">{html.escape(meta)}</div>'

            self._messages.append(
                f"""
                <div style="margin:12px 0;">
                  <div style="color:{author_color};font-size:12px;font-weight:700;">{author_html}</div>
                  <div style="color:{text_color};font-size:15px;line-height:1.45;margin-top:4px;">{text_html}</div>
                  {meta_html}
                </div>
                """
            )
            scrollbar = self._messages.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        def _message_author(self, message: Message) -> str:
            if message.role == "user":
                return "Вы"

            return "Агент"

    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
