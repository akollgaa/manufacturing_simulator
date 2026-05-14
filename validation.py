from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import FactoryModel, ValidationMessage


def validate_factory(factory: FactoryModel, registry_ids: Iterable[str] = ()) -> tuple[ValidationMessage, ...]:
    registry_id_set = set(registry_ids)
    messages: list[ValidationMessage] = []
    logical = factory.logical_model
    simulation = factory.simulation
    stage_ids = set(logical.stages)
    product_ids = set(logical.products)

    if simulation.horizon_duration <= 0:
        messages.append(
            ValidationMessage("error", "simulation.horizon", "Simulation horizon must be greater than 0.", "Simulation/Horizon")
        )

    if simulation.output_definition.sink_stage_ref not in stage_ids:
        messages.append(
            ValidationMessage(
                "error",
                "simulation.output_definition",
                f"OutputDefinition references unknown sink stage '{simulation.output_definition.sink_stage_ref}'.",
                "Simulation/OutputDefinition",
            )
        )

    if simulation.output_definition.product_ref and simulation.output_definition.product_ref not in product_ids:
        messages.append(
            ValidationMessage(
                "error",
                "simulation.output_product",
                f"OutputDefinition product '{simulation.output_definition.product_ref}' does not exist.",
                "Simulation/OutputDefinition",
            )
        )

    if simulation.replications.n <= 0:
        messages.append(
            ValidationMessage("error", "simulation.replications", "Replications.n must be a positive integer.", "Simulation/Replications")
        )

    scenario_ids = [scenario.scenario_id for scenario in simulation.scenarios]
    for scenario_id, count in Counter(scenario_ids).items():
        if count > 1:
            messages.append(
                ValidationMessage("error", "simulation.scenarios", f"Scenario id '{scenario_id}' is duplicated.", "Simulation/Scenarios")
            )

    for stage in logical.stages.values():
        if stage.capacity <= 0:
            messages.append(
                ValidationMessage("error", "stage.capacity", f"Stage '{stage.stage_id}' must have positive capacity.", f"Stage[{stage.stage_id}]")
            )
        if stage.is_machine and stage.operation is None:
            messages.append(
                ValidationMessage("warning", "stage.operation", f"Machine stage '{stage.stage_id}' has no Operation and will never process work.", f"Stage[{stage.stage_id}]")
            )
        if stage.operation:
            for input_requirement in stage.operation.inputs:
                if input_requirement.product_ref not in product_ids:
                    messages.append(
                        ValidationMessage(
                            "error",
                            "operation.input_product",
                            f"Stage '{stage.stage_id}' references unknown input product '{input_requirement.product_ref}'.",
                            f"Stage[{stage.stage_id}]/Operation/Input",
                        )
                    )
            for output_product in stage.operation.outputs:
                if output_product.product_ref not in product_ids:
                    messages.append(
                        ValidationMessage(
                            "error",
                            "operation.output_product",
                            f"Stage '{stage.stage_id}' references unknown output product '{output_product.product_ref}'.",
                            f"Stage[{stage.stage_id}]/Operation/Output",
                        )
                    )
        for worker_requirement in stage.workers_required:
            if worker_requirement.pool_ref not in logical.workers:
                messages.append(
                    ValidationMessage(
                        "error",
                        "workers.pool_ref",
                        f"Stage '{stage.stage_id}' references unknown worker pool '{worker_requirement.pool_ref}'.",
                        f"Stage[{stage.stage_id}]/WorkersRequired",
                    )
                )

    for transfer in logical.transfers.values():
        if transfer.from_stage not in stage_ids:
            messages.append(
                ValidationMessage(
                    "error",
                    "transfer.from_stage",
                    f"Transfer '{transfer.transfer_id}' references unknown source stage '{transfer.from_stage}'.",
                    f"Transfer[{transfer.transfer_id}]",
                )
            )
        if transfer.to_stage not in stage_ids:
            messages.append(
                ValidationMessage(
                    "error",
                    "transfer.to_stage",
                    f"Transfer '{transfer.transfer_id}' references unknown destination stage '{transfer.to_stage}'.",
                    f"Transfer[{transfer.transfer_id}]",
                )
            )
        if transfer.capacity is not None and transfer.capacity <= 0:
            messages.append(
                ValidationMessage(
                    "error",
                    "transfer.capacity",
                    f"Transfer '{transfer.transfer_id}' must have positive capacity when provided.",
                    f"Transfer[{transfer.transfer_id}]",
                )
            )

    for pool in logical.workers.values():
        if pool.size < 0:
            messages.append(
                ValidationMessage("error", "workers.size", f"Worker pool '{pool.pool_id}' must not be negative.", f"Workers/Pool[{pool.pool_id}]")
            )

    for arrival in logical.arrivals:
        if arrival.stage_ref not in stage_ids:
            messages.append(
                ValidationMessage(
                    "error",
                    "arrivals.stage_ref",
                    f"Arrival source references unknown stage '{arrival.stage_ref}'.",
                    f"Arrivals/Source[{arrival.arrival_id or arrival.stage_ref}]",
                )
            )
        if arrival.product_ref not in product_ids:
            messages.append(
                ValidationMessage(
                    "error",
                    "arrivals.product_ref",
                    f"Arrival source references unknown product '{arrival.product_ref}'.",
                    f"Arrivals/Source[{arrival.arrival_id or arrival.stage_ref}]",
                )
            )
        if arrival.quantity < 0:
            messages.append(
                ValidationMessage(
                    "error",
                    "arrivals.quantity",
                    "Arrival quantity must not be negative.",
                    f"Arrivals/Source[{arrival.arrival_id or arrival.stage_ref}]",
                )
            )

    for placement in factory.visual_model.layout.placements:
        if placement.stage_ref not in stage_ids:
            messages.append(
                ValidationMessage(
                    "error",
                    "layout.placement_stage",
                    f"Placement references unknown stage '{placement.stage_ref}'.",
                    f"Layout/Placement[{placement.stage_ref}]",
                )
            )
        if placement.machine_mesh_ref and placement.machine_mesh_ref not in registry_id_set:
            messages.append(
                ValidationMessage(
                    "warning",
                    "layout.machine_mesh_ref",
                    f"Placement for stage '{placement.stage_ref}' references missing DXF registry asset '{placement.machine_mesh_ref}'. Placeholder geometry will be used.",
                    f"Layout/Placement[{placement.stage_ref}]",
                )
            )

    for generic_visual in factory.visual_model.layout.generic_visuals:
        if generic_visual.transfer_ref and generic_visual.transfer_ref not in logical.transfers:
            messages.append(
                ValidationMessage(
                    "error",
                    "layout.transfer_ref",
                    f"GenericVisual '{generic_visual.visual_id}' references unknown transfer '{generic_visual.transfer_ref}'.",
                    f"Layout/GenericVisual[{generic_visual.visual_id}]",
                )
            )
        if generic_visual.stage_ref and generic_visual.stage_ref not in stage_ids:
            messages.append(
                ValidationMessage(
                    "error",
                    "layout.stage_ref",
                    f"GenericVisual '{generic_visual.visual_id}' references unknown stage '{generic_visual.stage_ref}'.",
                    f"Layout/GenericVisual[{generic_visual.visual_id}]",
                )
            )
        if generic_visual.from_stage_ref and generic_visual.from_stage_ref not in stage_ids:
            messages.append(
                ValidationMessage(
                    "error",
                    "layout.from_stage_ref",
                    f"GenericVisual '{generic_visual.visual_id}' references unknown fromStageRef '{generic_visual.from_stage_ref}'.",
                    f"Layout/GenericVisual[{generic_visual.visual_id}]",
                )
            )
        if generic_visual.to_stage_ref and generic_visual.to_stage_ref not in stage_ids:
            messages.append(
                ValidationMessage(
                    "error",
                    "layout.to_stage_ref",
                    f"GenericVisual '{generic_visual.visual_id}' references unknown toStageRef '{generic_visual.to_stage_ref}'.",
                    f"Layout/GenericVisual[{generic_visual.visual_id}]",
                )
            )

    return tuple(messages)

