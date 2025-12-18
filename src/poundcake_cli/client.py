"""HTTP client for PoundCake API."""

from typing import Any, Optional

import httpx


class PoundCakeClient:
    """Client for interacting with PoundCake API."""

    def __init__(self, base_url: str, api_key: Optional[str] = None) -> None:
        """
        Initialize the PoundCake API client.

        Args:
            base_url: Base URL of the PoundCake API
            api_key: Optional API key for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Make an HTTP request to the API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: API path
            json: JSON body for POST/PUT requests
            params: Query parameters

        Returns:
            Response JSON

        Raises:
            httpx.HTTPError: If request fails
        """
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method=method,
                url=url,
                headers=self.headers,
                json=json,
                params=params,
            )
            response.raise_for_status()
            return response.json()

    # Alert management

    def list_alerts(
        self,
        status: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List alerts with optional filters."""
        params = {}
        if status:
            params["status"] = status
        if severity:
            params["severity"] = severity
        return self._request("GET", "/api/alerts", params=params)

    def get_alert(self, fingerprint: str) -> dict[str, Any]:
        """Get a specific alert by fingerprint."""
        return self._request("GET", f"/api/alerts/{fingerprint}")

    # Prometheus rule management

    def list_rules(self) -> list[dict[str, Any]]:
        """List all Prometheus rules."""
        return self._request("GET", "/api/prometheus/rules")

    def get_rule(self, crd_name: str, group_name: str, rule_name: str) -> dict[str, Any]:
        """Get a specific Prometheus rule."""
        return self._request(
            "GET",
            f"/api/prometheus/rules/{crd_name}/{group_name}/{rule_name}",
        )

    def create_rule(
        self,
        crd_name: str,
        group_name: str,
        rule_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new Prometheus rule."""
        return self._request(
            "POST",
            f"/api/prometheus/rules/{crd_name}/{group_name}/{rule_name}",
            json=rule_data,
        )

    def update_rule(
        self,
        crd_name: str,
        group_name: str,
        rule_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing Prometheus rule."""
        return self._request(
            "PUT",
            f"/api/prometheus/rules/{crd_name}/{group_name}/{rule_name}",
            json=rule_data,
        )

    def delete_rule(
        self,
        crd_name: str,
        group_name: str,
        rule_name: str,
    ) -> dict[str, Any]:
        """Delete a Prometheus rule."""
        return self._request(
            "DELETE",
            f"/api/prometheus/rules/{crd_name}/{group_name}/{rule_name}",
        )

    # Mapping management

    def list_mappings(self) -> dict[str, Any]:
        """List all alert-to-action mappings."""
        return self._request("GET", "/api/mappings")

    def get_mapping(self, alert_name: str) -> dict[str, Any]:
        """Get a specific mapping by alert name."""
        return self._request("GET", f"/api/mappings/{alert_name}")

    # StackStorm action management

    def list_st2_actions(
        self,
        pack: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List StackStorm actions."""
        params = {"limit": limit}
        if pack:
            params["pack"] = pack
        return self._request("GET", "/api/stackstorm/actions", params=params)

    def get_st2_action(self, action_ref: str) -> dict[str, Any]:
        """Get a specific StackStorm action."""
        return self._request("GET", f"/api/stackstorm/actions/{action_ref}")

    # Health checks

    def health(self) -> dict[str, Any]:
        """Check API health."""
        return self._request("GET", "/health")

    def ready(self) -> dict[str, Any]:
        """Check if API is ready."""
        return self._request("GET", "/ready")
