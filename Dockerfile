# PoundCake Docker Image
#
# This Dockerfile builds the container image for PoundCake, which is deployed
# via the Helm chart. The image is published to GitHub Container Registry.
#
# Build: docker build -t ghcr.io/aedan/poundcake:VERSION .
# Push:  docker push ghcr.io/aedan/poundcake:VERSION
#
# For deployment instructions, see the Helm chart in ./helm/poundcake/

# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY src ./src

# Install the package
RUN pip install --no-cache-dir --prefix=/install .

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --from=builder /app/src ./src

# Create config directory for mappings (will be mounted in k8s)
RUN mkdir -p /app/config/mappings

# Create non-root user
RUN useradd -m -u 1000 poundcake && \
    chown -R poundcake:poundcake /app

USER poundcake

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Labels
LABEL org.opencontainers.image.title="PoundCake" \
      org.opencontainers.image.description="Auto-remediation framework for Prometheus Alertmanager and StackStorm" \
      org.opencontainers.image.authors="Jake Briggs" \
      org.opencontainers.image.source="https://github.com/aedan/poundCake"

# Run the application
ENTRYPOINT ["poundcake"]
