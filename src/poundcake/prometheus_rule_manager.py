"""Prometheus rule manager for editing and applying rule changes."""

from typing import Any

import yaml
import structlog

from poundcake.config import get_settings
from poundcake.git_manager import get_git_manager
from poundcake.prometheus import get_prometheus_client
from poundcake.prometheus_crd_manager import get_prometheus_crd_manager

logger = structlog.get_logger(__name__)


class PrometheusRuleManager:
    """Manages Prometheus alert rule editing and GitOps workflow."""

    def __init__(self) -> None:
        """Initialize the rule manager."""
        self.settings = get_settings()
        self.git_manager = get_git_manager()
        self.prometheus = get_prometheus_client()
        self.crd_manager = get_prometheus_crd_manager()

    def _get_file_path(
        self,
        rule_name: str,
        group_name: str,
        crd_name: str,
    ) -> str:
        """
        Get the file path for a rule based on configuration.

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            crd_name: Name of the CRD

        Returns:
            File path relative to git_rules_path
        """
        if self.settings.git_file_per_alert:
            filename = self.settings.git_file_pattern.format(
                alert_name=rule_name,
                group_name=group_name,
                crd_name=crd_name,
            )
            return filename
        else:
            return crd_name if crd_name.endswith((".yaml", ".yml")) else f"{crd_name}.yaml"

    async def update_rule(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update a Prometheus alert rule.

        Supports two modes:
        1. CRD mode: Updates PrometheusRule CRD (immediate effect) + optional Git
        2. Git-only mode: Updates Git repo and creates PR

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            file_name: Name of the YAML file or CRD name
            rule_data: Updated rule configuration

        Returns:
            Result of the update operation
        """
        result: dict[str, Any] = {
            "status": "success",
            "message": "Rule updated",
        }

        # Mode 1: CRD Mode (immediate effect via Prometheus Operator)
        if self.settings.prometheus_use_crds:
            crd_name = file_name.replace(".yaml", "").replace(".yml", "")
            crd_result = await self.crd_manager.create_or_update_rule(
                rule_name, group_name, crd_name, rule_data
            )

            if crd_result.get("status") == "error":
                return crd_result

            result["crd"] = crd_result
            logger.info(
                "Updated rule in CRD",
                rule=rule_name,
                crd=crd_name,
                action=crd_result.get("action"),
            )

        # Mode 2: Git Mode (persistence and audit trail)
        if self.settings.git_enabled:
            git_result = await self._update_rule_in_git(rule_name, group_name, file_name, rule_data)

            if git_result.get("status") == "error":
                if self.settings.prometheus_use_crds:
                    result["git_error"] = git_result.get("message")
                    result["message"] = "Rule updated in CRD, but Git commit failed"
                else:
                    return git_result
            else:
                result["git"] = git_result

        # If neither mode is enabled, return error
        if not self.settings.prometheus_use_crds and not self.settings.git_enabled:
            return {
                "status": "error",
                "message": "Neither CRD nor Git integration is enabled",
            }

        return result

    async def _update_rule_in_git(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a rule in Git repository."""

        try:
            if not await self.git_manager.clone_or_pull():
                return {
                    "status": "error",
                    "message": "Failed to clone/pull Git repository",
                }

            assert self.git_manager.repo_path is not None
            crd_name = file_name.replace(".yaml", "").replace(".yml", "")
            actual_file_name = self._get_file_path(rule_name, group_name, crd_name)
            file_path = f"{self.settings.git_rules_path}/{actual_file_name}"
            full_path = self.git_manager.repo_path / file_path

            if self.settings.git_file_per_alert:
                rules_yaml = {
                    "groups": [
                        {
                            "name": group_name,
                            "rules": [rule_data],
                        }
                    ]
                }
                updated_yaml = yaml.dump(rules_yaml, default_flow_style=False, sort_keys=False)
            else:
                if not full_path.exists():
                    return {
                        "status": "error",
                        "message": f"Rule file not found: {file_path}",
                    }

                with open(full_path) as f:
                    rules_yaml = yaml.safe_load(f)

                if "groups" not in rules_yaml:
                    return {
                        "status": "error",
                        "message": "Invalid rule file: no groups found",
                    }

                found = False
                for group in rules_yaml["groups"]:
                    if group.get("name") == group_name:
                        for idx, rule in enumerate(group.get("rules", [])):
                            if rule.get("alert") == rule_name:
                                group["rules"][idx] = rule_data
                                found = True
                                break
                        break

                if not found:
                    return {
                        "status": "error",
                        "message": f"Rule {rule_name} not found in group {group_name}",
                    }

                updated_yaml = yaml.dump(rules_yaml, default_flow_style=False, sort_keys=False)

            commit_message = (
                f"Update Prometheus alert rule: {rule_name}\n\n"
                f"Updated by PoundCake auto-remediation system\n"
                f"Group: {group_name}\n"
                f"File: {actual_file_name}"
            )

            success, branch_name = await self.git_manager.commit_and_push_changes(
                file_path, updated_yaml, commit_message
            )

            if not success:
                return {
                    "status": "error",
                    "message": "Failed to commit and push changes",
                }

            result: dict[str, Any] = {
                "status": "success",
                "message": "Rule updated in Git",
                "branch": branch_name,
            }

            pr_title = f"Update Prometheus alert: {rule_name}"
            pr_description = (
                f"## Alert Rule Update\n\n"
                f"**Alert**: `{rule_name}`\n"
                f"**Group**: `{group_name}`\n"
                f"**File**: `{actual_file_name}`\n\n"
                f"Updated via PoundCake UI.\n\n"
                f"### Changes\n"
                f"```yaml\n{yaml.dump(rule_data, default_flow_style=False)}\n```"
            )

            pr_result = await self.git_manager.create_pull_request(
                branch_name, pr_title, pr_description
            )

            if pr_result:
                result["pull_request"] = {
                    "number": pr_result.get("number") or pr_result.get("iid"),
                    "url": pr_result.get("html_url") or pr_result.get("web_url"),
                }

            logger.info(
                "Updated Prometheus rule",
                rule=rule_name,
                group=group_name,
                branch=branch_name,
            )

            return result
        except Exception as e:
            logger.error("Error updating Prometheus rule", error=str(e))
            return {
                "status": "error",
                "message": str(e),
            }

    async def create_rule(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create a new Prometheus alert rule.

        Supports two modes:
        1. CRD mode: Creates in PrometheusRule CRD (immediate effect) + optional Git
        2. Git-only mode: Creates in Git repo and creates PR

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            file_name: Name of the YAML file or CRD name
            rule_data: Rule configuration

        Returns:
            Result of the create operation
        """
        result: dict[str, Any] = {
            "status": "success",
            "message": "Rule created",
        }

        # Mode 1: CRD Mode (immediate effect via Prometheus Operator)
        if self.settings.prometheus_use_crds:
            crd_name = file_name.replace(".yaml", "").replace(".yml", "")
            crd_result = await self.crd_manager.create_or_update_rule(
                rule_name, group_name, crd_name, rule_data
            )

            if crd_result.get("status") == "error":
                return crd_result

            result["crd"] = crd_result
            logger.info(
                "Created rule in CRD",
                rule=rule_name,
                crd=crd_name,
                action=crd_result.get("action"),
            )

        # Mode 2: Git Mode (persistence and audit trail)
        if self.settings.git_enabled:
            git_result = await self._create_rule_in_git(rule_name, group_name, file_name, rule_data)

            if git_result.get("status") == "error":
                if self.settings.prometheus_use_crds:
                    result["git_error"] = git_result.get("message")
                    result["message"] = "Rule created in CRD, but Git commit failed"
                else:
                    return git_result
            else:
                result["git"] = git_result

        # If neither mode is enabled, return error
        if not self.settings.prometheus_use_crds and not self.settings.git_enabled:
            return {
                "status": "error",
                "message": "Neither CRD nor Git integration is enabled",
            }

        return result

    async def _create_rule_in_git(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a rule in Git repository."""

        try:
            if not await self.git_manager.clone_or_pull():
                return {
                    "status": "error",
                    "message": "Failed to clone/pull Git repository",
                }

            assert self.git_manager.repo_path is not None
            crd_name = file_name.replace(".yaml", "").replace(".yml", "")
            actual_file_name = self._get_file_path(rule_name, group_name, crd_name)
            file_path = f"{self.settings.git_rules_path}/{actual_file_name}"
            full_path = self.git_manager.repo_path / file_path

            if self.settings.git_file_per_alert:
                rules_yaml = {
                    "groups": [
                        {
                            "name": group_name,
                            "rules": [rule_data],
                        }
                    ]
                }
            else:
                if full_path.exists():
                    with open(full_path) as f:
                        rules_yaml = yaml.safe_load(f) or {}
                else:
                    rules_yaml = {"groups": []}

                if "groups" not in rules_yaml:
                    rules_yaml["groups"] = []

                group_found = False
                for group in rules_yaml["groups"]:
                    if group.get("name") == group_name:
                        if "rules" not in group:
                            group["rules"] = []
                        group["rules"].append(rule_data)  # type: ignore[union-attr]
                        group_found = True
                        break

                if not group_found:
                    rules_yaml["groups"].append(
                        {
                            "name": group_name,
                            "rules": [rule_data],
                        }
                    )

            updated_yaml = yaml.dump(rules_yaml, default_flow_style=False, sort_keys=False)

            commit_message = (
                f"Add Prometheus alert rule: {rule_name}\n\n"
                f"Created by PoundCake auto-remediation system\n"
                f"Group: {group_name}\n"
                f"File: {actual_file_name}"
            )

            success, branch_name = await self.git_manager.commit_and_push_changes(
                file_path, updated_yaml, commit_message
            )

            if not success:
                return {
                    "status": "error",
                    "message": "Failed to commit and push changes",
                }

            result: dict[str, Any] = {
                "status": "success",
                "message": "Rule created in Git",
                "branch": branch_name,
            }

            pr_title = f"Add Prometheus alert: {rule_name}"
            pr_description = (
                f"## New Alert Rule\n\n"
                f"**Alert**: `{rule_name}`\n"
                f"**Group**: `{group_name}`\n"
                f"**File**: `{actual_file_name}`\n\n"
                f"Created via PoundCake UI.\n\n"
                f"### Rule Definition\n"
                f"```yaml\n{yaml.dump(rule_data, default_flow_style=False)}\n```"
            )

            pr_result = await self.git_manager.create_pull_request(
                branch_name, pr_title, pr_description
            )

            if pr_result:
                result["pull_request"] = {
                    "number": pr_result.get("number") or pr_result.get("iid"),
                    "url": pr_result.get("html_url") or pr_result.get("web_url"),
                }

            logger.info(
                "Created Prometheus rule",
                rule=rule_name,
                group=group_name,
                branch=branch_name,
            )

            return result
        except Exception as e:
            logger.error("Error creating Prometheus rule", error=str(e))
            return {
                "status": "error",
                "message": str(e),
            }

    async def delete_rule(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
    ) -> dict[str, Any]:
        """
        Delete a Prometheus alert rule.

        Supports two modes:
        1. CRD mode: Deletes from PrometheusRule CRD (immediate effect) + optional Git
        2. Git-only mode: Deletes from Git repo and creates PR

        Args:
            rule_name: Name of the alert rule
            group_name: Name of the rule group
            file_name: Name of the YAML file or CRD name

        Returns:
            Result of the delete operation
        """
        result: dict[str, Any] = {
            "status": "success",
            "message": "Rule deleted",
        }

        # Mode 1: CRD Mode (immediate effect via Prometheus Operator)
        if self.settings.prometheus_use_crds:
            crd_name = file_name.replace(".yaml", "").replace(".yml", "")
            crd_result = await self.crd_manager.delete_rule(rule_name, group_name, crd_name)

            if crd_result.get("status") == "error":
                return crd_result

            result["crd"] = crd_result
            logger.info(
                "Deleted rule from CRD",
                rule=rule_name,
                crd=crd_name,
                action=crd_result.get("action"),
            )

        # Mode 2: Git Mode (persistence and audit trail)
        if self.settings.git_enabled:
            git_result = await self._delete_rule_in_git(rule_name, group_name, file_name)

            if git_result.get("status") == "error":
                if self.settings.prometheus_use_crds:
                    result["git_error"] = git_result.get("message")
                    result["message"] = "Rule deleted from CRD, but Git commit failed"
                else:
                    return git_result
            else:
                result["git"] = git_result

        # If neither mode is enabled, return error
        if not self.settings.prometheus_use_crds and not self.settings.git_enabled:
            return {
                "status": "error",
                "message": "Neither CRD nor Git integration is enabled",
            }

        return result

    async def _delete_rule_in_git(
        self,
        rule_name: str,
        group_name: str,
        file_name: str,
    ) -> dict[str, Any]:
        """Delete a rule from Git repository."""

        try:
            if not await self.git_manager.clone_or_pull():
                return {
                    "status": "error",
                    "message": "Failed to clone/pull Git repository",
                }

            assert self.git_manager.repo_path is not None
            crd_name = file_name.replace(".yaml", "").replace(".yml", "")
            actual_file_name = self._get_file_path(rule_name, group_name, crd_name)
            file_path = f"{self.settings.git_rules_path}/{actual_file_name}"
            full_path = self.git_manager.repo_path / file_path

            if not full_path.exists():
                return {
                    "status": "error",
                    "message": f"Rule file not found: {file_path}",
                }

            commit_message = (
                f"Delete Prometheus alert rule: {rule_name}\n\n"
                f"Deleted by PoundCake auto-remediation system\n"
                f"Group: {group_name}\n"
                f"File: {actual_file_name}"
            )

            if self.settings.git_file_per_alert:
                success, branch_name = await self.git_manager.commit_and_push_deletion(
                    file_path, commit_message
                )
            else:
                with open(full_path) as f:
                    rules_yaml = yaml.safe_load(f)

                if "groups" not in rules_yaml:
                    return {
                        "status": "error",
                        "message": "Invalid rule file: no groups found",
                    }

                found = False
                for group in rules_yaml["groups"]:
                    if group.get("name") == group_name:
                        rules = group.get("rules", [])
                        for idx, rule in enumerate(rules):
                            if rule.get("alert") == rule_name:
                                del rules[idx]
                                found = True
                                break
                        break

                if not found:
                    return {
                        "status": "error",
                        "message": f"Rule {rule_name} not found in group {group_name}",
                    }

                updated_yaml = yaml.dump(rules_yaml, default_flow_style=False, sort_keys=False)

                success, branch_name = await self.git_manager.commit_and_push_changes(
                    file_path, updated_yaml, commit_message
                )

            if not success:
                return {
                    "status": "error",
                    "message": "Failed to commit and push changes",
                }

            result: dict[str, Any] = {
                "status": "success",
                "message": "Rule deleted from Git",
                "branch": branch_name,
            }

            pr_title = f"Delete Prometheus alert: {rule_name}"
            pr_description = (
                f"## Delete Alert Rule\n\n"
                f"**Alert**: `{rule_name}`\n"
                f"**Group**: `{group_name}`\n"
                f"**File**: `{actual_file_name}`\n\n"
                f"Deleted via PoundCake UI."
            )

            pr_result = await self.git_manager.create_pull_request(
                branch_name, pr_title, pr_description
            )

            if pr_result:
                result["pull_request"] = {
                    "number": pr_result.get("number") or pr_result.get("iid"),
                    "url": pr_result.get("html_url") or pr_result.get("web_url"),
                }

            logger.info(
                "Deleted Prometheus rule",
                rule=rule_name,
                group=group_name,
                branch=branch_name,
            )

            return result
        except Exception as e:
            logger.error("Error deleting Prometheus rule", error=str(e))
            return {
                "status": "error",
                "message": str(e),
            }


_rule_manager: PrometheusRuleManager | None = None


def get_prometheus_rule_manager() -> PrometheusRuleManager:
    """Get the global Prometheus rule manager instance."""
    global _rule_manager
    if _rule_manager is None:
        _rule_manager = PrometheusRuleManager()
    return _rule_manager
