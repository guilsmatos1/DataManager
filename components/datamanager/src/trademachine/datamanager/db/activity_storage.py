"""Activity log storage for audit trail."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from trademachine.core.logger import LOGGER_NAME
from trademachine.datamanager.db.models import ActivityLog
from trademachine.datamanager.infrastructure.database import SessionLocal

logger = logging.getLogger(LOGGER_NAME)


class ActivityStorageManager:
    """Persists and queries activity log entries."""

    def log_activity(
        self,
        action: str,
        target: str,
        status: str,
        message: str = "",
    ) -> None:
        session: Session = SessionLocal()
        try:
            entry = ActivityLog(
                timestamp=datetime.now(UTC),
                action=action,
                target=target,
                status=status,
                message=message,
            )
            session.add(entry)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Failed to log activity")
        finally:
            session.close()

    def list_activities(self, limit: int = 50, offset: int = 0) -> list[dict]:
        session: Session = SessionLocal()
        try:
            stmt = (
                select(ActivityLog)
                .order_by(ActivityLog.timestamp.desc())
                .offset(offset)
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else "",
                    "action": r.action,
                    "target": r.target,
                    "status": r.status,
                    "message": r.message,
                }
                for r in rows
            ]
        finally:
            session.close()

    def count_activities(self) -> int:
        session: Session = SessionLocal()
        try:
            from sqlalchemy import func

            stmt = select(func.count(ActivityLog.id))
            return session.execute(stmt).scalar() or 0
        finally:
            session.close()
