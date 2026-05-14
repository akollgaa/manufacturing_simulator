from __future__ import annotations

import unittest
from pathlib import Path

from mfg_des import StudyConfig, run_study
from mfg_logic import load_factory_file


FIXTURE_XML = Path(__file__).parent / "fixtures" / "sample_factory.xml"


class EngineMetricTests(unittest.TestCase):
    def test_run_study_emits_stage_worker_and_transfer_metrics(self) -> None:
        parse_result = load_factory_file(FIXTURE_XML)
        study_result = run_study(parse_result, StudyConfig(include_distribution=True, include_metrics=True))

        likely = study_result.scenarios["likely"]
        self.assertIsNotNone(likely.metrics)

        stage_metrics = {metric.stage_id: metric for metric in likely.metrics.stages}
        worker_metrics = {metric.pool_id: metric for metric in likely.metrics.workers}
        transfer_metrics = {metric.transfer_id: metric for metric in likely.metrics.transfers}

        self.assertIn("M_ASSY", stage_metrics)
        self.assertGreater(stage_metrics["M_ASSY"].started_jobs, 0)
        self.assertGreater(stage_metrics["M_ASSY"].completed_jobs, 0)
        self.assertGreater(stage_metrics["M_ASSY"].busy_utilization, 0.8)
        self.assertGreater(stage_metrics["M_ASSY"].average_inventory, 0.0)

        self.assertIn("OP", worker_metrics)
        self.assertGreater(worker_metrics["OP"].busy_utilization, 0.8)
        self.assertGreaterEqual(worker_metrics["OP"].peak_busy, 1)

        self.assertIn("T2", transfer_metrics)
        self.assertGreater(transfer_metrics["T2"].moved_quantity, 0.0)


if __name__ == "__main__":
    unittest.main()
