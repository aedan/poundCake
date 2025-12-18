"""FastAPI application and API endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

from poundcake.config import get_settings
from poundcake.discovery import StackStormDiscovery
from poundcake.engine import get_engine
from poundcake.logging import setup_logging
from poundcake.management import get_mapping_manager, StackStormActionManager
from poundcake.models.alerts import AlertmanagerPayload
from poundcake.state import (
    MemoryStateStore,
    RedisStateStore,
    StateStore,
    set_state_store,
)

logger = structlog.get_logger(__name__)

# Prometheus metrics
ALERTS_RECEIVED = Counter(
    "poundcake_alerts_received_total",
    "Total number of alerts received",
    ["alertname", "severity", "status"],
)

REMEDIATIONS_EXECUTED = Counter(
    "poundcake_remediations_executed_total",
    "Total number of remediations executed",
    ["alertname", "action", "status"],
)

REMEDIATION_DURATION = Histogram(
    "poundcake_remediation_duration_seconds",
    "Duration of remediation actions",
    ["alertname", "action"],
)

ACTIVE_REMEDIATIONS = Gauge(
    "poundcake_active_remediations",
    "Number of currently active remediations",
)


class MappingCreate(BaseModel):
    """Request model for creating a mapping."""

    alert_name: str
    config: dict[str, Any]
    filename: str = "custom.yaml"


class MappingUpdate(BaseModel):
    """Request model for updating a mapping."""

    config: dict[str, Any]


class MappingImport(BaseModel):
    """Request model for importing mappings."""

    yaml_content: str
    filename: str = "imported.yaml"
    overwrite: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    # Startup
    setup_logging()
    settings = get_settings()

    # Initialize state store
    state_store: StateStore
    if settings.redis_url:
        state_store = RedisStateStore(
            url=settings.redis_url,
            password=settings.redis_password or None,
            alert_ttl_hours=settings.alert_ttl_hours,
            lock_timeout=settings.lock_timeout_seconds,
        )
        await state_store.connect()
        logger.info("Connected to Redis state store", url=settings.redis_url)
    else:
        state_store = MemoryStateStore()
        await state_store.connect()
        logger.warning("Using in-memory state store - not suitable for horizontal scaling")

    set_state_store(state_store)

    # Initialize API key manager and get key
    from poundcake.apikey_manager import get_api_key_manager

    api_key_manager = get_api_key_manager()
    api_key = await api_key_manager.get_api_key()

    if api_key:
        logger.info("StackStorm API key obtained successfully")
    else:
        logger.warning(
            "Could not obtain StackStorm API key - auto-remediation may not work. "
            "Ensure POUNDCAKE_STACKSTORM_API_KEY or admin credentials are configured."
        )

    # Auto-discover and configure StackStorm
    discovery = StackStormDiscovery()
    url, discovered_key = await discovery.auto_configure()
    if url:
        logger.info("StackStorm configured", url=url, has_key=bool(discovered_key))

    engine = get_engine()
    engine.initialize()
    logger.info("PoundCake started", instance_id=settings.instance_id)
    yield
    # Shutdown
    logger.info("PoundCake shutting down")
    await state_store.disconnect()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="PoundCake",
        description="Auto-remediation framework for Prometheus Alertmanager and StackStorm",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.post("/webhook")
    async def webhook(payload: AlertmanagerPayload) -> dict[str, Any]:
        """
        Receive alerts from Alertmanager and trigger remediation.

        This endpoint receives the standard Alertmanager webhook payload
        and processes each alert through the remediation engine.
        """
        engine = get_engine()
        results: list[dict[str, Any]] = []

        for alert in payload.alerts:
            # Record metrics
            ALERTS_RECEIVED.labels(
                alertname=alert.alertname,
                severity=alert.severity,
                status=alert.status.value,
            ).inc()

            # Process the alert
            remediation_results = await engine.process_alert(alert)

            for result in remediation_results:
                # Record remediation metrics
                REMEDIATIONS_EXECUTED.labels(
                    alertname=result.alert_name,
                    action=result.action_name,
                    status=result.status.value,
                ).inc()

                if result.duration_seconds:
                    REMEDIATION_DURATION.labels(
                        alertname=result.alert_name,
                        action=result.action_name,
                    ).observe(result.duration_seconds)

                results.append(
                    {
                        "alert": alert.alertname,
                        "action": result.action_name,
                        "status": result.status.value,
                        "execution_id": result.stackstorm_execution_id,
                        "error": result.error,
                    }
                )

        # Update active remediations gauge
        ACTIVE_REMEDIATIONS.set(len(engine.get_active_remediations()))

        return {
            "status": "processed",
            "alerts_received": len(payload.alerts),
            "remediations": results,
        }

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Health check endpoint."""
        engine = get_engine()
        health = await engine.health_check()
        return health

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        """Readiness check endpoint."""
        engine = get_engine()
        health = await engine.health_check()

        if health["status"] == "healthy":
            return {"status": "ready"}
        else:
            raise HTTPException(status_code=503, detail="Service not ready")

    @app.get("/handlers")
    async def list_handlers() -> dict[str, Any]:
        """List all registered handlers."""
        from poundcake.handlers import get_registry

        registry = get_registry()
        handlers = []

        for name in registry.list_handlers():
            handler = registry.get_handler(name)
            if handler:
                handlers.append(
                    {
                        "name": handler.name,
                        "description": handler.description,
                    }
                )

        return {"handlers": handlers}

    @app.get("/remediations")
    async def list_remediations(
        active: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List remediation history or active remediations."""
        engine = get_engine()

        if active:
            remediations = engine.get_active_remediations()
        else:
            remediations = engine.get_history(limit)

        return {
            "remediations": [
                {
                    "alert_name": r.alert_name,
                    "action_name": r.action_name,
                    "status": r.status.value,
                    "started_at": r.started_at.isoformat(),
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "execution_id": r.stackstorm_execution_id,
                    "error": r.error,
                }
                for r in remediations
            ]
        }

    # Alert tracking endpoints
    @app.get("/alerts")
    async def list_alerts(
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List all tracked alerts with their current status."""
        engine = get_engine()
        alerts = await engine.get_tracked_alerts(status=status, limit=limit)

        return {"alerts": [alert.to_summary() for alert in alerts]}

    @app.get("/alerts/stats")
    async def get_alert_stats() -> dict[str, Any]:
        """Get statistics about tracked alerts."""
        engine = get_engine()
        return await engine.get_alert_stats()

    @app.get("/alerts/{fingerprint}")
    async def get_alert(fingerprint: str) -> dict[str, Any]:
        """Get details for a specific tracked alert."""
        engine = get_engine()
        alert = await engine.get_tracked_alert(fingerprint)

        if alert is None:
            raise HTTPException(status_code=404, detail="Alert not found")

        return {
            "alert": alert.model_dump(mode="json"),
        }

    if settings.metrics_enabled:

        @app.get(settings.metrics_path)
        async def metrics() -> Response:
            """Prometheus metrics endpoint."""
            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST,
            )

    # Management API endpoints
    @app.get("/api/mappings")
    async def list_mappings() -> dict[str, Any]:
        """List all remediation mappings."""
        manager = get_mapping_manager()
        mappings = manager.list_mappings()
        return {"mappings": mappings}

    @app.get("/api/mappings/{alert_name}")
    async def get_mapping(alert_name: str) -> dict[str, Any]:
        """Get a specific mapping by alert name."""
        manager = get_mapping_manager()
        mapping = manager.get_mapping(alert_name)
        if not mapping:
            raise HTTPException(status_code=404, detail="Mapping not found")
        return {"alert_name": alert_name, "config": mapping}

    @app.post("/api/mappings")
    async def create_mapping(data: MappingCreate) -> dict[str, Any]:
        """Create a new remediation mapping."""
        manager = get_mapping_manager()
        success = manager.create_mapping(data.alert_name, data.config, data.filename)
        if not success:
            raise HTTPException(status_code=409, detail="Mapping already exists")
        return {"status": "created", "alert_name": data.alert_name}

    @app.put("/api/mappings/{alert_name}")
    async def update_mapping(alert_name: str, data: MappingUpdate) -> dict[str, Any]:
        """Update an existing remediation mapping."""
        manager = get_mapping_manager()
        success = manager.update_mapping(alert_name, data.config)
        if not success:
            raise HTTPException(status_code=404, detail="Mapping not found")
        return {"status": "updated", "alert_name": alert_name}

    @app.delete("/api/mappings/{alert_name}")
    async def delete_mapping(alert_name: str) -> dict[str, Any]:
        """Delete a remediation mapping."""
        manager = get_mapping_manager()
        success = manager.delete_mapping(alert_name)
        if not success:
            raise HTTPException(status_code=404, detail="Mapping not found")
        return {"status": "deleted", "alert_name": alert_name}

    @app.get("/api/mappings/export")
    async def export_mappings() -> Response:
        """Export all mappings as YAML."""
        manager = get_mapping_manager()
        yaml_content = manager.export_mappings()
        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={"Content-Disposition": "attachment; filename=mappings.yaml"},
        )

    @app.post("/api/mappings/import")
    async def import_mappings(data: MappingImport) -> dict[str, Any]:
        """Import mappings from YAML."""
        manager = get_mapping_manager()
        result = manager.import_mappings(data.yaml_content, data.filename, data.overwrite)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    # StackStorm action endpoints
    @app.get("/api/stackstorm/actions")
    async def list_stackstorm_actions(
        pack: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List available StackStorm actions."""
        from poundcake.handlers import get_registry

        registry = get_registry()
        action_manager = StackStormActionManager(registry.stackstorm_client)
        actions = await action_manager.list_actions(pack, limit)
        return {"actions": actions}

    @app.get("/api/stackstorm/actions/{action_ref:path}")
    async def get_stackstorm_action(action_ref: str) -> dict[str, Any]:
        """Get details of a specific StackStorm action."""
        from poundcake.handlers import get_registry

        registry = get_registry()
        action_manager = StackStormActionManager(registry.stackstorm_client)
        action = await action_manager.get_action(action_ref)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")
        return action

    @app.get("/api/stackstorm/packs")
    async def list_stackstorm_packs() -> dict[str, Any]:
        """List available StackStorm packs."""
        from poundcake.handlers import get_registry

        registry = get_registry()
        action_manager = StackStormActionManager(registry.stackstorm_client)
        packs = await action_manager.list_packs()
        return {"packs": packs}

    @app.get("/api/stackstorm/executions")
    async def list_stackstorm_executions(
        limit: int = 50,
        action: str | None = None,
    ) -> dict[str, Any]:
        """List StackStorm execution history."""
        from poundcake.handlers import get_registry

        registry = get_registry()
        action_manager = StackStormActionManager(registry.stackstorm_client)
        executions = await action_manager.get_execution_history(limit, action)
        return {"executions": executions}

    @app.put("/api/stackstorm/actions/{action_ref:path}")
    async def update_stackstorm_action(
        action_ref: str, action_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a StackStorm action definition."""
        from poundcake.handlers import get_registry

        registry = get_registry()
        action_manager = StackStormActionManager(registry.stackstorm_client)
        result = await action_manager.update_action(action_ref, action_data)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to update action")
        return result

    @app.post("/api/stackstorm/actions")
    async def create_stackstorm_action(action_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new StackStorm action."""
        from poundcake.handlers import get_registry

        registry = get_registry()
        action_manager = StackStormActionManager(registry.stackstorm_client)
        result = await action_manager.create_action(action_data)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create action")
        return result

    @app.delete("/api/stackstorm/actions/{action_ref:path}")
    async def delete_stackstorm_action(action_ref: str) -> dict[str, Any]:
        """Delete a StackStorm action."""
        from poundcake.handlers import get_registry

        registry = get_registry()
        action_manager = StackStormActionManager(registry.stackstorm_client)
        success = await action_manager.delete_action(action_ref)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to delete action")
        return {"status": "deleted", "action_ref": action_ref}

    # Prometheus endpoints
    @app.get("/api/prometheus/rules")
    async def list_prometheus_rules() -> dict[str, Any]:
        """List Prometheus alert rules."""
        from poundcake.prometheus import get_prometheus_client

        prometheus = get_prometheus_client()
        rules = await prometheus.get_rules()
        return {"rules": rules}

    @app.get("/api/prometheus/rule-groups")
    async def list_prometheus_rule_groups() -> dict[str, Any]:
        """List Prometheus rule groups."""
        from poundcake.prometheus import get_prometheus_client

        prometheus = get_prometheus_client()
        groups = await prometheus.get_rule_groups()
        return {"groups": groups}

    @app.get("/api/prometheus/health")
    async def prometheus_health() -> dict[str, Any]:
        """Check Prometheus health."""
        from poundcake.prometheus import get_prometheus_client

        prometheus = get_prometheus_client()
        health = await prometheus.health_check()
        return health

    @app.put("/api/prometheus/rules/{rule_name}")
    async def update_prometheus_rule(
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a Prometheus alert rule."""
        from poundcake.prometheus_rule_manager import get_prometheus_rule_manager

        manager = get_prometheus_rule_manager()
        result = await manager.update_rule(rule_name, group_name, file_name, rule_data)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))
        return result

    @app.post("/api/prometheus/rules")
    async def create_prometheus_rule(
        rule_name: str,
        group_name: str,
        file_name: str,
        rule_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new Prometheus alert rule."""
        from poundcake.prometheus_rule_manager import get_prometheus_rule_manager

        manager = get_prometheus_rule_manager()
        result = await manager.create_rule(rule_name, group_name, file_name, rule_data)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))
        return result

    @app.delete("/api/prometheus/rules/{rule_name}")
    async def delete_prometheus_rule(
        rule_name: str,
        group_name: str,
        file_name: str,
    ) -> dict[str, Any]:
        """Delete a Prometheus alert rule."""
        from poundcake.prometheus_rule_manager import get_prometheus_rule_manager

        manager = get_prometheus_rule_manager()
        result = await manager.delete_rule(rule_name, group_name, file_name)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))
        return result

    @app.get("/api/settings")
    async def get_settings_info() -> dict[str, Any]:
        """Get PoundCake settings information (non-sensitive)."""
        from poundcake.config import get_settings

        settings = get_settings()
        return {
            "git_enabled": settings.git_enabled,
            "git_provider": settings.git_provider if settings.git_enabled else None,
            "git_repo_url": settings.git_repo_url if settings.git_enabled else None,
            "git_branch": settings.git_branch if settings.git_enabled else None,
            "prometheus_use_crds": settings.prometheus_use_crds,
            "prometheus_crd_namespace": (
                settings.prometheus_crd_namespace if settings.prometheus_use_crds else None
            ),
            "stackstorm_url": settings.stackstorm_url,
        }

    # Web UI
    @app.get("/ui", response_class=HTMLResponse)
    async def ui() -> str:
        """Web UI for managing remediations."""
        return get_management_ui_html()

    return app


def get_management_ui_html() -> str:
    """Return the HTML for the management UI."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PoundCake - Remediation Management</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { background: #2c3e50; color: white; padding: 20px; margin-bottom: 20px; }
        header h1 { font-size: 24px; }
        .header-stats { display: flex; gap: 20px; margin-top: 10px; font-size: 14px; }
        .header-stats span { opacity: 0.9; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; }
        .tab { padding: 10px 20px; background: #ddd; border: none; cursor: pointer; border-radius: 4px; font-size: 14px; font-weight: 500; transition: all 0.2s; }
        .tab:hover:not(.active) { background: #bbb; }
        .tab.active { background: #3498db; color: white; }
        .panel { display: none; background: white; padding: 20px; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .panel.active { display: block; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f8f9fa; font-weight: 600; }
        .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; margin-right: 5px; }
        .btn-primary { background: #3498db; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-success { background: #27ae60; color: white; }
        .btn-sm { padding: 4px 8px; font-size: 12px; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); }
        .modal.active { display: flex; align-items: center; justify-content: center; }
        .modal-content { background: white; padding: 20px; border-radius: 4px; width: 600px; max-height: 80vh; overflow-y: auto; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: 600; }
        .form-group input, .form-group textarea, .form-group select { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        .form-group textarea { height: 200px; font-family: monospace; }
        .status { padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
        .status-received { background: #e3f2fd; color: #1565c0; }
        .status-pending { background: #fff3e0; color: #ef6c00; }
        .status-remediating { background: #fff3cd; color: #856404; }
        .status-remediated { background: #d4edda; color: #155724; }
        .status-resolved { background: #e8f5e9; color: #2e7d32; }
        .status-success { background: #d4edda; color: #155724; }
        .status-failed { background: #f8d7da; color: #721c24; }
        .status-running { background: #fff3cd; color: #856404; }
        .actions-list { max-height: 300px; overflow-y: auto; }
        .action-item { padding: 10px; border: 1px solid #ddd; margin-bottom: 5px; border-radius: 4px; cursor: pointer; }
        .action-item:hover { background: #f8f9fa; }
        .action-item .pack { color: #666; font-size: 12px; }
        pre { background: #f4f4f4; padding: 10px; border-radius: 4px; overflow-x: auto; }
        .filter-bar { display: flex; gap: 10px; margin-bottom: 15px; align-items: center; }
        .filter-bar select { padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        .auto-refresh { display: flex; align-items: center; gap: 5px; margin-left: auto; font-size: 14px; }
        .stats-bar { display: flex; gap: 15px; margin-bottom: 15px; }
        .stat-item { padding: 10px 15px; background: #f8f9fa; border-radius: 4px; }
        .stat-item .label { font-size: 12px; color: #666; }
        .stat-item .value { font-size: 20px; font-weight: 600; }
        .expandable { cursor: pointer; }
        .expandable:hover { background: #f8f9fa; }
        .details-row { display: none; }
        .details-row.active { display: table-row; }
        .details-content { padding: 15px; background: #f8f9fa; }
        .attempt-list { margin-top: 10px; }
        .attempt-item { padding: 8px; border-left: 3px solid #ddd; margin-bottom: 5px; background: white; }
        .attempt-item.success { border-color: #27ae60; }
        .attempt-item.failed { border-color: #e74c3c; }
        .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .dashboard-card { background: #f8f9fa; padding: 20px; border-radius: 4px; border-left: 4px solid #3498db; }
        .dashboard-card h3 { margin-bottom: 15px; font-size: 18px; color: #2c3e50; }
        .dashboard-card.healthy { border-color: #27ae60; }
        .dashboard-card.warning { border-color: #f39c12; }
        .dashboard-card.error { border-color: #e74c3c; }
        .metric-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #ddd; }
        .metric-row:last-child { border-bottom: none; }
        .metric-label { color: #666; font-size: 14px; }
        .metric-value { font-weight: 600; font-size: 16px; }
        .health-indicator { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
        .health-indicator.healthy { background: #27ae60; }
        .health-indicator.unhealthy { background: #e74c3c; }
        .health-indicator.unknown { background: #95a5a6; }
        .config-section { margin-bottom: 25px; }
        .config-section h3 { margin-bottom: 15px; font-size: 18px; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 8px; }
        .config-item { display: grid; grid-template-columns: 200px 1fr; padding: 12px; background: #f8f9fa; margin-bottom: 8px; border-radius: 4px; }
        .config-item .key { font-weight: 600; color: #555; }
        .config-item .value { color: #333; font-family: monospace; }
        .activity-feed { max-height: 400px; overflow-y: auto; }
        .activity-item { padding: 12px; border-left: 3px solid #3498db; margin-bottom: 8px; background: #f8f9fa; }
        .activity-item.success { border-color: #27ae60; }
        .activity-item.failed { border-color: #e74c3c; }
        .activity-item .time { font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>PoundCake - Remediation Management</h1>
            <div class="header-stats" id="header-stats"></div>
        </div>
    </header>

    <div class="container">
        <div class="tabs">
            <button class="tab active" onclick="showTab('dashboard')">Dashboard</button>
            <button class="tab" onclick="showTab('alerts')">Alert Status</button>
            <button class="tab" onclick="showTab('prometheus')">Prometheus Rules</button>
            <button class="tab" onclick="showTab('mappings')">Mappings</button>
            <button class="tab" onclick="showTab('actions')">StackStorm Actions</button>
            <button class="tab" onclick="showTab('history')">Execution History</button>
            <button class="tab" onclick="showTab('health')">Health</button>
            <button class="tab" onclick="showTab('settings')">Settings</button>
        </div>

        <div id="dashboard" class="panel active">
            <h2 style="margin-bottom: 20px;">System Overview</h2>
            <div class="dashboard-grid" id="dashboard-metrics"></div>
            <div class="dashboard-grid">
                <div class="dashboard-card">
                    <h3>Recent Activity</h3>
                    <div class="activity-feed" id="recent-activity"></div>
                </div>
                <div class="dashboard-card">
                    <h3>Quick Stats</h3>
                    <div id="quick-stats"></div>
                </div>
            </div>
        </div>

        <div id="alerts" class="panel">
            <div class="filter-bar">
                <select id="status-filter" onchange="loadAlerts()">
                    <option value="">All Statuses</option>
                    <option value="received">Received</option>
                    <option value="pending">Pending</option>
                    <option value="remediating">Remediating</option>
                    <option value="remediated">Remediated</option>
                    <option value="resolved">Resolved</option>
                </select>
                <button class="btn btn-primary btn-sm" onclick="loadAlerts()">Refresh</button>
                <div class="auto-refresh">
                    <input type="checkbox" id="auto-refresh" checked onchange="toggleAutoRefresh()">
                    <label for="auto-refresh">Auto-refresh (5s)</label>
                </div>
            </div>
            <div class="stats-bar" id="stats-bar"></div>
            <table>
                <thead>
                    <tr>
                        <th>Alert Name</th>
                        <th>Instance</th>
                        <th>Severity</th>
                        <th>Status</th>
                        <th>Received</th>
                        <th>Attempts</th>
                    </tr>
                </thead>
                <tbody id="alerts-table"></tbody>
            </table>
        </div>

        <div id="prometheus" class="panel">
            <div class="filter-bar">
                <select id="prom-state-filter" onchange="loadPrometheusRules()">
                    <option value="">All States</option>
                    <option value="firing">Firing</option>
                    <option value="pending">Pending</option>
                    <option value="inactive">Inactive</option>
                </select>
                <button class="btn btn-primary btn-sm" onclick="loadPrometheusRules()">Refresh</button>
                <span id="persistence-status" style="margin-left: 10px; font-size: 12px; color: #666;"></span>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Alert Name</th>
                        <th>Query</th>
                        <th>Duration</th>
                        <th>State</th>
                        <th>Group</th>
                        <th>File</th>
                        <th>Operations</th>
                    </tr>
                </thead>
                <tbody id="prometheus-table"></tbody>
            </table>
        </div>

        <div id="mappings" class="panel">
            <div style="margin-bottom: 15px;">
                <button class="btn btn-primary" onclick="showCreateModal()">Create Mapping</button>
                <button class="btn btn-success" onclick="exportMappings()">Export YAML</button>
                <button class="btn" onclick="showImportModal()">Import YAML</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Alert Name</th>
                        <th>Handler</th>
                        <th>Actions</th>
                        <th>Operations</th>
                    </tr>
                </thead>
                <tbody id="mappings-table"></tbody>
            </table>
        </div>

        <div id="actions" class="panel">
            <div style="margin-bottom: 15px;">
                <button class="btn btn-primary" onclick="showCreateActionModal()">Create Action</button>
                <select id="pack-filter" onchange="loadActions()" style="margin-left: 10px;">
                    <option value="">All Packs</option>
                </select>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Action Reference</th>
                        <th>Description</th>
                        <th>Pack</th>
                        <th>Operations</th>
                    </tr>
                </thead>
                <tbody id="actions-table"></tbody>
            </table>
        </div>

        <div id="history" class="panel">
            <table>
                <thead>
                    <tr>
                        <th>Alert</th>
                        <th>Action</th>
                        <th>Status</th>
                        <th>Started</th>
                        <th>Execution ID</th>
                    </tr>
                </thead>
                <tbody id="history-table"></tbody>
            </table>
        </div>

        <div id="health" class="panel">
            <h2 style="margin-bottom: 20px;">System Health</h2>
            <div class="dashboard-grid" id="health-components"></div>
        </div>

        <div id="settings" class="panel">
            <h2 style="margin-bottom: 20px;">Configuration</h2>
            <div id="settings-content"></div>
        </div>
    </div>

    <!-- Create/Edit Modal -->
    <div id="edit-modal" class="modal">
        <div class="modal-content">
            <h3 id="modal-title">Create Mapping</h3>
            <form id="mapping-form" onsubmit="saveMapping(event)">
                <div class="form-group">
                    <label>Alert Name</label>
                    <input type="text" id="alert-name" required>
                </div>
                <div class="form-group">
                    <label>Configuration (YAML)</label>
                    <textarea id="mapping-config" required></textarea>
                </div>
                <div style="text-align: right;">
                    <button type="button" class="btn" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Import Modal -->
    <div id="import-modal" class="modal">
        <div class="modal-content">
            <h3>Import Mappings</h3>
            <form onsubmit="importMappings(event)">
                <div class="form-group">
                    <label>YAML Content</label>
                    <textarea id="import-yaml" required></textarea>
                </div>
                <div class="form-group">
                    <label><input type="checkbox" id="import-overwrite"> Overwrite existing</label>
                </div>
                <div style="text-align: right;">
                    <button type="button" class="btn" onclick="closeImportModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Import</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Action Detail Modal -->
    <div id="action-modal" class="modal">
        <div class="modal-content">
            <h3 id="action-title">Action Details</h3>
            <pre id="action-details"></pre>
            <div style="text-align: right; margin-top: 15px;">
                <button class="btn btn-primary" onclick="useAction()">Use in Mapping</button>
                <button class="btn" onclick="closeActionModal()">Close</button>
            </div>
        </div>
    </div>

    <!-- Edit Action Modal -->
    <div id="edit-action-modal" class="modal">
        <div class="modal-content">
            <h3 id="action-modal-title">Edit Action</h3>
            <form id="action-form" onsubmit="saveAction(event)">
                <div class="form-group">
                    <label>Action Reference (pack.action)</label>
                    <input type="text" id="action-ref" required>
                </div>
                <div class="form-group">
                    <label>Action Definition (JSON)</label>
                    <textarea id="action-data" required style="height: 400px;"></textarea>
                </div>
                <div style="text-align: right;">
                    <button type="button" class="btn" onclick="closeEditActionModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Edit Prometheus Rule Modal -->
    <div id="edit-rule-modal" class="modal">
        <div class="modal-content">
            <h3 id="rule-modal-title">Edit Prometheus Rule</h3>
            <form id="rule-form" onsubmit="savePrometheusRule(event)">
                <div class="form-group">
                    <label>Alert Name</label>
                    <input type="text" id="rule-name" required>
                </div>
                <div class="form-group">
                    <label>Group Name</label>
                    <input type="text" id="rule-group" required>
                </div>
                <div class="form-group">
                    <label>File Name</label>
                    <input type="text" id="rule-file" required>
                </div>
                <div class="form-group">
                    <label>Rule Definition (YAML)</label>
                    <textarea id="rule-data" required style="height: 400px;"></textarea>
                </div>
                <div style="text-align: right;">
                    <button type="button" class="btn" onclick="closeEditRuleModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save & Create PR</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        let currentAction = null;
        let editMode = false;
        let editActionMode = false;
        let autoRefreshInterval = null;

        function showTab(tab) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.querySelector(`[onclick="showTab('${tab}')"]`).classList.add('active');
            document.getElementById(tab).classList.add('active');

            if (tab === 'dashboard') loadDashboard();
            if (tab === 'alerts') { loadAlerts(); loadStats(); }
            if (tab === 'prometheus') loadPrometheusRules();
            if (tab === 'mappings') loadMappings();
            if (tab === 'actions') { loadPacks(); loadActions(); }
            if (tab === 'history') loadHistory();
            if (tab === 'health') loadHealth();
            if (tab === 'settings') loadSettings();
        }

        // Alert tracking functions
        async function loadAlerts() {
            const status = document.getElementById('status-filter').value;
            const url = status ? `/alerts?status=${status}` : '/alerts';
            const res = await fetch(url);
            const data = await res.json();
            const tbody = document.getElementById('alerts-table');
            tbody.innerHTML = '';

            if (data.alerts.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #666;">No alerts found</td></tr>';
                return;
            }

            data.alerts.forEach(alert => {
                const statusClass = `status-${alert.status}`;
                const attempts = `${alert.successful_attempts}/${alert.total_attempts}`;
                const attemptsStyle = alert.failed_attempts > 0 ? 'color: #e74c3c;' : '';

                tbody.innerHTML += `
                    <tr class="expandable" onclick="toggleDetails('${alert.fingerprint}')">
                        <td><strong>${alert.alertname}</strong></td>
                        <td>${alert.instance || '-'}</td>
                        <td>${alert.severity || '-'}</td>
                        <td><span class="status ${statusClass}">${alert.status}</span></td>
                        <td>${new Date(alert.received_at).toLocaleString()}</td>
                        <td style="${attemptsStyle}">${attempts}</td>
                    </tr>
                    <tr class="details-row" id="details-${alert.fingerprint}">
                        <td colspan="6">
                            <div class="details-content" id="content-${alert.fingerprint}">
                                Loading...
                            </div>
                        </td>
                    </tr>
                `;
            });
        }

        async function loadStats() {
            const res = await fetch('/alerts/stats');
            const data = await res.json();

            // Update header stats
            const headerStats = document.getElementById('header-stats');
            headerStats.innerHTML = `
                <span>Total: ${data.total}</span>
                ${Object.entries(data.by_status).map(([k, v]) => `<span>${k}: ${v}</span>`).join('')}
            `;

            // Update stats bar
            const statsBar = document.getElementById('stats-bar');
            statsBar.innerHTML = '';

            const statusOrder = ['received', 'remediating', 'remediated', 'resolved'];
            statusOrder.forEach(status => {
                const count = data.by_status[status] || 0;
                if (count > 0 || status === 'received' || status === 'remediating') {
                    statsBar.innerHTML += `
                        <div class="stat-item">
                            <div class="label">${status.charAt(0).toUpperCase() + status.slice(1)}</div>
                            <div class="value">${count}</div>
                        </div>
                    `;
                }
            });
        }

        async function toggleDetails(fingerprint) {
            const row = document.getElementById(`details-${fingerprint}`);
            const content = document.getElementById(`content-${fingerprint}`);

            if (row.classList.contains('active')) {
                row.classList.remove('active');
                return;
            }

            // Load full alert details
            const res = await fetch(`/alerts/${fingerprint}`);
            const data = await res.json();
            const alert = data.alert;

            let attemptsHtml = '';
            if (alert.remediation_attempts && alert.remediation_attempts.length > 0) {
                attemptsHtml = '<div class="attempt-list"><strong>Remediation Attempts:</strong>';
                alert.remediation_attempts.forEach(attempt => {
                    const statusClass = attempt.status === 'success' ? 'success' : 'failed';
                    attemptsHtml += `
                        <div class="attempt-item ${statusClass}">
                            <strong>${attempt.action_name}</strong> (${attempt.stackstorm_action})<br>
                            Status: ${attempt.status} | Started: ${new Date(attempt.started_at).toLocaleString()}
                            ${attempt.error ? `<br><span style="color: #e74c3c;">Error: ${attempt.error}</span>` : ''}
                            ${attempt.execution_id ? `<br>Execution ID: ${attempt.execution_id}` : ''}
                        </div>
                    `;
                });
                attemptsHtml += '</div>';
            }

            content.innerHTML = `
                <div><strong>Fingerprint:</strong> ${alert.fingerprint}</div>
                <div><strong>Status Changed:</strong> ${new Date(alert.status_changed_at).toLocaleString()}</div>
                ${alert.resolved_at ? `<div><strong>Resolved:</strong> ${new Date(alert.resolved_at).toLocaleString()}</div>` : ''}
                ${alert.processed_by ? `<div><strong>Processed By:</strong> ${alert.processed_by}</div>` : ''}
                ${alert.last_error ? `<div style="color: #e74c3c;"><strong>Last Error:</strong> ${alert.last_error}</div>` : ''}
                ${attemptsHtml}
            `;

            row.classList.add('active');
        }

        function toggleAutoRefresh() {
            const checkbox = document.getElementById('auto-refresh');
            if (checkbox.checked) {
                autoRefreshInterval = setInterval(() => {
                    if (document.getElementById('alerts').classList.contains('active')) {
                        loadAlerts();
                        loadStats();
                    }
                }, 5000);
            } else {
                if (autoRefreshInterval) {
                    clearInterval(autoRefreshInterval);
                    autoRefreshInterval = null;
                }
            }
        }

        async function loadMappings() {
            const res = await fetch('/api/mappings');
            const data = await res.json();
            const tbody = document.getElementById('mappings-table');
            tbody.innerHTML = '';

            for (const [name, config] of Object.entries(data.mappings)) {
                const actions = config.actions ? config.actions.length : 0;
                tbody.innerHTML += `
                    <tr>
                        <td>${name}</td>
                        <td>${config.handler || 'yaml_config'}</td>
                        <td>${actions}</td>
                        <td>
                            <button class="btn btn-primary" onclick="editMapping('${name}')">Edit</button>
                            <button class="btn btn-danger" onclick="deleteMapping('${name}')">Delete</button>
                        </td>
                    </tr>
                `;
            }
        }

        async function loadPacks() {
            const res = await fetch('/api/stackstorm/packs');
            const data = await res.json();
            const select = document.getElementById('pack-filter');
            select.innerHTML = '<option value="">All Packs</option>';
            data.packs.forEach(pack => {
                select.innerHTML += `<option value="${pack.ref}">${pack.ref}</option>`;
            });
        }

        async function loadActions() {
            const pack = document.getElementById('pack-filter').value;
            const url = pack ? `/api/stackstorm/actions?pack=${pack}` : '/api/stackstorm/actions';
            const res = await fetch(url);
            const data = await res.json();
            const tbody = document.getElementById('actions-table');
            tbody.innerHTML = '';

            if (data.actions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #666;">No actions found</td></tr>';
                return;
            }

            data.actions.forEach(action => {
                const pack = action.pack || action.ref.split('.')[0];
                tbody.innerHTML += `
                    <tr>
                        <td><strong>${action.ref}</strong></td>
                        <td>${action.description || 'No description'}</td>
                        <td>${pack}</td>
                        <td>
                            <button class="btn btn-primary btn-sm" onclick="showAction('${action.ref}')">View</button>
                            <button class="btn btn-primary btn-sm" onclick="editAction('${action.ref}')">Edit</button>
                            <button class="btn btn-danger btn-sm" onclick="deleteAction('${action.ref}')">Delete</button>
                        </td>
                    </tr>
                `;
            });
        }

        async function loadPrometheusRules() {
            const state = document.getElementById('prom-state-filter').value;
            const res = await fetch('/api/prometheus/rules');
            const data = await res.json();
            const tbody = document.getElementById('prometheus-table');
            tbody.innerHTML = '';

            const settingsRes = await fetch('/api/settings');
            const settings = await settingsRes.json();

            const statusEl = document.getElementById('persistence-status');
            let statusParts = [];

            // CRD mode (default for Kubernetes)
            if (settings.prometheus_use_crds) {
                statusParts.push(`✓ CRD (${settings.prometheus_crd_namespace})`);
            }

            // Git persistence (optional)
            if (settings.git_enabled) {
                statusParts.push(`✓ Git: ${settings.git_provider}`);
            }

            if (statusParts.length === 0) {
                statusEl.textContent = '⚠ No backend configured';
                statusEl.style.color = '#e74c3c';
            } else {
                statusEl.textContent = statusParts.join(' | ');
                statusEl.style.color = '#27ae60';
            }

            // Tooltip
            if (settings.prometheus_use_crds && settings.git_enabled) {
                statusEl.title = 'CRD: Immediate effect | Git: Audit trail & persistence';
            } else if (settings.prometheus_use_crds) {
                statusEl.title = 'CRD mode: Changes apply immediately via Prometheus Operator';
            }

            let rules = data.rules || [];
            if (state) {
                rules = rules.filter(r => r.state === state);
            }

            if (rules.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #666;">No rules found</td></tr>';
                return;
            }

            rules.forEach(rule => {
                const stateClass = rule.state === 'firing' ? 'status-failed' :
                                 rule.state === 'pending' ? 'status-running' : 'status-success';
                const canEdit = settings.prometheus_use_crds || settings.git_enabled;
                const editBtn = canEdit ?
                    `<button class="btn btn-primary btn-sm" onclick='editPrometheusRule(${JSON.stringify(rule)})'>Edit</button>
                     <button class="btn btn-danger btn-sm" onclick='deletePrometheusRule("${rule.name}", "${rule.group}", "${rule.file}")'>Delete</button>` :
                    '<span style="color: #999; font-size: 11px;">No backend</span>';

                tbody.innerHTML += `
                    <tr>
                        <td><strong>${rule.name}</strong></td>
                        <td><code>${rule.query.substring(0, 50)}${rule.query.length > 50 ? '...' : ''}</code></td>
                        <td>${rule.duration}s</td>
                        <td><span class="status ${stateClass}">${rule.state}</span></td>
                        <td>${rule.group}</td>
                        <td>${rule.file}</td>
                        <td>${editBtn}</td>
                    </tr>
                `;
            });
        }

        async function editPrometheusRule(rule) {
            document.getElementById('rule-modal-title').textContent = 'Edit Prometheus Rule';
            document.getElementById('rule-name').value = rule.name;
            document.getElementById('rule-name').disabled = true;
            document.getElementById('rule-group').value = rule.group;
            document.getElementById('rule-file').value = rule.file;

            const ruleYaml = {
                alert: rule.name,
                expr: rule.query,
                for: `${rule.duration}s`,
                labels: rule.labels || {},
                annotations: rule.annotations || {}
            };

            document.getElementById('rule-data').value = jsyaml.dump(ruleYaml);
            document.getElementById('edit-rule-modal').classList.add('active');
        }

        async function savePrometheusRule(e) {
            e.preventDefault();
            const ruleName = document.getElementById('rule-name').value;
            const groupName = document.getElementById('rule-group').value;
            const fileName = document.getElementById('rule-file').value;
            const ruleYaml = document.getElementById('rule-data').value;

            try {
                const ruleData = jsyaml.load(ruleYaml);

                const res = await fetch(`/api/prometheus/rules/${ruleName}?group_name=${groupName}&file_name=${fileName}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(ruleData)
                });

                if (!res.ok) {
                    const error = await res.json();
                    alert(`Failed to update rule: ${error.detail || res.statusText}`);
                    return;
                }

                const result = await res.json();
                closeEditRuleModal();
                loadPrometheusRules();

                let message = `Rule updated successfully!

`;

                // CRD result
                if (result.crd) {
                    message += `✓ CRD: ${result.crd.action} in ${result.crd.crd_name}\n`;
                }

                // Git result
                if (result.git) {
                    if (result.git.branch) {
                        message += `✓ Git: ${result.git.branch}\n`;
                    }
                    if (result.git.pull_request) {
                        message += `✓ PR #${result.git.pull_request.number}: ${result.git.pull_request.url}\n`;
                    }
                }

                // Errors
                if (result.git_error) {
                    message += `⚠ Git error: ${result.git_error}\n`;
                }

                alert(message);
            } catch (err) {
                alert(`Error: ${err.message}`);
            }
        }

        async function deletePrometheusRule(ruleName, groupName, fileName) {
            if (!confirm(`Delete Prometheus rule "${ruleName}"?\n\nThis will create a PR to remove the rule.`)) return;

            const res = await fetch(`/api/prometheus/rules/${ruleName}?group_name=${groupName}&file_name=${fileName}`, {
                method: 'DELETE'
            });

            if (res.ok) {
                const result = await res.json();
                loadPrometheusRules();

                let message = `Rule deleted successfully!

`;

                // CRD result
                if (result.crd) {
                    message += `✓ CRD: ${result.crd.action}\n`;
                }

                // Git result
                if (result.git) {
                    if (result.git.branch) {
                        message += `✓ Git: ${result.git.branch}\n`;
                    }
                    if (result.git.pull_request) {
                        message += `✓ PR #${result.git.pull_request.number}: ${result.git.pull_request.url}\n`;
                    }
                }

                // Errors
                if (result.git_error) {
                    message += `⚠ Git error: ${result.git_error}\n`;
                }

                alert(message);
            } else {
                const error = await res.json();
                alert(`Failed to delete rule: ${error.detail || res.statusText}`);
            }
        }

        function closeEditRuleModal() {
            document.getElementById('edit-rule-modal').classList.remove('active');
        }

        async function loadHistory() {
            const res = await fetch('/remediations?limit=50');
            const data = await res.json();
            const tbody = document.getElementById('history-table');
            tbody.innerHTML = '';

            data.remediations.forEach(r => {
                const statusClass = r.status === 'success' ? 'status-success' :
                                   r.status === 'failed' ? 'status-failed' : 'status-running';
                tbody.innerHTML += `
                    <tr>
                        <td>${r.alert_name}</td>
                        <td>${r.action_name}</td>
                        <td><span class="status ${statusClass}">${r.status}</span></td>
                        <td>${new Date(r.started_at).toLocaleString()}</td>
                        <td>${r.execution_id || '-'}</td>
                    </tr>
                `;
            });
        }

        function showCreateModal() {
            editMode = false;
            document.getElementById('modal-title').textContent = 'Create Mapping';
            document.getElementById('alert-name').value = '';
            document.getElementById('alert-name').disabled = false;
            document.getElementById('mapping-config').value = `handler: yaml_config
actions:
  - name: example_action
    action: core.remote
    parameters:
      hosts: "{{instance}}"
      cmd: "echo hello"
    timeout: 60`;
            document.getElementById('edit-modal').classList.add('active');
        }

        async function editMapping(name) {
            editMode = true;
            const res = await fetch(`/api/mappings/${name}`);
            const data = await res.json();

            document.getElementById('modal-title').textContent = 'Edit Mapping';
            document.getElementById('alert-name').value = name;
            document.getElementById('alert-name').disabled = true;
            document.getElementById('mapping-config').value = jsyaml.dump(data.config);
            document.getElementById('edit-modal').classList.add('active');
        }

        async function saveMapping(e) {
            e.preventDefault();
            const name = document.getElementById('alert-name').value;
            const config = jsyaml.load(document.getElementById('mapping-config').value);

            const url = editMode ? `/api/mappings/${name}` : '/api/mappings';
            const method = editMode ? 'PUT' : 'POST';
            const body = editMode ? { config } : { alert_name: name, config };

            await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            closeModal();
            loadMappings();
        }

        async function deleteMapping(name) {
            if (!confirm(`Delete mapping "${name}"?`)) return;
            await fetch(`/api/mappings/${name}`, { method: 'DELETE' });
            loadMappings();
        }

        function closeModal() {
            document.getElementById('edit-modal').classList.remove('active');
        }

        function showImportModal() {
            document.getElementById('import-modal').classList.add('active');
        }

        function closeImportModal() {
            document.getElementById('import-modal').classList.remove('active');
        }

        async function importMappings(e) {
            e.preventDefault();
            const yaml_content = document.getElementById('import-yaml').value;
            const overwrite = document.getElementById('import-overwrite').checked;

            const res = await fetch('/api/mappings/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ yaml_content, overwrite })
            });

            const data = await res.json();
            alert(`Imported: ${data.imported}, Skipped: ${data.skipped}`);
            closeImportModal();
            loadMappings();
        }

        async function exportMappings() {
            window.open('/api/mappings/export', '_blank');
        }

        async function showAction(ref) {
            const res = await fetch(`/api/stackstorm/actions/${ref}`);
            currentAction = await res.json();
            document.getElementById('action-title').textContent = ref;
            document.getElementById('action-details').textContent = JSON.stringify(currentAction, null, 2);
            document.getElementById('action-modal').classList.add('active');
        }

        function closeActionModal() {
            document.getElementById('action-modal').classList.remove('active');
        }

        function useAction() {
            if (!currentAction) return;
            const params = {};
            if (currentAction.parameters) {
                Object.keys(currentAction.parameters).forEach(k => {
                    params[k] = `{{${k}}}`;
                });
            }

            const config = {
                handler: 'yaml_config',
                actions: [{
                    name: currentAction.ref.replace('.', '_'),
                    action: currentAction.ref,
                    description: currentAction.description || '',
                    parameters: params,
                    timeout: 300
                }]
            };

            closeActionModal();
            showCreateModal();
            document.getElementById('mapping-config').value = jsyaml.dump(config);
        }

        async function editAction(ref) {
            const res = await fetch(`/api/stackstorm/actions/${ref}`);
            const action = await res.json();

            editActionMode = true;
            document.getElementById('action-modal-title').textContent = 'Edit Action';
            document.getElementById('action-ref').value = ref;
            document.getElementById('action-ref').disabled = true;
            document.getElementById('action-data').value = JSON.stringify(action, null, 2);
            document.getElementById('edit-action-modal').classList.add('active');
        }

        function showCreateActionModal() {
            editActionMode = false;
            document.getElementById('action-modal-title').textContent = 'Create Action';
            document.getElementById('action-ref').value = '';
            document.getElementById('action-ref').disabled = false;
            document.getElementById('action-data').value = JSON.stringify({
                "name": "",
                "pack": "",
                "description": "",
                "enabled": true,
                "runner_type": "remote-shell-cmd",
                "parameters": {
                    "cmd": {
                        "type": "string",
                        "description": "Command to execute",
                        "required": true
                    }
                }
            }, null, 2);
            document.getElementById('edit-action-modal').classList.add('active');
        }

        async function saveAction(e) {
            e.preventDefault();
            const ref = document.getElementById('action-ref').value;
            const data = JSON.parse(document.getElementById('action-data').value);

            try {
                if (editActionMode) {
                    const res = await fetch(`/api/stackstorm/actions/${ref}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    if (!res.ok) {
                        const error = await res.json();
                        alert(`Failed to update action: ${error.detail || res.statusText}`);
                        return;
                    }
                } else {
                    const res = await fetch('/api/stackstorm/actions', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    if (!res.ok) {
                        const error = await res.json();
                        alert(`Failed to create action: ${error.detail || res.statusText}`);
                        return;
                    }
                }

                closeEditActionModal();
                loadActions();
                alert('Action saved successfully!');
            } catch (err) {
                alert(`Error: ${err.message}`);
            }
        }

        async function deleteAction(ref) {
            if (!confirm(`Delete action "${ref}"?`)) return;

            const res = await fetch(`/api/stackstorm/actions/${ref}`, {
                method: 'DELETE'
            });

            if (res.ok) {
                loadActions();
                alert('Action deleted successfully!');
            } else {
                const error = await res.json();
                alert(`Failed to delete action: ${error.detail || res.statusText}`);
            }
        }

        function closeEditActionModal() {
            document.getElementById('edit-action-modal').classList.remove('active');
        }

        // Dashboard functions
        async function loadDashboard() {
            // Load health data for dashboard cards
            const healthRes = await fetch('/health');
            const health = await healthRes.json();

            // Load alert stats
            const statsRes = await fetch('/alerts/stats');
            const stats = await statsRes.json();

            // Load recent history
            const historyRes = await fetch('/remediations?limit=10');
            const history = await historyRes.json();

            // Update dashboard metrics
            const metricsDiv = document.getElementById('dashboard-metrics');
            const stackstormClass = health.stackstorm === 'healthy' ? 'healthy' : 'error';
            const stateClass = health.state_store === 'healthy' ? 'healthy' : 'error';
            const overallClass = health.status === 'healthy' ? 'healthy' : (health.status === 'degraded' ? 'warning' : 'error');

            metricsDiv.innerHTML = `
                <div class="dashboard-card ${overallClass}">
                    <h3>System Status</h3>
                    <div class="metric-row">
                        <span class="metric-label">Overall</span>
                        <span class="metric-value">${health.status.toUpperCase()}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Instance</span>
                        <span class="metric-value">${health.instance_id || 'Unknown'}</span>
                    </div>
                </div>
                <div class="dashboard-card ${stackstormClass}">
                    <h3>StackStorm</h3>
                    <div class="metric-row">
                        <span class="metric-label">Status</span>
                        <span class="metric-value">${health.stackstorm.toUpperCase()}</span>
                    </div>
                </div>
                <div class="dashboard-card ${stateClass}">
                    <h3>State Store</h3>
                    <div class="metric-row">
                        <span class="metric-label">Status</span>
                        <span class="metric-value">${health.state_store.toUpperCase()}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Total Alerts</span>
                        <span class="metric-value">${stats.total}</span>
                    </div>
                </div>
            `;

            // Update recent activity
            const activityDiv = document.getElementById('recent-activity');
            if (history.remediations.length === 0) {
                activityDiv.innerHTML = '<p style="color: #666; text-align: center;">No recent activity</p>';
            } else {
                activityDiv.innerHTML = history.remediations.slice(0, 5).map(r => {
                    const statusClass = r.status === 'success' ? 'success' : 'failed';
                    const time = new Date(r.started_at).toLocaleString();
                    return `
                        <div class="activity-item ${statusClass}">
                            <div><strong>${r.alert_name}</strong> → ${r.action_name}</div>
                            <div class="time">${time}</div>
                        </div>
                    `;
                }).join('');
            }

            // Update quick stats
            const quickStatsDiv = document.getElementById('quick-stats');
            quickStatsDiv.innerHTML = `
                <div class="metric-row">
                    <span class="metric-label">Active Alerts</span>
                    <span class="metric-value">${stats.by_status.remediating || 0}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Resolved Today</span>
                    <span class="metric-value">${stats.by_status.resolved || 0}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Total Tracked</span>
                    <span class="metric-value">${stats.total}</span>
                </div>
            `;
        }

        // Health functions
        async function loadHealth() {
            const res = await fetch('/health');
            const health = await res.json();

            const componentsDiv = document.getElementById('health-components');
            const stackstormClass = health.stackstorm === 'healthy' ? 'healthy' : 'error';
            const stateClass = health.state_store === 'healthy' ? 'healthy' : 'error';
            const overallClass = health.status === 'healthy' ? 'healthy' : (health.status === 'degraded' ? 'warning' : 'error');

            componentsDiv.innerHTML = `
                <div class="dashboard-card ${overallClass}">
                    <h3><span class="health-indicator ${overallClass}"></span>Overall System</h3>
                    <div class="metric-row">
                        <span class="metric-label">Status</span>
                        <span class="metric-value">${health.status.toUpperCase()}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Instance ID</span>
                        <span class="metric-value" style="font-size: 12px;">${health.instance_id || 'Unknown'}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Timestamp</span>
                        <span class="metric-value" style="font-size: 12px;">${new Date().toLocaleString()}</span>
                    </div>
                </div>
                <div class="dashboard-card ${stackstormClass}">
                    <h3><span class="health-indicator ${stackstormClass}"></span>StackStorm</h3>
                    <div class="metric-row">
                        <span class="metric-label">Connection</span>
                        <span class="metric-value">${health.stackstorm.toUpperCase()}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">API Accessible</span>
                        <span class="metric-value">${health.stackstorm === 'healthy' ? 'Yes' : 'No'}</span>
                    </div>
                </div>
                <div class="dashboard-card ${stateClass}">
                    <h3><span class="health-indicator ${stateClass}"></span>State Store</h3>
                    <div class="metric-row">
                        <span class="metric-label">Status</span>
                        <span class="metric-value">${health.state_store.toUpperCase()}</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Type</span>
                        <span class="metric-value">${health.state_store === 'healthy' ? 'Connected' : 'Unavailable'}</span>
                    </div>
                </div>
            `;
        }

        // Settings functions
        async function loadSettings() {
            const res = await fetch('/api/settings');
            const settings = await res.json();

            const contentDiv = document.getElementById('settings-content');

            let gitSection = '';
            if (settings.git_enabled) {
                gitSection = `
                    <div class="config-section">
                        <h3>Git Configuration</h3>
                        <div class="config-item">
                            <div class="key">Enabled</div>
                            <div class="value">Yes</div>
                        </div>
                        <div class="config-item">
                            <div class="key">Provider</div>
                            <div class="value">${settings.git_provider || 'Not configured'}</div>
                        </div>
                        <div class="config-item">
                            <div class="key">Repository</div>
                            <div class="value">${settings.git_repo_url || 'Not configured'}</div>
                        </div>
                        <div class="config-item">
                            <div class="key">Branch</div>
                            <div class="value">${settings.git_branch || 'Not configured'}</div>
                        </div>
                    </div>
                `;
            } else {
                gitSection = `
                    <div class="config-section">
                        <h3>Git Configuration</h3>
                        <div class="config-item">
                            <div class="key">Enabled</div>
                            <div class="value">No</div>
                        </div>
                    </div>
                `;
            }

            let prometheusSection = '';
            if (settings.prometheus_use_crds) {
                prometheusSection = `
                    <div class="config-section">
                        <h3>Prometheus Configuration</h3>
                        <div class="config-item">
                            <div class="key">CRD Mode</div>
                            <div class="value">Enabled</div>
                        </div>
                        <div class="config-item">
                            <div class="key">CRD Namespace</div>
                            <div class="value">${settings.prometheus_crd_namespace || 'Not configured'}</div>
                        </div>
                    </div>
                `;
            } else {
                prometheusSection = `
                    <div class="config-section">
                        <h3>Prometheus Configuration</h3>
                        <div class="config-item">
                            <div class="key">CRD Mode</div>
                            <div class="value">Disabled</div>
                        </div>
                    </div>
                `;
            }

            contentDiv.innerHTML = `
                <div class="config-section">
                    <h3>StackStorm Configuration</h3>
                    <div class="config-item">
                        <div class="key">API URL</div>
                        <div class="value">${settings.stackstorm_url || 'Not configured'}</div>
                    </div>
                </div>
                ${prometheusSection}
                ${gitSection}
            `;
        }

        // Load js-yaml from CDN
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js';
        document.head.appendChild(script);

        // Initialize on page load
        document.addEventListener('DOMContentLoaded', () => {
            loadDashboard(); // Load dashboard by default
            toggleAutoRefresh(); // Start auto-refresh
        });
    </script>
</body>
</html>"""


app = create_app()
