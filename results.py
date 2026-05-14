from __future__ import annotations

from dataclasses import dataclass

from mfg_des import DistributionSummary, ScenarioResult, StageMetric, StudyResult, WorkerMetric


@dataclass(frozen=True)
class ScenarioDisplayRow:
    scenario_id: str
    label: str
    output: str
    replications: str
    policy: str
    seed: str


@dataclass(frozen=True)
class MetricDisplayRow:
    label: str
    value: str


@dataclass(frozen=True)
class StudyDisplayModel:
    horizon_label: str
    output_target_label: str
    scenario_rows: tuple[ScenarioDisplayRow, ...]
    distribution_rows: tuple[MetricDisplayRow, ...]
    stage_rows: tuple["StageDisplayRow", ...]
    worker_rows: tuple["WorkerDisplayRow", ...]
    raw_json: str


@dataclass(frozen=True)
class StageDisplayRow:
    stage_id: str
    label: str
    kind: str
    output: str
    utilization: str
    average_inventory: str
    peak_inventory: str


@dataclass(frozen=True)
class WorkerDisplayRow:
    pool_id: str
    label: str
    size: str
    utilization: str
    peak_busy: str


def build_study_display(result: StudyResult) -> StudyDisplayModel:
    scenario_rows = tuple(_scenario_row(result.scenarios[scenario_id]) for scenario_id in ("perfect", "likely", "worst") if scenario_id in result.scenarios)
    likely = result.scenarios.get("likely")
    likely_distribution = likely.distribution if likely else None
    likely_metrics = likely.metrics if likely else None
    distribution_rows = _distribution_rows(likely_distribution)
    target = result.output_definition.get("productRef") or "any product"
    sink = result.output_definition.get("sinkStageRef") or "unknown sink"
    quality = result.output_definition.get("quality") or "good"
    return StudyDisplayModel(
        horizon_label=f"{_format_number(result.horizon)} {result.horizon_unit}",
        output_target_label=f"{target} -> {sink} ({quality})",
        scenario_rows=scenario_rows,
        distribution_rows=distribution_rows,
        stage_rows=_stage_rows(likely_metrics.stages if likely_metrics else ()),
        worker_rows=_worker_rows(likely_metrics.workers if likely_metrics else ()),
        raw_json=result.to_json(include_distribution=True),
    )


def _scenario_row(scenario: ScenarioResult) -> ScenarioDisplayRow:
    return ScenarioDisplayRow(
        scenario_id=scenario.scenario_id,
        label=scenario.scenario_id.replace("_", " ").title(),
        output=_format_number(scenario.output),
        replications=str(scenario.replications),
        policy=scenario.policy,
        seed=str(scenario.seed) if scenario.seed is not None else "random",
    )


def _distribution_rows(distribution: DistributionSummary | None) -> tuple[MetricDisplayRow, ...]:
    if distribution is None:
        return ()
    rows = [
        ("Minimum", distribution.minimum),
        ("P05", distribution.p05),
        ("Median", distribution.p50),
        ("Mean", distribution.mean),
        ("P95", distribution.p95),
        ("Maximum", distribution.maximum),
    ]
    return tuple(MetricDisplayRow(label=label, value=_format_number(value)) for label, value in rows)


def _stage_rows(stage_metrics: tuple[StageMetric, ...]) -> tuple[StageDisplayRow, ...]:
    ranked = sorted(
        (metric for metric in stage_metrics if metric.kind == "machine"),
        key=lambda metric: (-metric.busy_utilization, metric.stage_id),
    )
    return tuple(
        StageDisplayRow(
            stage_id=metric.stage_id,
            label=metric.name,
            kind=metric.kind,
            output=_format_number(metric.produced_quantity),
            utilization=_format_percent(metric.busy_utilization),
            average_inventory=_format_number(metric.average_inventory),
            peak_inventory=_format_number(metric.peak_inventory),
        )
        for metric in ranked
    )


def _worker_rows(worker_metrics: tuple[WorkerMetric, ...]) -> tuple[WorkerDisplayRow, ...]:
    ranked = sorted(worker_metrics, key=lambda metric: (-metric.busy_utilization, metric.pool_id))
    return tuple(
        WorkerDisplayRow(
            pool_id=metric.pool_id,
            label=metric.role or metric.pool_id,
            size=str(metric.size),
            utilization=_format_percent(metric.busy_utilization),
            peak_busy=str(metric.peak_busy),
        )
        for metric in ranked
    )


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"
