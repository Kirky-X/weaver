# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Alert monitoring endpoints for rule CRUD, trigger, and acknowledgment."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.endpoints.deps_registry import Endpoints
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response
from modules.analytics import AlertService

router = APIRouter(prefix="/monitoring/alerts", tags=["monitoring", "alerts"])


def get_alert_service() -> AlertService:
    """Get the AlertService instance."""
    return AlertService(Endpoints.get_relational_pool())


# ── Request/Response Models ──────────────────────────────────────


class CreateAlertRuleRequest(BaseModel):
    """Request model for creating an alert rule."""

    entity_name: str = Field(..., max_length=200, description="Entity to monitor")
    metric: str = Field(
        ...,
        description="Metric: reference_count, sentiment_change, volume_spike",
    )
    operator: str = Field(
        ...,
        description="Operator: z_score>, pct_change>, absolute>",
    )
    threshold: float = Field(..., description="Threshold value")
    channel: str = Field(default="webhook", description="Notification channel")
    cooldown_minutes: int = Field(default=60, description="Cooldown in minutes")


class UpdateAlertRuleRequest(BaseModel):
    """Request model for updating an alert rule."""

    metric: str | None = None
    operator: str | None = None
    threshold: float | None = None
    channel: str | None = None
    cooldown_minutes: int | None = None
    enabled: bool | None = None


class TriggerAlertRequest(BaseModel):
    """Request model for triggering an alert."""

    rule_id: int = Field(..., description="Alert rule ID")
    metric_value: float = Field(..., description="Current metric value")
    detail: dict[str, Any] | None = Field(default=None, description="Additional detail")


class AlertRuleResponse(BaseModel):
    """Response model for an alert rule."""

    id: int
    entity_name: str
    metric: str
    operator: str
    threshold: float
    channel: str
    cooldown_minutes: int
    enabled: bool


class AlertEventResponse(BaseModel):
    """Response model for an alert event."""

    id: int
    rule_id: int
    entity_name: str
    metric_value: float
    triggered_at: str | None
    acknowledged_at: str | None
    detail: dict[str, Any] | None


# ── Alert Rule CRUD Endpoints ────────────────────────────────────


@router.post("/rules", response_model=APIResponse[AlertRuleResponse])
async def create_alert_rule(
    request: CreateAlertRuleRequest,
    _: str = Depends(verify_admin_api_key),
    service: AlertService = Depends(get_alert_service),
) -> APIResponse[AlertRuleResponse]:
    """Create a new alert rule."""
    rule = await service.create_rule(
        entity_name=request.entity_name,
        metric=request.metric,
        operator=request.operator,
        threshold=request.threshold,
        channel=request.channel,
        cooldown_minutes=request.cooldown_minutes,
    )
    return success_response(AlertRuleResponse(**rule))


@router.get("/rules", response_model=APIResponse[list[AlertRuleResponse]])
async def list_alert_rules(
    entity_name: str | None = Query(None, description="Filter by entity name"),
    enabled_only: bool = Query(False, description="Only return enabled rules"),
    _: str = Depends(verify_admin_api_key),
    service: AlertService = Depends(get_alert_service),
) -> APIResponse[list[AlertRuleResponse]]:
    """List alert rules with optional filters."""
    rules = await service.list_rules(entity_name=entity_name, enabled_only=enabled_only)
    return success_response([AlertRuleResponse(**r) for r in rules])


@router.get("/rules/{rule_id}", response_model=APIResponse[AlertRuleResponse])
async def get_alert_rule(
    rule_id: int,
    _: str = Depends(verify_admin_api_key),
    service: AlertService = Depends(get_alert_service),
) -> APIResponse[AlertRuleResponse]:
    """Get an alert rule by ID."""
    rule = await service.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return success_response(AlertRuleResponse(**rule))


@router.patch("/rules/{rule_id}", response_model=APIResponse[AlertRuleResponse])
async def update_alert_rule(
    rule_id: int,
    request: UpdateAlertRuleRequest,
    _: str = Depends(verify_admin_api_key),
    service: AlertService = Depends(get_alert_service),
) -> APIResponse[AlertRuleResponse]:
    """Update an alert rule."""
    fields = {k: v for k, v in request.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    rule = await service.update_rule(rule_id, **fields)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return success_response(AlertRuleResponse(**rule))


@router.delete("/rules/{rule_id}", response_model=APIResponse[bool])
async def delete_alert_rule(
    rule_id: int,
    _: str = Depends(verify_admin_api_key),
    service: AlertService = Depends(get_alert_service),
) -> APIResponse[bool]:
    """Delete an alert rule."""
    deleted = await service.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return success_response(True)


# ── Alert Trigger & Acknowledge ──────────────────────────────────


@router.post("/trigger", response_model=APIResponse[AlertEventResponse | None])
async def trigger_alert(
    request: TriggerAlertRequest,
    _: str = Depends(verify_admin_api_key),
    service: AlertService = Depends(get_alert_service),
) -> APIResponse[AlertEventResponse | None]:
    """Trigger an alert for a rule.

    Returns the created event, or None if cooldown prevented the trigger.
    """
    event = await service.trigger_alert(
        rule_id=request.rule_id,
        metric_value=request.metric_value,
        detail=request.detail,
    )
    if event is None:
        return success_response(None, warning="Alert not triggered (cooldown or rule not found)")
    return success_response(AlertEventResponse(**event))


@router.post("/events/{event_id}/acknowledge", response_model=APIResponse[bool])
async def acknowledge_alert(
    event_id: int,
    _: str = Depends(verify_admin_api_key),
    service: AlertService = Depends(get_alert_service),
) -> APIResponse[bool]:
    """Acknowledge an alert event."""
    result = await service.acknowledge_event(event_id)
    if not result:
        raise HTTPException(status_code=404, detail="Alert event not found")
    return success_response(True)


# ── Alert Event Listing ──────────────────────────────────────────


@router.get("/events", response_model=APIResponse[list[AlertEventResponse]])
async def list_alert_events(
    rule_id: int | None = Query(None, description="Filter by rule ID"),
    entity_name: str | None = Query(None, description="Filter by entity name"),
    acknowledged: bool | None = Query(None, description="Filter by acknowledgment status"),
    limit: int = Query(50, ge=1, le=200, description="Max events to return"),
    _: str = Depends(verify_admin_api_key),
    service: AlertService = Depends(get_alert_service),
) -> APIResponse[list[AlertEventResponse]]:
    """List alert events with optional filters."""
    events = await service.list_events(
        rule_id=rule_id,
        entity_name=entity_name,
        acknowledged=acknowledged,
        limit=limit,
    )
    return success_response([AlertEventResponse(**e) for e in events])
