"""Write to the append-only `event_log` table (and the JSON log). Payloads are masked first."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, mask_any
from app.models import EventLog

EventType = Literal["signal", "order", "risk", "error", "auth", "broker", "system"]
Level = Literal["debug", "info", "warning", "error", "critical"]

_log = get_logger("app.events")


async def record_event(
    db: AsyncSession,
    type: EventType,
    message: str,
    *,
    user_id: uuid.UUID | None = None,
    level: Level = "info",
    **payload: Any,
) -> None:
    """Add an event to the session (the caller commits)."""
    safe_payload = mask_any(payload)
    safe_message = mask_any(message)[:500]
    db.add(
        EventLog(
            user_id=user_id,
            type=type,
            level=level,
            message=safe_message,
            payload=safe_payload,
        )
    )
    _log.log(
        _LEVELS[level],
        safe_message,
        event_type=type,
        user_id=str(user_id) if user_id else None,
        **safe_payload,
    )


_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
