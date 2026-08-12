from decimal import Decimal

import pytest

from smart_retail.copilot.tools import (
    ToolGateway,
    ToolInvocation,
    ToolPermissionError,
    ToolRisk,
    ToolStatus,
)
from smart_retail.domain import (
    ActorRole,
    ApprovalStatus,
    Device,
    DeviceType,
    InventoryAdjustment,
    Sku,
    Store,
)
from smart_retail.repositories.memory import InMemoryRetailRepository


def configured_gateway() -> tuple[ToolGateway, InMemoryRetailRepository]:
    repository = InMemoryRetailRepository()
    repository.create_store(Store("store-1", "Chicago Loop"))
    repository.create_sku(Sku("sku-1", "Milk"))
    repository.adjust_inventory(
        InventoryAdjustment("seed-inventory", "store-1", "sku-1", 12, "seed")
    )
    repository.create_device(
        Device(
            device_id="sensor-1",
            store_id="store-1",
            device_type=DeviceType.TEMPERATURE_SENSOR,
            display_name="Dairy sensor",
        )
    )
    return ToolGateway(repository), repository


def test_tool_definitions_use_strict_schemas_and_risk_levels() -> None:
    gateway, _ = configured_gateway()
    definitions = {definition.name: definition for definition in gateway.definitions}

    assert definitions["get_inventory"].risk is ToolRisk.READ
    assert definitions["set_price"].risk is ToolRisk.HIGH_WRITE
    assert definitions["get_inventory"].as_openai_tool()["strict"] is True
    assert definitions["get_inventory"].parameters["additionalProperties"] is False


def test_read_and_low_risk_work_order_tools_execute() -> None:
    gateway, repository = configured_gateway()

    inventory = gateway.execute(
        ToolInvocation(
            call_id="call-1",
            name="get_inventory",
            arguments={"store_id": "store-1", "sku": "sku-1"},
        )
    )
    work_order = gateway.execute(
        ToolInvocation(
            call_id="call-2",
            name="create_work_order",
            arguments={
                "request_id": "ticket-1",
                "store_id": "store-1",
                "category": "refrigeration",
                "priority": "high",
                "summary": "Dairy case above 5 C",
            },
        )
    )

    assert inventory.status is ToolStatus.SUCCESS
    assert inventory.output is not None and inventory.output["quantity"] == 12
    assert work_order.status is ToolStatus.SUCCESS
    assert repository.get_work_order("ticket-1") is not None


def test_high_risk_write_requires_approval_before_execution() -> None:
    gateway, repository = configured_gateway()
    invocation = ToolInvocation(
        call_id="call-price",
        name="set_price",
        arguments={
            "request_id": "price-1",
            "store_id": "store-1",
            "sku": "sku-1",
            "new_price": "3.49",
            "reason": "approved promotion",
        },
    )

    pending = gateway.execute(invocation)

    assert pending.status is ToolStatus.APPROVAL_REQUIRED
    assert pending.approval_id is not None
    assert repository.get_price("store-1", "sku-1") is None

    with pytest.raises(ToolPermissionError, match="cannot approve"):
        gateway.decide_and_execute(
            pending.approval_id,
            approved=True,
            actor_id="operator-1",
            actor_role=ActorRole.OPERATOR,
        )

    approval = gateway.decide_and_execute(
        pending.approval_id,
        approved=True,
        actor_id="pricing-lead-1",
        actor_role=ActorRole.PRICING_LEAD,
    )

    assert approval.status is ApprovalStatus.EXECUTED
    stored_price = repository.get_price("store-1", "sku-1")
    assert stored_price is not None
    assert stored_price.amount == Decimal("3.49")


def test_invalid_tool_arguments_return_structured_error() -> None:
    gateway, _ = configured_gateway()

    result = gateway.execute(
        ToolInvocation(
            call_id="call-invalid",
            name="get_inventory",
            arguments={"store_id": "store-1"},
        )
    )

    assert result.status is ToolStatus.ERROR
    assert result.error is not None and "invalid tool arguments" in result.error
