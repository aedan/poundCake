"""Handler registry for managing remediation handlers."""

from pathlib import Path
from typing import Any

import structlog

from poundcake.config import get_settings, load_all_mappings
from poundcake.handlers.base import BaseHandler, HandlerContext
from poundcake.models.alerts import Alert
from poundcake.models.remediation import RemediationAction
from poundcake.stackstorm import StackStormClient

logger = structlog.get_logger(__name__)


class HandlerRegistry:
    """Registry for managing remediation handlers."""

    def __init__(self) -> None:
        """Initialize the handler registry."""
        self._handlers: dict[str, BaseHandler] = {}
        self._mappings: dict[str, Any] = {}
        self._stackstorm_client = StackStormClient()

    def register(self, handler: BaseHandler) -> None:
        """
        Register a handler with the registry.

        Args:
            handler: The handler to register
        """
        if handler.name in self._handlers:
            logger.warning(
                "Overwriting existing handler",
                handler=handler.name,
            )
        self._handlers[handler.name] = handler
        logger.info("Registered handler", handler=handler.name)

    def unregister(self, handler_name: str) -> None:
        """
        Unregister a handler from the registry.

        Args:
            handler_name: Name of the handler to unregister
        """
        if handler_name in self._handlers:
            del self._handlers[handler_name]
            logger.info("Unregistered handler", handler=handler_name)

    def get_handler(self, name: str) -> BaseHandler | None:
        """
        Get a handler by name.

        Args:
            name: The handler name

        Returns:
            The handler if found, None otherwise
        """
        return self._handlers.get(name)

    def list_handlers(self) -> list[str]:
        """Get a list of all registered handler names."""
        return list(self._handlers.keys())

    def load_mappings(self, mappings_path: Path | None = None) -> None:
        """
        Load alert-to-handler mappings from YAML files.

        Args:
            mappings_path: Path to the mappings directory
        """
        if mappings_path is None:
            mappings_path = get_settings().mappings_path

        self._mappings = load_all_mappings(mappings_path)
        logger.info(
            "Loaded alert mappings",
            count=len(self._mappings),
            path=str(mappings_path),
        )

    def get_mapping(self, alert_name: str) -> dict[str, Any] | None:
        """
        Get the mapping configuration for an alert.

        Args:
            alert_name: The alert name to look up

        Returns:
            The mapping configuration if found
        """
        return self._mappings.get(alert_name)

    async def find_handlers(self, alert: Alert) -> list[tuple[BaseHandler, dict[str, Any]]]:
        """
        Find all handlers that can process an alert.

        Args:
            alert: The alert to find handlers for

        Returns:
            List of (handler, config) tuples
        """
        result: list[tuple[BaseHandler, dict[str, Any]]] = []

        # First check if there's a mapping for this alert
        mapping = self.get_mapping(alert.alertname)
        if mapping:
            handler_name = mapping.get("handler", "yaml_config")
            handler = self.get_handler(handler_name)
            if handler:
                context = HandlerContext(
                    alert=alert,
                    config=mapping,
                    stackstorm_client=self._stackstorm_client,
                )
                if await handler.can_handle(context):
                    result.append((handler, mapping))

        # Also check all handlers if they can handle this alert
        for handler in self._handlers.values():
            if handler.name == "yaml_config":
                continue  # Already checked above

            context = HandlerContext(
                alert=alert,
                config={},
                stackstorm_client=self._stackstorm_client,
            )
            if await handler.can_handle(context):
                result.append((handler, {}))

        return result

    async def get_actions_for_alert(self, alert: Alert) -> list[RemediationAction]:
        """
        Get all remediation actions for an alert.

        Args:
            alert: The alert to get actions for

        Returns:
            List of remediation actions
        """
        handlers = await self.find_handlers(alert)
        actions: list[RemediationAction] = []

        for handler, config in handlers:
            context = HandlerContext(
                alert=alert,
                config=config,
                stackstorm_client=self._stackstorm_client,
            )
            handler_actions = await handler.get_actions(context)
            actions.extend(handler_actions)

        return actions

    @property
    def stackstorm_client(self) -> StackStormClient:
        """Get the StackStorm client."""
        return self._stackstorm_client


# Global registry instance
_registry: HandlerRegistry | None = None


def get_registry() -> HandlerRegistry:
    """Get the global handler registry."""
    global _registry
    if _registry is None:
        _registry = HandlerRegistry()
    return _registry
