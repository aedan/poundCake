"""Utility functions for CLI output formatting."""

import json
from typing import Any

import click
import yaml


def format_output(data: Any, format: str = "table") -> str:
    """
    Format data for output based on the specified format.

    Args:
        data: Data to format
        format: Output format (json, yaml, table)

    Returns:
        Formatted string
    """
    if format == "json":
        return json.dumps(data, indent=2)
    elif format == "yaml":
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
    elif format == "table":
        return format_table(data)
    else:
        return str(data)


def format_table(data: Any) -> str:
    """
    Format data as a simple table.

    Args:
        data: Data to format (dict or list of dicts)

    Returns:
        Formatted table string
    """
    if isinstance(data, dict):
        if not data:
            return "No data"

        max_key_len = max(len(str(k)) for k in data.keys())
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            lines.append(f"{str(key).ljust(max_key_len)}  {value}")
        return "\n".join(lines)

    elif isinstance(data, list):
        if not data:
            return "No items"

        if not isinstance(data[0], dict):
            return "\n".join(str(item) for item in data)

        keys = list(data[0].keys())
        col_widths = {k: len(str(k)) for k in keys}

        for item in data:
            for key in keys:
                value = str(item.get(key, ""))
                if len(value) > col_widths[key]:
                    col_widths[key] = min(len(value), 50)

        header = "  ".join(str(k).ljust(col_widths[k]) for k in keys)
        separator = "  ".join("-" * col_widths[k] for k in keys)

        rows = []
        for item in data:
            row = []
            for key in keys:
                value = str(item.get(key, ""))
                if len(value) > 50:
                    value = value[:47] + "..."
                row.append(value.ljust(col_widths[key]))
            rows.append("  ".join(row))

        return "\n".join([header, separator] + rows)

    else:
        return str(data)


def print_output(data: Any, format: str = "table") -> None:
    """
    Print formatted output to stdout.

    Args:
        data: Data to print
        format: Output format
    """
    output = format_output(data, format)
    click.echo(output)


def print_success(message: str) -> None:
    """Print a success message in green."""
    click.echo(click.style(f"✓ {message}", fg="green"))


def print_error(message: str) -> None:
    """Print an error message in red."""
    click.echo(click.style(f"✗ {message}", fg="red"), err=True)


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    click.echo(click.style(f"⚠ {message}", fg="yellow"))


def print_info(message: str) -> None:
    """Print an info message in blue."""
    click.echo(click.style(f"ℹ {message}", fg="blue"))
