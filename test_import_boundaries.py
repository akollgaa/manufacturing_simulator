from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _import_targets(file_path: Path) -> set[str]:
    module = ast.parse(file_path.read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


class ImportBoundaryTests(unittest.TestCase):
    def test_mfg_des_does_not_import_qt_or_viewport(self) -> None:
        for file_path in (ROOT / "mfg_des").glob("*.py"):
            targets = _import_targets(file_path)
            self.assertFalse(any(target.startswith("PySide6") for target in targets), file_path.name)
            self.assertFalse(any(target.startswith("mfg_viewport") for target in targets), file_path.name)

    def test_mfg_viewport_does_not_import_mfg_des(self) -> None:
        for file_path in (ROOT / "mfg_viewport").glob("*.py"):
            targets = _import_targets(file_path)
            self.assertFalse(any(target.startswith("mfg_des") for target in targets), file_path.name)


if __name__ == "__main__":
    unittest.main()

