"""StackStorm API client for executing remediation actions."""

from typing import Any

import httpx
import structlog

from poundcake.config import get_settings
from poundcake.models.remediation import RemediationAction

logger = structlog.get_logger(__name__)


class StackStormError(Exception):
    """Exception raised for StackStorm API errors."""

    pass


class StackStormClient:
    """Client for interacting with StackStorm API."""

    def __init__(self) -> None:
        """Initialize the StackStorm client."""
        settings = get_settings()
        self.base_url = settings.stackstorm_url.rstrip("/")
        self.api_key = settings.stackstorm_api_key
        self.auth_token = settings.stackstorm_auth_token
        self.verify_ssl = settings.stackstorm_verify_ssl

        # Build headers
        self.headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            self.headers["St2-Api-Key"] = self.api_key
        elif self.auth_token:
            self.headers["X-Auth-Token"] = self.auth_token

    async def execute_action(
        self,
        action: RemediationAction,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a StackStorm action.

        Args:
            action: The remediation action to execute
            parameters: Additional parameters to merge with action parameters

        Returns:
            The execution result from StackStorm
        """
        merged_params = {**action.parameters}
        if parameters:
            merged_params.update(parameters)

        payload = {
            "action": action.stackstorm_action,
            "parameters": merged_params,
        }

        log = logger.bind(
            action=action.stackstorm_action,
            parameters=merged_params,
        )

        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=httpx.Timeout(action.timeout),
        ) as client:
            try:
                log.info("Executing StackStorm action")

                response = await client.post(
                    f"{self.base_url}/api/v1/executions",
                    headers=self.headers,
                    json=payload,
                )

                if response.status_code == 201:
                    result: dict[str, Any] = response.json()
                    log.info(
                        "Action execution started",
                        execution_id=result.get("id"),
                    )
                    return result
                else:
                    error_msg = f"StackStorm API error: {response.status_code} - {response.text}"
                    log.error(error_msg)
                    raise StackStormError(error_msg)

            except httpx.TimeoutException as e:
                error_msg = f"StackStorm request timed out after {action.timeout}s"
                log.error(error_msg, error=str(e))
                raise StackStormError(error_msg) from e

            except httpx.RequestError as e:
                error_msg = f"StackStorm request failed: {e}"
                log.error(error_msg)
                raise StackStormError(error_msg) from e

    async def get_execution(self, execution_id: str) -> dict[str, Any]:
        """
        Get the status of a StackStorm execution.

        Args:
            execution_id: The execution ID to check

        Returns:
            The execution details
        """
        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/executions/{execution_id}",
                headers=self.headers,
            )

            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                return result
            else:
                raise StackStormError(
                    f"Failed to get execution {execution_id}: {response.status_code}"
                )

    async def wait_for_execution(
        self,
        execution_id: str,
        timeout: int = 300,
        poll_interval: int = 2,
    ) -> dict[str, Any]:
        """
        Wait for a StackStorm execution to complete.

        Args:
            execution_id: The execution ID to wait for
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks

        Returns:
            The final execution result
        """
        import asyncio

        elapsed = 0
        while elapsed < timeout:
            result = await self.get_execution(execution_id)
            status = result.get("status", "")

            if status in ("succeeded", "failed", "timeout", "abandoned", "canceled"):
                return result

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise StackStormError(f"Execution {execution_id} timed out after {timeout}s")

    async def health_check(self) -> bool:
        """Check if StackStorm API is accessible."""
        async with httpx.AsyncClient(
            verify=self.verify_ssl,
            timeout=httpx.Timeout(10),
        ) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/api/v1/actions",
                    headers=self.headers,
                    params={"limit": 1},
                )
                return response.status_code == 200
            except Exception as e:
                logger.error("StackStorm health check failed", error=str(e))
                return False
