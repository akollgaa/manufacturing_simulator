from __future__ import annotations

from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from .models import (
    ArrivalSource,
    DistributionSpec,
    FactoryModel,
    FailureMode,
    GenericVisual,
    InputRequirement,
    Layout,
    LogicalModel,
    Operation,
    OutputDefinition,
    OutputProduct,
    ParseResult,
    Placement,
    Product,
    Replications,
    Scenario,
    SimulationConfig,
    SourceMetadata,
    Stage,
    Transfer,
    ValidationMessage,
    VisualModel,
    WorkerPool,
    WorkersRequired,
)
from .validation import validate_factory


def _message(severity: str, code: str, message: str, path: str | None = None) -> ValidationMessage:
    return ValidationMessage(severity=severity, code=code, message=message, path=path)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attrs(element: ET.Element) -> dict[str, str]:
    return {key: value for key, value in element.attrib.items()}


def _float_attr(element: ET.Element, *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in element.attrib:
            try:
                return float(element.attrib[name])
            except ValueError:
                return default
    return default


def _int_attr(element: ET.Element, *names: str, default: int = 0) -> int:
    for name in names:
        if name in element.attrib:
            try:
                return int(float(element.attrib[name]))
            except ValueError:
                return default
    return default


def _tuple_from_attrs(element: ET.Element, prefix: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
    compact = element.attrib.get(prefix)
    if compact:
        parts = [part.strip() for part in compact.replace(",", " ").split() if part.strip()]
        if len(parts) == 3:
            try:
                return float(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                return default
    return (
        _float_attr(element, f"{prefix}X", f"{prefix}x", default=default[0]),
        _float_attr(element, f"{prefix}Y", f"{prefix}y", default=default[1]),
        _float_attr(element, f"{prefix}Z", f"{prefix}z", default=default[2]),
    )


def _parse_distribution(element: ET.Element | None, default_value: float = 1.0) -> DistributionSpec:
    if element is None:
        return DistributionSpec(distribution="fixed", parameters={"value": str(default_value)})
    parameters: dict[str, str] = {}
    for key, value in element.attrib.items():
        if key != "distribution":
            parameters[key] = value
    for child in element:
        if _local_name(child.tag) == "Param":
            key = child.attrib.get("key")
            value = child.attrib.get("value")
            if key and value is not None:
                parameters[key] = value
    return DistributionSpec(distribution=element.attrib.get("distribution", "fixed"), parameters=parameters)


def _parse_operation(element: ET.Element) -> Operation:
    inputs: list[InputRequirement] = []
    outputs: list[OutputProduct] = []
    service_time = DistributionSpec(distribution="fixed", parameters={"value": "1"})
    for child in element:
        tag = _local_name(child.tag)
        if tag == "Input":
            from_stages = tuple(part.strip() for part in child.attrib.get("fromStages", "").split(",") if part.strip())
            inputs.append(
                InputRequirement(
                    product_ref=child.attrib.get("productRef", ""),
                    quantity=_float_attr(child, "quantity", default=1.0),
                    from_stages=from_stages,
                )
            )
        elif tag == "Output":
            outputs.append(
                OutputProduct(
                    product_ref=child.attrib.get("productRef", ""),
                    quantity=_float_attr(child, "quantity", default=1.0),
                    quality=child.attrib.get("quality", "good"),
                )
            )
        elif tag == "ServiceTime":
            service_time = _parse_distribution(child)
    return Operation(inputs=tuple(inputs), outputs=tuple(outputs), service_time=service_time)


def _parse_failures(parent: ET.Element | None) -> tuple[FailureMode, ...]:
    failures: list[FailureMode] = []
    if parent is None:
        return ()
    for failure_element in parent:
        if _local_name(failure_element.tag) != "Failure":
            continue
        repair_time = None
        for child in failure_element:
            if _local_name(child.tag) == "RepairTime":
                repair_time = _parse_distribution(child, default_value=0.0)
                break
        failures.append(
            FailureMode(
                failure_type=failure_element.attrib.get("type", "jam"),
                timing=failure_element.attrib.get("timing", "on_cycle_start"),
                probability=_float_attr(failure_element, "probability", default=0.0),
                repair_time=repair_time,
                scrap_rate=_float_attr(failure_element, "scrapRate", default=0.0),
            )
        )
    return tuple(failures)


def _parse_workers_required(stage_element: ET.Element) -> tuple[WorkersRequired, ...]:
    requirements: list[WorkersRequired] = []
    for child in stage_element:
        if _local_name(child.tag) == "WorkersRequired":
            requirements.append(
                WorkersRequired(
                    pool_ref=child.attrib.get("poolRef", ""),
                    count=_int_attr(child, "count", default=1),
                    during=child.attrib.get("during", "whole_cycle"),
                )
            )
    return tuple(requirements)


def load_factory_file(path: str | Path, registry_ids: Iterable[str] = ()) -> ParseResult:
    document_path = Path(path)
    text = document_path.read_text(encoding="utf-8")
    return load_factory_text(text, source_path=document_path, registry_ids=registry_ids)


def load_factory_text(text: str, source_path: str | Path | None = None, registry_ids: Iterable[str] = ()) -> ParseResult:
    source = SourceMetadata(path=Path(source_path) if source_path else None, description="XML document")
    messages: list[ValidationMessage] = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        factory = _empty_factory()
        messages.append(_message("error", "xml.parse", f"XML parsing failed: {exc}", "Factory"))
        return ParseResult(factory=factory, messages=tuple(messages), source=source, xml_text=text)

    if _local_name(root.tag) != "Factory":
        messages.append(_message("error", "xml.root", "Root element must be <Factory>.", root.tag))

    schema_version = _int_attr(root, "schemaVersion", default=1)
    time_unit = root.attrib.get("timeUnit", "minute")
    products: dict[str, Product] = {}
    line_stages: dict[str, tuple[str, ...]] = {}
    stages: dict[str, Stage] = {}
    transfers: dict[str, Transfer] = {}
    workers: dict[str, WorkerPool] = {}
    arrivals: list[ArrivalSource] = []
    controls: list[str] = []
    placements: list[Placement] = []
    generic_visuals: list[GenericVisual] = []
    raw_extensions: list[str] = []
    simulation = _default_simulation()

    for child in root:
        tag = _local_name(child.tag)
        if tag == "Simulation":
            simulation = _parse_simulation(child)
        elif tag == "Products":
            for product_element in child:
                if _local_name(product_element.tag) != "Product":
                    continue
                product_id = product_element.attrib.get("id", "")
                if not product_id:
                    messages.append(_message("error", "product.id", "Product is missing an id.", "Products/Product"))
                    continue
                if product_id in products:
                    messages.append(_message("error", "product.duplicate", f"Product id '{product_id}' is duplicated.", f"Products/Product[{product_id}]"))
                    continue
                product_attrs = _attrs(product_element)
                product_attrs.pop("id", None)
                product_attrs.pop("name", None)
                products[product_id] = Product(product_id=product_id, name=product_element.attrib.get("name"), attributes=product_attrs)
        elif tag == "Lines":
            for line_element in child:
                if _local_name(line_element.tag) != "Line":
                    continue
                line_id = line_element.attrib.get("id", "")
                line_stage_ids: list[str] = []
                stages_element = line_element.find("Stages")
                if stages_element is None:
                    messages.append(_message("warning", "line.stages", f"Line '{line_id or '<unknown>'}' has no <Stages> block.", f"Lines/Line[{line_id}]"))
                    continue
                for stage_element in stages_element:
                    if _local_name(stage_element.tag) != "Stage":
                        continue
                    stage_id = stage_element.attrib.get("id", "")
                    if not stage_id:
                        messages.append(_message("error", "stage.id", "Stage is missing an id.", f"Lines/Line[{line_id}]/Stage"))
                        continue
                    if stage_id in stages:
                        messages.append(_message("error", "stage.duplicate", f"Stage id '{stage_id}' is duplicated.", f"Stage[{stage_id}]"))
                        continue
                    operation = None
                    failures = ()
                    for stage_child in stage_element:
                        tag_name = _local_name(stage_child.tag)
                        if tag_name == "Operation":
                            operation = _parse_operation(stage_child)
                        elif tag_name == "Failures":
                            failures = _parse_failures(stage_child)
                    stage_attrs = _attrs(stage_element)
                    for key in ("id", "kind", "name", "capacity"):
                        stage_attrs.pop(key, None)
                    stage = Stage(
                        stage_id=stage_id,
                        kind=stage_element.attrib.get("kind", "physical"),
                        name=stage_element.attrib.get("name"),
                        line_id=line_id or None,
                        capacity=_int_attr(stage_element, "capacity", default=1),
                        operation=operation,
                        workers_required=_parse_workers_required(stage_element),
                        failures=failures,
                        attributes=stage_attrs,
                    )
                    stages[stage_id] = stage
                    line_stage_ids.append(stage_id)
                if line_id:
                    line_stages[line_id] = tuple(line_stage_ids)
        elif tag == "Transfers":
            for transfer_element in child:
                if _local_name(transfer_element.tag) != "Transfer":
                    continue
                transfer_id = transfer_element.attrib.get("id", "")
                if not transfer_id:
                    messages.append(_message("error", "transfer.id", "Transfer is missing an id.", "Transfers/Transfer"))
                    continue
                if transfer_id in transfers:
                    messages.append(_message("error", "transfer.duplicate", f"Transfer id '{transfer_id}' is duplicated.", f"Transfer[{transfer_id}]"))
                    continue
                transit_element = transfer_element.find("TransitService")
                transfer_attrs = _attrs(transfer_element)
                for key in ("id", "from", "to", "mode", "capacity", "priority", "requiresWorkerPool", "requiresWorkerCount"):
                    transfer_attrs.pop(key, None)
                transfers[transfer_id] = Transfer(
                    transfer_id=transfer_id,
                    from_stage=transfer_element.attrib.get("from", ""),
                    to_stage=transfer_element.attrib.get("to", ""),
                    mode=transfer_element.attrib.get("mode", "conveyor"),
                    capacity=_float_attr(transfer_element, "capacity", default=None) if "capacity" in transfer_element.attrib else None,
                    transit_time=_parse_distribution(transit_element, default_value=0.0),
                    priority=_int_attr(transfer_element, "priority", default=0),
                    requires_worker_pool=transfer_element.attrib.get("requiresWorkerPool"),
                    requires_worker_count=_int_attr(transfer_element, "requiresWorkerCount", default=0),
                    attributes=transfer_attrs,
                )
        elif tag == "Workers":
            for pool_element in child:
                if _local_name(pool_element.tag) != "Pool":
                    continue
                pool_id = pool_element.attrib.get("id", "")
                if not pool_id:
                    messages.append(_message("error", "workers.id", "Worker pool is missing an id.", "Workers/Pool"))
                    continue
                workers[pool_id] = WorkerPool(
                    pool_id=pool_id,
                    size=_int_attr(pool_element, "size", default=0),
                    role=pool_element.attrib.get("role"),
                    skills=tuple(part.strip() for part in pool_element.attrib.get("skills", "").split(",") if part.strip()),
                )
        elif tag == "Arrivals":
            for arrival_element in child:
                local = _local_name(arrival_element.tag)
                if local not in {"Source", "PartSource"}:
                    continue
                arrivals.append(
                    ArrivalSource(
                        arrival_id=arrival_element.attrib.get("id"),
                        stage_ref=arrival_element.attrib.get("stageRef", ""),
                        product_ref=arrival_element.attrib.get("productRef", ""),
                        quantity=_float_attr(arrival_element, "quantity", default=0.0),
                        mode=arrival_element.attrib.get("mode", "initial"),
                        attributes={key: value for key, value in arrival_element.attrib.items() if key not in {"id", "stageRef", "productRef", "quantity", "mode"}},
                    )
                )
        elif tag == "Controls":
            controls.append(ET.tostring(child, encoding="unicode"))
        elif tag == "Layout":
            for layout_element in child:
                local = _local_name(layout_element.tag)
                if local == "Placement":
                    placement_attrs = _attrs(layout_element)
                    for key in (
                        "stageRef",
                        "machineMeshRef",
                        "translate",
                        "translateX",
                        "translateY",
                        "translateZ",
                        "rotate",
                        "rotateX",
                        "rotateY",
                        "rotateZ",
                        "scale",
                        "scaleX",
                        "scaleY",
                        "scaleZ",
                        "extentX",
                        "extentY",
                        "extentZ",
                    ):
                        placement_attrs.pop(key, None)
                    placements.append(
                        Placement(
                            stage_ref=layout_element.attrib.get("stageRef", ""),
                            machine_mesh_ref=layout_element.attrib.get("machineMeshRef"),
                            translate=_tuple_from_attrs(layout_element, "translate", (0.0, 0.0, 0.0)),
                            rotate=_tuple_from_attrs(layout_element, "rotate", (0.0, 0.0, 0.0)),
                            scale=_tuple_from_attrs(layout_element, "scale", (1.0, 1.0, 1.0)),
                            extents=(
                                _float_attr(layout_element, "extentX", default=4.0),
                                _float_attr(layout_element, "extentY", default=2.0),
                                _float_attr(layout_element, "extentZ", default=2.5),
                            ),
                            attributes=placement_attrs,
                        )
                    )
                elif local == "GenericVisual":
                    params = {key: value for key, value in layout_element.attrib.items() if key not in {"id", "primitive", "transferRef", "stageRef", "fromStageRef", "toStageRef"}}
                    for param_element in layout_element:
                        if _local_name(param_element.tag) == "Param":
                            key = param_element.attrib.get("key")
                            value = param_element.attrib.get("value")
                            if key and value is not None:
                                params[key] = value
                    visual_id = layout_element.attrib.get("id") or f"{layout_element.attrib.get('primitive', 'visual')}_{len(generic_visuals) + 1}"
                    generic_visuals.append(
                        GenericVisual(
                            visual_id=visual_id,
                            primitive=layout_element.attrib.get("primitive", "generic"),
                            transfer_ref=layout_element.attrib.get("transferRef"),
                            stage_ref=layout_element.attrib.get("stageRef"),
                            from_stage_ref=layout_element.attrib.get("fromStageRef"),
                            to_stage_ref=layout_element.attrib.get("toStageRef"),
                            params=params,
                        )
                    )
        elif tag == "Extensions":
            raw_extensions.extend(ET.tostring(grandchild, encoding="unicode") for grandchild in child)

    logical = LogicalModel(
        schema_version=schema_version,
        time_unit=time_unit,
        simulation=simulation,
        products=products,
        line_stages=line_stages,
        stages=stages,
        transfers=transfers,
        workers=workers,
        arrivals=tuple(arrivals),
        controls=tuple(controls),
        extensions=tuple(raw_extensions),
    )
    visual = VisualModel(
        layout=Layout(placements=tuple(placements), generic_visuals=tuple(generic_visuals)),
        stage_names={stage_id: stage.name or stage_id for stage_id, stage in stages.items()},
    )
    factory = FactoryModel(
        schema_version=schema_version,
        time_unit=time_unit,
        simulation=simulation,
        logical_model=logical,
        visual_model=visual,
        products=products,
        raw_extensions=tuple(raw_extensions),
    )
    messages.extend(validate_factory(factory, registry_ids=registry_ids))
    return ParseResult(factory=factory, messages=tuple(messages), source=source, xml_text=text)


def _parse_simulation(simulation_element: ET.Element) -> SimulationConfig:
    horizon_duration = 0.0
    horizon_unit = simulation_element.attrib.get("timeUnit", "minute")
    output_definition = OutputDefinition(sink_stage_ref="")
    scenarios: list[Scenario] = []
    replications = Replications()

    for child in simulation_element:
        tag = _local_name(child.tag)
        if tag == "Horizon":
            horizon_duration = _float_attr(child, "duration", default=0.0)
            horizon_unit = child.attrib.get("unit", horizon_unit)
        elif tag == "OutputDefinition":
            output_definition = OutputDefinition(
                sink_stage_ref=child.attrib.get("sinkStageRef", ""),
                product_ref=child.attrib.get("productRef"),
                quality=child.attrib.get("quality", "good"),
            )
        elif tag == "Scenarios":
            for scenario_element in child:
                if _local_name(scenario_element.tag) != "Scenario":
                    continue
                extensions = {key: value for key, value in scenario_element.attrib.items() if key not in {"id", "policy"}}
                scenarios.append(
                    Scenario(
                        scenario_id=scenario_element.attrib.get("id", ""),
                        policy=scenario_element.attrib.get("policy", "default_stochastic"),
                        extensions=extensions,
                    )
                )
        elif tag == "Replications":
            replications = Replications(
                n=_int_attr(child, "n", default=1),
                seed=_int_attr(child, "seed", default=0) if "seed" in child.attrib else None,
            )

    return SimulationConfig(
        horizon_duration=horizon_duration,
        horizon_unit=horizon_unit,
        output_definition=output_definition,
        scenarios=tuple(scenarios),
        replications=replications,
    )


def _default_simulation() -> SimulationConfig:
    return SimulationConfig(
        horizon_duration=0.0,
        horizon_unit="minute",
        output_definition=OutputDefinition(sink_stage_ref=""),
        scenarios=(),
        replications=Replications(),
    )


def _empty_factory() -> FactoryModel:
    simulation = _default_simulation()
    logical = LogicalModel(
        schema_version=1,
        time_unit="minute",
        simulation=simulation,
        products={},
        line_stages={},
        stages={},
        transfers={},
        workers={},
    )
    visual = VisualModel(layout=Layout(), stage_names={})
    return FactoryModel(
        schema_version=1,
        time_unit="minute",
        simulation=simulation,
        logical_model=logical,
        visual_model=visual,
        products={},
    )

