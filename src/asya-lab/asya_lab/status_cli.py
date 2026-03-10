"""CLI command for showing status of compiled flows."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from asya_lab.config.discovery import find_asya_dir


def _scan_flows(manifests_dir: Path) -> list[dict[str, str]]:
    """Scan manifests directory and collect flow status information."""
    flows = []

    for flow_dir in sorted(manifests_dir.iterdir()):
        if not flow_dir.is_dir():
            continue

        base_dir = flow_dir / "base"
        if not base_dir.is_dir():
            continue

        flow_info: dict[str, str] = {
            "name": flow_dir.name,
            "status": "compiled",
            "actors": "0",
            "exposed": "no",
        }

        kustomization_path = base_dir / "kustomization.yaml"
        if kustomization_path.exists():
            kustomization = yaml.safe_load(kustomization_path.read_text())
            if isinstance(kustomization, dict):
                resources = kustomization.get("resources", [])
                actor_resources = [r for r in resources if not r.startswith("configmap-")]
                flow_info["actors"] = str(len(actor_resources))
                if "configmap-flows.yaml" in resources:
                    flow_info["exposed"] = "yes"

        flows.append(flow_info)

    return flows


def _format_table(flows: list[dict[str, str]]) -> str:
    """Format flow status as a fixed-width table."""
    headers = {"name": "FLOW", "status": "STATUS", "actors": "ACTORS", "exposed": "EXPOSED"}

    col_widths = {key: max(len(headers[key]), *(len(f[key]) for f in flows) if flows else [0]) for key in headers}

    header_line = "  ".join(headers[key].ljust(col_widths[key]) for key in headers)
    lines = [header_line]

    for flow in flows:
        line = "  ".join(flow[key].ljust(col_widths[key]) for key in headers)
        lines.append(line)

    return "\n".join(lines)


@click.command()
def status() -> None:
    """Show status of compiled flows."""
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    manifests_dir = asya_dir / "manifests"
    if not manifests_dir.is_dir():
        click.echo(_format_table([]))
        return

    flows = _scan_flows(manifests_dir)
    click.echo(_format_table(flows))
