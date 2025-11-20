"""Tests for API endpoints."""

import pytest
from fastapi.testclient import TestClient

from poundcake.api import create_app


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    app = create_app()
    return TestClient(app)


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health(self, client: TestClient) -> None:
        """Test health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_handlers_list(self, client: TestClient) -> None:
        """Test listing handlers."""
        response = client.get("/handlers")
        assert response.status_code == 200
        data = response.json()
        assert "handlers" in data
        assert isinstance(data["handlers"], list)


class TestWebhookEndpoint:
    """Tests for webhook endpoint."""

    def test_webhook_empty_alerts(self, client: TestClient) -> None:
        """Test webhook with no alerts."""
        payload = {
            "version": "4",
            "status": "firing",
            "alerts": [],
        }

        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["alerts_received"] == 0

    def test_webhook_with_alert(self, client: TestClient) -> None:
        """Test webhook with an alert."""
        payload = {
            "version": "4",
            "status": "firing",
            "receiver": "poundcake",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "TestAlert",
                        "severity": "warning",
                        "instance": "localhost:9090",
                    },
                    "annotations": {
                        "summary": "Test alert",
                    },
                    "startsAt": "2024-01-01T00:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                    "fingerprint": "test123",
                }
            ],
        }

        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["alerts_received"] == 1

    def test_webhook_resolved_alert(self, client: TestClient) -> None:
        """Test webhook with resolved alert (should be skipped)."""
        payload = {
            "version": "4",
            "status": "resolved",
            "alerts": [
                {
                    "status": "resolved",
                    "labels": {"alertname": "TestAlert"},
                    "annotations": {},
                    "startsAt": "2024-01-01T00:00:00Z",
                    "endsAt": "2024-01-01T00:05:00Z",
                    "fingerprint": "test123",
                }
            ],
        }

        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["alerts_received"] == 1
        assert len(data["remediations"]) == 0  # Resolved alerts are skipped


class TestRemediationsEndpoint:
    """Tests for remediations endpoint."""

    def test_list_remediations(self, client: TestClient) -> None:
        """Test listing remediations."""
        response = client.get("/remediations")
        assert response.status_code == 200
        data = response.json()
        assert "remediations" in data
        assert isinstance(data["remediations"], list)

    def test_list_active_remediations(self, client: TestClient) -> None:
        """Test listing active remediations."""
        response = client.get("/remediations?active=true")
        assert response.status_code == 200
        data = response.json()
        assert "remediations" in data
