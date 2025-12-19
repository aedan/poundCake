"""Prometheus Operator CRD manager for PrometheusRule resources."""

from typing import Any

import structlog

from poundcake.config import get_settings

logger = structlog.get_logger(__name__)


class PrometheusCRDManager:
    """Manages Prometheus Operator PrometheusRule CRDs."""

    def __init__(self) -> None:
        """Initialize the CRD manager."""
        self.settings = get_settings()
        self.k8s_client = None
        self.custom_api = None

        if self.settings.prometheus_use_crds:
            try:
                from kubernetes import client, config

                try:
                    config.load_incluster_config()
                    logger.info("Loaded in-cluster Kubernetes config")
                except Exception:
                    config.load_kube_config()
                    logger.info("Loaded kubeconfig from file")

                self.k8s_client = client.ApiClient()
                self.custom_api = client.CustomObjectsApi(self.k8s_client)
            except ImportError:
                logger.error(
                    "kubernetes package not installed. Install with: pip install kubernetes"
                )
            except Exception as e:
                logger.error("Failed to initialize Kubernetes client", error=str(e))

    async def get_prometheus_rules(self) -> list[dict[str, Any]]:
        """
        Get all PrometheusRule CRDs from Kubernetes.

        Returns:
            List of PrometheusRule resources
        """
        if not self.custom_api:
            logger.warning("Kubernetes client not initialized")
            return []

        try:
            response = self.custom_api.list_namespaced_custom_object(
                group="monitoring.coreos.com",
                version="v1",
                namespace=self.settings.prometheus_crd_namespace,
                plural="prometheusrules",
            )

            rules = response.get("items", [])
            logger.info("Fetched PrometheusRule CRDs", count=len(rules))
            return rules  # type: ignore[no-any-return]
        except Exception as e:
            logger.error("Failed to fetch PrometheusRule CRDs", error=str(e))
            return []

    async def get_prometheus_rule(self, name: str) -> dict[str, Any] | None:
        """
        Get a specific PrometheusRule CRD.

        Args:
            name: Name of the PrometheusRule resource

        Returns:
            PrometheusRule resource or None
        """
        if not self.custom_api:
            return None

        try:
            rule = self.custom_api.get_namespaced_custom_object(
                group="monitoring.coreos.com",
                version="v1",
                namespace=self.settings.prometheus_crd_namespace,
                plural="prometheusrules",
                name=name,
            )
            return rule  # type: ignore[no-any-return]
        except Exception as e:
            logger.error("Failed to get PrometheusRule CRD", name=name, error=str(e))
            return None

    async def find_crd_containing_rule(
        self, rule_name: str, group_name: str
    ) -> dict[str, Any] | None:
        """
        Find which PrometheusRule CRD contains a specific alert rule.

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group

        Returns:
            The PrometheusRule CRD containing the rule, or None if not found
        """
        if not self.custom_api:
            return None

        try:
            all_crds = await self.get_prometheus_rules()

            for crd in all_crds:
                spec = crd.get("spec", {})
                groups = spec.get("groups", [])

                for group in groups:
                    if group.get("name") == group_name:
                        rules = group.get("rules", [])
                        for rule in rules:
                            if rule.get("alert") == rule_name:
                                logger.info(
                                    "Found rule in CRD",
                                    rule=rule_name,
                                    group=group_name,
                                    crd=crd["metadata"]["name"],
                                )
                                return crd

            logger.warning(
                "Rule not found in any CRD",
                rule=rule_name,
                group=group_name,
            )
            return None
        except Exception as e:
            logger.error(
                "Error finding CRD containing rule",
                rule=rule_name,
                error=str(e),
            )
            return None

    async def create_or_update_rule(
        self,
        rule_name: str,
        group_name: str,
        crd_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create or update a PrometheusRule CRD.

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            crd_name: Name of the PrometheusRule CRD (may be from sanitized file path)
            rule_data: Rule configuration

        Returns:
            Result of the operation
        """
        if not self.custom_api:
            return {
                "status": "error",
                "message": "Kubernetes client not initialized",
            }

        try:
            # First, try to find the existing CRD containing this rule
            existing = await self.find_crd_containing_rule(rule_name, group_name)

            if existing:
                # Update the rule in the existing CRD
                return await self._update_rule_in_crd(existing, rule_name, group_name, rule_data)
            else:
                # Try to get the CRD by name in case it's a new rule in an existing CRD
                crd_by_name = await self.get_prometheus_rule(crd_name)
                if crd_by_name:
                    return await self._update_rule_in_crd(
                        crd_by_name, rule_name, group_name, rule_data
                    )
                else:
                    # Create a new CRD
                    return await self._create_rule_crd(crd_name, group_name, rule_name, rule_data)
        except Exception as e:
            logger.error("Failed to create/update PrometheusRule", error=str(e))
            return {
                "status": "error",
                "message": str(e),
            }

    async def _update_rule_in_crd(
        self,
        existing_crd: dict[str, Any],
        rule_name: str,
        group_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a rule within an existing CRD."""
        if not self.custom_api:
            return {"status": "error", "message": "Kubernetes client not available"}

        crd_name = existing_crd["metadata"]["name"]
        spec = existing_crd.get("spec", {})
        groups = spec.get("groups", [])

        found_group = False
        found_rule = False

        for group in groups:
            if group.get("name") == group_name:
                found_group = True
                rules = group.get("rules", [])

                for idx, rule in enumerate(rules):
                    if rule.get("alert") == rule_name:
                        rules[idx] = rule_data
                        found_rule = True
                        break

                if not found_rule:
                    rules.append(rule_data)
                    found_rule = True

                group["rules"] = rules
                break

        if not found_group:
            groups.append(
                {
                    "name": group_name,
                    "rules": [rule_data],
                }
            )

        spec["groups"] = groups
        existing_crd["spec"] = spec

        try:
            self.custom_api.patch_namespaced_custom_object(
                group="monitoring.coreos.com",
                version="v1",
                namespace=self.settings.prometheus_crd_namespace,
                plural="prometheusrules",
                name=crd_name,
                body=existing_crd,
            )

            logger.info(
                "Updated PrometheusRule CRD",
                crd=crd_name,
                rule=rule_name,
                group=group_name,
            )

            return {
                "status": "success",
                "message": "Rule updated in CRD",
                "crd_name": crd_name,
                "action": "updated",
            }
        except Exception as e:
            logger.error("Failed to patch PrometheusRule CRD", error=str(e))
            return {
                "status": "error",
                "message": f"Failed to patch CRD: {e}",
            }

    async def _create_rule_crd(
        self,
        crd_name: str,
        group_name: str,
        rule_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new PrometheusRule CRD."""
        if not self.custom_api:
            return {"status": "error", "message": "Kubernetes client not available"}

        labels = {
            "managed-by": "poundcake",
            **self.settings.prometheus_crd_labels,
        }

        crd_body = {
            "apiVersion": "monitoring.coreos.com/v1",
            "kind": "PrometheusRule",
            "metadata": {
                "name": crd_name,
                "namespace": self.settings.prometheus_crd_namespace,
                "labels": labels,
            },
            "spec": {
                "groups": [
                    {
                        "name": group_name,
                        "rules": [rule_data],
                    }
                ]
            },
        }

        try:
            self.custom_api.create_namespaced_custom_object(
                group="monitoring.coreos.com",
                version="v1",
                namespace=self.settings.prometheus_crd_namespace,
                plural="prometheusrules",
                body=crd_body,
            )

            logger.info(
                "Created PrometheusRule CRD",
                crd=crd_name,
                rule=rule_name,
                group=group_name,
            )

            return {
                "status": "success",
                "message": "Rule created in new CRD",
                "crd_name": crd_name,
                "action": "created",
            }
        except Exception as e:
            logger.error("Failed to create PrometheusRule CRD", error=str(e))
            return {
                "status": "error",
                "message": f"Failed to create CRD: {e}",
            }

    async def delete_rule(
        self,
        rule_name: str,
        group_name: str,
        crd_name: str,
    ) -> dict[str, Any]:
        """
        Delete a rule from a PrometheusRule CRD.

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            crd_name: Name of the PrometheusRule CRD

        Returns:
            Result of the operation
        """
        if not self.custom_api:
            return {
                "status": "error",
                "message": "Kubernetes client not initialized",
            }

        try:
            existing = await self.get_prometheus_rule(crd_name)
            if not existing:
                return {
                    "status": "error",
                    "message": f"PrometheusRule CRD '{crd_name}' not found",
                }

            spec = existing.get("spec", {})
            groups = spec.get("groups", [])

            found = False
            for group in groups:
                if group.get("name") == group_name:
                    rules = group.get("rules", [])
                    for idx, rule in enumerate(rules):
                        if rule.get("alert") == rule_name:
                            del rules[idx]
                            found = True
                            break

                    if found and len(rules) == 0:
                        groups.remove(group)

                    break

            if not found:
                return {
                    "status": "error",
                    "message": f"Rule '{rule_name}' not found in group '{group_name}'",
                }

            if len(groups) == 0:
                self.custom_api.delete_namespaced_custom_object(
                    group="monitoring.coreos.com",
                    version="v1",
                    namespace=self.settings.prometheus_crd_namespace,
                    plural="prometheusrules",
                    name=crd_name,
                )

                logger.info("Deleted empty PrometheusRule CRD", crd=crd_name)
                return {
                    "status": "success",
                    "message": "Rule deleted, CRD removed (was empty)",
                    "crd_name": crd_name,
                    "action": "deleted_crd",
                }
            else:
                spec["groups"] = groups
                existing["spec"] = spec

                self.custom_api.patch_namespaced_custom_object(
                    group="monitoring.coreos.com",
                    version="v1",
                    namespace=self.settings.prometheus_crd_namespace,
                    plural="prometheusrules",
                    name=crd_name,
                    body=existing,
                )

                logger.info(
                    "Deleted rule from PrometheusRule CRD",
                    crd=crd_name,
                    rule=rule_name,
                )

                return {
                    "status": "success",
                    "message": "Rule deleted from CRD",
                    "crd_name": crd_name,
                    "action": "updated",
                }
        except Exception as e:
            logger.error("Failed to delete rule from CRD", error=str(e))
            return {
                "status": "error",
                "message": str(e),
            }


_crd_manager: PrometheusCRDManager | None = None


def get_prometheus_crd_manager() -> PrometheusCRDManager:
    """Get the global Prometheus CRD manager instance."""
    global _crd_manager
    if _crd_manager is None:
        _crd_manager = PrometheusCRDManager()
    return _crd_manager
