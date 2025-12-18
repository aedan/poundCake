"""Alert management commands."""

from typing import Optional

import click

from poundcake_cli.client import PoundCakeClient
from poundcake_cli.utils import print_error, print_output, print_success


@click.group()
def alerts() -> None:
    """Manage alerts and remediations."""
    pass


@alerts.command()
@click.option(
    "--status",
    "-s",
    type=click.Choice(["received", "pending", "remediating", "remediated", "resolved"]),
    help="Filter by status",
)
@click.option(
    "--severity",
    type=click.Choice(["critical", "warning", "info"]),
    help="Filter by severity",
)
@click.pass_context
def list(
    ctx: click.Context,
    status: Optional[str],
    severity: Optional[str],
) -> None:
    """List all alerts."""
    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        alerts = client.list_alerts(status=status, severity=severity)
        print_output(alerts, format)
    except Exception as e:
        print_error(f"Failed to list alerts: {e}")
        raise click.Abort()


@alerts.command()
@click.argument("fingerprint")
@click.pass_context
def get(ctx: click.Context, fingerprint: str) -> None:
    """Get details of a specific alert by fingerprint."""
    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        alert = client.get_alert(fingerprint)
        print_output(alert, format)
    except Exception as e:
        print_error(f"Failed to get alert: {e}")
        raise click.Abort()


@alerts.command()
@click.option(
    "--status",
    "-s",
    type=click.Choice(["received", "pending", "remediating", "remediated", "resolved"]),
    help="Filter by status",
)
@click.option(
    "--severity",
    type=click.Choice(["critical", "warning", "info"]),
    help="Filter by severity",
)
@click.option(
    "--watch",
    "-w",
    is_flag=True,
    help="Watch for new alerts (refreshes every 5 seconds)",
)
@click.pass_context
def watch(
    ctx: click.Context,
    status: Optional[str],
    severity: Optional[str],
    watch: bool,
) -> None:
    """Watch alerts in real-time."""
    import time

    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        while True:
            click.clear()
            alerts = client.list_alerts(status=status, severity=severity)
            click.echo(f"Alerts (refreshed at {time.strftime('%H:%M:%S')})")
            click.echo("=" * 80)
            print_output(alerts, format)
            if not watch:
                break
            time.sleep(5)
    except KeyboardInterrupt:
        print_success("Stopped watching alerts")
    except Exception as e:
        print_error(f"Failed to watch alerts: {e}")
        raise click.Abort()
