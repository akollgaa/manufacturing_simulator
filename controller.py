from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mfg_des import StudyConfig, StudyResult, run_study
from mfg_logic import ParseResult, ReplayLog, load_factory_file, load_factory_text, load_replay_jsonl, write_replay_jsonl
from mfg_viewport import ViewportScene, build_scene

from .project import ProjectMetadata, load_project_metadata, remove_asset, save_project_metadata, upsert_asset


@dataclass(frozen=True)
class ApplyResult:
    parse_result: ParseResult
    applied: bool
    used_last_valid_snapshot: bool


@dataclass
class StudioDocumentController:
    current_path: Path | None = None
    editor_text: str = ""
    project_metadata: ProjectMetadata = field(default_factory=ProjectMetadata)
    last_parse_result: ParseResult | None = None
    last_valid_result: ParseResult | None = None
    active_replay: ReplayLog | None = None
    active_replay_index: int = 0

    def open_document(self, document_path: str | Path) -> ApplyResult:
        self.current_path = Path(document_path)
        self.editor_text = self.current_path.read_text(encoding="utf-8")
        self.project_metadata = load_project_metadata(self.current_path)
        apply_result = self.apply_document()
        return apply_result

    def save_document(self, document_path: str | Path | None = None) -> Path:
        if document_path is not None:
            self.current_path = Path(document_path)
        if self.current_path is None:
            raise ValueError("A document path is required before saving.")
        self.current_path.write_text(self.editor_text, encoding="utf-8")
        return self.current_path

    def update_text(self, new_text: str) -> None:
        self.editor_text = new_text

    def apply_document(self) -> ApplyResult:
        parse_result = load_factory_text(
            self.editor_text,
            source_path=self.current_path,
            registry_ids=self.project_metadata.registry_ids(),
        )
        self.last_parse_result = parse_result
        applied = parse_result.is_valid
        if applied:
            self.last_valid_result = parse_result
        return ApplyResult(
            parse_result=parse_result,
            applied=applied,
            used_last_valid_snapshot=not applied and self.last_valid_result is not None,
        )

    def current_scene(self) -> ViewportScene:
        if self.last_valid_result is None:
            raise ValueError("No valid model is available for scene generation.")
        replay_frame = self.current_replay_frame()
        return build_scene(
            self.last_valid_result.factory,
            registry=self.project_metadata.as_scene_registry(self.current_path),
            replay_frame=replay_frame,
            replay_label=self.replay_label(),
        )

    def run_current_study(self, include_distribution: bool = False) -> StudyResult:
        if self.last_valid_result is None:
            raise ValueError("No valid model is available for simulation.")
        return run_study(self.last_valid_result, StudyConfig(include_distribution=include_distribution))

    def export_current_replay(self, replay_path: str | Path, scenario_id: str = "likely") -> Path:
        if self.last_valid_result is None:
            raise ValueError("No valid model is available for simulation.")
        study = run_study(
            self.last_valid_result,
            StudyConfig(
                include_distribution=False,
                include_metrics=False,
                capture_replay_scenarios=(scenario_id,),
            ),
        )
        replay = study.replays.get(scenario_id)
        if replay is None:
            raise ValueError(f"No replay was captured for scenario '{scenario_id}'.")
        return write_replay_jsonl(replay_path, replay)

    def load_replay(self, replay_path: str | Path) -> ReplayLog:
        replay = load_replay_jsonl(replay_path)
        self.active_replay = replay
        self.active_replay_index = max(replay.frame_count() - 1, 0)
        return replay

    def clear_replay(self) -> None:
        self.active_replay = None
        self.active_replay_index = 0

    def set_replay_index(self, index: int) -> None:
        if self.active_replay is None:
            self.active_replay_index = 0
            return
        self.active_replay_index = max(0, min(index, self.active_replay.frame_count() - 1))

    def current_replay_frame(self):
        if self.active_replay is None or self.active_replay.frame_count() == 0:
            return None
        return self.active_replay.frame_at_index(self.active_replay_index)

    def replay_label(self) -> str | None:
        if self.active_replay is None or self.active_replay.frame_count() == 0:
            return None
        frame = self.active_replay.frame_at_index(self.active_replay_index)
        return f"Replay {self.active_replay.scenario_id} @ {frame.time:.2f} {self.active_replay.horizon_unit}"

    def add_asset(self, asset_id: str, display_name: str, asset_path: str) -> None:
        self.project_metadata = upsert_asset(self.project_metadata, asset_id, display_name, asset_path)
        self._persist_project_metadata()

    def remove_asset(self, asset_id: str) -> None:
        self.project_metadata = remove_asset(self.project_metadata, asset_id)
        self._persist_project_metadata()

    def _persist_project_metadata(self) -> None:
        if self.current_path is None:
            return
        save_project_metadata(self.current_path, self.project_metadata)
