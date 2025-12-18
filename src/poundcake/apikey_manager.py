"""API key management for StackStorm with Kubernetes secret persistence."""

import base64
import os
from pathlib import Path
from typing import Any

import httpx
import structlog
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

from poundcake.config import get_settings

logger = structlog.get_logger(__name__)


class APIKeyManager:
    """Manage StackStorm API key with Kubernetes secret persistence."""

    def __init__(self) -> None:
        """Initialize the API key manager."""
        self.settings = get_settings()
        self._api_key: str | None = None
        self._in_cluster = self._check_in_cluster()
        self._k8s_core_api: Any | None = None

        if self._in_cluster:
            try:
                k8s_config.load_incluster_config()
                self._k8s_core_api = k8s_client.CoreV1Api()
            except Exception as e:
                logger.warning("Failed to load Kubernetes config", error=str(e))
                self._k8s_core_api = None

    def _check_in_cluster(self) -> bool:
        """Check if running inside a Kubernetes cluster."""
        return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")

    def _get_namespace(self) -> str:
        """Get the current namespace."""
        namespace_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
        if namespace_path.exists():
            return namespace_path.read_text().strip()
        return "default"

    async def _load_key_from_secret(self) -> str | None:
        """Load API key from Kubernetes secret."""
        if not self._k8s_core_api:
            return None

        try:
            namespace = self._get_namespace()
            secret = self._k8s_core_api.read_namespaced_secret(
                name="poundcake-stackstorm-key",
                namespace=namespace,
            )

            if secret.data and "api-key" in secret.data:
                api_key = base64.b64decode(secret.data["api-key"]).decode("utf-8")
                logger.info("Loaded API key from Kubernetes secret")
                return api_key

        except k8s_client.rest.ApiException as e:
            if e.status == 404:
                logger.debug("API key secret not found")
            else:
                logger.warning("Failed to read API key secret", error=str(e))
        except Exception as e:
            logger.error("Error loading API key from secret", error=str(e))

        return None

    async def _save_key_to_secret(self, api_key: str) -> bool:
        """Save API key to Kubernetes secret."""
        if not self._k8s_core_api:
            return False

        try:
            namespace = self._get_namespace()

            secret = k8s_client.V1Secret(
                metadata=k8s_client.V1ObjectMeta(
                    name="poundcake-stackstorm-key",
                    namespace=namespace,
                    labels={
                        "app.kubernetes.io/name": "poundcake",
                        "app.kubernetes.io/component": "stackstorm-integration",
                    },
                ),
                type="Opaque",
                data={
                    "api-key": base64.b64encode(api_key.encode("utf-8")).decode("utf-8"),
                },
            )

            try:
                # Try to update existing secret
                self._k8s_core_api.replace_namespaced_secret(
                    name="poundcake-stackstorm-key",
                    namespace=namespace,
                    body=secret,
                )
                logger.info("Updated API key in Kubernetes secret")
            except k8s_client.rest.ApiException as e:
                if e.status == 404:
                    # Create new secret
                    self._k8s_core_api.create_namespaced_secret(
                        namespace=namespace,
                        body=secret,
                    )
                    logger.info("Created API key in Kubernetes secret")
                else:
                    raise

            return True

        except Exception as e:
            logger.error("Failed to save API key to secret", error=str(e))
            return False

    async def _validate_key(self, api_key: str) -> bool:
        """Validate that an API key works with StackStorm."""
        async with httpx.AsyncClient(
            verify=self.settings.stackstorm_verify_ssl,
            timeout=httpx.Timeout(10),
        ) as http_client:
            try:
                response = await http_client.get(
                    f"{self.settings.stackstorm_url.rstrip('/')}/v1/actions",
                    headers={
                        "St2-Api-Key": api_key,
                        "Content-Type": "application/json",
                    },
                    params={"limit": 1},
                )
                return response.status_code == 200  # type: ignore[no-any-return]

            except Exception as e:
                logger.debug("API key validation failed", error=str(e))
                return False

    async def _generate_key(self, username: str, password: str) -> str | None:
        """Generate a new StackStorm API key."""
        auth_url = self.settings.stackstorm_auth_url or self.settings.stackstorm_url

        async with httpx.AsyncClient(
            verify=self.settings.stackstorm_verify_ssl,
            timeout=httpx.Timeout(30),
        ) as http_client:
            try:
                # Authenticate to get a token
                auth_response = await http_client.post(
                    f"{auth_url.rstrip('/')}/v1/tokens",
                    auth=(username, password),
                )

                if auth_response.status_code != 201:
                    logger.error(
                        "Failed to authenticate with StackStorm",
                        status=auth_response.status_code,
                        response=auth_response.text,
                    )
                    return None

                auth_token = auth_response.json().get("token")

                # Create an API key
                key_response = await http_client.post(
                    f"{self.settings.stackstorm_url.rstrip('/')}/v1/apikeys",
                    headers={
                        "X-Auth-Token": auth_token,
                        "Content-Type": "application/json",
                    },
                    json={
                        "metadata": {
                            "used_by": "poundcake",
                            "purpose": "auto-remediation",
                            "auto_generated": "true",
                        },
                    },
                )

                if key_response.status_code == 201:
                    api_key: str | None = key_response.json().get("key")
                    logger.info("Generated new StackStorm API key")
                    return api_key
                else:
                    logger.error(
                        "Failed to generate API key",
                        status=key_response.status_code,
                        response=key_response.text,
                    )
                    return None

            except Exception as e:
                logger.error("API key generation failed", error=str(e))
                return None

    async def get_api_key(self) -> str | None:
        """
        Get a valid API key, loading from secret or generating new one.

        Returns:
            Valid API key or None if unavailable
        """
        # Return cached key if available
        if self._api_key:
            return self._api_key

        # Check environment variable first
        env_key = os.environ.get("POUNDCAKE_STACKSTORM_API_KEY", "")
        if env_key:
            if await self._validate_key(env_key):
                logger.info("Using API key from environment variable")
                self._api_key = env_key
                return self._api_key
            else:
                logger.warning("API key from environment is invalid")

        # Try to load from Kubernetes secret
        secret_key = await self._load_key_from_secret()
        if secret_key:
            if await self._validate_key(secret_key):
                self._api_key = secret_key
                return self._api_key
            else:
                logger.warning("API key from secret is invalid, will regenerate")

        # Generate new API key if we have admin credentials
        admin_user = os.environ.get("POUNDCAKE_STACKSTORM_ADMIN_USER", "")
        admin_password = os.environ.get("POUNDCAKE_STACKSTORM_ADMIN_PASSWORD", "")

        if admin_user and admin_password:
            new_key = await self._generate_key(admin_user, admin_password)
            if new_key:
                # Save to secret for future use
                await self._save_key_to_secret(new_key)
                self._api_key = new_key
                return self._api_key

        logger.error(
            "Unable to obtain valid API key - no valid key found and cannot generate new one"
        )
        return None

    async def refresh_key(self) -> str | None:
        """
        Force refresh of the API key by generating a new one.

        Returns:
            New API key or None if failed
        """
        admin_user = os.environ.get("POUNDCAKE_STACKSTORM_ADMIN_USER", "")
        admin_password = os.environ.get("POUNDCAKE_STACKSTORM_ADMIN_PASSWORD", "")

        if not admin_user or not admin_password:
            logger.error("Cannot refresh API key - admin credentials not available")
            return None

        logger.info("Refreshing StackStorm API key")
        new_key = await self._generate_key(admin_user, admin_password)

        if new_key:
            await self._save_key_to_secret(new_key)
            self._api_key = new_key
            return new_key

        return None


# Global instance
_api_key_manager: APIKeyManager | None = None


def get_api_key_manager() -> APIKeyManager:
    """Get the global API key manager instance."""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager()
    return _api_key_manager
