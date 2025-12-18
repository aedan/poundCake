# PoundCake CLI (pcake)

The PoundCake CLI provides a command-line interface for managing alerts, Prometheus rules, and remediations through the PoundCake API.

## Installation

The CLI is installed automatically with PoundCake:

```bash
pip install poundcake
```

After installation, the `pcake` command will be available.

## Configuration

The CLI connects to a PoundCake API server. You can specify the server URL in multiple ways:

### Environment Variable

```bash
export POUNDCAKE_URL=http://poundcake.example.com:8080
pcake alerts list
```

### Command-line Flag

```bash
pcake --url http://poundcake.example.com:8080 alerts list
```

### API Authentication (if enabled)

```bash
export POUNDCAKE_API_KEY=your-api-key
# or
pcake --api-key your-api-key alerts list
```

## Global Options

```bash
pcake [OPTIONS] COMMAND [ARGS]...

Options:
  -u, --url TEXT         PoundCake API URL (default: http://localhost:8080)
  -k, --api-key TEXT     API key for authentication (if required)
  -f, --format [json|yaml|table]  Output format (default: table)
  -v, --verbose          Enable verbose output
  --help                 Show help message
```

## Commands

### Alerts Management

#### List Alerts

List all alerts with optional filtering:

```bash
# List all alerts
pcake alerts list

# Filter by status
pcake alerts list --status remediating

# Filter by severity
pcake alerts list --severity critical

# Output as JSON
pcake --format json alerts list
```

**Statuses:**
- `received` - Alert just arrived from Alertmanager
- `pending` - Queued for remediation
- `remediating` - Remediation in progress
- `remediated` - Remediation completed
- `resolved` - Alert cleared by Alertmanager

**Severities:**
- `critical`
- `warning`
- `info`

#### Get Alert Details

Get detailed information about a specific alert:

```bash
pcake alerts get <fingerprint>
```

Example:
```bash
pcake alerts get 7c7e6f4c8a9b2e1d
```

#### Watch Alerts

Watch alerts in real-time (refreshes every 5 seconds):

```bash
# Watch all alerts
pcake alerts watch --watch

# Watch critical alerts
pcake alerts watch --severity critical --watch

# Watch remediating alerts
pcake alerts watch --status remediating --watch
```

Press `Ctrl+C` to stop watching.

### Prometheus Rule Management

#### List Rules

List all Prometheus alert rules:

```bash
# List all rules
pcake rules list

# Output as YAML
pcake --format yaml rules list
```

#### Get Rule Details

Get details of a specific rule:

```bash
pcake rules get <crd-name> <group-name> <rule-name>
```

Example:
```bash
pcake rules get node-alerts system-alerts HighCPU
```

#### Create Rule

Create a new Prometheus alert rule:

**From a YAML file:**

```bash
pcake rules create my-alerts app-alerts HighMemory --file rule.yaml
```

**From command-line options:**

```bash
pcake rules create my-alerts app-alerts HighMemory \
  --expr 'memory_usage > 90' \
  --for 5m \
  --severity critical \
  --summary "High memory usage detected" \
  --description "Memory usage is above 90%"
```

**YAML file format:**

```yaml
alert: HighMemory
expr: memory_usage > 90
for: 5m
labels:
  severity: critical
annotations:
  summary: "High memory usage detected"
  description: "Memory usage is above 90%"
```

#### Update Rule

Update an existing Prometheus alert rule:

**From a YAML file:**

```bash
pcake rules update my-alerts app-alerts HighMemory --file updated-rule.yaml
```

**Update specific fields:**

```bash
pcake rules update my-alerts app-alerts HighMemory \
  --expr 'memory_usage > 85' \
  --for 10m
```

#### Delete Rule

Delete a Prometheus alert rule:

```bash
# With confirmation prompt
pcake rules delete my-alerts app-alerts HighMemory

# Skip confirmation
pcake rules delete my-alerts app-alerts HighMemory --yes
```

#### Apply Rules from File

Apply multiple rules from a YAML file (creates or updates as needed):

```bash
# Apply rules
pcake rules apply prometheus-rules.yaml

# Specify CRD name
pcake rules apply rules.yaml --crd-name custom-alerts

# Dry run (show what would be created)
pcake rules apply rules.yaml --dry-run
```

**File format:**

```yaml
groups:
  - name: system-alerts
    rules:
      - alert: HighCPU
        expr: cpu_usage > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage"

      - alert: LowDisk
        expr: disk_free < 10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Low disk space"

  - name: app-alerts
    rules:
      - alert: HighLatency
        expr: request_duration > 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High request latency"
```

## Output Formats

### Table (default)

Human-readable table format:

```bash
pcake alerts list
```

Output:
```
fingerprint       alertname    severity  status        instance
7c7e6f4c8a9b2e1d  HighCPU      critical  remediating   server-01
a1b2c3d4e5f6g7h8  LowDisk      warning   pending       server-02
```

### JSON

Machine-readable JSON format:

```bash
pcake --format json alerts list
```

Output:
```json
[
  {
    "fingerprint": "7c7e6f4c8a9b2e1d",
    "alertname": "HighCPU",
    "severity": "critical",
    "status": "remediating",
    "instance": "server-01"
  }
]
```

### YAML

YAML format:

```bash
pcake --format yaml rules get my-alerts app-alerts HighMemory
```

Output:
```yaml
alert: HighMemory
expr: memory_usage > 90
for: 5m
labels:
  severity: critical
annotations:
  summary: High memory usage detected
  description: Memory usage is above 90%
```

## Examples

### Monitor Critical Alerts

```bash
# Watch critical alerts in real-time
pcake alerts watch --severity critical --watch
```

### Create Alert Rule from Template

```bash
# Create rule.yaml
cat > rule.yaml <<EOF
alert: HighErrorRate
expr: error_rate > 5
for: 5m
labels:
  severity: critical
  team: platform
annotations:
  summary: "High error rate detected"
  description: "Error rate is {{ \$value }}% (threshold: 5%)"
  runbook_url: "https://wiki.example.com/runbooks/high-error-rate"
EOF

# Apply the rule
pcake rules create app-alerts monitoring HighErrorRate --file rule.yaml
```

### Bulk Update Rules

```bash
# Export all rules to YAML
pcake --format yaml rules list > all-rules.yaml

# Edit the file
vim all-rules.yaml

# Apply changes
pcake rules apply all-rules.yaml
```

### Check Alert Remediation Status

```bash
# List alerts being remediated
pcake alerts list --status remediating

# Get details of specific alert
pcake alerts get 7c7e6f4c8a9b2e1d
```

## Troubleshooting

### Connection Issues

If you can't connect to the PoundCake API:

```bash
# Check if API is reachable
curl http://poundcake.example.com:8080/health

# Verify URL is correct
pcake --url http://poundcake.example.com:8080 --verbose alerts list
```

### Authentication Errors

If you get authentication errors:

```bash
# Verify API key is set
echo $POUNDCAKE_API_KEY

# Use explicit API key
pcake --api-key your-key alerts list
```

### Rule Not Found

If you get "rule not found" errors when updating:

```bash
# List all rules to find correct CRD/group/rule names
pcake rules list

# Get specific rule
pcake rules get <crd-name> <group-name> <rule-name>
```

## Integration with GitOps

When Git integration is enabled in PoundCake, rule changes via the CLI will:

1. Update the rule in Kubernetes (immediate effect via CRD)
2. Commit the change to Git repository
3. Create a pull request for team review

The CLI will display the PR URL:

```bash
pcake rules update my-alerts app-alerts HighMemory --expr 'memory_usage > 85'
```

Output:
```
✓ Updated rule: HighMemory
ℹ Pull request created: https://github.com/yourorg/config/pull/123
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POUNDCAKE_URL` | PoundCake API URL | `http://localhost:8080` |
| `POUNDCAKE_API_KEY` | API key for authentication | (none) |

## Exit Codes

- `0` - Success
- `1` - Error (connection failure, API error, invalid input, etc.)

## Shell Completion

Generate shell completion scripts:

```bash
# Bash
_PCAKE_COMPLETE=bash_source pcake > ~/.pcake-complete.bash
echo 'source ~/.pcake-complete.bash' >> ~/.bashrc

# Zsh
_PCAKE_COMPLETE=zsh_source pcake > ~/.pcake-complete.zsh
echo 'source ~/.pcake-complete.zsh' >> ~/.zshrc

# Fish
_PCAKE_COMPLETE=fish_source pcake > ~/.config/fish/completions/pcake.fish
```
