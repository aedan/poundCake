"""Prometheus API client for fetching and managing alert rules."""

from typing import Any

import httpx
import structlog

from poundcake.config import get_settings

logger = structlog.get_logger(__name__)


class PrometheusClient:
    """Client for interacting with Prometheus API."""

    def __init__(self) -> None:
        """Initialize the Prometheus client."""
        settings = get_settings()
        self.base_url = settings.prometheus_url.rstrip("/")
        self.verify_ssl = settings.prometheus_verify_ssl

    async def get_rules(self) -> list[dict[str, Any]]:
        """
        Fetch all alert rules from Prometheus.

        Returns:
            List of alert rule groups with their rules
        """
        try:
            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(30),
            ) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/rules",
                    params={"type": "alert"},
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        groups = data.get("data", {}).get("groups", [])
                        return self._flatten_rules(groups)
                    else:
                        logger.error(
                            "Prometheus API returned error",
                            error=data.get("error"),
                        )
                        return []
                else:
                    logger.error(
                        "Failed to fetch Prometheus rules",
                        status_code=response.status_code,
                        response=response.text,
                    )
                    return []
        except Exception as e:
            logger.error("Error fetching Prometheus rules", error=str(e))
            return []

    def _flatten_rules(self, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Flatten rule groups into a list of individual rules.

        Args:
            groups: List of rule groups from Prometheus API

        Returns:
            List of individual alert rules with group context
        """
        rules = []
        for group in groups:
            group_name = group.get("name", "")
            group_file = group.get("file", "")
            group_interval = group.get("interval", 0)

            for rule in group.get("rules", []):
                if rule.get("type") == "alerting":
                    rules.append(
                        {
                            "group": group_name,
                            "file": group_file,
                            "interval": group_interval,
                            "name": rule.get("name", ""),
                            "query": rule.get("query", ""),
                            "duration": rule.get("duration", 0),
                            "labels": rule.get("labels", {}),
                            "annotations": rule.get("annotations", {}),
                            "state": rule.get("state", "inactive"),
                            "health": rule.get("health", "unknown"),
                            "last_evaluation": rule.get("lastEvaluation", ""),
                            "evaluation_time": rule.get("evaluationTime", 0),
                        }
                    )
        return rules

    async def get_rule_groups(self) -> list[dict[str, Any]]:
        """
        Get all rule groups with their full structure.

        Returns:
            List of rule groups
        """
        try:
            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(30),
            ) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/rules",
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return data.get("data", {}).get("groups", [])  # type: ignore[no-any-return]
                    else:
                        logger.error(
                            "Prometheus API returned error",
                            error=data.get("error"),
                        )
                        return []
                else:
                    logger.error(
                        "Failed to fetch Prometheus rule groups",
                        status_code=response.status_code,
                    )
                    return []
        except Exception as e:
            logger.error("Error fetching Prometheus rule groups", error=str(e))
            return []

    async def health_check(self) -> dict[str, Any]:
        """
        Check if Prometheus is reachable.

        Returns:
            Health status information
        """
        try:
            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(10),
            ) as client:
                response = await client.get(f"{self.base_url}/-/healthy")
                return {
                    "status": "healthy" if response.status_code == 200 else "unhealthy",
                    "url": self.base_url,
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "url": self.base_url,
                "error": str(e),
            }

    async def reload_config(self) -> dict[str, Any]:
        """
        Reload Prometheus configuration.

        Note: Requires Prometheus to be started with --web.enable-lifecycle flag.

        Returns:
            Result of reload operation
        """
        settings = get_settings()

        if not settings.prometheus_reload_enabled:
            return {
                "status": "disabled",
                "message": "Prometheus reload is not enabled in settings",
            }

        try:
            reload_url = (
                settings.prometheus_reload_url
                if settings.prometheus_reload_url
                else f"{self.base_url}/-/reload"
            )

            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(30),
            ) as client:
                response = await client.post(reload_url)

                if response.status_code == 200:
                    logger.info("Prometheus configuration reloaded successfully")
                    return {
                        "status": "success",
                        "message": "Prometheus configuration reloaded",
                    }
                else:
                    logger.error(
                        "Failed to reload Prometheus",
                        status_code=response.status_code,
                        response=response.text,
                    )
                    return {
                        "status": "error",
                        "message": f"Failed to reload: {response.status_code}",
                        "detail": response.text,
                    }
        except Exception as e:
            logger.error("Error reloading Prometheus", error=str(e))
            return {
                "status": "error",
                "message": str(e),
            }

    async def get_metric_names(self) -> list[str]:
        """
        Fetch all available metric names from Prometheus.

        Returns:
            List of metric names
        """
        try:
            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(30),
            ) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/label/__name__/values",
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return data.get("data", [])  # type: ignore[no-any-return]
                    else:
                        logger.error(
                            "Prometheus API returned error",
                            error=data.get("error"),
                        )
                        return []
                else:
                    logger.error(
                        "Failed to fetch metric names",
                        status_code=response.status_code,
                    )
                    return []
        except Exception as e:
            logger.error("Error fetching metric names", error=str(e))
            return []

    async def get_label_names(self, metric: str | None = None) -> list[str]:
        """
        Fetch all available label names from Prometheus.

        Args:
            metric: Optional metric name to get labels for a specific metric

        Returns:
            List of label names
        """
        try:
            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(30),
            ) as client:
                # If metric is provided, get labels for that specific metric
                if metric:
                    # Query the series endpoint to get labels for this metric
                    response = await client.get(
                        f"{self.base_url}/api/v1/series",
                        params={"match[]": metric},
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "success":
                            # Extract unique label names from series data
                            label_names = set()
                            for series in data.get("data", []):
                                label_names.update(series.keys())
                            # Remove __name__ as it's always present
                            label_names.discard("__name__")
                            return sorted(list(label_names))
                else:
                    # Get all label names
                    response = await client.get(
                        f"{self.base_url}/api/v1/labels",
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "success":
                            labels = data.get("data", [])
                            # Remove __name__ as it's handled separately
                            return [
                                label for label in labels if label != "__name__"
                            ]

                logger.error(
                    "Failed to fetch label names",
                    status_code=response.status_code,
                )
                return []
        except Exception as e:
            logger.error("Error fetching label names", error=str(e))
            return []

    async def get_label_values(
        self,
        label_name: str,
        metric: str | None = None,
    ) -> list[str]:
        """
        Fetch all available values for a specific label.

        Args:
            label_name: The label name to get values for
            metric: Optional metric name to filter values

        Returns:
            List of label values
        """
        try:
            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(30),
            ) as client:
                if metric:
                    # Get label values for a specific metric
                    response = await client.get(
                        f"{self.base_url}/api/v1/series",
                        params={"match[]": metric},
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "success":
                            # Extract unique values for this label
                            values = set()
                            for series in data.get("data", []):
                                if label_name in series:
                                    values.add(series[label_name])
                            return sorted(list(values))
                else:
                    # Get all values for this label
                    response = await client.get(
                        f"{self.base_url}/api/v1/label/{label_name}/values",
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "success":
                            return data.get("data", [])  # type: ignore[no-any-return]

                logger.error(
                    "Failed to fetch label values",
                    label=label_name,
                    status_code=response.status_code,
                )
                return []
        except Exception as e:
            logger.error(
                "Error fetching label values",
                label=label_name,
                error=str(e),
            )
            return []


# Global client instance
_prometheus_client: PrometheusClient | None = None


def get_prometheus_client() -> PrometheusClient:
    """Get the global Prometheus client instance."""
    global _prometheus_client
    if _prometheus_client is None:
        _prometheus_client = PrometheusClient()
    return _prometheus_client
