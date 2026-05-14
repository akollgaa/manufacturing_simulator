from __future__ import annotations

import unittest
from pathlib import Path

from mfg_logic import load_factory_file, load_factory_text


FIXTURE_XML = Path(__file__).parent / "fixtures" / "sample_factory.xml"


class LogicParserTests(unittest.TestCase):
    def test_valid_fixture_parses_into_logical_and_visual_models(self) -> None:
        result = load_factory_file(FIXTURE_XML, registry_ids=["CAD_ASSY_PRESS_01"])

        self.assertTrue(result.is_valid)
        self.assertEqual(result.factory.logical_model.simulation.horizon_duration, 120)
        self.assertIn("M_ASSY", result.factory.logical_model.stages)
        self.assertEqual(len(result.factory.visual_model.layout.placements), 3)

    def test_invalid_transfer_reference_surfaces_error(self) -> None:
        invalid_xml = FIXTURE_XML.read_text(encoding="utf-8").replace('to="SHIP"', 'to="DOES_NOT_EXIST"', 1)
        result = load_factory_text(invalid_xml)

        self.assertFalse(result.is_valid)
        self.assertTrue(any(message.code == "transfer.to_stage" for message in result.errors))

    def test_missing_registry_entry_is_warning_not_error(self) -> None:
        result = load_factory_file(FIXTURE_XML)

        self.assertTrue(result.is_valid)
        self.assertTrue(any(message.code == "layout.machine_mesh_ref" for message in result.warnings))


if __name__ == "__main__":
    unittest.main()

