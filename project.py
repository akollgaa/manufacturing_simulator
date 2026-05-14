from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AssetRegistryEntry:
    asset_id: str
    display_name: str
    path: str


@dataclass
class ProjectMetadata:
    assets: dict[str, AssetRegistryEntry] = field(default_factory=dict)

    def registry_ids(self) -> tuple[str, ...]:
        return tuple(self.assets)

    def as_scene_registry(self, document_path: str | Path | None = None) -> dict[str, dict[str, str]]:
        return {
            asset_id: {
                "asset_id": entry.asset_id,
                "display_name": entry.display_name,
                "path": _resolve_asset_path(document_path, entry.path),
            }
            for asset_id, entry in self.assets.items()
        }


def sidecar_path_for(document_path: str | Path) -> Path:
    path = Path(document_path)
    return path.with_suffix(path.suffix + ".mfgstudio.json")


def load_project_metadata(document_path: str | Path) -> ProjectMetadata:
    sidecar_path = sidecar_path_for(document_path)
    if not sidecar_path.exists():
        return ProjectMetadata()
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assets = {
        asset_id: AssetRegistryEntry(asset_id=asset_id, display_name=data["display_name"], path=data["path"])
        for asset_id, data in payload.get("assets", {}).items()
    }
    return ProjectMetadata(assets=assets)


def save_project_metadata(document_path: str | Path, metadata: ProjectMetadata) -> Path:
    sidecar_path = sidecar_path_for(document_path)
    payload = {
        "assets": {
            asset_id: {
                "display_name": entry.display_name,
                "path": entry.path,
            }
            for asset_id, entry in metadata.assets.items()
        }
    }
    sidecar_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sidecar_path


def upsert_asset(metadata: ProjectMetadata, asset_id: str, display_name: str, path: str) -> ProjectMetadata:
    next_assets = dict(metadata.assets)
    next_assets[asset_id] = AssetRegistryEntry(asset_id=asset_id, display_name=display_name, path=path)
    return ProjectMetadata(assets=next_assets)


def remove_asset(metadata: ProjectMetadata, asset_id: str) -> ProjectMetadata:
    next_assets = dict(metadata.assets)
    next_assets.pop(asset_id, None)
    return ProjectMetadata(assets=next_assets)


def _resolve_asset_path(document_path: str | Path | None, asset_path: str) -> str:
    candidate = Path(asset_path)
    if candidate.is_absolute() or document_path is None:
        return str(candidate)
    return str((Path(document_path).parent / candidate).resolve())
