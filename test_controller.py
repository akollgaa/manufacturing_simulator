from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mfg_studio.controller import StudioDocumentController
from mfg_studio.project import sidecar_path_for


FIXTURE_XML = Path(__file__).parent / "fixtures" / "sample_factory.xml"


class StudioControllerTests(unittest.TestCase):
    def test_fixture_sidecar_resolves_relative_dxf_path(self) -> None:
        controller = StudioDocumentController()
        controller.open_document(FIXTURE_XML)

        scene = controller.current_scene()
        machine_node = next(node for node in scene.nodes if node.node_id == "M_ASSY")

        self.assertEqual(machine_node.source, "dxf")
        self.assertTrue(any("usable_asset.dxf" in value for value in machine_node.metadata.values()))

    def test_invalid_apply_keeps_last_valid_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document_path = Path(temp_dir) / "factory.xml"
            document_path.write_text(FIXTURE_XML.read_text(encoding="utf-8"), encoding="utf-8")
            controller = StudioDocumentController()
            first_apply = controller.open_document(document_path)

            self.assertTrue(first_apply.applied)
            self.assertIsNotNone(controller.last_valid_result)

            invalid_text = controller.editor_text.replace('to="SHIP"', 'to="UNKNOWN_STAGE"', 1)
            controller.update_text(invalid_text)
            second_apply = controller.apply_document()

            self.assertFalse(second_apply.applied)
            self.assertTrue(second_apply.used_last_valid_snapshot)
            self.assertEqual(
                controller.last_valid_result.factory.logical_model.transfers["T2"].to_stage,
                "SHIP",
            )

    def test_save_writes_current_text_even_when_it_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document_path = Path(temp_dir) / "factory.xml"
            document_path.write_text(FIXTURE_XML.read_text(encoding="utf-8"), encoding="utf-8")
            controller = StudioDocumentController()
            controller.open_document(document_path)

            invalid_text = "<Factory><Broken></Factory>"
            controller.update_text(invalid_text)
            controller.save_document()

            self.assertEqual(document_path.read_text(encoding="utf-8"), invalid_text)

    def test_asset_updates_persist_to_project_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document_path = Path(temp_dir) / "factory.xml"
            document_path.write_text(FIXTURE_XML.read_text(encoding="utf-8"), encoding="utf-8")
            controller = StudioDocumentController()
            controller.open_document(document_path)

            controller.add_asset("CAD_ASSY_PRESS_01", "Assembly Press", "/tmp/assembly_press.dxf")

            sidecar_path = sidecar_path_for(document_path)
            self.assertTrue(sidecar_path.exists())
            self.assertIn("CAD_ASSY_PRESS_01", sidecar_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
