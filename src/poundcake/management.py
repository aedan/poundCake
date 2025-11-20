"""Management API for remediation mappings and StackStorm actions."""

from typing import TYPE_CHECKING, Any

import yaml
import structlog

if TYPE_CHECKING:
    from poundcake.stackstorm import StackStormClient

from poundcake.config import get_settings, load_all_mappings

logger = structlog.get_logger(__name__)


class MappingManager:
    """Manager for remediation mappings CRUD operations."""

    def __init__(self) -> None:
        """Initialize the mapping manager."""
        self.settings = get_settings()
        self._mappings_path = self.settings.mappings_path

    def list_mappings(self) -> dict[str, Any]:
        """
        List all remediation mappings.

        Returns:
            Dictionary of all mappings
        """
        return load_all_mappings(self._mappings_path)

    def get_mapping(self, alert_name: str) -> dict[str, Any] | None:
        """
        Get a specific mapping by alert name.

        Args:
            alert_name: The alert name to look up

        Returns:
            The mapping configuration or None
        """
        mappings = self.list_mappings()
        return mappings.get(alert_name)

    def create_mapping(
        self,
        alert_name: str,
        config: dict[str, Any],
        filename: str = "custom.yaml",
    ) -> bool:
        """
        Create a new remediation mapping.

        Args:
            alert_name: The alert name
            config: The mapping configuration
            filename: The YAML file to write to

        Returns:
            True if successful
        """
        file_path = self._mappings_path / filename

        # Load existing file or create new
        if file_path.exists():
            with open(file_path) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        if "alerts" not in data:
            data["alerts"] = {}

        if alert_name in data["alerts"]:
            logger.warning("Mapping already exists", alert_name=alert_name)
            return False

        data["alerts"][alert_name] = config

        with open(file_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        logger.info("Created mapping", alert_name=alert_name, file=filename)
        return True

    def update_mapping(
        self,
        alert_name: str,
        config: dict[str, Any],
    ) -> bool:
        """
        Update an existing remediation mapping.

        Args:
            alert_name: The alert name
            config: The new mapping configuration

        Returns:
            True if successful
        """
        # Find which file contains this mapping
        for yaml_file in self._mappings_path.glob("*.yaml"):
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}

            if "alerts" in data and alert_name in data["alerts"]:
                data["alerts"][alert_name] = config

                with open(yaml_file, "w") as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False)

                logger.info("Updated mapping", alert_name=alert_name, file=yaml_file.name)
                return True

        logger.warning("Mapping not found", alert_name=alert_name)
        return False

    def delete_mapping(self, alert_name: str) -> bool:
        """
        Delete a remediation mapping.

        Args:
            alert_name: The alert name to delete

        Returns:
            True if successful
        """
        for yaml_file in self._mappings_path.glob("*.yaml"):
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}

            if "alerts" in data and alert_name in data["alerts"]:
                del data["alerts"][alert_name]

                with open(yaml_file, "w") as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False)

                logger.info("Deleted mapping", alert_name=alert_name, file=yaml_file.name)
                return True

        logger.warning("Mapping not found for deletion", alert_name=alert_name)
        return False

    def export_mappings(self) -> str:
        """
        Export all mappings as YAML.

        Returns:
            YAML string of all mappings
        """
        mappings = self.list_mappings()
        return yaml.dump({"alerts": mappings}, default_flow_style=False, sort_keys=False)

    def import_mappings(
        self,
        yaml_content: str,
        filename: str = "imported.yaml",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """
        Import mappings from YAML content.

        Args:
            yaml_content: YAML string to import
            filename: File to write to
            overwrite: Whether to overwrite existing mappings

        Returns:
            Summary of imported mappings
        """
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            return {"error": f"Invalid YAML: {e}", "imported": 0}

        if not data or "alerts" not in data:
            return {"error": "No alerts found in YAML", "imported": 0}

        existing = self.list_mappings()
        imported = 0
        skipped = 0

        for alert_name, config in data["alerts"].items():
            if alert_name in existing and not overwrite:
                skipped += 1
                continue

            if alert_name in existing:
                self.update_mapping(alert_name, config)
            else:
                self.create_mapping(alert_name, config, filename)
            imported += 1

        return {
            "imported": imported,
            "skipped": skipped,
            "total": len(data["alerts"]),
        }


class StackStormActionManager:
    """Manager for viewing StackStorm actions."""

    def __init__(self, client: "StackStormClient") -> None:
        """Initialize with a StackStorm client."""
        self._client = client

    async def list_actions(
        self,
        pack: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        List available StackStorm actions.

        Args:
            pack: Filter by pack name
            limit: Maximum number of actions to return

        Returns:
            List of action definitions
        """
        import httpx

        params: dict[str, Any] = {"limit": limit}
        if pack:
            params["pack"] = pack

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self._client.base_url}/api/v1/actions",
                headers=self._client.headers,
                params=params,
            )

            if response.status_code == 200:
                result: list[dict[str, Any]] = response.json()
                return result
            return []

    async def get_action(self, action_ref: str) -> dict[str, Any] | None:
        """
        Get details of a specific action.

        Args:
            action_ref: Action reference (pack.action)

        Returns:
            Action definition or None
        """
        import httpx

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self._client.base_url}/api/v1/actions/{action_ref}",
                headers=self._client.headers,
            )

            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                return result
            return None

    async def list_packs(self) -> list[dict[str, Any]]:
        """
        List available StackStorm packs.

        Returns:
            List of pack definitions
        """
        import httpx

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self._client.base_url}/api/v1/packs",
                headers=self._client.headers,
            )

            if response.status_code == 200:
                result: list[dict[str, Any]] = response.json()
                return result
            return []

    async def get_execution_history(
        self,
        limit: int = 50,
        action: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get StackStorm execution history.

        Args:
            limit: Maximum number of executions
            action: Filter by action reference

        Returns:
            List of executions
        """
        import httpx

        params: dict[str, Any] = {"limit": limit, "sort_desc": "start_timestamp"}
        if action:
            params["action"] = action

        async with httpx.AsyncClient(
            verify=self._client.verify_ssl,
            timeout=httpx.Timeout(30),
        ) as client:
            response = await client.get(
                f"{self._client.base_url}/api/v1/executions",
                headers=self._client.headers,
                params=params,
            )

            if response.status_code == 200:
                result: list[dict[str, Any]] = response.json()
                return result
            return []


# Global manager instance
_mapping_manager: MappingManager | None = None


def get_mapping_manager() -> MappingManager:
    """Get the global mapping manager."""
    global _mapping_manager
    if _mapping_manager is None:
        _mapping_manager = MappingManager()
    return _mapping_manager
