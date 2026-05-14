from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

MessageSeverity = Literal["error", "warning", "info"]


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ValidationMessage:
    severity: MessageSeverity
    code: str
    message: str
    path: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass(frozen=True)
class SourceMetadata:
    path: Path | None = None
    description: str | None = None


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DistributionSpec:
    distribution: str = "fixed"
    parameters: dict[str, str] = field(default_factory=dict)

    def float_parameter(self, *names: str, default: float = 0.0) -> float:
        for name in names:
            if name in self.parameters:
                return _coerce_float(self.parameters[name], default)
        return default

    def nominal_value(self) -> float:
        if self.distribution == "triangular":
            return self.float_parameter("mode", default=self.float_parameter("mean", default=1.0))
        if self.distribution == "normal":
            return self.float_parameter("mean", "value", "seconds", "duration", default=1.0)
        if self.distribution == "lognormal":
            return self.float_parameter("mean", "median", "value", default=1.0)
        if self.distribution == "empirical":
            values = [float(value) for key, value in self.parameters.items() if key.startswith("value")]
            return sum(values) / len(values) if values else 1.0
        return self.float_parameter("value", "seconds", "duration", "mean", default=1.0)

    def pessimistic_value(self) -> float:
        if self.distribution == "triangular":
            return self.float_parameter("high", default=max(self.nominal_value(), 1.0))
        if self.distribution in {"normal", "lognormal"}:
            mean = self.float_parameter("mean", default=self.nominal_value())
            spread = abs(self.float_parameter("sd", "sigma", default=mean * 0.25))
            return max(mean + spread, 0.0)
        return max(self.nominal_value(), self.float_parameter("max", "high", default=self.nominal_value()))


@dataclass(frozen=True)
class InputRequirement:
    product_ref: str
    quantity: float = 1.0
    from_stages: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputProduct:
    product_ref: str
    quantity: float = 1.0
    quality: str = "good"


@dataclass(frozen=True)
class WorkersRequired:
    pool_ref: str
    count: int = 1
    during: str = "whole_cycle"


@dataclass(frozen=True)
class FailureMode:
    failure_type: str = "jam"
    timing: str = "on_cycle_start"
    probability: float = 0.0
    repair_time: DistributionSpec | None = None
    scrap_rate: float = 0.0


@dataclass(frozen=True)
class Operation:
    inputs: tuple[InputRequirement, ...] = ()
    outputs: tuple[OutputProduct, ...] = ()
    service_time: DistributionSpec = field(default_factory=DistributionSpec)


@dataclass(frozen=True)
class Stage:
    stage_id: str
    kind: str
    name: str | None = None
    line_id: str | None = None
    capacity: int = 1
    operation: Operation | None = None
    workers_required: tuple[WorkersRequired, ...] = ()
    failures: tuple[FailureMode, ...] = ()
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def is_machine(self) -> bool:
        return self.kind == "machine"


@dataclass(frozen=True)
class Transfer:
    transfer_id: str
    from_stage: str
    to_stage: str
    mode: str = "conveyor"
    capacity: float | None = None
    transit_time: DistributionSpec = field(default_factory=lambda: DistributionSpec(distribution="fixed", parameters={"value": "0"}))
    priority: int = 0
    requires_worker_pool: str | None = None
    requires_worker_count: int = 0
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerPool:
    pool_id: str
    size: int
    role: str | None = None
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    policy: str
    extensions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Replications:
    n: int = 1
    seed: int | None = None


@dataclass(frozen=True)
class OutputDefinition:
    sink_stage_ref: str
    product_ref: str | None = None
    quality: str = "good"


@dataclass(frozen=True)
class SimulationConfig:
    horizon_duration: float
    horizon_unit: str
    output_definition: OutputDefinition
    scenarios: tuple[Scenario, ...] = ()
    replications: Replications = field(default_factory=Replications)


@dataclass(frozen=True)
class ArrivalSource:
    stage_ref: str
    product_ref: str
    quantity: float
    arrival_id: str | None = None
    mode: str = "initial"
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Placement:
    stage_ref: str
    machine_mesh_ref: str | None = None
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    extents: tuple[float, float, float] = (4.0, 2.0, 2.5)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GenericVisual:
    visual_id: str
    primitive: str
    transfer_ref: str | None = None
    stage_ref: str | None = None
    from_stage_ref: str | None = None
    to_stage_ref: str | None = None
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Layout:
    placements: tuple[Placement, ...] = ()
    generic_visuals: tuple[GenericVisual, ...] = ()


@dataclass(frozen=True)
class LogicalModel:
    schema_version: int
    time_unit: str
    simulation: SimulationConfig
    products: dict[str, Product]
    line_stages: dict[str, tuple[str, ...]]
    stages: dict[str, Stage]
    transfers: dict[str, Transfer]
    workers: dict[str, WorkerPool]
    arrivals: tuple[ArrivalSource, ...] = ()
    controls: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisualModel:
    layout: Layout
    stage_names: dict[str, str]


@dataclass(frozen=True)
class FactoryModel:
    schema_version: int
    time_unit: str
    simulation: SimulationConfig
    logical_model: LogicalModel
    visual_model: VisualModel
    products: dict[str, Product]
    raw_extensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParseResult:
    factory: FactoryModel
    messages: tuple[ValidationMessage, ...]
    source: SourceMetadata = field(default_factory=SourceMetadata)
    xml_text: str = ""

    @property
    def is_valid(self) -> bool:
        return not any(message.is_error for message in self.messages)

    @property
    def errors(self) -> tuple[ValidationMessage, ...]:
        return tuple(message for message in self.messages if message.is_error)

    @property
    def warnings(self) -> tuple[ValidationMessage, ...]:
        return tuple(message for message in self.messages if message.severity == "warning")

