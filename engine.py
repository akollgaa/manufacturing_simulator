from __future__ import annotations

import heapq
import json
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from mfg_logic.models import (
    DistributionSpec,
    FactoryModel,
    FailureMode,
    LogicalModel,
    ParseResult,
    Scenario,
    Stage,
    Transfer,
    WorkersRequired,
)
from mfg_logic.replay import ReplayFrame, ReplayLog


@dataclass(frozen=True)
class DistributionSummary:
    minimum: float
    maximum: float
    mean: float
    p05: float
    p50: float
    p95: float
    samples: tuple[float, ...] = ()

    def to_dict(self, include_samples: bool = False) -> dict[str, Any]:
        payload = {
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
            "p05": self.p05,
            "p50": self.p50,
            "p95": self.p95,
        }
        if include_samples:
            payload["samples"] = list(self.samples)
        return payload


@dataclass(frozen=True)
class StageMetric:
    stage_id: str
    name: str
    kind: str
    line_id: str | None
    started_jobs: int
    completed_jobs: int
    produced_quantity: float
    busy_utilization: float
    average_inventory: float
    peak_inventory: float
    ending_inventory: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "stageId": self.stage_id,
            "name": self.name,
            "kind": self.kind,
            "lineId": self.line_id,
            "startedJobs": self.started_jobs,
            "completedJobs": self.completed_jobs,
            "producedQuantity": self.produced_quantity,
            "busyUtilization": self.busy_utilization,
            "averageInventory": self.average_inventory,
            "peakInventory": self.peak_inventory,
            "endingInventory": self.ending_inventory,
        }


@dataclass(frozen=True)
class WorkerMetric:
    pool_id: str
    role: str | None
    size: int
    busy_utilization: float
    average_busy: float
    peak_busy: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "poolId": self.pool_id,
            "role": self.role,
            "size": self.size,
            "busyUtilization": self.busy_utilization,
            "averageBusy": self.average_busy,
            "peakBusy": self.peak_busy,
        }


@dataclass(frozen=True)
class TransferMetric:
    transfer_id: str
    mode: str
    from_stage: str
    to_stage: str
    moved_quantity: float
    average_inflight: float
    peak_inflight: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "transferId": self.transfer_id,
            "mode": self.mode,
            "fromStage": self.from_stage,
            "toStage": self.to_stage,
            "movedQuantity": self.moved_quantity,
            "averageInflight": self.average_inflight,
            "peakInflight": self.peak_inflight,
        }


@dataclass(frozen=True)
class ScenarioMetrics:
    event_count: int
    stages: tuple[StageMetric, ...]
    workers: tuple[WorkerMetric, ...]
    transfers: tuple[TransferMetric, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "eventCount": self.event_count,
            "stages": [stage.to_dict() for stage in self.stages],
            "workers": [worker.to_dict() for worker in self.workers],
            "transfers": [transfer.to_dict() for transfer in self.transfers],
        }


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    policy: str
    output: float
    replications: int
    seed: int | None = None
    distribution: DistributionSummary | None = None
    metrics: ScenarioMetrics | None = None

    def to_dict(self, include_distribution: bool = False, include_metrics: bool = True) -> dict[str, Any]:
        payload = {
            "scenarioId": self.scenario_id,
            "policy": self.policy,
            "output": self.output,
            "replications": self.replications,
            "seed": self.seed,
        }
        if include_distribution and self.distribution is not None:
            payload["distribution"] = self.distribution.to_dict()
        if include_metrics and self.metrics is not None:
            payload["metrics"] = self.metrics.to_dict()
        return payload


@dataclass(frozen=True)
class StudyConfig:
    include_distribution: bool = False
    include_metrics: bool = True
    capture_replay_scenarios: tuple[str, ...] = ()
    likely_replications: int | None = None
    seed: int | None = None


@dataclass(frozen=True)
class StudyResult:
    horizon: float
    horizon_unit: str
    output_definition: dict[str, str | None]
    scenarios: dict[str, ScenarioResult]
    replays: dict[str, ReplayLog] = field(default_factory=dict)

    def to_dict(self, include_distribution: bool = False, include_metrics: bool = True, include_replays: bool = False) -> dict[str, Any]:
        payload = {
            "horizon": self.horizon,
            "horizonUnit": self.horizon_unit,
            "outputDefinition": self.output_definition,
            "scenarios": {
                scenario_id: scenario.to_dict(include_distribution=include_distribution, include_metrics=include_metrics)
                for scenario_id, scenario in self.scenarios.items()
            },
        }
        if include_replays:
            payload["replays"] = {
                scenario_id: {
                    "scenarioId": replay.scenario_id,
                    "policy": replay.policy,
                    "horizon": replay.horizon,
                    "horizonUnit": replay.horizon_unit,
                    "frameCount": len(replay.frames),
                }
                for scenario_id, replay in self.replays.items()
            }
        return payload

    def to_json(self, include_distribution: bool = False, include_metrics: bool = True, include_replays: bool = False) -> str:
        return json.dumps(
            self.to_dict(
                include_distribution=include_distribution,
                include_metrics=include_metrics,
                include_replays=include_replays,
            ),
            indent=2,
            sort_keys=True,
        )


@dataclass
class _StageRuntime:
    active_jobs: int = 0
    inventory: dict[str, float] = field(default_factory=lambda: defaultdict(float))


@dataclass
class _TransferRuntime:
    inflight: float = 0.0


@dataclass
class _StageStats:
    started_jobs: int = 0
    completed_jobs: int = 0
    produced_quantity: float = 0.0
    active_job_area: float = 0.0
    inventory_area: float = 0.0
    peak_inventory: float = 0.0


@dataclass
class _TransferStats:
    moved_quantity: float = 0.0
    inflight_area: float = 0.0
    peak_inflight: float = 0.0


@dataclass
class _WorkerStats:
    busy_area: float = 0.0
    peak_busy: int = 0


@dataclass(frozen=True)
class _SimulationOutcome:
    output: float
    metrics: ScenarioMetrics
    replay: ReplayLog | None = None


class _EventSimulator:
    def __init__(self, logical: LogicalModel, scenario: Scenario, seed: int | None, capture_replay: bool = False):
        self.logical = logical
        self.scenario = scenario
        self.seed = seed
        self.capture_replay = capture_replay
        self.rng = random.Random(seed)
        self.event_counter = count()
        self.events: list[tuple[float, int, str, dict[str, Any]]] = []
        self.stage_state: dict[str, _StageRuntime] = {stage_id: _StageRuntime() for stage_id in logical.stages}
        self.transfer_state: dict[str, _TransferRuntime] = {transfer_id: _TransferRuntime() for transfer_id in logical.transfers}
        self.available_workers: dict[str, int] = {pool_id: pool.size for pool_id, pool in logical.workers.items()}
        self.stage_stats: dict[str, _StageStats] = {stage_id: _StageStats() for stage_id in logical.stages}
        self.transfer_stats: dict[str, _TransferStats] = {transfer_id: _TransferStats() for transfer_id in logical.transfers}
        self.worker_stats: dict[str, _WorkerStats] = {pool_id: _WorkerStats() for pool_id in logical.workers}
        self.sink_output = 0.0
        self.event_count = 0
        self.current_time = 0.0
        self.replay_frames: list[ReplayFrame] = []
        self.outbound_transfers: dict[str, list[Transfer]] = defaultdict(list)
        self.inbound_transfers: dict[str, list[Transfer]] = defaultdict(list)
        for transfer in logical.transfers.values():
            self.outbound_transfers[transfer.from_stage].append(transfer)
            self.inbound_transfers[transfer.to_stage].append(transfer)

    def run(self, horizon: float) -> _SimulationOutcome:
        self._seed_arrivals()
        for stage_id, stage in self.logical.stages.items():
            if stage.kind in {"buffer", "queue", "physical"}:
                self._try_dispatch_from_stage(stage_id, 0.0)
            if stage.is_machine:
                self._try_start_machine(stage_id, 0.0)
        self._capture_frame(0.0)

        while self.events:
            event_time, _, event_kind, payload = heapq.heappop(self.events)
            if event_time > horizon:
                break
            self._advance_time(event_time)
            self.event_count += 1
            if event_kind == "deliver_transfer":
                self._handle_transfer_delivery(event_time, payload)
            elif event_kind == "complete_machine":
                self._handle_machine_completion(event_time, payload)
            self._capture_frame(event_time)

        if self.current_time < horizon:
            self._advance_time(horizon)
        self._capture_frame(horizon)

        replay = self._build_replay(horizon)
        return _SimulationOutcome(output=self.sink_output, metrics=self._build_metrics(horizon), replay=replay)

    def _advance_time(self, next_time: float) -> None:
        delta = max(next_time - self.current_time, 0.0)
        if delta <= 0:
            self.current_time = max(self.current_time, next_time)
            return
        for stage_id, runtime in self.stage_state.items():
            stats = self.stage_stats[stage_id]
            stats.active_job_area += runtime.active_jobs * delta
            stats.inventory_area += _inventory_total(runtime.inventory) * delta
        for transfer_id, runtime in self.transfer_state.items():
            self.transfer_stats[transfer_id].inflight_area += runtime.inflight * delta
        for pool_id, pool in self.logical.workers.items():
            busy = max(pool.size - self.available_workers.get(pool_id, 0), 0)
            self.worker_stats[pool_id].busy_area += busy * delta
        self.current_time = next_time

    def _seed_arrivals(self) -> None:
        for arrival in self.logical.arrivals:
            if arrival.mode != "initial":
                continue
            stage_runtime = self.stage_state[arrival.stage_ref]
            stage_runtime.inventory[arrival.product_ref] += arrival.quantity
            self._update_stage_inventory_peak(arrival.stage_ref)

    def _push_event(self, event_time: float, event_kind: str, payload: dict[str, Any]) -> None:
        heapq.heappush(self.events, (event_time, next(self.event_counter), event_kind, payload))

    def _handle_transfer_delivery(self, event_time: float, payload: dict[str, Any]) -> None:
        transfer = self.logical.transfers[payload["transfer_id"]]
        runtime = self.transfer_state[transfer.transfer_id]
        runtime.inflight = max(0.0, runtime.inflight - payload["quantity"])
        self.transfer_stats[transfer.transfer_id].moved_quantity += payload["quantity"]
        stage_runtime = self.stage_state[transfer.to_stage]
        stage_runtime.inventory[payload["product_ref"]] += payload["quantity"]
        self._update_stage_inventory_peak(transfer.to_stage)
        if transfer.to_stage == self.logical.simulation.output_definition.sink_stage_ref:
            output_product = self.logical.simulation.output_definition.product_ref
            if output_product is None or output_product == payload["product_ref"]:
                self.sink_output += payload["quantity"]
        self._try_dispatch_from_stage(transfer.to_stage, event_time)
        self._try_start_machine(transfer.to_stage, event_time)
        self._try_dispatch_from_stage(transfer.from_stage, event_time)

    def _handle_machine_completion(self, event_time: float, payload: dict[str, Any]) -> None:
        stage = self.logical.stages[payload["stage_id"]]
        stage_runtime = self.stage_state[stage.stage_id]
        stage_stats = self.stage_stats[stage.stage_id]
        stage_runtime.active_jobs = max(0, stage_runtime.active_jobs - 1)
        stage_stats.completed_jobs += 1
        self._release_workers(payload["reserved_workers"])
        output_multiplier = 1.0 - float(payload.get("scrap_rate", 0.0))
        if stage.operation:
            for output in stage.operation.outputs:
                produced_quantity = output.quantity * output_multiplier
                if produced_quantity <= 0:
                    continue
                stage_runtime.inventory[output.product_ref] += produced_quantity
                stage_stats.produced_quantity += produced_quantity
        self._update_stage_inventory_peak(stage.stage_id)
        self._try_dispatch_from_stage(stage.stage_id, event_time)
        self._try_start_machine(stage.stage_id, event_time)

    def _try_dispatch_from_stage(self, stage_id: str, event_time: float) -> None:
        runtime = self.stage_state[stage_id]
        if not runtime.inventory:
            return
        for transfer in self.outbound_transfers.get(stage_id, []):
            candidate_products = self._candidate_products_for_transfer(transfer, runtime.inventory)
            if not candidate_products:
                continue
            capacity_remaining = math.inf
            if transfer.capacity is not None:
                capacity_remaining = max(0.0, transfer.capacity - self.transfer_state[transfer.transfer_id].inflight)
                if capacity_remaining <= 0:
                    continue
            for product_ref in candidate_products:
                available = runtime.inventory.get(product_ref, 0.0)
                if available <= 0:
                    continue
                quantity = available if math.isinf(capacity_remaining) else min(available, capacity_remaining)
                if quantity <= 0:
                    continue
                runtime.inventory[product_ref] -= quantity
                if runtime.inventory[product_ref] <= 1e-9:
                    runtime.inventory.pop(product_ref, None)
                self.transfer_state[transfer.transfer_id].inflight += quantity
                self.transfer_stats[transfer.transfer_id].peak_inflight = max(
                    self.transfer_stats[transfer.transfer_id].peak_inflight,
                    self.transfer_state[transfer.transfer_id].inflight,
                )
                self._push_event(
                    event_time + self._sample_distribution(transfer.transit_time),
                    "deliver_transfer",
                    {
                        "transfer_id": transfer.transfer_id,
                        "quantity": quantity,
                        "product_ref": product_ref,
                    },
                )
                if not math.isinf(capacity_remaining):
                    capacity_remaining -= quantity
                    if capacity_remaining <= 0:
                        break

    def _candidate_products_for_transfer(self, transfer: Transfer, inventory: dict[str, float]) -> list[str]:
        source = self.logical.stages.get(transfer.from_stage)
        if source and source.is_machine:
            if source.operation is None:
                return []
            return [output.product_ref for output in source.operation.outputs if inventory.get(output.product_ref, 0.0) > 0]

        destination = self.logical.stages.get(transfer.to_stage)
        if destination and destination.operation and destination.operation.inputs:
            accepted: list[str] = []
            for input_requirement in destination.operation.inputs:
                if input_requirement.from_stages and transfer.from_stage not in input_requirement.from_stages:
                    continue
                if inventory.get(input_requirement.product_ref, 0.0) > 0:
                    accepted.append(input_requirement.product_ref)
            if accepted:
                return accepted
        return [product_ref for product_ref, quantity in inventory.items() if quantity > 0]

    def _try_start_machine(self, stage_id: str, event_time: float) -> None:
        stage = self.logical.stages.get(stage_id)
        if stage is None or not stage.is_machine or stage.operation is None:
            return
        runtime = self.stage_state[stage_id]
        stage_stats = self.stage_stats[stage_id]
        capacity = max(stage.capacity, 1)
        while runtime.active_jobs < capacity and self._inputs_available(stage) and self._workers_available(stage.workers_required):
            reserved_workers = self._reserve_workers(stage.workers_required)
            if reserved_workers is None:
                return
            for input_requirement in stage.operation.inputs:
                runtime.inventory[input_requirement.product_ref] -= input_requirement.quantity
                if runtime.inventory[input_requirement.product_ref] <= 1e-9:
                    runtime.inventory.pop(input_requirement.product_ref, None)
            duration = self._sample_distribution(stage.operation.service_time)
            failure_delay, scrap_rate = self._failure_effects(stage.failures)
            runtime.active_jobs += 1
            stage_stats.started_jobs += 1
            self._push_event(
                event_time + duration + failure_delay,
                "complete_machine",
                {
                    "stage_id": stage_id,
                    "reserved_workers": reserved_workers,
                    "scrap_rate": scrap_rate,
                },
            )

    def _inputs_available(self, stage: Stage) -> bool:
        if stage.operation is None:
            return False
        inventory = self.stage_state[stage.stage_id].inventory
        return all(inventory.get(input_requirement.product_ref, 0.0) >= input_requirement.quantity for input_requirement in stage.operation.inputs)

    def _workers_available(self, requirements: tuple[WorkersRequired, ...]) -> bool:
        return all(self.available_workers.get(requirement.pool_ref, 0) >= requirement.count for requirement in requirements)

    def _reserve_workers(self, requirements: tuple[WorkersRequired, ...]) -> list[tuple[str, int]] | None:
        if not self._workers_available(requirements):
            return None
        reservations: list[tuple[str, int]] = []
        for requirement in requirements:
            self.available_workers[requirement.pool_ref] -= requirement.count
            busy = max(self.logical.workers[requirement.pool_ref].size - self.available_workers[requirement.pool_ref], 0)
            self.worker_stats[requirement.pool_ref].peak_busy = max(self.worker_stats[requirement.pool_ref].peak_busy, busy)
            reservations.append((requirement.pool_ref, requirement.count))
        return reservations

    def _release_workers(self, reservations: list[tuple[str, int]]) -> None:
        for pool_ref, count in reservations:
            self.available_workers[pool_ref] += count

    def _failure_effects(self, failures: tuple[FailureMode, ...]) -> tuple[float, float]:
        if not failures:
            return 0.0, 0.0
        if _scenario_mode(self.scenario) == "perfect":
            return 0.0, 0.0
        total_delay = 0.0
        total_scrap = 0.0
        for failure in failures:
            if _scenario_mode(self.scenario) == "worst":
                if failure.probability > 0:
                    total_delay += self._sample_distribution(failure.repair_time or DistributionSpec(parameters={"value": "0"}))
                    total_scrap = max(total_scrap, failure.scrap_rate)
                continue
            if self.rng.random() <= failure.probability:
                total_delay += self._sample_distribution(failure.repair_time or DistributionSpec(parameters={"value": "0"}))
                total_scrap = max(total_scrap, failure.scrap_rate)
        return total_delay, min(max(total_scrap, 0.0), 1.0)

    def _sample_distribution(self, distribution: DistributionSpec) -> float:
        mode = _scenario_mode(self.scenario)
        if mode == "perfect":
            return max(distribution.nominal_value(), 0.0)
        if mode == "worst":
            return max(distribution.pessimistic_value(), 0.0)
        if distribution.distribution == "fixed":
            return max(distribution.nominal_value(), 0.0)
        if distribution.distribution == "normal":
            mean = distribution.float_parameter("mean", "value", "seconds", "duration", default=distribution.nominal_value())
            sigma = distribution.float_parameter("sd", "sigma", default=max(mean * 0.1, 0.1))
            return max(self.rng.gauss(mean, sigma), 0.0)
        if distribution.distribution == "lognormal":
            mean = max(distribution.float_parameter("mean", default=distribution.nominal_value()), 0.1)
            sigma = max(distribution.float_parameter("sd", "sigma", default=0.25), 0.01)
            return max(self.rng.lognormvariate(math.log(mean), sigma), 0.0)
        if distribution.distribution == "triangular":
            low = distribution.float_parameter("low", default=max(distribution.nominal_value() * 0.5, 0.0))
            high = distribution.float_parameter("high", default=max(distribution.nominal_value() * 1.5, low))
            midpoint = distribution.float_parameter("mode", default=(low + high) / 2.0)
            return max(self.rng.triangular(low, high, midpoint), 0.0)
        return max(distribution.nominal_value(), 0.0)

    def _build_metrics(self, horizon: float) -> ScenarioMetrics:
        safe_horizon = max(horizon, 1e-9)
        stage_metrics = []
        for stage_id, stage in self.logical.stages.items():
            stats = self.stage_stats[stage_id]
            runtime = self.stage_state[stage_id]
            utilization_denominator = max(stage.capacity, 1) if stage.is_machine else 1
            busy_utilization = stats.active_job_area / (safe_horizon * utilization_denominator) if stage.is_machine else 0.0
            stage_metrics.append(
                StageMetric(
                    stage_id=stage_id,
                    name=stage.name or stage_id,
                    kind=stage.kind,
                    line_id=stage.line_id,
                    started_jobs=stats.started_jobs,
                    completed_jobs=stats.completed_jobs,
                    produced_quantity=stats.produced_quantity,
                    busy_utilization=min(max(busy_utilization, 0.0), 1.0),
                    average_inventory=stats.inventory_area / safe_horizon,
                    peak_inventory=stats.peak_inventory,
                    ending_inventory=_inventory_total(runtime.inventory),
                )
            )

        worker_metrics = []
        for pool_id, pool in self.logical.workers.items():
            stats = self.worker_stats[pool_id]
            denominator = max(pool.size, 1)
            worker_metrics.append(
                WorkerMetric(
                    pool_id=pool_id,
                    role=pool.role,
                    size=pool.size,
                    busy_utilization=stats.busy_area / (safe_horizon * denominator) if pool.size > 0 else 0.0,
                    average_busy=stats.busy_area / safe_horizon,
                    peak_busy=stats.peak_busy,
                )
            )

        transfer_metrics = []
        for transfer_id, transfer in self.logical.transfers.items():
            stats = self.transfer_stats[transfer_id]
            transfer_metrics.append(
                TransferMetric(
                    transfer_id=transfer_id,
                    mode=transfer.mode,
                    from_stage=transfer.from_stage,
                    to_stage=transfer.to_stage,
                    moved_quantity=stats.moved_quantity,
                    average_inflight=stats.inflight_area / safe_horizon,
                    peak_inflight=stats.peak_inflight,
                )
            )

        return ScenarioMetrics(
            event_count=self.event_count,
            stages=tuple(sorted(stage_metrics, key=lambda metric: metric.stage_id)),
            workers=tuple(sorted(worker_metrics, key=lambda metric: metric.pool_id)),
            transfers=tuple(sorted(transfer_metrics, key=lambda metric: metric.transfer_id)),
        )

    def _update_stage_inventory_peak(self, stage_id: str) -> None:
        self.stage_stats[stage_id].peak_inventory = max(
            self.stage_stats[stage_id].peak_inventory,
            _inventory_total(self.stage_state[stage_id].inventory),
        )

    def _capture_frame(self, time_value: float) -> None:
        if not self.capture_replay:
            return
        frame = ReplayFrame(
            time=time_value,
            stages={
                stage_id: {
                    "activeJobs": runtime.active_jobs,
                    "inventory": _inventory_total(runtime.inventory),
                    "completedJobs": self.stage_stats[stage_id].completed_jobs,
                    "startedJobs": self.stage_stats[stage_id].started_jobs,
                }
                for stage_id, runtime in self.stage_state.items()
            },
            transfers={
                transfer_id: {
                    "inflight": runtime.inflight,
                    "movedQuantity": self.transfer_stats[transfer_id].moved_quantity,
                }
                for transfer_id, runtime in self.transfer_state.items()
            },
            workers={
                pool_id: {
                    "busy": max(pool.size - self.available_workers.get(pool_id, 0), 0),
                    "available": self.available_workers.get(pool_id, 0),
                }
                for pool_id, pool in self.logical.workers.items()
            },
        )
        if self.replay_frames and math.isclose(self.replay_frames[-1].time, time_value, rel_tol=0.0, abs_tol=1e-9):
            self.replay_frames[-1] = frame
        else:
            self.replay_frames.append(frame)

    def _build_replay(self, horizon: float) -> ReplayLog | None:
        if not self.capture_replay:
            return None
        return ReplayLog(
            scenario_id=self.scenario.scenario_id,
            policy=self.scenario.policy,
            horizon=horizon,
            horizon_unit=self.logical.simulation.horizon_unit,
            frames=tuple(self.replay_frames),
        )


def run_study(model: FactoryModel | LogicalModel | ParseResult, study_config: StudyConfig | None = None) -> StudyResult:
    study_config = study_config or StudyConfig()
    logical = _extract_logical_model(model)
    simulation = logical.simulation
    scenarios = {scenario.scenario_id: scenario for scenario in simulation.scenarios if scenario.scenario_id}
    scenarios.setdefault("perfect", Scenario("perfect", "no_failures_nominal_time"))
    scenarios.setdefault("likely", Scenario("likely", "default_stochastic"))
    scenarios.setdefault("worst", Scenario("worst", "max_downtime_failures"))
    seed = study_config.seed if study_config.seed is not None else simulation.replications.seed
    likely_replications = study_config.likely_replications or simulation.replications.n or 1

    ordered_ids = ["perfect", "likely", "worst"]
    results: dict[str, ScenarioResult] = {}
    replays: dict[str, ReplayLog] = {}
    for index, scenario_id in enumerate(ordered_ids):
        scenario = scenarios[scenario_id]
        capture_replay = scenario_id in study_config.capture_replay_scenarios
        if scenario_id == "likely" and likely_replications > 1:
            outcomes = tuple(
                _EventSimulator(
                    logical,
                    scenario,
                    _replication_seed(seed, index, replication_index),
                    capture_replay=capture_replay,
                ).run(simulation.horizon_duration)
                for replication_index in range(likely_replications)
            )
            outputs = tuple(outcome.output for outcome in outcomes)
            distribution = _summarize_distribution(outputs)
            representative = _select_representative_outcome(outcomes, distribution.p50)
            if capture_replay and representative.replay is not None:
                replays[scenario_id] = representative.replay
            results[scenario_id] = ScenarioResult(
                scenario_id=scenario_id,
                policy=scenario.policy,
                output=distribution.p50,
                replications=likely_replications,
                seed=seed,
                distribution=distribution if study_config.include_distribution else None,
                metrics=representative.metrics if study_config.include_metrics else None,
            )
        else:
            outcome = _EventSimulator(
                logical,
                scenario,
                _replication_seed(seed, index, 0),
                capture_replay=capture_replay,
            ).run(simulation.horizon_duration)
            if capture_replay and outcome.replay is not None:
                replays[scenario_id] = outcome.replay
            results[scenario_id] = ScenarioResult(
                scenario_id=scenario_id,
                policy=scenario.policy,
                output=outcome.output,
                replications=1,
                seed=seed,
                metrics=outcome.metrics if study_config.include_metrics else None,
            )

    return StudyResult(
        horizon=simulation.horizon_duration,
        horizon_unit=simulation.horizon_unit,
        output_definition={
            "sinkStageRef": simulation.output_definition.sink_stage_ref,
            "productRef": simulation.output_definition.product_ref,
            "quality": simulation.output_definition.quality,
        },
        scenarios=results,
        replays=replays,
    )


def _extract_logical_model(model: FactoryModel | LogicalModel | ParseResult) -> LogicalModel:
    if isinstance(model, ParseResult):
        return model.factory.logical_model
    if isinstance(model, FactoryModel):
        return model.logical_model
    return model


def _scenario_mode(scenario: Scenario) -> str:
    scenario_name = f"{scenario.scenario_id} {scenario.policy}".lower()
    if "perfect" in scenario_name or "no_failures" in scenario_name:
        return "perfect"
    if "worst" in scenario_name or "max_downtime" in scenario_name:
        return "worst"
    return "likely"


def _replication_seed(base_seed: int | None, scenario_index: int, replication_index: int) -> int | None:
    if base_seed is None:
        return None
    return int(base_seed + (scenario_index * 100_003) + replication_index)


def _summarize_distribution(samples: tuple[float, ...]) -> DistributionSummary:
    ordered = tuple(sorted(samples))
    return DistributionSummary(
        minimum=ordered[0],
        maximum=ordered[-1],
        mean=statistics.mean(ordered),
        p05=_percentile(ordered, 0.05),
        p50=_percentile(ordered, 0.50),
        p95=_percentile(ordered, 0.95),
        samples=samples,
    )


def _select_representative_outcome(outcomes: tuple[_SimulationOutcome, ...], target_output: float) -> _SimulationOutcome:
    return min(outcomes, key=lambda outcome: (abs(outcome.output - target_output), -outcome.output))


def _percentile(values: tuple[float, ...], quantile: float) -> float:
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    weight = index - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _inventory_total(inventory: dict[str, float]) -> float:
    return sum(quantity for quantity in inventory.values() if quantity > 0)
