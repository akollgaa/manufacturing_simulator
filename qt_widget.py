from __future__ import annotations

import math
from dataclasses import dataclass

from .scene import SceneNode, ScenePolyline, ViewportScene

try:
    from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPen, QWheelEvent
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    from PySide6.QtWidgets import QToolTip
except ImportError as exc:  # pragma: no cover - exercised only when Qt is unavailable
    raise RuntimeError("PySide6 is required to use the Qt viewport widget.") from exc

Vector3 = tuple[float, float, float]


@dataclass
class _CameraState:
    target: Vector3 = (0.0, 0.0, 0.8)
    zoom: float = 34.0
    azimuth: float = 0.72
    elevation: float = 0.62


class ViewportWidget(QOpenGLWidget):  # pragma: no cover - GUI-only behavior
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = ViewportScene(nodes=(), messages=())
        self._camera = _CameraState()
        self._last_mouse_position = QPoint()
        self._hovered_node_id: str | None = None
        self._hovered_label = ""
        self._did_frame_scene = False
        self.setMouseTracking(True)
        self.setMinimumSize(640, 420)

    def set_scene(self, scene: ViewportScene) -> None:
        self._scene = scene
        if not self._did_frame_scene or not self._scene.nodes:
            self.frame_scene()
        self.update()

    def frame_scene(self) -> None:
        self._did_frame_scene = True
        min_x, max_x, min_y, max_y, min_z, max_z = self._scene.world_bounds
        self._camera.target = (
            (min_x + max_x) / 2.0,
            (min_y + max_y) / 2.0,
            (min_z + max_z) / 2.0,
        )
        self._camera.zoom = self._fit_zoom()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_mouse_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.frame_scene()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        position = event.position().toPoint()
        delta = position - self._last_mouse_position
        if event.buttons() & Qt.LeftButton:
            if event.modifiers() & Qt.ShiftModifier:
                self._camera.azimuth += delta.x() * 0.01
                self._camera.elevation = max(0.15, min(1.35, self._camera.elevation - (delta.y() * 0.01)))
            else:
                self._pan_by_pixels(delta.x(), delta.y())
            self.update()
        else:
            self._update_hover(position, event.globalPosition().toPoint())
        self._last_mouse_position = position
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered_node_id = None
        self._hovered_label = ""
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        cursor = event.position().toPoint()
        before = self._screen_to_world_on_plane(cursor, z_plane=0.0)
        angle = event.angleDelta().y() / 120.0
        self._camera.zoom = max(8.0, min(320.0, self._camera.zoom * (1.0 + (angle * 0.12))))
        after = self._screen_to_world_on_plane(cursor, z_plane=0.0)
        if before and after:
            self._camera.target = (
                self._camera.target[0] + (before[0] - after[0]),
                self._camera.target[1] + (before[1] - after[1]),
                self._camera.target[2],
            )
        self.update()
        super().wheelEvent(event)

    def paintGL(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint_background(painter)
        self._paint_grid(painter)
        self._paint_scene(painter)
        self._paint_overlay(painter)
        painter.end()

    def _paint_background(self, painter: QPainter) -> None:
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor("#08121b"))
        gradient.setColorAt(0.5, QColor("#102433"))
        gradient.setColorAt(1.0, QColor("#1a3141"))
        painter.fillRect(self.rect(), gradient)

    def _paint_grid(self, painter: QPainter) -> None:
        min_x, max_x, min_y, max_y, _, _ = self._scene.world_bounds
        span = max(max_x - min_x, max_y - min_y, 6.0)
        step = _grid_step(span)
        padded = span * 0.75
        painter.setPen(QPen(QColor("#24475f"), 1.0))

        x = math.floor((min_x - padded) / step) * step
        while x <= max_x + padded:
            self._draw_polyline(
                painter,
                ScenePolyline(points=((x, min_y - padded, 0.0), (x, max_y + padded, 0.0))),
                color=QColor("#24475f"),
            )
            x += step

        y = math.floor((min_y - padded) / step) * step
        while y <= max_y + padded:
            self._draw_polyline(
                painter,
                ScenePolyline(points=((min_x - padded, y, 0.0), (max_x + padded, y, 0.0))),
                color=QColor("#24475f"),
            )
            y += step

        self._draw_polyline(
            painter,
            ScenePolyline(points=((min_x - padded, 0.0, 0.0), (max_x + padded, 0.0, 0.0))),
            color=QColor("#4e88b0"),
            width=1.5,
        )
        self._draw_polyline(
            painter,
            ScenePolyline(points=((0.0, min_y - padded, 0.0), (0.0, max_y + padded, 0.0))),
            color=QColor("#4e88b0"),
            width=1.5,
        )

    def _paint_scene(self, painter: QPainter) -> None:
        ordered_nodes = sorted(self._scene.nodes, key=self._node_depth)
        for node in ordered_nodes:
            hovered = node.node_id == self._hovered_node_id
            base_color = QColor(_node_color(node))
            line_width = 2.4 if hovered else 1.6
            if hovered:
                base_color = QColor("#ffd166")
            for polyline in node.polylines:
                self._draw_polyline(
                    painter,
                    polyline,
                    color=_polyline_color(node, polyline, base_color),
                    width=line_width if polyline.style != "highlight" else line_width + 0.6,
                )
            if hovered:
                self._paint_hover_label(painter, node)

    def _paint_overlay(self, painter: QPainter) -> None:
        painter.setPen(QColor("#e7f1ff"))
        painter.setFont(QFont("Helvetica", 10))
        summary = f"{len(self._scene.nodes)} scene objects | {len(self._scene.messages)} warnings | double-click to frame"
        if self._scene.overlay_label:
            summary = f"{summary} | {self._scene.overlay_label}"
        painter.drawText(QRectF(16, 14, self.width() - 32, 24), Qt.AlignLeft | Qt.AlignVCenter, summary)
        controls = "LMB pan  |  Shift+LMB orbit  |  Wheel zoom  |  Hover for details"
        painter.drawText(QRectF(16, self.height() - 30, self.width() - 32, 20), Qt.AlignLeft | Qt.AlignVCenter, controls)

    def _paint_hover_label(self, painter: QPainter, node: SceneNode) -> None:
        projected = [self._project_point(point) for polyline in node.polylines for point in polyline.points]
        if not projected:
            return
        min_x = min(point[0] for point in projected)
        min_y = min(point[1] for point in projected)
        rect = QRectF(min_x + 10, min_y - 34, 180, 28)
        painter.setBrush(QColor(8, 18, 27, 220))
        painter.setPen(QPen(QColor("#ffd166"), 1.0))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor("#fff4cf"))
        painter.drawText(rect.adjusted(8, 4, -8, -4), Qt.AlignLeft | Qt.AlignVCenter, node.metadata.get("name", node.label))

    def _draw_polyline(self, painter: QPainter, polyline: ScenePolyline, color: QColor, width: float = 1.4) -> None:
        if len(polyline.points) < 2:
            return
        projected = [self._project_point(point) for point in polyline.points]
        painter.setPen(QPen(color, width))
        for start, end in zip(projected, projected[1:]):
            painter.drawLine(QPointF(start[0], start[1]), QPointF(end[0], end[1]))
        if polyline.closed:
            painter.drawLine(QPointF(projected[-1][0], projected[-1][1]), QPointF(projected[0][0], projected[0][1]))

    def _update_hover(self, point: QPoint, global_point: QPoint) -> None:
        hovered = self._hit_test(point)
        hovered_id = hovered.node_id if hovered else None
        if hovered_id != self._hovered_node_id:
            self._hovered_node_id = hovered_id
            if hovered is None:
                self._hovered_label = ""
                QToolTip.hideText()
            else:
                details = [hovered.metadata.get("name", hovered.label), f"kind={hovered.kind}", f"source={hovered.source}"]
                details.extend(f"{key}={value}" for key, value in sorted(hovered.metadata.items()) if key not in {"name"})
                details.extend(f"replay.{key}={value}" for key, value in sorted(hovered.overlay.items()))
                self._hovered_label = "\n".join(details)
                QToolTip.showText(global_point, self._hovered_label, self)
            self.update()

    def _hit_test(self, point: QPoint) -> SceneNode | None:
        best_node: SceneNode | None = None
        best_distance = 22.0
        for node in self._scene.nodes:
            projected = [self._project_point(p) for polyline in node.polylines for p in polyline.points]
            if not projected:
                projected = [self._project_point(node.position)]
            center_x = sum(item[0] for item in projected) / len(projected)
            center_y = sum(item[1] for item in projected) / len(projected)
            distance = math.dist((point.x(), point.y()), (center_x, center_y))
            if distance < best_distance:
                best_distance = distance
                best_node = node
        return best_node

    def _project_point(self, point: Vector3) -> tuple[float, float, float]:
        right, up, forward = _camera_basis(self._camera.azimuth, self._camera.elevation)
        relative = (
            point[0] - self._camera.target[0],
            point[1] - self._camera.target[1],
            point[2] - self._camera.target[2],
        )
        camera_x = _dot(relative, right)
        camera_y = _dot(relative, up)
        depth = _dot(relative, forward)
        return (
            (self.width() / 2.0) + (camera_x * self._camera.zoom),
            (self.height() / 2.0) - (camera_y * self._camera.zoom),
            depth,
        )

    def _pan_by_pixels(self, dx: int, dy: int) -> None:
        right, up, _ = _camera_basis(self._camera.azimuth, self._camera.elevation)
        scale = 1.0 / max(self._camera.zoom, 1.0)
        self._camera.target = (
            self._camera.target[0] - (right[0] * dx * scale) + (up[0] * dy * scale),
            self._camera.target[1] - (right[1] * dx * scale) + (up[1] * dy * scale),
            self._camera.target[2] - (right[2] * dx * scale) + (up[2] * dy * scale),
        )

    def _screen_to_world_on_plane(self, point: QPoint, z_plane: float) -> Vector3 | None:
        right, up, _ = _camera_basis(self._camera.azimuth, self._camera.elevation)
        determinant = (right[0] * up[1]) - (right[1] * up[0])
        if abs(determinant) < 1e-6:
            return None
        world_x = (point.x() - (self.width() / 2.0)) / self._camera.zoom
        world_y = -((point.y() - (self.height() / 2.0)) / self._camera.zoom)
        rhs_x = world_x + _dot(self._camera.target, right) - (z_plane * right[2])
        rhs_y = world_y + _dot(self._camera.target, up) - (z_plane * up[2])
        x = ((rhs_x * up[1]) - (right[1] * rhs_y)) / determinant
        y = ((right[0] * rhs_y) - (rhs_x * up[0])) / determinant
        return (x, y, z_plane)

    def _fit_zoom(self) -> float:
        min_x, max_x, min_y, max_y, min_z, max_z = self._scene.world_bounds
        corners = [
            (x, y, z)
            for x in (min_x, max_x)
            for y in (min_y, max_y)
            for z in (min_z, max_z)
        ]
        right, up, _ = _camera_basis(self._camera.azimuth, self._camera.elevation)
        projected_x = []
        projected_y = []
        target = (
            (min_x + max_x) / 2.0,
            (min_y + max_y) / 2.0,
            (min_z + max_z) / 2.0,
        )
        for corner in corners:
            relative = (corner[0] - target[0], corner[1] - target[1], corner[2] - target[2])
            projected_x.append(_dot(relative, right))
            projected_y.append(_dot(relative, up))
        span_x = max(max(projected_x) - min(projected_x), 1.0)
        span_y = max(max(projected_y) - min(projected_y), 1.0)
        usable_width = max(self.width() * 0.78, 320.0)
        usable_height = max(self.height() * 0.72, 220.0)
        return max(8.0, min(240.0, min(usable_width / span_x, usable_height / span_y)))

    def _node_depth(self, node: SceneNode) -> float:
        projected = [self._project_point(point) for polyline in node.polylines for point in polyline.points]
        if not projected:
            projected = [self._project_point(node.position)]
        return sum(point[2] for point in projected) / len(projected)


def _camera_basis(azimuth: float, elevation: float) -> tuple[Vector3, Vector3, Vector3]:
    right = (math.cos(azimuth), -math.sin(azimuth), 0.0)
    forward = (
        math.sin(azimuth) * math.cos(elevation),
        math.cos(azimuth) * math.cos(elevation),
        -math.sin(elevation),
    )
    up = _normalize(_cross(forward, right))
    return _normalize(right), up, _normalize(forward)


def _grid_step(span: float) -> float:
    if span <= 10:
        return 1.0
    if span <= 25:
        return 2.0
    if span <= 60:
        return 5.0
    return 10.0


def _node_color(node: SceneNode) -> str:
    status = node.overlay.get("status")
    if status == "busy":
        return "#ffb25c"
    if status == "queued":
        return "#f4dd7b"
    if status == "moving":
        return "#8de1ff"
    if node.source == "dxf":
        return "#7ec8ff"
    if node.source == "placeholder":
        return "#e6a54e"
    if node.kind in {"buffer", "queue"}:
        return "#87d6b3"
    if node.kind == "conveyor":
        return "#b8d4f2"
    if node.kind == "human":
        return "#ff8c6b"
    return "#9fd6c2"


def _polyline_color(node: SceneNode, polyline: ScenePolyline, default: QColor) -> QColor:
    if polyline.style == "highlight":
        return QColor("#f8f4c7")
    if polyline.style == "conveyor":
        return QColor("#9ec3f0")
    if polyline.style == "human":
        return QColor("#ff9b7a")
    return default


def _dot(left: Vector3, right: Vector3) -> float:
    return (left[0] * right[0]) + (left[1] * right[1]) + (left[2] * right[2])


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        (left[1] * right[2]) - (left[2] * right[1]),
        (left[2] * right[0]) - (left[0] * right[2]),
        (left[0] * right[1]) - (left[1] * right[0]),
    )


def _normalize(vector: Vector3) -> Vector3:
    magnitude = math.sqrt(_dot(vector, vector)) or 1.0
    return (vector[0] / magnitude, vector[1] / magnitude, vector[2] / magnitude)
