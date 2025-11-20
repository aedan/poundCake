"""Models for tracking alert lifecycle and state."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AlertTrackingStatus(str, Enum):
    """Status of a tracked alert through its lifecycle."""

    RECEIVED = "received"  # Alert just arrived from Alertmanager
    PENDING = "pending"  # Queued, waiting for remediation to start
    REMEDIATING = "remediating"  # Remediation action(s) currently executing
    REMEDIATED = "remediated"  # All remediation actions completed
    RESOLVED = "resolved"  # Alert cleared by Alertmanager


class RemediationAttempt(BaseModel):
    """Record of a single remediation action attempt."""

    action_name: str
    stackstorm_action: str
    status: str  # success, failed, running
    started_at: datetime
    completed_at: datetime | None = None
    execution_id: str | None = None
    error: str | None = None


class TrackedAlert(BaseModel):
    """A tracked alert with full lifecycle state."""

    # Alert identification
    fingerprint: str
    alertname: str
    instance: str | None = None
    severity: str | None = None

    # Alert metadata
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)

    # Lifecycle tracking
    status: AlertTrackingStatus = AlertTrackingStatus.RECEIVED
    received_at: datetime
    status_changed_at: datetime
    resolved_at: datetime | None = None

    # Remediation tracking
    remediation_attempts: list[RemediationAttempt] = Field(default_factory=list)
    total_attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0

    # Processing metadata
    processed_by: str | None = None  # Instance ID that processed this alert
    last_error: str | None = None

    def add_remediation_attempt(self, attempt: RemediationAttempt) -> None:
        """Add a remediation attempt and update counters."""
        self.remediation_attempts.append(attempt)
        self.total_attempts += 1
        if attempt.status == "success":
            self.successful_attempts += 1
        elif attempt.status == "failed":
            self.failed_attempts += 1

    def update_status(self, new_status: AlertTrackingStatus, timestamp: datetime) -> None:
        """Update the alert status with timestamp."""
        self.status = new_status
        self.status_changed_at = timestamp
        if new_status == AlertTrackingStatus.RESOLVED:
            self.resolved_at = timestamp

    def to_summary(self) -> dict[str, Any]:
        """Return a summary dict suitable for API responses."""
        return {
            "fingerprint": self.fingerprint,
            "alertname": self.alertname,
            "instance": self.instance,
            "severity": self.severity,
            "status": self.status.value,
            "received_at": self.received_at.isoformat(),
            "status_changed_at": self.status_changed_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "total_attempts": self.total_attempts,
            "successful_attempts": self.successful_attempts,
            "failed_attempts": self.failed_attempts,
            "last_error": self.last_error,
        }


class AlertStats(BaseModel):
    """Statistics about tracked alerts."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
