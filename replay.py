from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JsonValue = str | int | float | bool | None


@dataclass(frozen=True)
class ReplayFrame:
    time: float
    stages: dict[str, dict[str, JsonValue]] = field(default_factory=dict)
    transfers: dict[str, dict[str, JsonValue]] = field(default_factory=dict)
    workers: dict[str, dict[str, JsonValue]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recordType": "frame",
            "time": self.time,
            "stages": self.stages,
            "transfers": self.transfers,
            "workers": self.workers,
        }


@dataclass(frozen=True)
class ReplayLog:
    scenario_id: str
    policy: str
    horizon: float
    horizon_unit: str
    frames: tuple[ReplayFrame, ...]
    source_path: Path | None = None

    def frame_count(self) -> int:
        return len(self.frames)

    def frame_at_index(self, index: int) -> ReplayFrame:
        if not self.frames:
            raise IndexError("Replay log has no frames.")
        bounded_index = max(0, min(index, len(self.frames) - 1))
        return self.frames[bounded_index]

    def final_frame(self) -> ReplayFrame:
        return self.frame_at_index(len(self.frames) - 1)

    def to_meta_dict(self) -> dict[str, Any]:
        return {
            "recordType": "meta",
            "schemaVersion": 1,
            "scenarioId": self.scenario_id,
            "policy": self.policy,
            "horizon": self.horizon,
            "horizonUnit": self.horizon_unit,
            "frameCount": len(self.frames),
        }


def write_replay_jsonl(path: str | Path, replay_log: ReplayLog) -> Path:
    replay_path = Path(path)
    with replay_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(replay_log.to_meta_dict(), sort_keys=True) + "\n")
        for frame in replay_log.frames:
            handle.write(json.dumps(frame.to_dict(), sort_keys=True) + "\n")
    return replay_path


def load_replay_jsonl(path: str | Path) -> ReplayLog:
    replay_path = Path(path)
    meta: dict[str, Any] | None = None
    frames: list[ReplayFrame] = []
    for line in replay_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        record_type = payload.get("recordType")
        if record_type == "meta":
            meta = payload
        elif record_type == "frame":
            frames.append(
                ReplayFrame(
                    time=float(payload.get("time", 0.0)),
                    stages=dict(payload.get("stages", {})),
                    transfers=dict(payload.get("transfers", {})),
                    workers=dict(payload.get("workers", {})),
                )
            )
    if meta is None:
        raise ValueError(f"Replay file {replay_path} is missing a metadata record.")
    return ReplayLog(
        scenario_id=str(meta.get("scenarioId", "unknown")),
        policy=str(meta.get("policy", "unknown")),
        horizon=float(meta.get("horizon", 0.0)),
        horizon_unit=str(meta.get("horizonUnit", "minute")),
        frames=tuple(frames),
        source_path=replay_path,
    )
