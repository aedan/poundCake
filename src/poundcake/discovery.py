"""Kubernetes service discovery and StackStorm auto-configuration."""

import os
from pathlib import Path

import httpx
import structlog

from poundcake.config import get_settings

logger = structlog.get_logger(__name__)


class StackStormDiscovery:
    """Discover and configure StackStorm connection automatically."""

    def __init__(self) -> None:
        """Initialize the discovery service."""
        self.settings = get_settings()
        self._k8s_token: str | None = None
        self._k8s_ca_cert: str | None = None
        self._in_cluster = self._check_in_cluster()

    def _check_in_cluster(self) -> bool:
        """Check if running inside a Kubernetes cluster."""
        return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")

    def _load_k8s_credentials(self) -> None:
        """Load Kubernetes service account credentials."""
        if not self._in_cluster:
            return

        token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        ca_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")

        if token_path.exists():
            self._k8s_token = token_path.read_text().strip()
        if ca_path.exists():
            self._k8s_ca_cert = str(ca_path)

    async def discover_stackstorm(self) -> str | None:
        """
        Discover StackStorm service in the Kubernetes cluster.

        Returns:
            StackStorm API URL if found, None otherwise
        """
        if not self._in_cluster:
            logger.debug("Not running in Kubernetes, skipping discovery")
            return None

        self._load_k8s_credentials()

        if not self._k8s_token:
            logger.warning("No Kubernetes token available")
            return None

        # Get current namespace
        namespace_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
        current_namespace = (
            namespace_path.read_text().strip() if namespace_path.exists() else "default"
        )

        # Common StackStorm service names and namespaces to check
        search_locations = [
            ("stackstorm", "stackstorm-api"),
            ("stackstorm", "stackstorm"),
            ("st2", "stackstorm-api"),
            ("st2", "stackstorm"),
            (current_namespace, "stackstorm-api"),
            (current_namespace, "stackstorm"),
        ]

        k8s_host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        k8s_port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")

        async with httpx.AsyncClient(
            verify=self._k8s_ca_cert or False,
            timeout=httpx.Timeout(10),
        ) as client:
            for namespace, service_name in search_locations:
                try:
                    url = f"https://{k8s_host}:{k8s_port}/api/v1/namespaces/{namespace}/services/{service_name}"
                    response = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {self._k8s_token}"},
                    )

                    if response.status_code == 200:
                        service = response.json()
                        port = 443
                        for port_spec in service.get("spec", {}).get("ports", []):
                            if port_spec.get("name") in ("https", "api"):
                                port = port_spec.get("port", 443)
                                break

                        stackstorm_url = (
                            f"https://{service_name}.{namespace}.svc.cluster.local:{port}"
                        )
                        logger.info(
                            "Discovered StackStorm service",
                            url=stackstorm_url,
                            namespace=namespace,
                            service=service_name,
                        )
                        return stackstorm_url

                except Exception as e:
                    logger.debug(
                        "Failed to check service",
                        namespace=namespace,
                        service=service_name,
                        error=str(e),
                    )

        logger.warning("StackStorm service not found in cluster")
        return None

    async def validate_api_key(self, url: str, api_key: str) -> bool:
        """
        Validate that an API key works with StackStorm.

        Args:
            url: StackStorm API URL
            api_key: API key to validate

        Returns:
            True if the API key is valid
        """
        async with httpx.AsyncClient(
            verify=self.settings.stackstorm_verify_ssl,
            timeout=httpx.Timeout(10),
        ) as client:
            try:
                response = await client.get(
                    f"{url.rstrip('/')}/v1/actions",
                    headers={
                        "St2-Api-Key": api_key,
                        "Content-Type": "application/json",
                    },
                    params={"limit": 1},
                )
                return response.status_code == 200

            except Exception as e:
                logger.error("API key validation failed", error=str(e))
                return False

    async def generate_api_key(
        self,
        url: str,
        username: str,
        password: str,
    ) -> str | None:
        """
        Generate a new StackStorm API key.

        Args:
            url: StackStorm API URL
            username: StackStorm admin username
            password: StackStorm admin password

        Returns:
            The generated API key, or None if failed
        """
        async with httpx.AsyncClient(
            verify=self.settings.stackstorm_verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            try:
                # Use separate auth URL if configured, otherwise use main URL
                auth_url = self.settings.stackstorm_auth_url or url

                # First, authenticate to get a token
                auth_response = await client.post(
                    f"{auth_url.rstrip('/')}/auth/v1/tokens",
                    auth=(username, password),
                )

                if auth_response.status_code != 201:
                    logger.error(
                        "Failed to authenticate with StackStorm",
                        status=auth_response.status_code,
                    )
                    return None

                auth_token = auth_response.json().get("token")

                # Now create an API key
                key_response = await client.post(
                    f"{url.rstrip('/')}/v1/apikeys",
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

    async def auto_configure(self) -> tuple[str | None, str | None]:
        """
        Automatically discover and configure StackStorm connection.

        Returns:
            Tuple of (url, api_key) if successful
        """
        # Check if already configured
        if self.settings.stackstorm_api_key:
            url = self.settings.stackstorm_url
            if await self.validate_api_key(url, self.settings.stackstorm_api_key):
                logger.info("Existing API key is valid")
                return url, self.settings.stackstorm_api_key
            else:
                logger.warning("Existing API key is invalid")

        # Try to discover StackStorm
        discovered_url = await self.discover_stackstorm()
        if not discovered_url:
            discovered_url = self.settings.stackstorm_url

        # Check for admin credentials to generate API key
        admin_user = os.environ.get("POUNDCAKE_STACKSTORM_ADMIN_USER", "st2admin")
        admin_pass = os.environ.get("POUNDCAKE_STACKSTORM_ADMIN_PASSWORD", "")

        if admin_pass:
            api_key = await self.generate_api_key(discovered_url, admin_user, admin_pass)
            if api_key:
                return discovered_url, api_key

        return discovered_url, None
