"""YAML configuration-based handler for remediation actions."""

from typing import Any

import structlog

from poundcake.handlers.base import BaseHandler, HandlerContext
from poundcake.models.remediation import RemediationAction

logger = structlog.get_logger(__name__)


class YAMLConfigHandler(BaseHandler):
    """Handler that uses YAML configuration to define remediation actions."""

    @property
    def name(self) -> str:
        return "yaml_config"

    @property
    def description(self) -> str:
        return "Executes remediation actions defined in YAML configuration files"

    async def can_handle(self, context: HandlerContext) -> bool:
        """Check if there's a valid YAML configuration for this alert."""
        return bool(context.config and context.config.get("actions"))

    async def get_actions(self, context: HandlerContext) -> list[RemediationAction]:
        """Build remediation actions from YAML configuration."""
        actions: list[RemediationAction] = []

        action_configs = context.config.get("actions", [])

        for action_config in action_configs:
            # Check conditions if specified
            if not self._check_conditions(context, action_config):
                logger.debug(
                    "Action skipped due to conditions",
                    action=action_config.get("name"),
                    alert=context.alert.alertname,
                )
                continue

            # Build parameters by merging config params with alert context
            parameters = {**action_config.get("parameters", {})}
            parameters.update(self.build_parameters(context))

            # Apply parameter templates
            parameters = self._apply_templates(parameters, context)

            action = RemediationAction(
                name=action_config.get("name", action_config["action"]),
                description=action_config.get("description", ""),
                action=action_config["action"],
                parameters=parameters,
                timeout=action_config.get("timeout", 300),
                retry_count=action_config.get("retry_count", 0),
                retry_delay=action_config.get("retry_delay", 30),
            )
            actions.append(action)

        return actions

    def _check_conditions(
        self,
        context: HandlerContext,
        action_config: dict[str, Any],
    ) -> bool:
        """Check if conditions are met for this action."""
        conditions = action_config.get("conditions", {})

        if not conditions:
            return True

        # Check severity condition
        if "severity" in conditions:
            allowed_severities = conditions["severity"]
            if isinstance(allowed_severities, str):
                allowed_severities = [allowed_severities]
            if context.alert.severity not in allowed_severities:
                return False

        # Check label conditions
        if "labels" in conditions:
            for key, value in conditions["labels"].items():
                if context.alert.labels.get(key) != value:
                    return False

        # Check label existence
        if "has_labels" in conditions:
            for label in conditions["has_labels"]:
                if label not in context.alert.labels:
                    return False

        return True

    def _apply_templates(
        self,
        parameters: dict[str, Any],
        context: HandlerContext,
    ) -> dict[str, Any]:
        """Apply template substitutions to parameters."""
        result: dict[str, Any] = {}

        for key, value in parameters.items():
            if isinstance(value, str):
                # Simple template substitution for labels and annotations
                value = value.replace("{{alertname}}", context.alert.alertname)
                value = value.replace("{{instance}}", context.alert.instance)
                value = value.replace("{{severity}}", context.alert.severity)

                # Replace label templates
                for label_key, label_value in context.alert.labels.items():
                    value = value.replace(f"{{{{labels.{label_key}}}}}", label_value)

                # Replace annotation templates
                for ann_key, ann_value in context.alert.annotations.items():
                    value = value.replace(f"{{{{annotations.{ann_key}}}}}", ann_value)

            result[key] = value

        return result
