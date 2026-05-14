from __future__ import annotations

import unittest
from pathlib import Path

from mfg_des import StudyConfig, run_study
from mfg_logic import load_factory_file
from mfg_studio.results import build_study_display


FIXTURE_XML = Path(__file__).parent / "fixtures" / "sample_factory.xml"


class StudyDisplayTests(unittest.TestCase):
    def test_build_study_display_creates_structured_rows(self) -> None:
        parse_result = load_factory_file(FIXTURE_XML)
        study_result = run_study(parse_result, StudyConfig(include_distribution=True))
        display = build_study_display(study_result)

        self.assertEqual(display.horizon_label, "120 minute")
        self.assertEqual(len(display.scenario_rows), 3)
        self.assertEqual(display.scenario_rows[1].label, "Likely")
        self.assertGreaterEqual(len(display.distribution_rows), 1)
        self.assertGreaterEqual(len(display.stage_rows), 1)
        self.assertGreaterEqual(len(display.worker_rows), 1)
        self.assertEqual(display.stage_rows[0].label, "Assembler")
        self.assertIn("FINISHED_WIDGET", display.output_target_label)


if __name__ == "__main__":
    unittest.main()
