from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from mfg_logic.models import FactoryModel, GenericVisual, Placement, Stage, ValidationMessage
from mfg_logic.replay import ReplayFrame

from .dxf import DXFAssetSummary, inspect_dxf_asset

Point3D = tuple[float, float, float]


@dataclass(frozen=True)
class ScenePolyline:
    points: tuple[Point3D, ...]
    closed: bool = False
    style: str = "wire"


@dataclass(frozen=True)
class SceneNode:
    node_id: str
    kind: str
    source: str
    label: str
    position: Point3D
    extents: tuple[float, float, float]
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    polylines: tuple[ScenePolyline, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    overlay: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ViewportScene:
    nodes: tuple[SceneNode, ...]
    messages: tuple[ValidationMessage, ...] = ()
    world_bounds: tuple[float, float, float, float, float, float] = (-10.0, 10.0, -10.0, 10.0, 0.0, 5.0)
    overlay_label: str | None = None


def _registry_entry_path(entry: Any) -> str | None:
    if entry is None:
        return None
    if isinstance(entry, Mapping):
        path = entry.get("path")
        return str(path) if path else None
    path = getattr(entry, "path", None)
    return str(path) if path else None


def _registry_entry_name(entry: Any, fallback: str) -> str:
    if entry is None:
        return fallback
    if isinstance(entry, Mapping):
        return str(entry.get("display_name") or entry.get("displayName") or fallback)
    return str(getattr(entry, "display_name", None) or getattr(entry, "displayName", None) or fallback)


def build_scene(
    factory: FactoryModel,
    registry: Mapping[str, Any] | None = None,
    replay_frame: ReplayFrame | None = None,
    replay_label: str | None = None,
) -> ViewportScene:
    registry = registry or {}
    messages: list[ValidationMessage] = []
    nodes: list[SceneNode] = []
    logical = factory.logical_model
    placements_by_stage = {placement.stage_ref: placement for placement in factory.visual_model.layout.placements}

    for stage_id, stage in logical.stages.items():
        placement = placements_by_stage.get(stage_id, Placement(stage_ref=stage_id))
        nodes.append(_build_stage_node(stage, placement, registry, messages, replay_frame))

    for generic_visual in factory.visual_model.layout.generic_visuals:
        nodes.append(_generic_scene_node(generic_visual, placements_by_stage, replay_frame))

    return ViewportScene(
        nodes=tuple(nodes),
        messages=tuple(messages),
        world_bounds=_world_bounds(nodes),
        overlay_label=replay_label,
    )


def _build_stage_node(
    stage: Stage,
    placement: Placement,
    registry: Mapping[str, Any],
    messages: list[ValidationMessage],
    replay_frame: ReplayFrame | None,
) -> SceneNode:
    metadata = _stage_metadata(stage, placement)
    overlay = _stage_overlay(stage.stage_id, replay_frame)
    if stage.kind == "machine":
        registry_entry = registry.get(placement.machine_mesh_ref or "")
        asset_path = _registry_entry_path(registry_entry)
        dxf_summary = inspect_dxf_asset(asset_path) if placement.machine_mesh_ref and asset_path else None
        if placement.machine_mesh_ref and asset_path and Path(asset_path).exists() and dxf_summary is not None:
            metadata["machineMeshRef"] = placement.machine_mesh_ref
            metadata["assetPath"] = asset_path
            metadata["entityCount"] = str(dxf_summary.entity_count)
            return SceneNode(
                node_id=stage.stage_id,
                kind=stage.kind,
                source="dxf",
                label=_registry_entry_name(registry_entry, placement.machine_mesh_ref),
                position=placement.translate,
                rotation=placement.rotate,
                extents=dxf_summary.extents,
                polylines=_dxf_polylines(dxf_summary, placement),
                metadata=metadata,
                overlay=overlay,
            )

        if placement.machine_mesh_ref:
            metadata["machineMeshRef"] = placement.machine_mesh_ref
            messages.append(
                ValidationMessage(
                    "warning",
                    "viewport.placeholder",
                    f"Machine '{stage.stage_id}' is using placeholder geometry because asset '{placement.machine_mesh_ref}' is unavailable.",
                    f"Layout/Placement[{stage.stage_id}]",
                )
            )
        return SceneNode(
            node_id=stage.stage_id,
            kind=stage.kind,
            source="placeholder",
            label=stage.name or stage.stage_id,
            position=placement.translate,
            rotation=placement.rotate,
            extents=placement.extents,
            polylines=_box_polylines(placement.translate, placement.extents, placement.rotate),
            metadata=metadata,
            overlay=overlay,
        )

    extents = placement.extents
    if stage.kind in {"buffer", "queue"}:
        polylines = _bin_polylines(placement.translate, extents, placement.rotate)
    else:
        polylines = _slab_polylines(placement.translate, extents, placement.rotate)
    return SceneNode(
        node_id=stage.stage_id,
        kind=stage.kind,
        source="generic",
        label=stage.name or stage.stage_id,
        position=placement.translate,
        rotation=placement.rotate,
        extents=extents,
        polylines=polylines,
        metadata=metadata,
        overlay=overlay,
    )


def _generic_scene_node(
    generic_visual: GenericVisual,
    placements_by_stage: Mapping[str, Placement],
    replay_frame: ReplayFrame | None,
) -> SceneNode:
    metadata = {key: str(value) for key, value in generic_visual.params.items()}
    if generic_visual.transfer_ref:
        metadata["transferRef"] = generic_visual.transfer_ref
    if generic_visual.from_stage_ref:
        metadata["fromStageRef"] = generic_visual.from_stage_ref
    if generic_visual.to_stage_ref:
        metadata["toStageRef"] = generic_visual.to_stage_ref

    from_stage = generic_visual.from_stage_ref or generic_visual.stage_ref or ""
    to_stage = generic_visual.to_stage_ref or generic_visual.stage_ref or ""
    from_position = placements_by_stage.get(from_stage, Placement(stage_ref=from_stage)).translate
    to_position = placements_by_stage.get(to_stage, Placement(stage_ref=to_stage)).translate

    if generic_visual.primitive == "conveyor":
        polylines = _conveyor_polylines(from_position, to_position)
        extents = (
            max(abs(to_position[0] - from_position[0]), 1.0),
            max(abs(to_position[1] - from_position[1]), 1.0),
            0.6,
        )
        position = (
            (from_position[0] + to_position[0]) / 2.0,
            (from_position[1] + to_position[1]) / 2.0,
            max(from_position[2], to_position[2]) + 0.2,
        )
    elif generic_visual.primitive == "human":
        position = from_position
        extents = (0.8, 0.8, 1.8)
        polylines = _human_polylines(position)
    else:
        position = from_position
        extents = (1.0, 1.0, 1.0)
        polylines = _slab_polylines(position, extents, (0.0, 0.0, 0.0))

    return SceneNode(
        node_id=generic_visual.visual_id,
        kind=generic_visual.primitive,
        source="generic",
        label=generic_visual.visual_id,
        position=position,
        rotation=(0.0, 0.0, 0.0),
        extents=extents,
        polylines=polylines,
        metadata=metadata,
        overlay=_generic_overlay(generic_visual, replay_frame),
    )


def _stage_metadata(stage: Stage, placement: Placement) -> dict[str, str]:
    metadata = {
        "id": stage.stage_id,
        "kind": stage.kind,
        "lineId": stage.line_id or "",
        "capacity": str(stage.capacity),
        "translate": _format_triplet(placement.translate),
    }
    if stage.name:
        metadata["name"] = stage.name
    if stage.operation is not None:
        metadata["serviceTime"] = stage.operation.service_time.distribution
        if stage.operation.inputs:
            metadata["inputs"] = ", ".join(
                f"{item.product_ref} x{_format_number(item.quantity)}" for item in stage.operation.inputs
            )
        if stage.operation.outputs:
            metadata["outputs"] = ", ".join(
                f"{item.product_ref} x{_format_number(item.quantity)}" for item in stage.operation.outputs
            )
    if stage.workers_required:
        metadata["workers"] = ", ".join(f"{item.pool_ref} x{item.count}" for item in stage.workers_required)
    if stage.failures:
        metadata["failures"] = ", ".join(f"{item.failure_type}@{item.probability:g}" for item in stage.failures)
    return metadata


def _stage_overlay(stage_id: str, replay_frame: ReplayFrame | None) -> dict[str, str]:
    if replay_frame is None:
        return {}
    state = replay_frame.stages.get(stage_id)
    if not state:
        return {}
    active_jobs = int(state.get("activeJobs", 0) or 0)
    inventory = float(state.get("inventory", 0.0) or 0.0)
    if active_jobs > 0:
        status = "busy"
    elif inventory > 0:
        status = "queued"
    else:
        status = "idle"
    return {
        "status": status,
        "time": _format_number(replay_frame.time),
        "activeJobs": str(active_jobs),
        "inventory": _format_number(inventory),
        "completedJobs": str(int(state.get("completedJobs", 0) or 0)),
        "startedJobs": str(int(state.get("startedJobs", 0) or 0)),
    }


def _generic_overlay(generic_visual: GenericVisual, replay_frame: ReplayFrame | None) -> dict[str, str]:
    if replay_frame is None or not generic_visual.transfer_ref:
        return {}
    state = replay_frame.transfers.get(generic_visual.transfer_ref)
    if not state:
        return {}
    inflight = float(state.get("inflight", 0.0) or 0.0)
    moved_quantity = float(state.get("movedQuantity", 0.0) or 0.0)
    return {
        "status": "moving" if inflight > 0 else "idle",
        "time": _format_number(replay_frame.time),
        "inflight": _format_number(inflight),
        "movedQuantity": _format_number(moved_quantity),
    }


def _dxf_polylines(summary: DXFAssetSummary, placement: Placement) -> tuple[ScenePolyline, ...]:
    transformed: list[ScenePolyline] = []
    for polyline in summary.polylines:
        points = tuple(
            _apply_transform(
                (
                    point[0] - summary.center[0],
                    point[1] - summary.center[1],
                    0.0,
                ),
                placement.translate,
                placement.rotate,
                placement.scale,
            )
            for point in polyline.points
        )
        transformed.append(ScenePolyline(points=points, closed=polyline.closed, style="dxf"))
    return tuple(transformed)


def _box_polylines(position: Point3D, extents: tuple[float, float, float], rotation: tuple[float, float, float]) -> tuple[ScenePolyline, ...]:
    x_extent, y_extent, z_extent = extents
    half_x = x_extent / 2.0
    half_y = y_extent / 2.0
    base = [
        (-half_x, -half_y, 0.0),
        (half_x, -half_y, 0.0),
        (half_x, half_y, 0.0),
        (-half_x, half_y, 0.0),
    ]
    top = [(x, y, z_extent) for x, y, _ in base]
    polylines = [
        ScenePolyline(points=tuple(_apply_transform(point, position, rotation) for point in base), closed=True),
        ScenePolyline(points=tuple(_apply_transform(point, position, rotation) for point in top), closed=True),
    ]
    for lower, upper in zip(base, top):
        polylines.append(
            ScenePolyline(
                points=(
                    _apply_transform(lower, position, rotation),
                    _apply_transform(upper, position, rotation),
                ),
                closed=False,
            )
        )
    return tuple(polylines)


def _bin_polylines(position: Point3D, extents: tuple[float, float, float], rotation: tuple[float, float, float]) -> tuple[ScenePolyline, ...]:
    box = list(_box_polylines(position, extents, rotation))
    open_top = ScenePolyline(points=box[1].points, closed=True, style="highlight")
    return tuple(box + [open_top])


def _slab_polylines(position: Point3D, extents: tuple[float, float, float], rotation: tuple[float, float, float]) -> tuple[ScenePolyline, ...]:
    x_extent, y_extent, _ = extents
    half_x = x_extent / 2.0
    half_y = y_extent / 2.0
    points = [
        (-half_x, -half_y, 0.0),
        (half_x, -half_y, 0.0),
        (half_x, half_y, 0.0),
        (-half_x, half_y, 0.0),
    ]
    return (
        ScenePolyline(points=tuple(_apply_transform(point, position, rotation) for point in points), closed=True),
    )


def _conveyor_polylines(from_position: Point3D, to_position: Point3D) -> tuple[ScenePolyline, ...]:
    lift = 0.25
    path = (
        (from_position[0], from_position[1], from_position[2] + lift),
        (to_position[0], to_position[1], to_position[2] + lift),
    )
    arrow_mid = (
        (path[0][0] * 0.4) + (path[1][0] * 0.6),
        (path[0][1] * 0.4) + (path[1][1] * 0.6),
        (path[0][2] * 0.4) + (path[1][2] * 0.6),
    )
    arrow_delta = (to_position[0] - from_position[0], to_position[1] - from_position[1])
    length = math.hypot(*arrow_delta) or 1.0
    perp = (-arrow_delta[1] / length, arrow_delta[0] / length)
    arrow_a = (arrow_mid[0] - (arrow_delta[0] * 0.08) + (perp[0] * 0.25), arrow_mid[1] - (arrow_delta[1] * 0.08) + (perp[1] * 0.25), arrow_mid[2])
    arrow_b = (arrow_mid[0] - (arrow_delta[0] * 0.08) - (perp[0] * 0.25), arrow_mid[1] - (arrow_delta[1] * 0.08) - (perp[1] * 0.25), arrow_mid[2])
    return (
        ScenePolyline(points=path, closed=False, style="conveyor"),
        ScenePolyline(points=(arrow_a, path[1], arrow_b), closed=False, style="conveyor"),
    )


def _human_polylines(position: Point3D) -> tuple[ScenePolyline, ...]:
    x, y, z = position
    head = []
    for index in range(10):
        angle = (index / 9.0) * math.tau
        head.append((x + (math.cos(angle) * 0.2), y + (math.sin(angle) * 0.2), z + 1.55))
    return (
        ScenePolyline(points=tuple(head), closed=True, style="human"),
        ScenePolyline(points=((x, y, z + 1.35), (x, y, z + 0.65)), style="human"),
        ScenePolyline(points=((x, y, z + 1.0), (x - 0.3, y, z + 0.8), (x + 0.3, y, z + 0.8)), style="human"),
        ScenePolyline(points=((x, y, z + 0.65), (x - 0.25, y, z), (x + 0.25, y, z)), style="human"),
    )


def _apply_transform(
    local_point: Point3D,
    translate: Point3D,
    rotation: tuple[float, float, float],
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> Point3D:
    x = local_point[0] * scale[0]
    y = local_point[1] * scale[1]
    z = local_point[2] * scale[2]
    yaw = math.radians(rotation[2])
    rotated_x = (x * math.cos(yaw)) - (y * math.sin(yaw))
    rotated_y = (x * math.sin(yaw)) + (y * math.cos(yaw))
    return (
        translate[0] + rotated_x,
        translate[1] + rotated_y,
        translate[2] + z,
    )


def _world_bounds(nodes: list[SceneNode]) -> tuple[float, float, float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for node in nodes:
        for polyline in node.polylines:
            for x, y, z in polyline.points:
                xs.append(x)
                ys.append(y)
                zs.append(z)
    if not xs:
        return (-10.0, 10.0, -10.0, 10.0, 0.0, 5.0)
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _format_triplet(value: Point3D) -> str:
    return ", ".join(_format_number(component) for component in value)
