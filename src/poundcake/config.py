"""Configuration management for PoundCake."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="POUNDCAKE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # StackStorm settings
    stackstorm_url: str = "https://localhost"
    stackstorm_auth_url: str = ""  # If empty, defaults to stackstorm_url
    stackstorm_api_key: str = ""
    stackstorm_auth_token: str = ""
    stackstorm_verify_ssl: bool = True

    # Prometheus settings
    prometheus_url: str = "http://localhost:9090"
    prometheus_verify_ssl: bool = True

    # Prometheus Operator CRD settings (Kubernetes)
    prometheus_use_crds: bool = True  # Use PrometheusRule CRDs (default for K8s)
    prometheus_crd_namespace: str = "monitoring"  # Namespace for PrometheusRule CRDs
    prometheus_crd_labels: dict[str, str] = Field(
        default_factory=dict
    )  # Labels to apply to created CRDs

    # Git repository settings for Prometheus rule management
    git_enabled: bool = False
    git_repo_url: str = ""  # Git repo URL (https:// or git@)
    git_branch: str = "main"  # Branch to create PRs against
    git_rules_path: str = "prometheus/rules"  # Path to rules directory in repo
    git_file_per_alert: bool = True  # Create separate file for each alert
    git_file_pattern: str = (
        "{alert_name}.yaml"  # Pattern for alert files: {alert_name}, {group_name}, {crd_name}
    )
    git_token: str = ""  # Git token for HTTPS auth (GitHub/GitLab/Gitea)
    git_ssh_key_path: str = ""  # Path to SSH key for git@ URLs
    git_user_name: str = "PoundCake"  # Git commit author name
    git_user_email: str = "poundcake@localhost"  # Git commit author email
    git_provider: str = "github"  # github, gitlab, gitea, or none (no PR creation)

    # Remediation settings
    mappings_path: Path = Field(default=Path("config/mappings"))
    default_timeout: int = 300
    max_concurrent_remediations: int = 10

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Metrics
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"

    # Redis / State Store
    redis_url: str = ""  # Empty means use in-memory store
    redis_password: str = ""
    alert_ttl_hours: int = 24  # How long to keep resolved alerts
    lock_timeout_seconds: int = 300  # Distributed lock timeout

    # Instance identification (for tracking which instance processed an alert)
    instance_id: str = Field(default_factory=lambda: os.getenv("HOSTNAME", "poundcake-0"))


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_all_mappings(mappings_path: Path) -> dict[str, Any]:
    """Load all YAML mapping files from the mappings directory."""
    mappings: dict[str, Any] = {}

    if not mappings_path.exists():
        return mappings

    for yaml_file in mappings_path.glob("*.yaml"):
        file_mappings = load_yaml_config(yaml_file)
        if "alerts" in file_mappings:
            for alert_name, config in file_mappings["alerts"].items():
                mappings[alert_name] = config

    for yml_file in mappings_path.glob("*.yml"):
        file_mappings = load_yaml_config(yml_file)
        if "alerts" in file_mappings:
            for alert_name, config in file_mappings["alerts"].items():
                mappings[alert_name] = config

    return mappings
