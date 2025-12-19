"""Authentication and session management for PoundCake."""

import secrets
from datetime import datetime, timedelta
from typing import Any

import structlog
from fastapi import Cookie, HTTPException, Request, status

from poundcake.config import get_settings

logger = structlog.get_logger(__name__)

# In-memory session store (for single instance deployments)
# For multi-instance, this should be moved to Redis
_sessions: dict[str, dict[str, Any]] = {}


def get_admin_credentials() -> tuple[str, str] | None:
    """
    Get admin credentials from Kubernetes secret.

    Returns:
        Tuple of (username, password) or None if not available
    """
    settings = get_settings()

    if not settings.auth_enabled:
        return None

    # Try to load from Kubernetes secret
    try:
        import base64
        from kubernetes import client, config

        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except Exception:
            config.load_kube_config()
            logger.info("Loaded local Kubernetes config")

        v1 = client.CoreV1Api()
        secret = v1.read_namespaced_secret(
            name=settings.auth_secret_name,
            namespace=settings.auth_secret_namespace,
        )

        username = base64.b64decode(secret.data["username"]).decode("utf-8")
        password = base64.b64decode(secret.data["password"]).decode("utf-8")

        logger.info(
            "Loaded admin credentials from Kubernetes secret",
            secret_name=settings.auth_secret_name,
            namespace=settings.auth_secret_namespace,
        )
        return (username, password)
    except Exception as e:
        logger.warning(
            "Failed to load admin credentials from Kubernetes secret",
            error=str(e),
            secret_name=settings.auth_secret_name,
            namespace=settings.auth_secret_namespace,
        )

        # Fallback to environment variables for local development
        if settings.auth_dev_username and settings.auth_dev_password:
            logger.info("Using development credentials from environment variables")
            return (settings.auth_dev_username, settings.auth_dev_password)

        logger.error(
            "No admin credentials available - set POUNDCAKE_AUTH_DEV_USERNAME "
            "and POUNDCAKE_AUTH_DEV_PASSWORD for local development"
        )
        return None


def create_session(username: str) -> str:
    """
    Create a new session for a user.

    Args:
        username: The username to create a session for

    Returns:
        Session token
    """
    settings = get_settings()
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(seconds=settings.auth_session_timeout)

    _sessions[session_token] = {
        "username": username,
        "created_at": datetime.utcnow(),
        "expires_at": expires_at,
    }

    logger.info("Created new session", username=username, expires_at=expires_at.isoformat())
    return session_token


def validate_session(session_token: str | None) -> str | None:
    """
    Validate a session token.

    Args:
        session_token: The session token to validate

    Returns:
        Username if valid, None otherwise
    """
    if not session_token:
        return None

    session = _sessions.get(session_token)
    if not session:
        return None

    if datetime.utcnow() > session["expires_at"]:
        # Session expired
        del _sessions[session_token]
        return None

    username: str = session["username"]
    return username


def destroy_session(session_token: str | None) -> None:
    """
    Destroy a session.

    Args:
        session_token: The session token to destroy
    """
    if session_token and session_token in _sessions:
        del _sessions[session_token]
        logger.info("Destroyed session")


def verify_credentials(username: str, password: str) -> bool:
    """
    Verify user credentials.

    Args:
        username: Username to verify
        password: Password to verify

    Returns:
        True if credentials are valid
    """
    credentials = get_admin_credentials()
    if not credentials:
        return False

    admin_username, admin_password = credentials
    return username == admin_username and password == admin_password


def get_current_user(session: str | None = Cookie(default=None)) -> str:
    """
    Get the current authenticated user.

    Args:
        session: Session cookie value

    Returns:
        Username of authenticated user

    Raises:
        HTTPException: If not authenticated
    """
    username = validate_session(session)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def require_auth_if_enabled(
    request: Request, session: str | None = Cookie(default=None)
) -> str | None:
    """
    Require authentication only if auth is enabled.

    Args:
        request: FastAPI request object
        session: Session cookie value

    Returns:
        Username if authenticated, None if auth disabled

    Raises:
        HTTPException: If auth enabled but not authenticated
    """
    settings = get_settings()

    if not settings.auth_enabled:
        return None

    # Allow access to login page, static resources, and public endpoints
    if request.url.path in ["/login", "/api/login", "/health", "/metrics", "/webhook"]:
        return None

    username = validate_session(session)
    if not username:
        # Redirect to login page for browser requests
        if "text/html" in request.headers.get("accept", ""):
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/login"},
            )
        else:
            # Return 401 for API requests
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return username
