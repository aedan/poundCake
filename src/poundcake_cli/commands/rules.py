"""Prometheus rule management commands."""

import sys
from pathlib import Path
from typing import Optional

import click
import yaml

from poundcake_cli.client import PoundCakeClient
from poundcake_cli.utils import print_error, print_info, print_output, print_success


@click.group()
def rules() -> None:
    """Manage Prometheus alert rules."""
    pass


@rules.command()
@click.pass_context
def list(ctx: click.Context) -> None:
    """List all Prometheus rules."""
    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        rules = client.list_rules()
        print_output(rules, format)
    except Exception as e:
        print_error(f"Failed to list rules: {e}")
        raise click.Abort()


@rules.command()
@click.argument("crd_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.pass_context
def get(
    ctx: click.Context,
    crd_name: str,
    group_name: str,
    rule_name: str,
) -> None:
    """Get a specific Prometheus rule."""
    client: PoundCakeClient = ctx.obj["client"]
    format: str = ctx.obj["format"]

    try:
        rule = client.get_rule(crd_name, group_name, rule_name)
        print_output(rule, format)
    except Exception as e:
        print_error(f"Failed to get rule: {e}")
        raise click.Abort()


@rules.command()
@click.argument("crd_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True, path_type=Path),
    help="YAML file containing rule definition",
)
@click.option(
    "--expr",
    help="PromQL expression for the alert",
)
@click.option(
    "--for",
    "duration",
    help="Duration before alert fires (e.g., 5m, 1h)",
)
@click.option(
    "--severity",
    help="Alert severity label",
)
@click.option(
    "--summary",
    help="Alert summary annotation",
)
@click.option(
    "--description",
    help="Alert description annotation",
)
@click.pass_context
def create(
    ctx: click.Context,
    crd_name: str,
    group_name: str,
    rule_name: str,
    file: Optional[Path],
    expr: Optional[str],
    duration: Optional[str],
    severity: Optional[str],
    summary: Optional[str],
    description: Optional[str],
) -> None:
    """Create a new Prometheus rule."""
    client: PoundCakeClient = ctx.obj["client"]

    try:
        if file:
            with open(file) as f:
                rule_data = yaml.safe_load(f)
        elif expr:
            rule_data = {
                "alert": rule_name,
                "expr": expr,
            }
            if duration:
                rule_data["for"] = duration
            if severity or summary or description:
                rule_data["labels"] = {}
                rule_data["annotations"] = {}
                if severity:
                    rule_data["labels"]["severity"] = severity
                if summary:
                    rule_data["annotations"]["summary"] = summary
                if description:
                    rule_data["annotations"]["description"] = description
        else:
            print_error("Either --file or --expr must be provided")
            raise click.Abort()

        result = client.create_rule(crd_name, group_name, rule_name, rule_data)
        print_success(f"Created rule: {rule_name}")

        if result.get("git", {}).get("pull_request"):
            pr = result["git"]["pull_request"]
            print_info(f"Pull request created: {pr.get('url')}")

    except Exception as e:
        print_error(f"Failed to create rule: {e}")
        raise click.Abort()


@rules.command()
@click.argument("crd_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option(
    "--file",
    "-f",
    type=click.Path(exists=True, path_type=Path),
    help="YAML file containing updated rule definition",
)
@click.option(
    "--expr",
    help="PromQL expression for the alert",
)
@click.option(
    "--for",
    "duration",
    help="Duration before alert fires (e.g., 5m, 1h)",
)
@click.option(
    "--severity",
    help="Alert severity label",
)
@click.option(
    "--summary",
    help="Alert summary annotation",
)
@click.option(
    "--description",
    help="Alert description annotation",
)
@click.pass_context
def update(
    ctx: click.Context,
    crd_name: str,
    group_name: str,
    rule_name: str,
    file: Optional[Path],
    expr: Optional[str],
    duration: Optional[str],
    severity: Optional[str],
    summary: Optional[str],
    description: Optional[str],
) -> None:
    """Update an existing Prometheus rule."""
    client: PoundCakeClient = ctx.obj["client"]

    try:
        if file:
            with open(file) as f:
                rule_data = yaml.safe_load(f)
        elif expr:
            current = client.get_rule(crd_name, group_name, rule_name)
            rule_data = current.copy()
            rule_data["expr"] = expr

            if duration:
                rule_data["for"] = duration
            if "labels" not in rule_data:
                rule_data["labels"] = {}
            if "annotations" not in rule_data:
                rule_data["annotations"] = {}
            if severity:
                rule_data["labels"]["severity"] = severity
            if summary:
                rule_data["annotations"]["summary"] = summary
            if description:
                rule_data["annotations"]["description"] = description
        else:
            print_error("Either --file or --expr must be provided")
            raise click.Abort()

        result = client.update_rule(crd_name, group_name, rule_name, rule_data)
        print_success(f"Updated rule: {rule_name}")

        if result.get("git", {}).get("pull_request"):
            pr = result["git"]["pull_request"]
            print_info(f"Pull request created: {pr.get('url')}")

    except Exception as e:
        print_error(f"Failed to update rule: {e}")
        raise click.Abort()


@rules.command()
@click.argument("crd_name")
@click.argument("group_name")
@click.argument("rule_name")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.pass_context
def delete(
    ctx: click.Context,
    crd_name: str,
    group_name: str,
    rule_name: str,
    yes: bool,
) -> None:
    """Delete a Prometheus rule."""
    client: PoundCakeClient = ctx.obj["client"]

    if not yes:
        click.confirm(
            f"Are you sure you want to delete rule '{rule_name}'?",
            abort=True,
        )

    try:
        result = client.delete_rule(crd_name, group_name, rule_name)
        print_success(f"Deleted rule: {rule_name}")

        if result.get("git", {}).get("pull_request"):
            pr = result["git"]["pull_request"]
            print_info(f"Pull request created: {pr.get('url')}")

    except Exception as e:
        print_error(f"Failed to delete rule: {e}")
        raise click.Abort()


@rules.command()
@click.argument(
    "file",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--crd-name",
    help="CRD name (defaults to filename without extension)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be created without actually creating",
)
@click.pass_context
def apply(
    ctx: click.Context,
    file: Path,
    crd_name: Optional[str],
    dry_run: bool,
) -> None:
    """Apply rules from a YAML file."""
    client: PoundCakeClient = ctx.obj["client"]

    try:
        with open(file) as f:
            data = yaml.safe_load(f)

        if not crd_name:
            crd_name = file.stem

        if "groups" not in data:
            print_error("Invalid rule file: no 'groups' found")
            raise click.Abort()

        for group in data["groups"]:
            group_name = group["name"]
            for rule in group.get("rules", []):
                rule_name = rule.get("alert")
                if not rule_name:
                    continue

                if dry_run:
                    print_info(f"Would create/update: {crd_name}/{group_name}/{rule_name}")
                    continue

                try:
                    client.get_rule(crd_name, group_name, rule_name)
                    result = client.update_rule(crd_name, group_name, rule_name, rule)
                    print_success(f"Updated rule: {rule_name}")
                except Exception:
                    result = client.create_rule(crd_name, group_name, rule_name, rule)
                    print_success(f"Created rule: {rule_name}")

                if result.get("git", {}).get("pull_request"):
                    pr = result["git"]["pull_request"]
                    print_info(f"Pull request: {pr.get('url')}")

    except Exception as e:
        print_error(f"Failed to apply rules: {e}")
        raise click.Abort()
