from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mfg_des import StudyConfig, run_study
from mfg_logic import load_factory_file, load_replay_jsonl, write_replay_jsonl
from mfg_studio.controller import StudioDocumentController


FIXTURE_XML = Path(__file__).parent / "fixtures" / "sample_factory.xml"


class ReplayTests(unittest.TestCase):
    def test_replay_round_trip_and_controller_overlay(self) -> None:
        parse_result = load_factory_file(FIXTURE_XML)
        study_result = run_study(
            parse_result,
            StudyConfig(capture_replay_scenarios=("likely",)),
        )
        replay = study_result.replays["likely"]

        with tempfile.TemporaryDirectory() as temp_dir:
            replay_path = Path(temp_dir) / "likely.jsonl"
            write_replay_jsonl(replay_path, replay)
            loaded = load_replay_jsonl(replay_path)

            self.assertEqual(loaded.scenario_id, "likely")
            self.assertGreater(loaded.frame_count(), 1)

            controller = StudioDocumentController()
            controller.open_document(FIXTURE_XML)
            controller.load_replay(replay_path)
            scene = controller.current_scene()
            machine_node = next(node for node in scene.nodes if node.node_id == "M_ASSY")
            conveyor_node = next(node for node in scene.nodes if node.node_id == "GV_T2")

            self.assertIsNotNone(scene.overlay_label)
            self.assertIn(machine_node.overlay.get("status"), {"busy", "queued", "idle"})
            self.assertIn("inflight", conveyor_node.overlay)


if __name__ == "__main__":
    unittest.main()
