from __future__ import annotations

import unittest
from pathlib import Path

from mfg_logic import load_factory_file
from mfg_viewport import build_scene


FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_XML = FIXTURE_DIR / "sample_factory.xml"
FIXTURE_DXF = FIXTURE_DIR / "usable_asset.dxf"


class ViewportSceneTests(unittest.TestCase):
    def test_missing_registry_entry_uses_placeholder_geometry(self) -> None:
        parse_result = load_factory_file(FIXTURE_XML)
        scene = build_scene(parse_result.factory, registry={})
        machine_node = next(node for node in scene.nodes if node.node_id == "M_ASSY")

        self.assertEqual(machine_node.source, "placeholder")
        self.assertTrue(any(message.code == "viewport.placeholder" for message in scene.messages))

    def test_present_registry_entry_uses_dxf_source(self) -> None:
        parse_result = load_factory_file(FIXTURE_XML, registry_ids=["CAD_ASSY_PRESS_01"])
        scene = build_scene(
            parse_result.factory,
            registry={
                "CAD_ASSY_PRESS_01": {
                    "display_name": "Assembly Press",
                    "path": str(FIXTURE_DXF),
                }
            },
        )
        machine_node = next(node for node in scene.nodes if node.node_id == "M_ASSY")

        self.assertEqual(machine_node.source, "dxf")
        self.assertGreater(len(machine_node.polylines), 2)
        self.assertEqual(machine_node.metadata["entityCount"], "4")
        self.assertFalse(any(message.code == "viewport.placeholder" for message in scene.messages))


if __name__ == "__main__":
    unittest.main()
