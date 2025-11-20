"""Tests for handlers."""

from datetime import datetime, timezone

import pytest

from poundcake.handlers.base import HandlerContext
from poundcake.handlers.registry import HandlerRegistry
from poundcake.handlers.yaml_config import YAMLConfigHandler
from poundcake.models.alerts import Alert, AlertStatus
from poundcake.stackstorm import StackStormClient


@pytest.fixture
def alert() -> Alert:
    """Create a test alert."""
    return Alert(
        status=AlertStatus.FIRING,
        labels={
            "alertname": "HighCPU",
            "severity": "critical",
            "instance": "server1:9090",
            "service": "nginx",
        },
        annotations={
            "summary": "High CPU usage",
        },
        startsAt=datetime.now(timezone.utc),
        endsAt=datetime.now(timezone.utc),
        fingerprint="test123",
    )


@pytest.fixture
def stackstorm_client() -> StackStormClient:
    """Create a mock StackStorm client."""
    return StackStormClient()


class TestHandlerRegistry:
    """Tests for HandlerRegistry."""

    def test_register_handler(self) -> None:
        """Test registering a handler."""
        registry = HandlerRegistry()
        handler = YAMLConfigHandler()

        registry.register(handler)

        assert "yaml_config" in registry.list_handlers()
        assert registry.get_handler("yaml_config") is handler

    def test_unregister_handler(self) -> None:
        """Test unregistering a handler."""
        registry = HandlerRegistry()
        handler = YAMLConfigHandler()

        registry.register(handler)
        registry.unregister("yaml_config")

        assert "yaml_config" not in registry.list_handlers()


class TestYAMLConfigHandler:
    """Tests for YAMLConfigHandler."""

    @pytest.mark.asyncio
    async def test_can_handle_with_config(
        self, alert: Alert, stackstorm_client: StackStormClient
    ) -> None:
        """Test can_handle returns True with valid config."""
        handler = YAMLConfigHandler()
        context = HandlerContext(
            alert=alert,
            config={
                "actions": [
                    {
                        "name": "test",
                        "action": "test.action",
                    }
                ]
            },
            stackstorm_client=stackstorm_client,
        )

        assert await handler.can_handle(context) is True

    @pytest.mark.asyncio
    async def test_can_handle_without_config(
        self, alert: Alert, stackstorm_client: StackStormClient
    ) -> None:
        """Test can_handle returns False without config."""
        handler = YAMLConfigHandler()
        context = HandlerContext(
            alert=alert,
            config={},
            stackstorm_client=stackstorm_client,
        )

        assert await handler.can_handle(context) is False

    @pytest.mark.asyncio
    async def test_get_actions(self, alert: Alert, stackstorm_client: StackStormClient) -> None:
        """Test getting actions from config."""
        handler = YAMLConfigHandler()
        context = HandlerContext(
            alert=alert,
            config={
                "actions": [
                    {
                        "name": "restart_service",
                        "action": "linux.service",
                        "parameters": {
                            "host": "{{instance}}",
                        },
                    }
                ]
            },
            stackstorm_client=stackstorm_client,
        )

        actions = await handler.get_actions(context)

        assert len(actions) == 1
        assert actions[0].name == "restart_service"
        assert actions[0].stackstorm_action == "linux.service"
        # Check template was applied
        assert actions[0].parameters["host"] == "server1:9090"

    @pytest.mark.asyncio
    async def test_condition_severity_match(
        self, alert: Alert, stackstorm_client: StackStormClient
    ) -> None:
        """Test action is included when severity matches."""
        handler = YAMLConfigHandler()
        context = HandlerContext(
            alert=alert,
            config={
                "actions": [
                    {
                        "name": "test",
                        "action": "test.action",
                        "conditions": {"severity": "critical"},
                    }
                ]
            },
            stackstorm_client=stackstorm_client,
        )

        actions = await handler.get_actions(context)
        assert len(actions) == 1

    @pytest.mark.asyncio
    async def test_condition_severity_no_match(
        self, alert: Alert, stackstorm_client: StackStormClient
    ) -> None:
        """Test action is excluded when severity doesn't match."""
        handler = YAMLConfigHandler()
        context = HandlerContext(
            alert=alert,
            config={
                "actions": [
                    {
                        "name": "test",
                        "action": "test.action",
                        "conditions": {"severity": "warning"},
                    }
                ]
            },
            stackstorm_client=stackstorm_client,
        )

        actions = await handler.get_actions(context)
        assert len(actions) == 0

    @pytest.mark.asyncio
    async def test_condition_has_labels(
        self, alert: Alert, stackstorm_client: StackStormClient
    ) -> None:
        """Test action is included when required labels exist."""
        handler = YAMLConfigHandler()
        context = HandlerContext(
            alert=alert,
            config={
                "actions": [
                    {
                        "name": "test",
                        "action": "test.action",
                        "conditions": {"has_labels": ["service"]},
                    }
                ]
            },
            stackstorm_client=stackstorm_client,
        )

        actions = await handler.get_actions(context)
        assert len(actions) == 1

    @pytest.mark.asyncio
    async def test_condition_missing_labels(
        self, alert: Alert, stackstorm_client: StackStormClient
    ) -> None:
        """Test action is excluded when required labels missing."""
        handler = YAMLConfigHandler()
        context = HandlerContext(
            alert=alert,
            config={
                "actions": [
                    {
                        "name": "test",
                        "action": "test.action",
                        "conditions": {"has_labels": ["missing_label"]},
                    }
                ]
            },
            stackstorm_client=stackstorm_client,
        )

        actions = await handler.get_actions(context)
        assert len(actions) == 0
