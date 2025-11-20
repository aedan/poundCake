"""Example remediation handlers for common scenarios."""

from typing import TYPE_CHECKING

import structlog

from poundcake.handlers.base import BaseHandler, HandlerContext
from poundcake.models.remediation import RemediationAction

if TYPE_CHECKING:
    from poundcake.handlers.registry import HandlerRegistry

logger = structlog.get_logger(__name__)


class HighCPUHandler(BaseHandler):
    """Handler for high CPU usage alerts."""

    @property
    def name(self) -> str:
        return "high_cpu"

    @property
    def description(self) -> str:
        return "Handles high CPU usage alerts by restarting services or scaling"

    async def can_handle(self, context: HandlerContext) -> bool:
        """Check if this is a CPU-related alert."""
        alertname = context.alert.alertname.lower()
        return any(keyword in alertname for keyword in ["cpu", "processor", "load"])

    async def get_actions(self, context: HandlerContext) -> list[RemediationAction]:
        """Get CPU remediation actions based on severity."""
        actions = []
        severity = context.alert.severity

        if severity in ["warning", "critical"]:
            # First, try to identify the problematic process
            actions.append(
                RemediationAction(
                    name="identify_high_cpu_process",
                    description="Identify the process consuming high CPU",
                    action="linux.top",
                    parameters={
                        "host": context.alert.instance,
                        **self.build_parameters(context),
                    },
                )
            )

        if severity == "critical":
            # For critical, also consider restarting the service
            service = context.alert.labels.get("service", "")
            if service:
                actions.append(
                    RemediationAction(
                        name=f"restart_{service}",
                        description=f"Restart the {service} service",
                        action="linux.service",
                        parameters={
                            "host": context.alert.instance,
                            "service": service,
                            "action": "restart",
                            **self.build_parameters(context),
                        },
                    )
                )

        return actions


class DiskSpaceHandler(BaseHandler):
    """Handler for disk space alerts."""

    @property
    def name(self) -> str:
        return "disk_space"

    @property
    def description(self) -> str:
        return "Handles disk space alerts by cleaning up and expanding storage"

    async def can_handle(self, context: HandlerContext) -> bool:
        """Check if this is a disk space alert."""
        alertname = context.alert.alertname.lower()
        return any(keyword in alertname for keyword in ["disk", "storage", "filesystem", "space"])

    async def get_actions(self, context: HandlerContext) -> list[RemediationAction]:
        """Get disk cleanup actions."""
        actions = []
        mount_point = context.alert.labels.get("mountpoint", "/")

        # Clean up old log files
        actions.append(
            RemediationAction(
                name="cleanup_old_logs",
                description="Remove old log files to free up space",
                action="linux.rm",
                parameters={
                    "host": context.alert.instance,
                    "target": f"{mount_point}/var/log/*.gz",
                    "force": True,
                    **self.build_parameters(context),
                },
            )
        )

        # Clean up package cache
        actions.append(
            RemediationAction(
                name="cleanup_package_cache",
                description="Clean up package manager cache",
                action="linux.apt_clean",
                parameters={
                    "host": context.alert.instance,
                    **self.build_parameters(context),
                },
            )
        )

        return actions


class ServiceDownHandler(BaseHandler):
    """Handler for service down alerts."""

    @property
    def name(self) -> str:
        return "service_down"

    @property
    def description(self) -> str:
        return "Handles service down alerts by restarting the service"

    async def can_handle(self, context: HandlerContext) -> bool:
        """Check if this is a service down alert."""
        alertname = context.alert.alertname.lower()
        return any(keyword in alertname for keyword in ["down", "unavailable", "unhealthy", "dead"])

    async def get_actions(self, context: HandlerContext) -> list[RemediationAction]:
        """Get service restart actions."""
        actions = []
        service = context.alert.labels.get("service", "")
        job = context.alert.labels.get("job", "")

        target_service = service or job

        if target_service:
            # Check service status first
            actions.append(
                RemediationAction(
                    name=f"check_{target_service}_status",
                    description=f"Check status of {target_service}",
                    action="linux.service",
                    parameters={
                        "host": context.alert.instance,
                        "service": target_service,
                        "action": "status",
                        **self.build_parameters(context),
                    },
                )
            )

            # Restart the service
            actions.append(
                RemediationAction(
                    name=f"restart_{target_service}",
                    description=f"Restart {target_service} service",
                    action="linux.service",
                    parameters={
                        "host": context.alert.instance,
                        "service": target_service,
                        "action": "restart",
                        **self.build_parameters(context),
                    },
                )
            )

        return actions


class MemoryHandler(BaseHandler):
    """Handler for memory usage alerts."""

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return "Handles memory usage alerts by clearing caches and restarting services"

    async def can_handle(self, context: HandlerContext) -> bool:
        """Check if this is a memory alert."""
        alertname = context.alert.alertname.lower()
        return any(keyword in alertname for keyword in ["memory", "ram", "oom", "swap"])

    async def get_actions(self, context: HandlerContext) -> list[RemediationAction]:
        """Get memory remediation actions."""
        actions = []

        # Clear system caches
        actions.append(
            RemediationAction(
                name="clear_system_caches",
                description="Clear system memory caches",
                action="core.remote",
                parameters={
                    "hosts": context.alert.instance,
                    "cmd": "sync; echo 3 > /proc/sys/vm/drop_caches",
                    **self.build_parameters(context),
                },
            )
        )

        # If critical, identify memory-hungry processes
        if context.alert.severity == "critical":
            actions.append(
                RemediationAction(
                    name="identify_memory_hogs",
                    description="Identify processes consuming high memory",
                    action="core.remote",
                    parameters={
                        "hosts": context.alert.instance,
                        "cmd": "ps aux --sort=-%mem | head -20",
                        **self.build_parameters(context),
                    },
                )
            )

        return actions


def register_example_handlers(registry: "HandlerRegistry") -> None:
    """Register all example handlers with the registry."""
    handlers = [
        HighCPUHandler(),
        DiskSpaceHandler(),
        ServiceDownHandler(),
        MemoryHandler(),
    ]

    for handler in handlers:
        registry.register(handler)
