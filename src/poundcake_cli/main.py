"""Main CLI entry point for PoundCake CLI."""

import sys
from typing import Optional

import click

from poundcake_cli.client import PoundCakeClient
from poundcake_cli.commands import alerts, rules


@click.group()
@click.option(
    "--url",
    "-u",
    envvar="POUNDCAKE_URL",
    default="http://localhost:8080",
    help="PoundCake API URL",
)
@click.option(
    "--api-key",
    "-k",
    envvar="POUNDCAKE_API_KEY",
    help="API key for authentication (if required)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "yaml", "table"]),
    default="table",
    help="Output format",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
@click.pass_context
def cli(
    ctx: click.Context,
    url: str,
    api_key: Optional[str],
    format: str,
    verbose: bool,
) -> None:
    """PoundCake CLI - Manage alerts, rules, and remediations."""
    ctx.ensure_object(dict)
    ctx.obj["client"] = PoundCakeClient(url, api_key)
    ctx.obj["format"] = format
    ctx.obj["verbose"] = verbose


# Register subcommands
cli.add_command(alerts.alerts)
cli.add_command(rules.rules)


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli(obj={})
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
