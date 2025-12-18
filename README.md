# PoundCake

An extensible auto-remediation framework that bridges Prometheus Alertmanager with StackStorm. PoundCake receives alerts from Alertmanager and automatically executes remediation actions through StackStorm.

## Features

- **Webhook Receiver**: Receives alerts from Prometheus Alertmanager
- **StackStorm Integration**: Executes remediation actions via StackStorm API
- **Prometheus Rule Management**: Edit and manage Prometheus alert rules via CRDs and GitOps
- **Management UI**: Comprehensive web interface with Dashboard, Health monitoring, and Settings
- **Command-Line Interface**: Powerful CLI (`pcake`) for managing alerts and rules
- **Alert Tracking**: Real-time status tracking through alert lifecycle (received → remediating → resolved)
- **YAML Configuration**: Define alert-to-action mappings in YAML files
- **Handler Registry**: Extensible handler system for custom remediation logic
- **Built-in Handlers**: Pre-built handlers for common scenarios (CPU, disk, memory, services)
- **GitOps Workflow**: Automatic PR creation for rule changes with audit trail
- **Prometheus Metrics**: Built-in metrics for monitoring remediation performance
- **Conditional Execution**: Execute actions based on severity, labels, or other conditions
- **Template Support**: Dynamic parameters using alert labels and annotations
- **Horizontal Scaling**: Distributed locking with Redis for multi-instance deployments

## Quick Start

### 1. Install StackStorm

PoundCake requires a running StackStorm instance to execute remediation actions. Use the provided install script:

```bash
# Install StackStorm using the install script
cd bin
./install-stackstorm.sh
```

This script will:
- Install StackStorm via Helm
- Create admin credentials secret in both `stackstorm` and `poundcake` namespaces
- Configure RBAC and authentication
- Display the generated admin password

### 2. Install PoundCake

```bash
# Install PoundCake using the install script
./install-poundcake.sh
```

PoundCake will automatically:
- Connect to StackStorm using the shared `stackstorm-admin` secret
- Auto-generate API keys for authentication
- Set up alert tracking with Redis
- Configure the webhook endpoint for Alertmanager

### 3. Configure Alertmanager

Add PoundCake as a webhook receiver in Alertmanager:

```yaml
receivers:
  - name: poundcake
    webhook_configs:
      - url: http://poundcake.poundcake.svc.cluster.local:8080/webhook
```

## Command-Line Interface (CLI)

PoundCake includes a powerful CLI tool (`pcake`) for managing alerts and Prometheus rules from the command line.

### Installation

The CLI is installed automatically with PoundCake:

```bash
pip install poundcake
```

### Basic Usage

```bash
# Configure API endpoint
export POUNDCAKE_URL=http://poundcake.example.com:8080

# List all alerts
pcake alerts list

# Filter alerts by status
pcake alerts list --status remediating

# Watch alerts in real-time
pcake alerts watch --watch

# List Prometheus rules
pcake rules list

# Create a new rule
pcake rules create my-alerts app-alerts HighMemory \
  --expr 'memory_usage > 90' \
  --for 5m \
  --severity critical

# Update a rule from file
pcake rules update my-alerts app-alerts HighMemory --file rule.yaml

# Apply rules from a file
pcake rules apply prometheus-rules.yaml

# Delete a rule
pcake rules delete my-alerts app-alerts HighMemory --yes
```

### Output Formats

The CLI supports multiple output formats:

```bash
# Human-readable table (default)
pcake alerts list

# JSON output
pcake --format json alerts list

# YAML output
pcake --format yaml rules get my-alerts app-alerts HighMemory
```

### Documentation

See [CLI Documentation](docs/CLI.md) for complete usage guide and examples.

## Prerequisites

### StackStorm

PoundCake requires a running StackStorm instance to execute remediation actions. StackStorm is an open-source
automation platform that provides event-driven automation and integrates with various infrastructure tools.

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
helm install poundcake oci://ghcr.io/aedan/poundcake --version 0.2.0 \
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
docker build -t ghcr.io/aedan/poundcake:0.2.0 .

# Push to GitHub Container Registry
docker push ghcr.io/aedan/poundcake:0.2.0
```

### Using a Specific Image Version

```bash
# The chart automatically uses the correct image version
# Override if needed:
helm install poundcake oci://ghcr.io/aedan/poundcake --version 0.2.0 \
  --namespace poundcake \
  --create-namespace \
  --set image.tag=0.2.0 \
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

#### Management UI

Access the web UI at `/ui` to manage your PoundCake instance:

**Dashboard Tab** (Default Landing Page):
- System status overview with health indicators
- Real-time metrics for StackStorm and State Store connectivity
- Recent remediation activity feed
- Quick stats showing active alerts and resolution counts

**Alert Status Tab**:
- Real-time alert status with auto-refresh (5 seconds)
- Filter alerts by status (received, pending, remediating, remediated, resolved)
- Expandable rows showing detailed remediation attempts
- Statistics dashboard with alert counts by status

**Prometheus Rules Tab**:
- View and manage Prometheus alert rules via CRDs
- Create, edit, and delete rules through the UI
- GitOps integration for automatic PR creation
- Filter by state (firing/pending/inactive)

**Mappings Tab**:
- Create and edit alert-to-action mappings
- Import/export YAML configurations
- Visual mapping builder

**StackStorm Actions Tab**:
- Browse available StackStorm actions by pack
- View action parameters and documentation
- Create and edit custom actions
- Quick integration with mappings

**Execution History Tab**:
- View past remediation executions
- Filter by status and time range
- Execution details and timing information

**Health Tab**:
- System component health checks
- Real-time status of StackStorm connection
- State Store connectivity monitoring
- Overall system health indicators

**Settings Tab**:
- View current configuration
- StackStorm API endpoint settings
- Prometheus CRD configuration
- Git repository integration settings

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
