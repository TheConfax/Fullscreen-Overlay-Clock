"""Click-through guide shown on the clock's monitor while it is dragged."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..services import win32
from . import positioning
from .style import MARKER_EDGE, MARKER_FILL, accent

_PEN = 2

_FRAME_GLOW_LAYERS = ((17, 36), (11, 62), (6, 98))  # (pen width, alpha), outermost first
_FRAME_CORE_ALPHA = 185

_WARP_MAX = 40        # px of inward pull at full intensity
_WARP_SIGMA = 80      # px, spread of the pull along the edge
_WARP_FADE = 130      # px from each corner over which the pull fades to 0
_FRAME_STEPS = 48     # samples per edge
_SNAP_FLAT_THRESH = 0.99  # intensity of a flush border is 1.0

_NODE_CORE_R = 9.0
_NODE_BORDER_W = 3

# Holds the line pulled fully inward plus its widest glow. A multiple of 4, so the strips
# meet on whole pixels at 125/150/175%.
_STRIP = 52
_REACH = 10  # px beyond a strip from which the widest pen still touches it

_Point = tuple[float, float]


def _pieces(loop: list[_Point], x0: float, y0: float, x1: float, y1: float) -> list[list[_Point]]:
    """The stretches of the closed *loop* whose segments reach the box."""
    n = len(loop)

    def hits(i: int) -> bool:
        (ax, ay), (bx, by) = loop[i], loop[(i + 1) % n]
        return min(ax, bx) <= x1 and max(ax, bx) >= x0 and min(ay, by) <= y1 and max(ay, by) >= y0

    keep = [hits(i) for i in range(n)]
    if all(keep):
        return [loop + loop[:1]]
    if not any(keep):
        return []
    start = keep.index(False)
    pieces: list[list[_Point]] = []
    cur: list[_Point] = []
    for k in range(1, n + 1):
        i = (start + k) % n
        if keep[i]:
            if not cur:
                cur.append(loop[i])
            cur.append(loop[(i + 1) % n])
        elif cur:
            pieces.append(cur)
            cur = []
    return pieces


class _Strip(QWidget):
    """One band of the guide in its own window, painting only its piece of the frame: a
    single full-monitor window is repainted and re-uploaded whole on every drag move."""

    def __init__(self, guide: PositionGuide) -> None:
        super().__init__()
        self._guide = guide
        self.area = QRect()  # in guide coords
        self._pieces: list[list[_Point]] = []
        self._win_ready = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def place(self, monitor: QRect, area: QRect) -> None:
        """Cover *area* (guide coords) of *monitor* (global coords)."""
        self.area = area
        self.setGeometry(area.translated(monitor.topLeft()))
        self.show()
        if not self._win_ready:
            self._win_ready = True
            hwnd = win32.get_hwnd(self)
            win32.set_tool_window(hwnd)
            win32.set_click_through(hwnd, True)
        self.update()

    def set_pieces(self, pieces: list[list[_Point]]) -> None:
        if pieces != self._pieces:
            self._pieces = pieces
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(-self.area.x(), -self.area.y())
        self._guide.paint_piece(painter, self._pieces)
        painter.end()


class PositionGuide:
    """Full-monitor guide: an accent frame that bends toward the dragged clock, and the
    8 anchor dots. Drawn by four strips along the borders."""

    def __init__(self) -> None:
        self._glow: dict[str, tuple[float, int]] = {}
        self._w = self._h = 0
        self._shown = False
        self._accent = accent()
        self._strips = [_Strip(self) for _ in range(4)]

    @property
    def shown(self) -> bool:
        return self._shown

    def show_on(self, geometry: QRect) -> None:
        """Cover *geometry* (global coords)."""
        w, h, t = geometry.width(), geometry.height(), _STRIP
        self._w, self._h = w, h
        self._accent = accent()
        self._shown = True
        areas = (QRect(0, 0, w, t), QRect(0, h - t, w, t),
                 QRect(0, t, t, h - 2 * t), QRect(w - t, t, t, h - 2 * t))
        for strip, area in zip(self._strips, areas):
            strip.place(geometry, area)
        self._refresh()

    def set_glow(self, glow: dict[str, tuple[float, int]]) -> None:
        """Per border, (intensity in 0..1, where the clock projects on it); {} for none."""
        self._glow = glow
        if self._shown:
            self._refresh()

    def hide(self) -> None:
        self._shown = False
        for strip in self._strips:
            strip.hide()

    def close(self) -> None:
        for strip in self._strips:
            strip.close()

    def _refresh(self) -> None:
        """Hand each strip its piece of the frame; a strip whose piece is unchanged skips the repaint."""
        loop = self._outline()
        r = _REACH
        for strip in self._strips:
            a = strip.area
            strip.set_pieces(_pieces(loop, a.x() - r, a.y() - r,
                                     a.x() + a.width() + r, a.y() + a.height() + r))

    def _warp(self, edge: str, coord: float) -> float:
        """Inward pull of *edge*'s line at *coord* (x on top/bottom, y on left/right): a
        gaussian bump at the clock, faded to 0 near the corners so no side rises into one."""
        if edge not in self._glow:
            return 0.0
        intensity, along = self._glow[edge]
        intensity = min(1.0, intensity)
        if intensity <= 0.0:
            return 0.0
        bump = math.exp(-((coord - along) ** 2) / (2 * _WARP_SIGMA ** 2))
        span = (self._w if edge in ("top", "bottom") else self._h) - _PEN
        fade = max(0.0, min(1.0, min(coord - _PEN / 2, span + _PEN / 2 - coord) / _WARP_FADE))
        return _WARP_MAX * intensity * bump * fade

    def _attached(self) -> bool:
        """True when the clock is flush with a border."""
        return any(i >= _SNAP_FLAT_THRESH for i, _ in self._glow.values())

    def _outline(self) -> list[_Point]:
        """The frame line as a closed loop clockwise from the top-left corner, each side
        bent toward the clock; flat while it is attached."""
        left = top = _PEN / 2
        right, bottom = self._w - _PEN / 2, self._h - _PEN / 2
        attached = self._attached()

        def warp(edge: str, coord: float) -> float:
            return 0.0 if attached else self._warp(edge, coord)

        n = _FRAME_STEPS
        loop: list[_Point] = []
        for i in range(n):
            x = left + (right - left) * i / n
            loop.append((x, top + warp("top", x)))
        for i in range(n):
            y = top + (bottom - top) * i / n
            loop.append((right - warp("right", y), y))
        for i in range(n):
            x = right - (right - left) * i / n
            loop.append((x, bottom - warp("bottom", x)))
        for i in range(n):
            y = bottom - (bottom - top) * i / n
            loop.append((left + warp("left", y), y))
        return loop

    def paint_piece(self, painter: QPainter, pieces: list[list[_Point]]) -> None:
        """The glow layers, then the core line, along *pieces*; then the anchor dots. In
        guide coords: the strip's window clips the rest."""
        path = QPainterPath()
        for piece in pieces:
            path.moveTo(*piece[0])
            for x, y in piece[1:]:
                path.lineTo(x, y)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in (*_FRAME_GLOW_LAYERS, (1.5, _FRAME_CORE_ALPHA)):
            c = QColor(self._accent)
            c.setAlpha(alpha)
            pen = QPen(c, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPath(path)
        monitor = QRect(0, 0, self._w, self._h)
        for anchor in positioning.ANCHORS:
            _paint_node(painter, QPointF(positioning.marker_point(monitor, anchor)))


def _paint_node(painter: QPainter, center: QPointF) -> None:
    """White dot with a black outline drawn outside its _NODE_CORE_R radius."""
    painter.setPen(QPen(MARKER_EDGE, _NODE_BORDER_W))
    painter.setBrush(MARKER_FILL)
    r = _NODE_CORE_R + _NODE_BORDER_W / 2
    painter.drawEllipse(center, r, r)
