"""In-theme modals: the confirmation before an action, a notice, and the licenses panel."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QStyle, QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..i18n import S
from ..services.paths import root_file
from .style import (
    DESTRUCTIVE_RED, DESTRUCTIVE_RED_HOVER, DESTRUCTIVE_TEXT, is_dark, muted_gray, on_theme_change,
    panel_button_colors, panel_colors, px,
)

_SEP = "=" * 80
_TEXT_PX = 12
_VIEW_H = 360
_SCREEN_MARGIN = 16  # kept clear between the licenses panel and the screen's edges


class _PanelDialog(QDialog):
    """Frameless in-theme modal: a title, the content, the buttons on the right."""

    def __init__(self, parent: QWidget | None, title: str, *, topmost: bool = False) -> None:
        # *topmost*: asked from the always-on-top clock, otherwise Windows draws it underneath.
        flags = Qt.WindowType.FramelessWindowHint
        if topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Parented: without this every dialog ever asked stays alive, hidden.
        self.finished.connect(self.deleteLater)

        self._panel = QFrame(self)
        self._panel.setObjectName("panel")
        self._shell = QVBoxLayout(self)
        self._shell.setContentsMargins(0, 0, 0, 0)
        self._shell.addWidget(self._panel)

        self._title = QLabel(title)
        self._buttons = QHBoxLayout()
        self._buttons.addStretch(1)
        self._inner = QVBoxLayout(self._panel)
        self._inner.setContentsMargins(px(18), px(16), px(18), px(14))
        self._inner.setSpacing(px(12))
        self._inner.addWidget(self._title)
        self._inner.addLayout(self._buttons)
        on_theme_change(self._restyle)

    def _add_content(self, widget: QWidget) -> None:
        """Between the title and the buttons."""
        self._inner.insertWidget(self._inner.count() - 1, widget)

    @staticmethod
    def _red_button(label: str) -> QPushButton:
        button = QPushButton(label)
        button.setStyleSheet(
            f"QPushButton {{ padding:{px(6)}px {px(16)}px; border-radius:5px;"
            f" border:1px solid {DESTRUCTIVE_RED}; background:{DESTRUCTIVE_RED}; color:{DESTRUCTIVE_TEXT}; }}"
            f"QPushButton:hover {{ background:{DESTRUCTIVE_RED_HOVER};"
            f" border-color:{DESTRUCTIVE_RED_HOVER}; }}")
        return button

    def _restyle(self) -> None:
        bg, border, fg = panel_colors(is_dark())
        self._panel.setStyleSheet(
            f"#panel {{ background:{bg}; border:1px solid {border}; border-radius:8px; }}")
        self._title.setStyleSheet(f"color:{fg}; font-weight:bold; font-size:{px(14)}px;")

    def showEvent(self, e) -> None:  # center over the parent window once sized
        super().showEvent(e)
        parent = self.parentWidget()
        window = parent.window() if parent is not None else None
        if window is not None:
            self.move(window.frameGeometry().center() - self.rect().center())


class ConfirmDialog(_PanelDialog):
    """Asks before an action runs; `ask` returns True only on confirm."""

    @staticmethod
    def ask(parent: QWidget, title: str, body: str, confirm_label: str, cancel_label: str,
            *, topmost: bool = False) -> bool:
        dlg = ConfirmDialog(parent, title, body, confirm_label, cancel_label, topmost=topmost)
        return dlg.exec() == QDialog.DialogCode.Accepted

    def __init__(self, parent: QWidget, title: str, body: str, confirm_label: str,
                 cancel_label: str, *, topmost: bool = False) -> None:
        super().__init__(parent, title, topmost=topmost)
        self._body = QLabel(body)
        self._body.setWordWrap(True)
        self._body.setMinimumWidth(px(300))
        self._add_content(self._body)

        self._cancel_btn = QPushButton(cancel_label)
        self._cancel_btn.clicked.connect(self.reject)
        self._cancel_btn.setDefault(True)  # a stray Enter backs out
        confirm_btn = self._red_button(confirm_label)
        confirm_btn.clicked.connect(self.accept)
        self._buttons.addWidget(self._cancel_btn)
        self._buttons.addWidget(confirm_btn)
        self._restyle()

    def _restyle(self) -> None:
        super()._restyle()
        dark = is_dark()
        _, _, fg = panel_colors(dark)
        btn_bg, btn_hover, btn_border = panel_button_colors(dark)
        self._body.setStyleSheet(f"color:{muted_gray(dark)};")
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ padding:{px(6)}px {px(16)}px; border-radius:5px;"
            f" border:1px solid {btn_border}; background:{btn_bg}; color:{fg}; }}"
            f"QPushButton:hover {{ background:{btn_hover}; }}")


class NoticeDialog(_PanelDialog):
    """Tells the user something; one button closes it."""

    @staticmethod
    def tell(parent: QWidget | None, title: str, body: str, close_label: str) -> None:
        NoticeDialog(parent, title, body, close_label).exec()

    def __init__(self, parent: QWidget | None, title: str, body: str, close_label: str) -> None:
        super().__init__(parent, title, topmost=True)
        self._body = QLabel(body)
        self._body.setWordWrap(True)
        self._body.setMinimumWidth(px(300))
        self._add_content(self._body)

        close_btn = self._red_button(close_label)
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        self._buttons.addWidget(close_btn)
        self._restyle()

    def _restyle(self) -> None:
        super()._restyle()
        self._body.setStyleSheet(f"color:{muted_gray(is_dark())};")


def _licenses_text() -> str:
    ours = root_file("LICENSE").read_text(encoding="utf-8").strip("\n")
    theirs = root_file("THIRD_PARTY_LICENSES").read_text(encoding="utf-8").strip("\n")
    return f"{_SEP}\n{APP_NAME.upper()} {__version__}\n{_SEP}\n\n{ours}\n\n\n{theirs}\n"


class LicensesDialog(_PanelDialog):
    """Ours first, then the third-party notices. Closes only with Esc or Close, not on losing
    focus: following a source link keeps the place."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, S.tabs.system.about.licenses)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPixelSize(px(_TEXT_PX))
        self._view = view = QPlainTextEdit(_licenses_text())
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        view.setFont(font)
        # 80 columns, measured as a whole run: one glyph × 80 can round short and wrap a full line.
        doc, style = view.document(), view.style()
        width = (QFontMetrics(font).horizontalAdvance("0" * len(_SEP)) + 2
                 + (2 * int(doc.documentMargin()) if doc is not None else 0)
                 + (style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent) if style is not None else 0))
        view.setFixedSize(width, px(_VIEW_H))
        self._add_content(view)

        close_btn = self._red_button(S.tabs.system.about.modals.licenses.close)
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.reject)
        self._buttons.addWidget(close_btn)
        self._restyle()
        self._fit_to_screen()

    def _restyle(self) -> None:
        super()._restyle()
        bg, border, fg = panel_colors(is_dark())
        self._view.setStyleSheet(
            f"QPlainTextEdit {{ background:{bg}; color:{fg};"
            f" border:1px solid {border}; border-radius:4px; }}")

    def _fit_to_screen(self) -> None:
        """Shrink the text view so the panel fits the screen. Before the first show: afterwards
        the panel keeps the size it opened with."""
        screen = (self.parentWidget() or self).screen()
        if screen is None:
            return
        edge = px(_SCREEN_MARGIN)
        room = screen.availableGeometry().size() - QSize(2 * edge, 2 * edge)
        chrome = self.sizeHint() - self._view.size()
        self._view.setFixedSize(QSize(min(self._view.width(), room.width() - chrome.width()),
                                      min(self._view.height(), room.height() - chrome.height())))
        # Sized by hand, inner layout first: otherwise Qt opens it at the size from before the
        # view shrank.
        self._inner.activate()
        self._panel.updateGeometry()
        self._shell.activate()
        self.resize(self.sizeHint())

    def showEvent(self, e) -> None:  # kept on screen
        super().showEvent(e)
        screen = self.screen()
        if screen is None:
            return
        edge = px(_SCREEN_MARGIN)
        room = screen.availableGeometry().adjusted(edge, edge, -edge, -edge)
        self.move(max(room.left(), min(self.x(), room.right() - self.width())),
                  max(room.top(), min(self.y(), room.bottom() - self.height())))
