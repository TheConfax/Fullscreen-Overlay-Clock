"""Position geometry: x and y as fractions of the free space (monitor minus clock)."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize

#: The 8 snap points as (x, y): the corners and the middle of each edge.
ANCHORS = (
    (0.0, 0.0), (0.5, 0.0), (1.0, 0.0),
    (0.0, 0.5), (1.0, 0.5),
    (0.0, 1.0), (0.5, 1.0), (1.0, 1.0),
)


def _dist2(a: QPoint, b: QPoint) -> int:
    return (a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2


def _fraction(start: int, span: int, length: int, pos: int) -> float:
    free = span - length
    return (pos - start) / free if free else 0.0


def topleft_for(geom: QRect, size: QSize, x: float, y: float) -> QPoint:
    """Top-left of a *size* window at (x, y) on *geom*: 0 is flush with the left / top
    edge, 1 with the right / bottom one; outside 0..1 it overhangs that edge."""
    return QPoint(geom.x() + round(x * (geom.width() - size.width())),
                  geom.y() + round(y * (geom.height() - size.height())))


def fraction_for(geom: QRect, size: QSize, tl: QPoint) -> tuple[float, float]:
    """Inverse of topleft_for: the (x, y) that puts the top-left at *tl*."""
    return (_fraction(geom.x(), geom.width(), size.width(), tl.x()),
            _fraction(geom.y(), geom.height(), size.height(), tl.y()))


def anchor_under_rect(geom: QRect, rect: QRect, tol: int = 0) -> tuple[float, float] | None:
    """The anchor whose guide dot lies inside *rect* grown by *tol*: the one nearest
    the rect's center if several, None if none."""
    probe = rect.adjusted(-tol, -tol, tol, tol)
    hits = [a for a in ANCHORS if probe.contains(marker_point(geom, a))]
    if not hits:
        return None
    return min(hits, key=lambda a: _dist2(marker_point(geom, a), rect.center()))


def _snap_axis(start: int, span: int, length: int, pos: int, tol: int) -> float | None:
    """0 or 1 when a segment at *pos* is within *tol* of the start or end edge, else None."""
    if abs(pos - start) <= tol:
        return 0.0
    if abs(pos + length - (start + span)) <= tol:
        return 1.0
    return None


def edge_snap(geom: QRect, size: QSize, tl: QPoint, tol: int) -> tuple[float, float] | None:
    """Snap each axis on its own flush to a monitor edge within *tol* px; a free axis stays
    where it is. Returns (x, y), or None when neither axis is near an edge."""
    snap_x = _snap_axis(geom.x(), geom.width(), size.width(), tl.x(), tol)
    snap_y = _snap_axis(geom.y(), geom.height(), size.height(), tl.y(), tol)
    if snap_x is None and snap_y is None:
        return None
    x, y = fraction_for(geom, size, tl)
    return (x if snap_x is None else snap_x), (y if snap_y is None else snap_y)


def marker_point(rect: QRect, anchor: tuple[float, float]) -> QPoint:
    """Center of an anchor's guide dot on *rect*, in *rect*'s coordinates."""
    return QPoint(rect.x() + int(anchor[0] * rect.width()),
                  rect.y() + int(anchor[1] * rect.height()))


def snapped_edges(x: float, y: float) -> frozenset[str]:
    """The monitor borders a clock at (x, y) is flush with."""
    edges = set()
    if x == 0:
        edges.add("left")
    elif x == 1:
        edges.add("right")
    if y == 0:
        edges.add("top")
    elif y == 1:
        edges.add("bottom")
    return frozenset(edges)
