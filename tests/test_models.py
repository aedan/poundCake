"""Tests for data models."""

from datetime import datetime, timezone

from poundcake.models.alerts import Alert, AlertmanagerPayload, AlertStatus
from poundcake.models.remediation import (
    RemediationAction,
    RemediationResult,
    RemediationStatus,
)


class TestAlert:
    """Tests for Alert model."""

    def test_alert_from_dict(self) -> None:
        """Test creating an alert from dictionary."""
        alert = Alert(
            status="firing",  # type: ignore[arg-type]
            labels={
                "alertname": "HighCPU",
                "severity": "critical",
                "instance": "server1:9090",
            },
            annotations={
                "summary": "High CPU usage detected",
            },
            startsAt="2024-01-01T00:00:00Z",  # type: ignore[arg-type]
            endsAt="0001-01-01T00:00:00Z",  # type: ignore[arg-type]
            fingerprint="abc123",
        )

        assert alert.status == AlertStatus.FIRING
        assert alert.alertname == "HighCPU"
        assert alert.severity == "critical"
        assert alert.instance == "server1:9090"
        assert alert.fingerprint == "abc123"

    def test_alert_defaults(self) -> None:
        """Test alert default values."""
        alert = Alert(
            status=AlertStatus.FIRING,
            startsAt=datetime.now(timezone.utc),
            endsAt=datetime.now(timezone.utc),
        )

        assert alert.alertname == "unknown"
        assert alert.severity == "unknown"
        assert alert.instance == "unknown"


class TestAlertmanagerPayload:
    """Tests for AlertmanagerPayload model."""

    def test_payload_with_alerts(self) -> None:
        """Test creating a payload with alerts."""
        payload = AlertmanagerPayload(
            version="4",
            status="firing",  # type: ignore[arg-type]
            receiver="poundcake",
            alerts=[
                {  # type: ignore[list-item]
                    "status": "firing",
                    "labels": {"alertname": "Test"},
                    "annotations": {},
                    "startsAt": "2024-01-01T00:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                }
            ],
        )

        assert payload.status == AlertStatus.FIRING
        assert len(payload.alerts) == 1
        assert payload.alerts[0].alertname == "Test"


class TestRemediationAction:
    """Tests for RemediationAction model."""

    def test_action_with_parameters(self) -> None:
        """Test creating an action with parameters."""
        action = RemediationAction(
            name="restart_service",
            description="Restart the service",
            action="linux.service",
            parameters={"host": "server1", "service": "nginx"},
        )

        assert action.name == "restart_service"
        assert action.stackstorm_action == "linux.service"
        assert action.parameters["host"] == "server1"
        assert action.timeout == 300


class TestRemediationResult:
    """Tests for RemediationResult model."""

    def test_result_duration(self) -> None:
        """Test duration calculation."""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, 0, 1, 30, tzinfo=timezone.utc)

        result = RemediationResult(
            alert_fingerprint="abc123",
            alert_name="HighCPU",
            action_name="restart",
            status=RemediationStatus.SUCCESS,
            started_at=start,
            completed_at=end,
        )

        assert result.duration_seconds == 90.0

    def test_result_duration_not_completed(self) -> None:
        """Test duration when not completed."""
        result = RemediationResult(
            alert_fingerprint="abc123",
            alert_name="HighCPU",
            action_name="restart",
            status=RemediationStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )

        assert result.duration_seconds is None
