from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from mfg_des import StudyConfig, run_study
from mfg_logic import load_factory_file, load_replay_jsonl


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_XML = ROOT / "tests" / "fixtures" / "sample_factory.xml"


class SimulatorCliParityTests(unittest.TestCase):
    def test_cli_matches_direct_run(self) -> None:
        parse_result = load_factory_file(FIXTURE_XML)
        direct = run_study(parse_result, StudyConfig(include_distribution=True)).to_dict(include_distribution=True)

        completed = subprocess.run(
            ["python3", "-m", "mfg_sim_run", str(FIXTURE_XML), "--distribution"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        from_cli = json.loads(completed.stdout)

        self.assertEqual(direct["horizon"], from_cli["horizon"])
        self.assertEqual(direct["outputDefinition"], from_cli["outputDefinition"])
        for scenario_id in ("perfect", "likely", "worst"):
            self.assertAlmostEqual(
                direct["scenarios"][scenario_id]["output"],
                from_cli["scenarios"][scenario_id]["output"],
            )
        self.assertIn("distribution", from_cli["scenarios"]["likely"])
        self.assertIn("metrics", from_cli["scenarios"]["likely"])
        stage_ids = {stage["stageId"] for stage in from_cli["scenarios"]["likely"]["metrics"]["stages"]}
        self.assertIn("M_ASSY", stage_ids)

    def test_cli_can_export_replay_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            replay_path = Path(temp_dir) / "likely.jsonl"
            subprocess.run(
                [
                    "python3",
                    "-m",
                    "mfg_sim_run",
                    str(FIXTURE_XML),
                    "--replay-out",
                    str(replay_path),
                    "--replay-scenario",
                    "likely",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            replay = load_replay_jsonl(replay_path)
            self.assertEqual(replay.scenario_id, "likely")
            self.assertGreater(replay.frame_count(), 1)


if __name__ == "__main__":
    unittest.main()
