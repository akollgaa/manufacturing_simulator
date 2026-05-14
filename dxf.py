from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    import ezdxf
except ImportError:  # pragma: no cover - optional dependency
    ezdxf = None

Point2D = tuple[float, float]


@dataclass(frozen=True)
class DXFPolyline:
    points: tuple[Point2D, ...]
    closed: bool = False


@dataclass(frozen=True)
class DXFAssetSummary:
    path: str
    entity_count: int
    extents: tuple[float, float, float]
    center: Point2D
    polylines: tuple[DXFPolyline, ...]


@lru_cache(maxsize=64)
def inspect_dxf_asset(path: str | Path | None) -> DXFAssetSummary | None:
    if ezdxf is None or path is None:
        return None
    asset_path = Path(path)
    if not asset_path.exists():
        return None
    try:
        document = ezdxf.readfile(asset_path)
    except Exception:
        return None

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    entity_count = 0
    polylines: list[DXFPolyline] = []

    for entity in document.modelspace():
        points, closed = _entity_points(entity)
        if not points:
            continue
        entity_count += 1
        polylines.append(DXFPolyline(points=tuple(points), closed=closed))
        for x, y in points:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

    if min_x == float("inf"):
        center = (0.0, 0.0)
        extents = (4.0, 2.0, 2.5)
    else:
        center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
        extents = (
            max(max_x - min_x, 1.0),
            max(max_y - min_y, 1.0),
            2.5,
        )

    return DXFAssetSummary(
        path=str(asset_path),
        entity_count=entity_count,
        extents=extents,
        center=center,
        polylines=tuple(polylines),
    )


def _entity_points(entity) -> tuple[list[Point2D], bool]:
    dxftype = entity.dxftype()
    if dxftype == "LINE":
        return (
            [
                (float(entity.dxf.start.x), float(entity.dxf.start.y)),
                (float(entity.dxf.end.x), float(entity.dxf.end.y)),
            ],
            False,
        )
    if dxftype == "LWPOLYLINE":
        points = [(float(point[0]), float(point[1])) for point in entity.get_points()]
        return points, bool(entity.closed)
    if dxftype == "POLYLINE":
        points = [(float(vertex.dxf.location.x), float(vertex.dxf.location.y)) for vertex in entity.vertices]
        return points, bool(entity.is_closed)
    if dxftype == "CIRCLE":
        center = (float(entity.dxf.center.x), float(entity.dxf.center.y))
        radius = float(entity.dxf.radius)
        return _arc_points(center, radius, 0.0, 360.0), True
    if dxftype == "ARC":
        center = (float(entity.dxf.center.x), float(entity.dxf.center.y))
        radius = float(entity.dxf.radius)
        return _arc_points(center, radius, float(entity.dxf.start_angle), float(entity.dxf.end_angle)), False
    return [], False


def _arc_points(center: Point2D, radius: float, start_angle_degrees: float, end_angle_degrees: float) -> list[Point2D]:
    start = math.radians(start_angle_degrees)
    end = math.radians(end_angle_degrees)
    if end <= start:
        end += math.tau
    span = end - start
    steps = max(12, int((span / math.tau) * 48))
    points: list[Point2D] = []
    for index in range(steps + 1):
        angle = start + (span * (index / steps))
        points.append(
            (
                center[0] + (math.cos(angle) * radius),
                center[1] + (math.sin(angle) * radius),
            )
        )
    return points
