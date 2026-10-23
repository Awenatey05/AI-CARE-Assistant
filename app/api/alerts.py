"""Alerts for the dashboard: list open alerts and confirm them.

The team leader or supervisor sees open alerts in the dashboard and confirms
each one there; confirming stops the escalation. Both routes need the API key
(X-Api-Key), like the other office routes.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.api.office import check_api_key, check_region
from app.services import notifier

router = APIRouter(tags=["alerts"])
log = logging.getLogger("api")


class Confirmation(BaseModel):
    confirmed_by: str = Field(min_length=2, description="Name or role of the person confirming")


def database_or_503(action, *args) -> Any:
    try:
        return action(*args)
    except Exception as error:          # Postgres unavailable
        log.error("alerts route failed: %s", type(error).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Alerts are not available now") from error


# 1. OPEN ALERTS
@router.get("/alerts")
def list_open_alerts(region: str | None = None,
                     x_api_key: Annotated[str | None, Header()] = None) -> list[dict[str, Any]]:
    """Open alerts, urgent first, then the most escalated, then the oldest. Optionally for one region."""
    check_api_key(x_api_key)
    return database_or_503(notifier.open_alerts, check_region(region) if region else None)


# 2. CONFIRM
@router.post("/alerts/{alert_id}/confirm")
def confirm_alert(alert_id: int, confirmation: Confirmation,
                  x_api_key: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """A person has seen the alert and acted: close it and stop the escalation."""
    check_api_key(x_api_key)
    if not database_or_503(notifier.confirm, alert_id, confirmation.confirmed_by):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open alert with this id")
    return {"status": "confirmed", "alert_id": alert_id}
