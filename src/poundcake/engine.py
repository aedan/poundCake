"""Remediation engine for processing alerts and executing actions."""

from datetime import datetime, timezone
from typing import Any

import structlog

from poundcake.config import get_settings
from poundcake.handlers import get_registry
from poundcake.handlers.yaml_config import YAMLConfigHandler
from poundcake.handlers.examples import register_example_handlers
from poundcake.models.alerts import Alert, AlertStatus
from poundcake.models.remediation import RemediationAction, RemediationResult, RemediationStatus
from poundcake.models.tracking import (
    AlertTrackingStatus,
    RemediationAttempt,
    TrackedAlert,
)
from poundcake.stackstorm import StackStormError
from poundcake.state import StateStore, get_state_store

logger = structlog.get_logger(__name__)


class RemediationEngine:
    """Engine for processing alerts and executing remediation actions."""

    def __init__(self, state_store: StateStore | None = None) -> None:
        """Initialize the remediation engine."""
        self._registry = get_registry()
        self._state_store = state_store or get_state_store()
        self._initialized = False
        self._settings = get_settings()

    def initialize(self) -> None:
        """Initialize the engine with handlers and mappings."""
        if self._initialized:
            return

        # Register built-in handlers
        self._registry.register(YAMLConfigHandler())
        register_example_handlers(self._registry)

        # Load mappings
        self._registry.load_mappings()

        self._initialized = True
        logger.info(
            "Remediation engine initialized",
            handlers=self._registry.list_handlers(),
        )

    async def process_alert(self, alert: Alert) -> list[RemediationResult]:
        """
        Process an alert and execute remediation actions.

        Args:
            alert: The alert to process

        Returns:
            List of remediation results
        """
        log = logger.bind(
            alert_name=alert.alertname,
            alert_status=alert.status,
            fingerprint=alert.fingerprint,
            severity=alert.severity,
            instance=alert.instance,
        )

        now = datetime.now(timezone.utc)

        # Handle resolved alerts
        if alert.status == AlertStatus.RESOLVED:
            return await self._handle_resolved_alert(alert, log)

        # Try to acquire lock for this alert
        acquired: bool
        async with self._state_store.lock(f"alert:{alert.fingerprint}") as acquired:
            if not acquired:
                log.info("Alert is being processed by another instance")
                return []

            # Get or create tracked alert
            tracked = await self._state_store.get_alert(alert.fingerprint)
            if tracked is None:
                tracked = TrackedAlert(
                    fingerprint=alert.fingerprint,
                    alertname=alert.alertname,
                    instance=alert.instance,
                    severity=alert.severity,
                    labels=alert.labels,
                    annotations=alert.annotations,
                    status=AlertTrackingStatus.RECEIVED,
                    received_at=now,
                    status_changed_at=now,
                    processed_by=self._settings.instance_id,
                )
                await self._state_store.save_alert(tracked)
                log.info("New alert received and tracked")
            else:
                log.info("Alert already being tracked", current_status=tracked.status.value)

            # Skip if already resolved
            if tracked.status == AlertTrackingStatus.RESOLVED:
                log.info("Skipping already resolved alert")
                return []

            # Find handlers and get actions
            actions = await self._registry.get_actions_for_alert(alert)

            if not actions:
                log.warning("No remediation actions found for alert")
                # Update status to indicate no actions available
                tracked.update_status(AlertTrackingStatus.REMEDIATED, now)
                await self._state_store.save_alert(tracked)
                return []

            log.info("Found remediation actions", count=len(actions))

            # Update status to remediating
            tracked.update_status(AlertTrackingStatus.REMEDIATING, now)
            tracked.processed_by = self._settings.instance_id
            await self._state_store.save_alert(tracked)

            # Execute actions
            results: list[RemediationResult] = []
            for action in actions:
                result = await self._execute_action(alert, action, tracked)
                results.append(result)

            # Update status to remediated
            tracked.update_status(AlertTrackingStatus.REMEDIATED, datetime.now(timezone.utc))
            await self._state_store.save_alert(tracked)

            return results

    async def _handle_resolved_alert(self, alert: Alert, log: Any) -> list[RemediationResult]:
        """Handle a resolved alert from Alertmanager."""
        tracked = await self._state_store.get_alert(alert.fingerprint)

        if tracked is None:
            log.info("Resolved alert was not tracked")
            return []

        if tracked.status == AlertTrackingStatus.RESOLVED:
            log.info("Alert already marked as resolved")
            return []

        # Update status to resolved
        tracked.update_status(AlertTrackingStatus.RESOLVED, datetime.now(timezone.utc))
        await self._state_store.save_alert(tracked)

        log.info(
            "Alert resolved",
            total_attempts=tracked.total_attempts,
            successful_attempts=tracked.successful_attempts,
        )

        return []

    async def _execute_action(
        self,
        alert: Alert,
        action: RemediationAction,
        tracked: TrackedAlert,
    ) -> RemediationResult:
        """
        Execute a single remediation action.

        Args:
            alert: The alert being remediated
            action: The action to execute
            tracked: The tracked alert to update

        Returns:
            The remediation result
        """
        log = logger.bind(
            action_name=action.name,
            stackstorm_action=action.stackstorm_action,
            alert_name=alert.alertname,
        )

        now = datetime.now(timezone.utc)

        result = RemediationResult(
            alert_fingerprint=alert.fingerprint,
            alert_name=alert.alertname,
            action_name=action.name,
            status=RemediationStatus.RUNNING,
            started_at=now,
        )

        # Create remediation attempt for tracking
        attempt = RemediationAttempt(
            action_name=action.name,
            stackstorm_action=action.stackstorm_action,
            status="running",
            started_at=now,
        )

        try:
            log.info("Executing remediation action")

            # Execute the action
            client = self._registry.stackstorm_client
            execution = await client.execute_action(action)

            execution_id = execution.get("id", "")
            result.stackstorm_execution_id = execution_id
            attempt.execution_id = execution_id

            # Wait for completion if configured
            if action.timeout > 0:
                final_execution = await client.wait_for_execution(
                    execution_id,
                    timeout=action.timeout,
                )

                status = final_execution.get("status", "")
                if status == "succeeded":
                    result.status = RemediationStatus.SUCCESS
                    result.output = final_execution.get("result", {})
                    attempt.status = "success"
                else:
                    result.status = RemediationStatus.FAILED
                    result.error = final_execution.get("result", {}).get(
                        "stderr", f"Execution {status}"
                    )
                    attempt.status = "failed"
                    attempt.error = result.error
            else:
                # Fire and forget
                result.status = RemediationStatus.SUCCESS
                result.output = {"execution_id": execution_id}
                attempt.status = "success"

            log.info(
                "Remediation action completed",
                status=result.status,
                execution_id=execution_id,
            )

        except StackStormError as e:
            result.status = RemediationStatus.FAILED
            result.error = str(e)
            attempt.status = "failed"
            attempt.error = str(e)
            log.error("Remediation action failed", error=str(e))

        except Exception as e:
            result.status = RemediationStatus.FAILED
            result.error = f"Unexpected error: {e}"
            attempt.status = "failed"
            attempt.error = result.error
            log.exception("Unexpected error during remediation")

        finally:
            result.completed_at = datetime.now(timezone.utc)
            attempt.completed_at = result.completed_at

            # Update tracked alert with attempt
            tracked.add_remediation_attempt(attempt)
            if result.error:
                tracked.last_error = result.error
            await self._state_store.save_alert(tracked)

        return result

    async def get_tracked_alerts(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[TrackedAlert]:
        """Get tracked alerts from state store."""
        return await self._state_store.list_alerts(status=status, limit=limit)

    async def get_tracked_alert(self, fingerprint: str) -> TrackedAlert | None:
        """Get a specific tracked alert."""
        return await self._state_store.get_alert(fingerprint)

    async def get_alert_stats(self) -> dict[str, Any]:
        """Get statistics about tracked alerts."""
        stats = await self._state_store.get_stats()
        return {
            "total": stats.total,
            "by_status": stats.by_status,
            "by_severity": stats.by_severity,
        }

    def get_active_remediations(self) -> list[RemediationResult]:
        """Get all currently active remediations (deprecated - use get_tracked_alerts)."""
        # This is kept for backwards compatibility
        return []

    def get_history(self, limit: int = 100) -> list[RemediationResult]:
        """Get remediation history (deprecated - use get_tracked_alerts)."""
        # This is kept for backwards compatibility
        return []

    async def health_check(self) -> dict[str, Any]:
        """Check the health of the remediation engine."""
        stackstorm_healthy = await self._registry.stackstorm_client.health_check()
        state_store_healthy = await self._state_store.health_check()

        overall_healthy = stackstorm_healthy and state_store_healthy

        return {
            "status": "healthy" if overall_healthy else "degraded",
            "stackstorm": stackstorm_healthy,
            "state_store": state_store_healthy,
            "handlers": len(self._registry.list_handlers()),
        }


# Global engine instance
_engine: RemediationEngine | None = None


def get_engine() -> RemediationEngine:
    """Get the global remediation engine."""
    global _engine
    if _engine is None:
        _engine = RemediationEngine()
    return _engine


def set_engine(engine: RemediationEngine) -> None:
    """Set the global remediation engine instance."""
    global _engine
    _engine = engine
