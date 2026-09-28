from ui import colors


COMPOSER_HEIGHT = 96


WINDOW_STYLESHEET = """
QMainWindow {
    background: __PAGE_BACKGROUND__;
}
QLabel {
    color: __TEXT_MUTED__;
    font-size: 14px;
}
QLabel#TaskStateLabel {
    border: 1px solid __BORDER__;
    border-radius: 8px;
    background: __SURFACE__;
    color: __TEXT_PRIMARY__;
    font-size: 13px;
    padding: 8px 10px;
}
QTextBrowser,
QTextEdit,
QComboBox {
    border: 1px solid __BORDER__;
    border-radius: 8px;
    background: __SURFACE__;
    color: __TEXT_PRIMARY__;
    font-size: 15px;
    padding: 10px;
    selection-background-color: __ACCENT__;
    selection-color: __TEXT_ON_ACCENT__;
}
QComboBox {
    min-height: 34px;
    padding: 0 10px;
}
QPushButton {
    border: 0;
    border-radius: 8px;
    background: __ACCENT__;
    color: __TEXT_ON_ACCENT__;
    font-weight: 700;
    padding: 0 16px;
}
QPushButton:hover {
    background: __ACCENT_HOVER__;
}
QPushButton:disabled {
    background: __CONTROL_DISABLED_BACKGROUND__;
    color: __CONTROL_DISABLED_TEXT__;
}
QScrollBar:vertical {
    width: 12px;
    background: __PAGE_BACKGROUND__;
    margin: 4px 2px 4px 2px;
}
QScrollBar::handle:vertical {
    min-height: 34px;
    border-radius: 6px;
    background: __CONTROL_DISABLED_BACKGROUND__;
}
QScrollBar::handle:vertical:hover {
    background: __SCROLLBAR_HANDLE_HOVER__;
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
""".replace("__COMPOSER_HEIGHT__", str(COMPOSER_HEIGHT)).replace(
    "__PAGE_BACKGROUND__", colors.PAGE_BACKGROUND
).replace(
    "__TEXT_MUTED__", colors.TEXT_MUTED
).replace(
    "__BORDER__", colors.BORDER
).replace(
    "__SURFACE__", colors.SURFACE
).replace(
    "__TEXT_PRIMARY__", colors.TEXT_PRIMARY
).replace(
    "__ACCENT__", colors.ACCENT
).replace(
    "__TEXT_ON_ACCENT__", colors.TEXT_ON_ACCENT
).replace(
    "__ACCENT_HOVER__", colors.ACCENT_HOVER
).replace(
    "__CONTROL_DISABLED_BACKGROUND__", colors.CONTROL_DISABLED_BACKGROUND
).replace(
    "__CONTROL_DISABLED_TEXT__", colors.CONTROL_DISABLED_TEXT
).replace(
    "__SCROLLBAR_HANDLE_HOVER__", colors.SCROLLBAR_HANDLE_HOVER
)
