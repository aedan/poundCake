"""State storage for alert tracking."""

from poundcake.state.base import StateStore
from poundcake.state.memory import MemoryStateStore
from poundcake.state.redis_store import RedisStateStore

__all__ = [
    "StateStore",
    "MemoryStateStore",
    "RedisStateStore",
    "get_state_store",
]

# Global state store instance
_state_store: StateStore | None = None


def get_state_store() -> StateStore:
    """Get the global state store instance."""
    global _state_store
    if _state_store is None:
        # Default to memory store, will be configured at startup
        _state_store = MemoryStateStore()
    return _state_store


def set_state_store(store: StateStore) -> None:
    """Set the global state store instance."""
    global _state_store
    _state_store = store
