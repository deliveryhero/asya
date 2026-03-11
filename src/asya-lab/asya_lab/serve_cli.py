"""CLI command for asya serve."""

from __future__ import annotations

import click


@click.command("serve")
@click.option("--port", type=int, default=0, help="Port to listen on (0 = auto)")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--working-dir", type=click.Path(exists=True), default=None)
def serve_cmd(port: int, host: str, working_dir: str | None) -> None:
    """Start local development server for @asya/ui."""
    try:
        import uvicorn
    except ImportError:
        click.echo("[-] Missing dependency: pip install asya-lab[ui]", err=True)
        raise SystemExit(1) from None

    from pathlib import Path

    from asya_lab.config.project import AsyaProject
    from asya_lab.serve.app import create_app

    try:
        project = AsyaProject.from_dir(Path(working_dir) if working_dir else Path.cwd())
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"[-] {e}", err=True)
        raise SystemExit(1) from None

    app = create_app(project)

    if port == 0:
        import socket

        with socket.socket() as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

    click.echo(f"Listening on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
