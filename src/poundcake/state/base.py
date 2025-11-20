"""Abstract base class for state storage."""

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager

from poundcake.models.tracking import AlertStats, TrackedAlert


class StateStore(ABC):
    """Abstract interface for alert state storage."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the state store."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the state store."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the state store is healthy."""
        pass

    # Alert operations
    @abstractmethod
    async def get_alert(self, fingerprint: str) -> TrackedAlert | None:
        """Get a tracked alert by fingerprint."""
        pass

    @abstractmethod
    async def save_alert(self, alert: TrackedAlert) -> None:
        """Save or update a tracked alert."""
        pass

    @abstractmethod
    async def delete_alert(self, fingerprint: str) -> bool:
        """Delete a tracked alert."""
        pass

    @abstractmethod
    async def list_alerts(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TrackedAlert]:
        """List tracked alerts with optional filtering."""
        pass

    @abstractmethod
    async def get_stats(self) -> AlertStats:
        """Get statistics about tracked alerts."""
        pass

    # Distributed locking
    @abstractmethod
    def lock(self, key: str, timeout: int = 300) -> AbstractAsyncContextManager[bool]:
        """
        Acquire a distributed lock.

        Args:
            key: Lock identifier
            timeout: Lock timeout in seconds

        Yields:
            True if lock was acquired, False otherwise
        """
        pass

    @abstractmethod
    async def is_locked(self, key: str) -> bool:
        """Check if a key is currently locked."""
        pass
