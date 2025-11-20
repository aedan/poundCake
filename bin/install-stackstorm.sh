#!/bin/bash
# StackStorm Installation Script
# This script installs StackStorm using Helm and creates necessary secrets

# Detect OS
OS_TYPE=$(uname -s)

# Source common functions if available
if [ -f "$(dirname "$0")/common.sh" ]; then
    source "$(dirname "$0")/common.sh"
fi

# Configuration
NAMESPACE="${STACKSTORM_NAMESPACE:-stackstorm}"
RELEASE_NAME="${STACKSTORM_RELEASE_NAME:-stackstorm}"
HELM_REPO="https://helm.stackstorm.com/"
CHART_NAME="stackstorm/stackstorm-ha"

# Get version from helm-chart-versions.yaml if it exists
if [ -f "/etc/genestack/helm-chart-versions.yaml" ]; then
    VERSION=$(grep "^stackstorm:" /etc/genestack/helm-chart-versions.yaml | awk '{print $2}')
fi
VERSION="${VERSION:-}"

# StackStorm admin credentials
ST2_ADMIN_USER="${ST2_ADMIN_USER:-st2admin}"
ST2_ADMIN_PASSWORD="${ST2_ADMIN_PASSWORD:-$(openssl rand -base64 32)}"

# Create namespace with PodSecurity policies if it doesn't exist
if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    echo "Creating namespace $NAMESPACE with PodSecurity policies..."
    kubectl create namespace "$NAMESPACE"
    kubectl label namespace "$NAMESPACE" \
        pod-security.kubernetes.io/enforce=baseline \
        pod-security.kubernetes.io/audit=baseline \
        pod-security.kubernetes.io/warn=baseline
    echo "Namespace $NAMESPACE created with baseline PodSecurity policy"
fi

# Create secret for StackStorm admin credentials in stackstorm namespace
echo "Creating StackStorm admin credentials secret in $NAMESPACE namespace..."
kubectl create secret generic stackstorm-admin \
    --from-literal=username="$ST2_ADMIN_USER" \
    --from-literal=password="$ST2_ADMIN_PASSWORD" \
    --namespace="$NAMESPACE" \
    --dry-run=client -o yaml | kubectl apply -f -

# Also create the secret in poundcake namespace for cross-namespace access
echo "Creating StackStorm admin credentials secret in poundcake namespace..."
kubectl get namespace poundcake >/dev/null 2>&1 || kubectl create namespace poundcake
kubectl create secret generic stackstorm-admin \
    --from-literal=username="$ST2_ADMIN_USER" \
    --from-literal=password="$ST2_ADMIN_PASSWORD" \
    --namespace=poundcake \
    --dry-run=client -o yaml | kubectl apply -f -

echo "StackStorm admin credentials:"
echo "  Username: $ST2_ADMIN_USER"
echo "  Password: $ST2_ADMIN_PASSWORD"
echo ""
echo "Secret 'stackstorm-admin' created in namespaces: $NAMESPACE, poundcake"
echo ""

# Add Helm repository
echo "Adding StackStorm Helm repository..."
helm repo add stackstorm "$HELM_REPO" >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1

# Build Helm command
HELM_CMD="helm upgrade --install $RELEASE_NAME $CHART_NAME"

# Add version if specified
if [ -n "$VERSION" ]; then
    HELM_CMD="$HELM_CMD --version $VERSION"
fi

# Add namespace and other flags
HELM_CMD="$HELM_CMD \
  --namespace=$NAMESPACE \
  --create-namespace \
  --timeout 120m"

# Add external services configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELM_CMD="$HELM_CMD -f ${SCRIPT_DIR}/stackstorm-external-services-values.yaml"

# Add post-renderer if available (for genestack integration) AND overlay exists
if [ -f "/etc/genestack/kustomize/kustomize.sh" ] && [ -d "/etc/genestack/kustomize/stackstorm/overlay" ]; then
    HELM_CMD="$HELM_CMD \
  --post-renderer /etc/genestack/kustomize/kustomize.sh \
  --post-renderer-args stackstorm/overlay"
fi

# Add values files (these override the external services config if needed)
if [ -f "/etc/genestack/helm-configs/stackstorm/stackstorm-helm-overrides.yaml" ]; then
    HELM_CMD="$HELM_CMD -f /etc/genestack/helm-configs/stackstorm/stackstorm-helm-overrides.yaml"
fi

if [ -f "/etc/genestack/helm-configs/global_overrides/endpoints.yaml" ]; then
    HELM_CMD="$HELM_CMD -f /etc/genestack/helm-configs/global_overrides/endpoints.yaml"
fi

# Execute Helm command
echo "Executing Helm command:"
echo "$HELM_CMD"
echo ""

eval $HELM_CMD

# Wait for StackStorm to be ready
echo ""
echo "Waiting for StackStorm to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=stackstorm -n "$NAMESPACE" --timeout=600s

echo ""
echo "StackStorm installation complete!"
echo ""
echo "To access StackStorm:"
echo "  kubectl port-forward -n $NAMESPACE svc/stackstorm-st2web 8080:80"
echo "  Open: http://localhost:8080"
echo ""
echo "To get the admin password:"
echo "  kubectl get secret stackstorm-admin -n $NAMESPACE -o jsonpath='{.data.password}' | base64 -d"
echo ""
