"""Remediation models for StackStorm actions."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RemediationStatus(str, Enum):
    """Status of a remediation action."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class RemediationAction(BaseModel):
    """Definition of a remediation action to execute."""

    name: str
    description: str = ""
    stackstorm_action: str = Field(alias="action")
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout: int = 300  # seconds
    retry_count: int = 0
    retry_delay: int = 30  # seconds

    model_config = ConfigDict(populate_by_name=True)


class RemediationResult(BaseModel):
    """Result of a remediation action execution."""

    alert_fingerprint: str
    alert_name: str
    action_name: str
    status: RemediationStatus
    started_at: datetime
    completed_at: datetime | None = None
    stackstorm_execution_id: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        """Calculate the duration of the remediation."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
