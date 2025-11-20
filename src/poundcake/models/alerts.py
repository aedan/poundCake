"""Alert models for Prometheus Alertmanager payloads."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AlertStatus(str, Enum):
    """Alert status from Alertmanager."""

    FIRING = "firing"
    RESOLVED = "resolved"


class Alert(BaseModel):
    """Individual alert from Alertmanager."""

    status: AlertStatus
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime = Field(alias="endsAt")
    generator_url: str = Field(default="", alias="generatorURL")
    fingerprint: str = ""

    model_config = ConfigDict(populate_by_name=True)

    @property
    def alertname(self) -> str:
        """Get the alert name from labels."""
        return self.labels.get("alertname", "unknown")

    @property
    def severity(self) -> str:
        """Get the alert severity from labels."""
        return self.labels.get("severity", "unknown")

    @property
    def instance(self) -> str:
        """Get the instance from labels."""
        return self.labels.get("instance", "unknown")


class AlertmanagerPayload(BaseModel):
    """Webhook payload from Alertmanager."""

    version: str = "4"
    group_key: str = Field(default="", alias="groupKey")
    truncated_alerts: int = Field(default=0, alias="truncatedAlerts")
    status: AlertStatus
    receiver: str = ""
    group_labels: dict[str, str] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, str] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, str] = Field(default_factory=dict, alias="commonAnnotations")
    external_url: str = Field(default="", alias="externalURL")
    alerts: list[Alert] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)
