"""Base handler class for remediation actions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import structlog

from poundcake.models.alerts import Alert
from poundcake.models.remediation import RemediationAction, RemediationResult
from poundcake.stackstorm import StackStormClient

logger = structlog.get_logger(__name__)


@dataclass
class HandlerContext:
    """Context passed to handlers during remediation."""

    alert: Alert
    config: dict[str, Any]
    stackstorm_client: StackStormClient


class BaseHandler(ABC):
    """Base class for all remediation handlers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this handler."""
        pass

    @property
    def description(self) -> str:
        """Description of what this handler does."""
        return ""

    @abstractmethod
    async def can_handle(self, context: HandlerContext) -> bool:
        """
        Determine if this handler can process the given alert.

        Args:
            context: The handler context with alert and config

        Returns:
            True if this handler can process the alert
        """
        pass

    @abstractmethod
    async def get_actions(self, context: HandlerContext) -> list[RemediationAction]:
        """
        Get the remediation actions to execute for this alert.

        Args:
            context: The handler context with alert and config

        Returns:
            List of remediation actions to execute
        """
        pass

    async def pre_execute(self, context: HandlerContext, action: RemediationAction) -> bool:
        """
        Hook called before executing an action.

        Args:
            context: The handler context
            action: The action about to be executed

        Returns:
            True to proceed, False to skip this action
        """
        return True

    async def post_execute(
        self,
        context: HandlerContext,
        action: RemediationAction,
        result: RemediationResult,
    ) -> None:
        """
        Hook called after executing an action.

        Args:
            context: The handler context
            action: The action that was executed
            result: The result of the execution
        """
        pass

    def build_parameters(self, context: HandlerContext) -> dict[str, Any]:
        """
        Build dynamic parameters from the alert context.

        Override this to add custom parameter building logic.

        Args:
            context: The handler context

        Returns:
            Dictionary of parameters to pass to StackStorm
        """
        return {
            "alert_name": context.alert.alertname,
            "alert_labels": context.alert.labels,
            "alert_annotations": context.alert.annotations,
            "instance": context.alert.instance,
            "severity": context.alert.severity,
        }
