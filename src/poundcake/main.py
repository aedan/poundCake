"""Main entry point for PoundCake."""

import uvicorn

from poundcake.config import get_settings


def main() -> None:
    """Run the PoundCake application."""
    settings = get_settings()

    uvicorn.run(
        "poundcake.api:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
