# PoundCake

An extensible auto-remediation framework that bridges Prometheus Alertmanager with StackStorm. PoundCake receives alerts from Alertmanager and automatically executes remediation actions through StackStorm.

## Features

- **Webhook Receiver**: Receives alerts from Prometheus Alertmanager
- **StackStorm Integration**: Executes remediation actions via StackStorm API
- **YAML Configuration**: Define alert-to-action mappings in YAML files
- **Handler Registry**: Extensible handler system for custom remediation logic
- **Built-in Handlers**: Pre-built handlers for common scenarios (CPU, disk, memory, services)
- **Prometheus Metrics**: Built-in metrics for monitoring remediation performance
- **Conditional Execution**: Execute actions based on severity, labels, or other conditions
- **Template Support**: Dynamic parameters using alert labels and annotations

## Prerequisites

### StackStorm

PoundCake requires a running StackStorm instance to execute remediation actions. StackStorm is an open-source
automation platform that provides event-driven automation and integrates with various infrastructure tools.

#### Installing StackStorm on Kubernetes

```bash
# Add the StackStorm Helm repository
helm repo add stackstorm https://helm.stackstorm.com
helm repo update

# Install StackStorm HA (High Availability)
helm install stackstorm stackstorm/stackstorm-ha \
  --namespace stackstorm \
  --create-namespace \
  --set st2.password=your-admin-password

# Wait for pods to be ready
kubectl -n stackstorm get pods -w
```

For production deployments, see the [StackStorm Kubernetes documentation](https://docs.stackstorm.com/install/k8s_ha.html).

#### StackStorm Authentication

PoundCake can automatically generate and manage its own API key. You have two options:

**Option 1: Automatic API Key Generation (Recommended)**

Provide StackStorm admin credentials and PoundCake will automatically:
- Discover StackStorm in the Kubernetes cluster
- Validate any existing API key
- Generate a new API key if needed

```bash
# Deploy with admin credentials for auto-configuration
helm install poundcake ./helm/poundcake \
  --set stackstorm.adminUser=st2admin \
  --set stackstorm.adminPassword=your-admin-password
```

Or use an existing secret:

```bash
# Create secret with admin password
kubectl create secret generic stackstorm-admin \
  --from-literal=password=your-admin-password

# Deploy referencing the secret
helm install poundcake ./helm/poundcake \
  --set stackstorm.adminUser=st2admin \
  --set stackstorm.adminPasswordSecret=stackstorm-admin
```

**Option 2: Manual API Key**

If you prefer to manage the API key manually:

```bash
# Generate API key in StackStorm
st2 login st2admin -p your-password
st2 apikey create -k -m '{"used_by": "poundcake"}'

# Deploy with the API key
helm install poundcake ./helm/poundcake \
  --set stackstorm.apiKey=your-generated-key
```

#### Required StackStorm Packs

Install the packs needed for your remediation actions:

```bash
# Core pack (included by default)
# Provides: core.remote, core.local, core.http, etc.

# Linux pack for service management
st2 pack install linux
# Provides: linux.service, linux.rm, linux.cp, etc.

# Optional: Additional packs based on your needs
st2 pack install slack      # Slack notifications
st2 pack install email      # Email notifications
st2 pack install aws        # AWS actions
st2 pack install kubernetes # Kubernetes actions
```

#### Verifying StackStorm Setup

Test that StackStorm is working correctly:

```bash
# List available actions
st2 action list --pack=core

# Test a simple action
st2 run core.local cmd="echo 'StackStorm is working'"

# Test remote execution (requires SSH setup)
st2 run core.remote hosts="your-server" cmd="uptime"
```

### Prometheus & Alertmanager

PoundCake receives alerts from Prometheus Alertmanager. If you don't have these installed:

```bash
# Using Prometheus Operator (recommended for Kubernetes)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

## Deployment

PoundCake is deployed using Helm on Kubernetes. Both the Docker image and Helm chart are published to GitHub Container Registry.

### Quick Start

```bash
# Install from OCI registry
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set stackstorm.url=https://stackstorm-api.stackstorm.svc.cluster.local \
  --set stackstorm.apiKey=your-st2-api-key

# Or install a specific version
helm install poundcake oci://ghcr.io/aedan/poundcake --version 0.1.0 \
  --namespace poundcake \
  --create-namespace \
  --set stackstorm.apiKey=your-st2-api-key

# Or install from local chart (for development)
helm install poundcake ./helm/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set stackstorm.apiKey=your-st2-api-key
```

### Building the Docker Image

The Dockerfile is used to build images for the Helm chart deployment:

```bash
# Build the image
docker build -t ghcr.io/aedan/poundcake:0.1.0 .

# Push to GitHub Container Registry
docker push ghcr.io/aedan/poundcake:0.1.0
```

### Using a Specific Image Version

```bash
# The chart automatically uses the correct image version
# Override if needed:
helm install poundcake oci://ghcr.io/aedan/poundcake --version 0.1.0 \
  --namespace poundcake \
  --create-namespace \
  --set image.tag=0.1.0 \
  --set stackstorm.apiKey=your-st2-api-key
```

### Using an Existing Secret for StackStorm Credentials

```bash
# Create secret manually
kubectl create secret generic stackstorm-credentials \
  --namespace poundcake \
  --from-literal=api-key=your-st2-api-key

# Install with existing secret
helm install poundcake ./helm/poundcake \
  --namespace poundcake \
  --set stackstorm.existingSecret=stackstorm-credentials
```

### Custom Alert Mappings

Create a custom values file with your mappings:

```yaml
# my-values.yaml
mappings:
  custom.yaml: |
    alerts:
      MyCustomAlert:
        handler: yaml_config
        actions:
          - name: fix_issue
            action: core.remote
            parameters:
              hosts: "{{instance}}"
              cmd: "systemctl restart myservice"
```

```bash
helm install poundcake ./helm/poundcake -f my-values.yaml
```

### Horizontal Scaling with Redis

For production deployments with multiple replicas, PoundCake requires Redis for distributed state management and alert tracking. This enables:

- **Stateful alert tracking** - Track alerts through their lifecycle (received, remediating, remediated, resolved)
- **Distributed locking** - Prevent duplicate processing across instances
- **Shared state** - All instances see the same alert status

#### Deploy with Built-in Redis (Recommended)

The Helm chart includes an independent Redis deployment with persistent storage:

```bash
# Deploy with built-in Redis (uses default storage class)
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set replicaCount=3 \
  --set redis.enabled=true \
  --set redis.password=my-redis-password \
  --set stackstorm.url=https://stackstorm-api.stackstorm.svc.cluster.local \
  --set stackstorm.apiKey=your-st2-api-key
```

Customize the Redis persistence:

```bash
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set replicaCount=3 \
  --set redis.enabled=true \
  --set redis.password=my-redis-password \
  --set redis.persistence.storageClass=my-storage-class \
  --set redis.persistence.size=5Gi \
  --set stackstorm.apiKey=your-st2-api-key
```

#### Use External Redis

To use an existing Redis instance instead of deploying one:

```bash
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --create-namespace \
  --set replicaCount=3 \
  --set redis.enabled=true \
  --set redis.deploy=false \
  --set redis.external.url=redis://my-redis:6379/0 \
  --set redis.external.password=my-redis-password \
  --set stackstorm.apiKey=your-st2-api-key
```

Or use an existing secret for the Redis password:

```bash
# Create Redis secret
kubectl create secret generic redis-credentials \
  --namespace poundcake \
  --from-literal=redis-password=my-redis-password

# Deploy with secret reference
helm install poundcake oci://ghcr.io/aedan/poundcake \
  --namespace poundcake \
  --set replicaCount=3 \
  --set redis.enabled=true \
  --set redis.deploy=false \
  --set redis.external.url=redis://my-redis:6379/0 \
  --set redis.external.existingSecret=redis-credentials
```

#### Alert Lifecycle States

| Status | Description |
|--------|-------------|
| `received` | Alert just arrived from Alertmanager |
| `pending` | Queued, waiting for remediation |
| `remediating` | Remediation actions in progress |
| `remediated` | All actions completed |
| `resolved` | Alert cleared by Alertmanager |

#### Alert Status UI

Access the web UI at `/ui` to view:
- Real-time alert status with auto-refresh (5 seconds)
- Filter alerts by status
- Expandable rows showing remediation attempts
- Statistics dashboard

### Configure Alertmanager

Point Alertmanager to the PoundCake webhook:

```yaml
receivers:
  - name: 'poundcake'
    webhook_configs:
      - url: 'http://poundcake:8080/webhook'
        send_resolved: true
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Alertmanager│────▶│  PoundCake  │────▶│  StackStorm │────▶│   Target    │
│             │     │   Webhook   │     │     API     │     │   Systems   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │    YAML     │
                    │  Mappings   │
                    └─────────────┘
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POUNDCAKE_HOST` | Server bind address | `0.0.0.0` |
| `POUNDCAKE_PORT` | Server port | `8080` |
| `POUNDCAKE_DEBUG` | Enable debug mode | `false` |
| `POUNDCAKE_STACKSTORM_URL` | StackStorm API URL | `https://localhost` |
| `POUNDCAKE_STACKSTORM_API_KEY` | StackStorm API key | `` |
| `POUNDCAKE_STACKSTORM_AUTH_TOKEN` | StackStorm auth token | `` |
| `POUNDCAKE_STACKSTORM_VERIFY_SSL` | Verify SSL certificates | `true` |
| `POUNDCAKE_MAPPINGS_PATH` | Path to YAML mappings | `config/mappings` |
| `POUNDCAKE_LOG_LEVEL` | Logging level | `INFO` |
| `POUNDCAKE_METRICS_ENABLED` | Enable Prometheus metrics | `true` |
| `POUNDCAKE_REDIS_URL` | Redis connection URL | `` |
| `POUNDCAKE_REDIS_PASSWORD` | Redis password | `` |
| `POUNDCAKE_ALERT_TTL_HOURS` | TTL for resolved alerts | `24` |
| `POUNDCAKE_LOCK_TIMEOUT_SECONDS` | Distributed lock timeout | `300` |

### YAML Mappings

Create YAML files in the `config/mappings` directory to define alert-to-action mappings:

```yaml
alerts:
  HighCPUUsage:
    description: "Remediate high CPU usage"
    handler: yaml_config
    actions:
      - name: identify_cpu_process
        action: core.remote
        description: "Identify CPU-intensive processes"
        parameters:
          hosts: "{{instance}}"
          cmd: "ps aux --sort=-%cpu | head -10"
        timeout: 60

      - name: restart_service
        action: linux.service
        description: "Restart the problematic service"
        conditions:
          severity: critical
          has_labels:
            - service
        parameters:
          host: "{{instance}}"
          service: "{{labels.service}}"
          action: restart
        timeout: 120
```

### Template Variables

Use these templates in your YAML configurations:

- `{{alertname}}` - Alert name
- `{{instance}}` - Instance label value
- `{{severity}}` - Severity label value
- `{{labels.key}}` - Any label value
- `{{annotations.key}}` - Any annotation value

### Conditions

Actions can have conditions that must be met:

```yaml
conditions:
  severity: critical  # or [warning, critical]
  labels:
    environment: production
  has_labels:
    - service
    - job
```

## Creating Custom Handlers

Create custom handlers for complex remediation logic:

```python
from poundcake.handlers.base import BaseHandler, HandlerContext
from poundcake.models.remediation import RemediationAction

class MyCustomHandler(BaseHandler):
    @property
    def name(self) -> str:
        return "my_custom_handler"

    @property
    def description(self) -> str:
        return "Handles my specific alerts"

    async def can_handle(self, context: HandlerContext) -> bool:
        # Return True if this handler can process the alert
        return "my_keyword" in context.alert.alertname.lower()

    async def get_actions(self, context: HandlerContext) -> list[RemediationAction]:
        # Return list of remediation actions
        return [
            RemediationAction(
                name="my_action",
                action="my.stackstorm.action",
                parameters={
                    "host": context.alert.instance,
                    **self.build_parameters(context),
                },
            )
        ]
```

Register your handler:

```python
from poundcake.handlers import get_registry

registry = get_registry()
registry.register(MyCustomHandler())
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook` | POST | Receive Alertmanager webhooks |
| `/health` | GET | Health check |
| `/ready` | GET | Readiness check |
| `/handlers` | GET | List registered handlers |
| `/remediations` | GET | List remediation history |
| `/alerts` | GET | List tracked alerts with status |
| `/alerts/stats` | GET | Alert statistics by status/severity |
| `/alerts/{fingerprint}` | GET | Get specific alert details |
| `/metrics` | GET | Prometheus metrics |

## Prometheus Metrics

- `poundcake_alerts_received_total` - Total alerts received
- `poundcake_remediations_executed_total` - Total remediations executed
- `poundcake_remediation_duration_seconds` - Duration of remediation actions
- `poundcake_active_remediations` - Currently active remediations

## Alertmanager Configuration

PoundCake receives alerts via the standard Alertmanager webhook format. Configure Alertmanager to forward alerts to PoundCake's `/webhook` endpoint.

### Basic Configuration

Add PoundCake as a receiver in your Alertmanager configuration:

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'poundcake'

receivers:
  - name: 'poundcake'
    webhook_configs:
      - url: 'http://poundcake.poundcake.svc.cluster.local:8080/webhook'
        send_resolved: true
        max_alerts: 10
```

### Routing Specific Alerts to PoundCake

Route only certain alerts to PoundCake based on labels:

```yaml
route:
  receiver: 'default'
  routes:
    # Route auto-remediable alerts to PoundCake
    - match:
        auto_remediate: "true"
      receiver: 'poundcake'
      continue: true  # Also send to other receivers

    # Route by severity
    - match:
        severity: critical
      receiver: 'poundcake'
      group_wait: 0s  # Send critical alerts immediately

    # Route specific alert types
    - match_re:
        alertname: ^(HighCPU|LowDiskSpace|ServiceDown)$
      receiver: 'poundcake'

receivers:
  - name: 'default'
    # Your default notification config

  - name: 'poundcake'
    webhook_configs:
      - url: 'http://poundcake.poundcake.svc.cluster.local:8080/webhook'
        send_resolved: true
```

### Multiple Environments

Send alerts to different PoundCake instances based on environment:

```yaml
route:
  receiver: 'default'
  routes:
    - match:
        environment: production
      receiver: 'poundcake-prod'

    - match:
        environment: staging
      receiver: 'poundcake-staging'

receivers:
  - name: 'poundcake-prod'
    webhook_configs:
      - url: 'http://poundcake.production.svc.cluster.local:8080/webhook'
        send_resolved: true

  - name: 'poundcake-staging'
    webhook_configs:
      - url: 'http://poundcake.staging.svc.cluster.local:8080/webhook'
        send_resolved: true
```

### Inhibit Rules

Prevent remediation storms by inhibiting related alerts:

```yaml
inhibit_rules:
  # Don't remediate warning if critical is firing
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']

  # Don't remediate if maintenance mode is active
  - source_match:
      alertname: 'MaintenanceMode'
    target_match_re:
      alertname: '.+'
    equal: ['instance']
```

### Configuring with Prometheus Operator

If using the Prometheus Operator, configure Alertmanager via AlertmanagerConfig CRD:

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: poundcake
  namespace: monitoring
spec:
  route:
    receiver: 'poundcake'
    groupBy: ['alertname']
    groupWait: 10s
    groupInterval: 10s
    repeatInterval: 1h
    matchers:
      - name: auto_remediate
        value: "true"
  receivers:
    - name: 'poundcake'
      webhookConfigs:
        - url: 'http://poundcake.poundcake.svc.cluster.local:8080/webhook'
          sendResolved: true
```

### Prometheus Alert Rules with Remediation Labels

Add labels to your Prometheus alert rules to enable auto-remediation:

```yaml
groups:
  - name: auto-remediation
    rules:
      - alert: HighCPUUsage
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
        for: 5m
        labels:
          severity: warning
          auto_remediate: "true"
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is above 80% for more than 5 minutes"

      - alert: LowDiskSpace
        expr: (node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100 < 10
        for: 5m
        labels:
          severity: critical
          auto_remediate: "true"
        annotations:
          summary: "Low disk space on {{ $labels.instance }}"
          description: "Disk space is below 10%"

      - alert: ServiceDown
        expr: up{job="myservice"} == 0
        for: 1m
        labels:
          severity: critical
          auto_remediate: "true"
          service: myservice
        annotations:
          summary: "Service {{ $labels.job }} is down"
```

### Testing the Webhook

Test that Alertmanager can reach PoundCake:

```bash
# From within the cluster
kubectl run curl --image=curlimages/curl --rm -it --restart=Never -- \
  curl -X POST http://poundcake.poundcake.svc.cluster.local:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "version": "4",
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "TestAlert",
        "severity": "warning",
        "instance": "test-server:9090"
      },
      "annotations": {
        "summary": "Test alert"
      },
      "startsAt": "2024-01-01T00:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "fingerprint": "test123"
    }]
  }'
```

### Enabling Prometheus ServiceMonitor

If using Prometheus Operator:

```bash
helm install poundcake ./helm/poundcake \
  --set serviceMonitor.enabled=true \
  --set serviceMonitor.labels.release=prometheus
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src tests
ruff check src tests

# Type check
mypy src
```

## Example Alert Flow

1. Prometheus detects high CPU usage
2. Alertmanager receives the alert and forwards to PoundCake webhook
3. PoundCake matches the alert to handlers/mappings
4. Remediation actions are extracted and executed via StackStorm
5. Results are logged and metrics are updated

## License

MIT License
