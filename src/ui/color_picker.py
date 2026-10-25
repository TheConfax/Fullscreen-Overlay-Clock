"""In-theme color picker popup with a screen eyedropper."""

from __future__ import annotations

from PyQt6.QtCore import (
    QByteArray, QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QCursor, QGuiApplication, QIcon, QImage, QLinearGradient, QPainter, QPen, QPixmap,
    QScreen,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from ..services.paths import resource_path
from ..i18n import S
from .style import (
    MARKER_EDGE, MARKER_FILL, ink, is_dark, muted_gray, on_theme_change, panel_colors, px,
)

_SQUARE = 140          # SV square side: with the hue strip, as wide as the R/G/B row
_HUE_W = 14
_MAX_HUE = 0.9999      # Qt treats hue 1.0 as invalid


def _pipette_icon(size: int, dpr: float) -> QIcon:
    """The eyedropper SVG in the theme's ink, drawn at *dpr*: at density 1 Qt scales it up blurry."""
    col = ink(is_dark())
    svg = resource_path("resources", "color_picker.svg").read_text(encoding="latin-1")
    renderer = QSvgRenderer(QByteArray(svg.replace('fill="#000000"', f'fill="{col}"').encode()))
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


def _draw_marker(painter: QPainter, center: QPointF, r: float) -> None:
    """A ring marker that reads on any background: black halo under a white ring."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(MARKER_EDGE, 3))
    painter.drawEllipse(center, r, r)
    painter.setPen(QPen(MARKER_FILL, 1.5))
    painter.drawEllipse(center, r, r)


class _SVSquare(QWidget):
    """Saturation (x) × Value (y) square for the current hue."""

    changed = pyqtSignal(float, float)  # s, v in [0, 1]

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(px(_SQUARE), px(_SQUARE))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._hue = 0.0
        self._s = 0.0
        self._v = 1.0

    def set_hue(self, h: float) -> None:
        self._hue = min(_MAX_HUE, max(0.0, h))
        self.update()

    def set_sv(self, s: float, v: float) -> None:
        self._s, self._v = s, v
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        gs = QLinearGradient(0, 0, w, 0)
        gs.setColorAt(0.0, QColor("#ffffff"))
        gs.setColorAt(1.0, QColor.fromHsvF(self._hue, 1.0, 1.0))
        p.fillRect(self.rect(), gs)
        gv = QLinearGradient(0, 0, 0, h)
        gv.setColorAt(0.0, QColor(0, 0, 0, 0))
        gv.setColorAt(1.0, QColor(0, 0, 0, 255))
        p.fillRect(self.rect(), gv)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _draw_marker(p, QPointF(self._s * w, (1.0 - self._v) * h), float(px(5)))

    def _emit_at(self, pos: QPointF) -> None:
        self._s = min(1.0, max(0.0, pos.x() / self.width()))
        self._v = 1.0 - min(1.0, max(0.0, pos.y() / self.height()))
        self.update()
        self.changed.emit(self._s, self._v)

    def mousePressEvent(self, e) -> None:
        self._emit_at(e.position())

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._emit_at(e.position())


class _HueStrip(QWidget):
    """Vertical hue rainbow."""

    changed = pyqtSignal(float)  # hue in [0, 1]

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(px(_HUE_W), px(_SQUARE))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._hue = 0.0

    def set_hue(self, h: float) -> None:
        self._hue = min(_MAX_HUE, max(0.0, h))
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, 0, h)
        for i in range(7):
            g.setColorAt(i / 6.0, QColor.fromHsvF(min(_MAX_HUE, i / 6.0), 1.0, 1.0))
        p.fillRect(self.rect(), g)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        y = self._hue * h
        p.setPen(QPen(MARKER_EDGE, 3))
        p.drawLine(QPointF(0, y), QPointF(w, y))
        p.setPen(QPen(MARKER_FILL, 1.5))
        p.drawLine(QPointF(0, y), QPointF(w, y))

    def _emit_at(self, pos: QPointF) -> None:
        self._hue = min(1.0, max(0.0, pos.y() / self.height()))
        self.update()
        self.changed.emit(self._hue)

    def mousePressEvent(self, e) -> None:
        self._emit_at(e.position())

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._emit_at(e.position())


class _Shot(QWidget):
    """One monitor frozen in its own screenshot, at that monitor's scaling."""

    clicked = pyqtSignal(QColor)
    escaped = pyqtSignal()

    def __init__(self, screen: QScreen) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._img: QImage = screen.grabWindow().toImage()
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

    def paintEvent(self, _e) -> None:
        QPainter(self).drawImage(self.rect(), self._img)

    def mousePressEvent(self, e) -> None:
        # The image is in physical pixels, the click in logical ones.
        img, pos = self._img, e.position()
        x = min(int(pos.x() * img.width() / self.width()), img.width() - 1)
        y = min(int(pos.y() * img.height() / self.height()), img.height() - 1)
        self.clicked.emit(QColor(img.pixel(x, y)))

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.escaped.emit()


class _EyeDropper(QObject):
    """Every monitor frozen at once: a click on any samples that pixel, Esc cancels."""

    picked = pyqtSignal(QColor)
    canceled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._shots: list[_Shot] = []

    def start(self) -> None:
        # All grabbed before any shows, or a later grab captures an earlier shot.
        self._shots = [_Shot(screen) for screen in QGuiApplication.screens()]
        for shot in self._shots:
            shot.clicked.connect(self._on_clicked)
            shot.escaped.connect(self._on_escaped)
            shot.show()
        cursor = QCursor.pos()
        focus = next((s for s in self._shots if s.geometry().contains(cursor)), self._shots[0])
        focus.activateWindow()
        focus.raise_()

    def _on_clicked(self, color: QColor) -> None:
        self._hide()
        self.picked.emit(color)

    def _on_escaped(self) -> None:
        self._hide()
        self.canceled.emit()

    def _hide(self) -> None:
        for shot in self._shots:
            shot.hide()


class ColorPicker(QWidget):
    """Opens beside *anchor*, emits `colorChanged` live, closes on Esc or click-away. RGB
    only: opacity has its own sliders."""

    colorChanged = pyqtSignal(str)  # "#RRGGBB"

    def __init__(self, initial_hex: str, anchor: QWidget) -> None:
        super().__init__(anchor.window(),
                         Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._updating = False
        self._keep_open = False  # no click-away close while the eyedropper runs
        self._eye: _EyeDropper | None = None
        self._pipe_base = None
        self._tags: list[QLabel] = []

        c = QColor(initial_hex)
        h, s, v, _ = c.getHsvF()
        self._h = max(0.0, h)   # -1 for grays
        self._s, self._v = s, v

        self._build()
        self._restyle()
        on_theme_change(self._restyle)
        self._apply(emit=False)
        self.adjustSize()
        self._place_beside(anchor)

    # -- layout --------------------------------------------------------------
    def _build(self) -> None:
        self._panel = panel = QFrame(self)
        panel.setObjectName("cpPanel")
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.addWidget(panel)
        shell.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)  # no 200px top-level minimum

        self._sv = _SVSquare()
        self._sv.changed.connect(self._on_sv)
        self._hue = _HueStrip()
        self._hue.changed.connect(self._on_hue)

        top = QHBoxLayout()
        top.setSpacing(px(6))
        top.addWidget(self._sv)
        top.addWidget(self._hue)

        self._r = self._channel()
        self._g = self._channel()
        self._b = self._channel()
        for ch in (self._r, self._g, self._b):
            ch.valueChanged.connect(self._on_rgb)
        self._hex = QLineEdit()
        self._hex.setMaxLength(7)
        self._hex.setFixedWidth(px(76))
        self._hex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hex.textEdited.connect(self._on_hex)

        self._eye_btn = QPushButton()
        self._eye_btn.setIconSize(QSize(px(16), px(16)))
        self._eye_btn.setToolTip(S.tabs.clock.color_picker.eyedropper)
        self._eye_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._eye_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._eye_btn.clicked.connect(self._start_eyedropper)

        fields = QHBoxLayout()
        fields.setSpacing(px(6))
        for name, box in (("R", self._r), ("G", self._g), ("B", self._b)):
            fields.addWidget(self._tag(name))
            fields.addWidget(box)
        fields.addStretch()

        bottom = self._bottom = QHBoxLayout()
        bottom.setSpacing(px(6))
        bottom.addWidget(self._tag("HEX"))
        bottom.addWidget(self._hex)
        bottom.addSpacing(px(6))
        bottom.addWidget(self._eye_btn, 1)

        inner = QVBoxLayout(panel)
        inner.setContentsMargins(px(8), px(8), px(8), px(8))
        inner.setSpacing(px(8))
        inner.addLayout(top)
        inner.addLayout(fields)
        inner.addLayout(bottom)

    def _restyle(self) -> None:
        dark = is_dark()
        bg, border, _ = panel_colors(dark)
        self._panel.setStyleSheet(
            f"#cpPanel {{ background:{bg}; border:1px solid {border}; border-radius:8px; }}")
        muted = f"color:{muted_gray(dark)};"
        for tag in self._tags:
            tag.setStyleSheet(muted)
        self._eye_btn.setIcon(_pipette_icon(px(16), self.devicePixelRatioF()))

    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(0, self._inflate_pipette)  # after the layout pass settles the cell

    def _inflate_pipette(self) -> None:
        """1px past its layout cell on the right. From the cell captured once: the layout doesn't
        reset it on re-show, so the +1 would add up."""
        if self._pipe_base is None:
            self._pipe_base = self._eye_btn.geometry()
        b = self._pipe_base
        self._eye_btn.setGeometry(b.x(), b.y(), b.width() + 1, b.height())

    @staticmethod
    def _channel() -> QSpinBox:
        box = QSpinBox()
        box.setRange(0, 255)
        box.setFixedWidth(px(36))
        box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return box

    def _tag(self, text: str) -> QLabel:
        lbl = QLabel(text)
        self._tags.append(lbl)
        return lbl

    def _place_beside(self, anchor: QWidget) -> None:
        """Open to the RIGHT of the swatch, top-aligned; flip to the left if it won't fit."""
        left = anchor.mapToGlobal(QPoint(0, 0))
        screen = anchor.screen() or QGuiApplication.screenAt(left)
        if screen is None:
            return
        area = screen.availableGeometry()
        right = anchor.mapToGlobal(QPoint(anchor.width() + px(6), 0))
        x = right.x()
        if x + self.width() > area.right():
            x = left.x() - self.width() - px(6)
        x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
        y = max(area.top() + 4, min(right.y(), area.bottom() - self.height() - 4))
        self.move(x, y)

    # -- color plumbing -----------------------------------------------------
    def _color(self) -> QColor:
        return QColor.fromHsvF(min(_MAX_HUE, self._h), self._s, self._v)

    def _apply(self, emit: bool = True) -> None:
        """Push the current H,S,V to every widget (without re-triggering handlers)."""
        self._updating = True
        c = self._color()
        self._sv.set_hue(self._h)
        self._sv.set_sv(self._s, self._v)
        self._hue.set_hue(self._h)
        self._r.setValue(c.red())
        self._g.setValue(c.green())
        self._b.setValue(c.blue())
        self._hex.setText(c.name().upper())
        self._updating = False
        if emit:
            self.colorChanged.emit(c.name().upper())

    def _on_sv(self, s: float, v: float) -> None:
        if self._updating:
            return
        self._s, self._v = s, v
        self._apply()

    def _on_hue(self, h: float) -> None:
        if self._updating:
            return
        self._h = min(_MAX_HUE, h)
        self._apply()

    def _on_rgb(self, _v: int) -> None:
        if self._updating:
            return
        self._set_from_color(QColor(self._r.value(), self._g.value(), self._b.value()))

    def _on_hex(self, text: str) -> None:
        if self._updating:
            return
        t = text.strip()
        if not t.startswith("#"):
            t = "#" + t
        c = QColor(t)
        if c.isValid() and len(t) == 7:
            self._set_from_color(c)

    def _set_from_color(self, c: QColor) -> None:
        h, s, v, _ = c.getHsvF()
        if h >= 0:  # grays (-1) keep the prior hue
            self._h = h
        self._s, self._v = s, v
        self._apply()

    # -- eyedropper ----------------------------------------------------------
    def _start_eyedropper(self) -> None:
        self._keep_open = True
        self.hide()
        self._eye = _EyeDropper()
        self._eye.picked.connect(self._on_eyedropped)
        self._eye.canceled.connect(self._after_eyedropper)
        self._eye.start()

    def _on_eyedropped(self, color: QColor) -> None:
        if color.isValid():
            self._set_from_color(color)
        self._after_eyedropper()

    def _after_eyedropper(self) -> None:
        self._keep_open = False
        self.show()
        self.activateWindow()
        self.raise_()
        # Not here: this runs inside the dropper's own event, and the last reference going destroys it.
        QTimer.singleShot(0, self._release_eyedropper)

    def _release_eyedropper(self) -> None:
        """Frees the dropper and its desktop screenshot."""
        self._eye = None

    # -- dismissal -----------------------------------------------------------
    def event(self, e) -> bool:
        if e.type() == QEvent.Type.WindowDeactivate and not self._keep_open:
            self.close()
        return super().event(e)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)
