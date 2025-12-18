"""Redis implementation of state storage."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import redis.asyncio as redis
import structlog

from poundcake.models.tracking import AlertStats, AlertTrackingStatus, TrackedAlert
from poundcake.state.base import StateStore

logger = structlog.get_logger(__name__)


class RedisStateStore(StateStore):
    """Redis-based state storage for horizontal scaling."""

    # Key prefixes
    ALERT_PREFIX = "poundcake:alert:"
    LOCK_PREFIX = "poundcake:lock:"
    INDEX_PREFIX = "poundcake:index:"

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        password: str | None = None,
        alert_ttl_hours: int = 24,
        lock_timeout: int = 300,
    ) -> None:
        """
        Initialize Redis state store.

        Args:
            url: Redis connection URL
            password: Redis password (optional)
            alert_ttl_hours: TTL for resolved alerts in hours
            lock_timeout: Default lock timeout in seconds
        """
        self._url = url
        self._password = password
        self._alert_ttl_hours = alert_ttl_hours
        self._lock_timeout = lock_timeout
        self._client: redis.Redis[str] | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.from_url(
            self._url,
            password=self._password,
            decode_responses=True,
        )
        logger.info("Connected to Redis", url=self._url)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Disconnected from Redis")

    async def health_check(self) -> bool:
        """Check if Redis is healthy."""
        if not self._client:
            return False
        try:
            await self._client.ping()
            return True
        except Exception as e:
            logger.error("Redis health check failed", error=str(e))
            return False

    def _alert_key(self, fingerprint: str) -> str:
        """Get Redis key for an alert."""
        return f"{self.ALERT_PREFIX}{fingerprint}"

    def _lock_key(self, key: str) -> str:
        """Get Redis key for a lock."""
        return f"{self.LOCK_PREFIX}{key}"

    def _serialize_alert(self, alert: TrackedAlert) -> str:
        """Serialize alert to JSON."""
        data = alert.model_dump(mode="json")
        return json.dumps(data)

    def _deserialize_alert(self, data: str) -> TrackedAlert:
        """Deserialize alert from JSON."""
        return TrackedAlert.model_validate_json(data)

    async def get_alert(self, fingerprint: str) -> TrackedAlert | None:
        """Get a tracked alert by fingerprint."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        data = await self._client.get(self._alert_key(fingerprint))
        if data:
            return self._deserialize_alert(data)
        return None

    async def save_alert(self, alert: TrackedAlert) -> None:
        """Save or update a tracked alert."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        key = self._alert_key(alert.fingerprint)
        data = self._serialize_alert(alert)

        # Set TTL for resolved alerts
        if alert.status == AlertTrackingStatus.RESOLVED:
            ttl_seconds = self._alert_ttl_hours * 3600
            await self._client.setex(key, ttl_seconds, data)
        else:
            await self._client.set(key, data)

        # Update status index
        await self._update_status_index(alert)

    async def _update_status_index(self, alert: TrackedAlert) -> None:
        """Update the status index for an alert."""
        if not self._client:
            return

        # Remove from all status sets
        for status in AlertTrackingStatus:
            await self._client.srem(
                f"{self.INDEX_PREFIX}status:{status.value}",
                alert.fingerprint,
            )

        # Add to current status set
        await self._client.sadd(
            f"{self.INDEX_PREFIX}status:{alert.status.value}",
            alert.fingerprint,
        )

    async def delete_alert(self, fingerprint: str) -> bool:
        """Delete a tracked alert."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        key = self._alert_key(fingerprint)
        result = await self._client.delete(key)

        # Remove from all indexes
        for status in AlertTrackingStatus:
            await self._client.srem(
                f"{self.INDEX_PREFIX}status:{status.value}",
                fingerprint,
            )

        return bool(result > 0)

    async def list_alerts(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TrackedAlert]:
        """List tracked alerts with optional filtering."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        alerts: list[TrackedAlert] = []

        if status:
            # Get fingerprints from status index
            fingerprints = await self._client.smembers(f"{self.INDEX_PREFIX}status:{status}")
            fingerprints_list = list(fingerprints)
        else:
            # Get all alert keys
            keys = await self._client.keys(f"{self.ALERT_PREFIX}*")
            fingerprints_list = [k.replace(self.ALERT_PREFIX, "") for k in keys]

        # Sort by fingerprint for consistent ordering
        fingerprints_list.sort()

        # Apply pagination
        paginated = fingerprints_list[offset : offset + limit]

        # Fetch alerts
        for fingerprint in paginated:
            alert = await self.get_alert(fingerprint)
            if alert:
                alerts.append(alert)

        # Sort by received_at descending
        alerts.sort(key=lambda a: a.received_at, reverse=True)

        return alerts

    async def get_stats(self) -> AlertStats:
        """Get statistics about tracked alerts."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        stats = AlertStats()
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}

        # Count by status from indexes
        for status in AlertTrackingStatus:
            count = await self._client.scard(f"{self.INDEX_PREFIX}status:{status.value}")
            if count > 0:
                by_status[status.value] = count
                stats.total += count

        # Get severity counts (need to scan alerts)
        keys = await self._client.keys(f"{self.ALERT_PREFIX}*")
        for key in keys:
            data = await self._client.get(key)
            if data:
                alert = self._deserialize_alert(data)
                severity = alert.severity or "unknown"
                by_severity[severity] = by_severity.get(severity, 0) + 1

        stats.by_status = by_status
        stats.by_severity = by_severity

        return stats

    @asynccontextmanager
    async def lock(self, key: str, timeout: int | None = None) -> AsyncIterator[bool]:
        """
        Acquire a distributed lock using Redis.

        Uses SET NX with expiration for distributed locking.
        """
        if not self._client:
            raise RuntimeError("Redis client not connected")

        lock_key = self._lock_key(key)
        lock_timeout = timeout or self._lock_timeout

        # Try to acquire lock
        acquired = await self._client.set(
            lock_key,
            datetime.now(timezone.utc).isoformat(),
            nx=True,
            ex=lock_timeout,
        )

        try:
            yield bool(acquired)
        finally:
            # Release lock if we acquired it
            if acquired:
                await self._client.delete(lock_key)

    async def is_locked(self, key: str) -> bool:
        """Check if a key is currently locked."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        lock_key = self._lock_key(key)
        result = await self._client.exists(lock_key)
        return bool(result > 0)
