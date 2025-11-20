#!/bin/bash
# shellcheck disable=SC2124,SC2145,SC2294
GLOBAL_OVERRIDES_DIR="/etc/genestack/helm-configs/global_overrides"
SERVICE_CONFIG_DIR="/etc/genestack/helm-configs/poundcake"
BASE_OVERRIDES="/opt/genestack/base-helm-configs/poundcake/poundcake-helm-overrides.yaml"

# Read poundcake version from helm-chart-versions.yaml
VERSION_FILE="/etc/genestack/helm-chart-versions.yaml"
if [ ! -f "$VERSION_FILE" ]; then
    echo "Error: helm-chart-versions.yaml not found at $VERSION_FILE"
    exit 1
fi

# Extract poundcake version using grep and sed
POUNDCAKE_VERSION=$(grep 'poundcake:' "$VERSION_FILE" | sed 's/.*poundcake: *//')

if [ -z "$POUNDCAKE_VERSION" ]; then
    echo "Error: Could not extract poundcake version from $VERSION_FILE"
    exit 1
fi

HELM_CMD="helm upgrade --install poundcake oci://ghcr.io/aedan/poundcake \
  --version ${POUNDCAKE_VERSION} \
  --namespace=poundcake \
  --create-namespace \
  --timeout 120m \
  --post-renderer /etc/genestack/kustomize/kustomize.sh \
  --post-renderer-args poundcake/overlay"

HELM_CMD+=" -f ${BASE_OVERRIDES}"

for dir in "$GLOBAL_OVERRIDES_DIR" "$SERVICE_CONFIG_DIR"; do
    if compgen -G "${dir}/*.yaml" > /dev/null; then
        for yaml_file in "${dir}"/*.yaml; do
            HELM_CMD+=" -f ${yaml_file}"
        done
    fi
done

HELM_CMD+=" $@"

echo "Executing Helm command:"
echo "${HELM_CMD}"
eval "${HELM_CMD}"
