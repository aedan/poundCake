"""In-memory state storage for development and single-instance deployments."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog

from poundcake.models.tracking import AlertStats, TrackedAlert
from poundcake.state.base import StateStore

logger = structlog.get_logger(__name__)


class MemoryStateStore(StateStore):
    """In-memory state storage (not suitable for horizontal scaling)."""

    def __init__(self) -> None:
        """Initialize in-memory state store."""
        self._alerts: dict[str, TrackedAlert] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_locks: set[str] = set()

    async def connect(self) -> None:
        """No-op for in-memory store."""
        logger.warning("Using in-memory state store - not suitable for horizontal scaling")

    async def disconnect(self) -> None:
        """Clear all state."""
        self._alerts.clear()
        self._locks.clear()
        self._active_locks.clear()

    async def health_check(self) -> bool:
        """Always healthy for in-memory store."""
        return True

    async def get_alert(self, fingerprint: str) -> TrackedAlert | None:
        """Get a tracked alert by fingerprint."""
        return self._alerts.get(fingerprint)

    async def save_alert(self, alert: TrackedAlert) -> None:
        """Save or update a tracked alert."""
        self._alerts[alert.fingerprint] = alert

    async def delete_alert(self, fingerprint: str) -> bool:
        """Delete a tracked alert."""
        if fingerprint in self._alerts:
            del self._alerts[fingerprint]
            return True
        return False

    async def list_alerts(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TrackedAlert]:
        """List tracked alerts with optional filtering."""
        alerts = list(self._alerts.values())

        # Filter by status if specified
        if status:
            alerts = [a for a in alerts if a.status.value == status]

        # Sort by received_at descending
        alerts.sort(key=lambda a: a.received_at, reverse=True)

        # Apply pagination
        return alerts[offset : offset + limit]

    async def get_stats(self) -> AlertStats:
        """Get statistics about tracked alerts."""
        stats = AlertStats()
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}

        for alert in self._alerts.values():
            stats.total += 1

            # Count by status
            status_val = alert.status.value
            by_status[status_val] = by_status.get(status_val, 0) + 1

            # Count by severity
            severity = alert.severity or "unknown"
            by_severity[severity] = by_severity.get(severity, 0) + 1

        stats.by_status = by_status
        stats.by_severity = by_severity

        return stats

    @asynccontextmanager
    async def lock(self, key: str, timeout: int = 300) -> AsyncIterator[bool]:
        """
        Acquire a lock using asyncio.Lock.

        Note: This only works within a single process.
        """
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()

        lock = self._locks[key]

        # Try to acquire without blocking
        acquired = lock.locked() is False
        if acquired:
            await lock.acquire()
            self._active_locks.add(key)

        try:
            yield acquired
        finally:
            if acquired:
                self._active_locks.discard(key)
                lock.release()

    async def is_locked(self, key: str) -> bool:
        """Check if a key is currently locked."""
        return key in self._active_locks
