#!/usr/bin/env python3
"""Main CLI entry point for asya developer tools."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import click


def get_version() -> str:
    try:
        pkg_version = version("asya-lab")
        return f"v{pkg_version}"
    except PackageNotFoundError:
        return "v0.0.0-dev"


class LazyGroup(click.Group):
    """Click group that defers subcommand imports until invoked."""

    def __init__(self, *args, lazy_subcommands: dict[str, str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._lazy_subcommands: dict[str, str] = lazy_subcommands or {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        base = super().list_commands(ctx)
        lazy = sorted(self._lazy_subcommands.keys())
        return base + lazy

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.BaseCommand | None:
        if cmd_name in self._lazy_subcommands:
            return self._load_lazy(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _load_lazy(self, cmd_name: str) -> click.BaseCommand:
        import importlib

        module_path, attr_name = self._lazy_subcommands[cmd_name].rsplit(":", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)


@click.group(
    cls=LazyGroup,
    lazy_subcommands={
        "build": "asya_lab.build_cli:build",
        "compile": "asya_lab.compile_cli:compile_cmd",
        "config": "asya_lab.config_cli:config",
        "expose": "asya_lab.expose_cli:expose",
        "flow": "asya_lab.flow_cli:flow",
        "init": "asya_lab.init_cli:init",
        "k": "asya_lab.k_cli:k",
        "kube": "asya_lab.k_cli:k",
        "kubernetes": "asya_lab.k_cli:k",
        "show": "asya_lab.show_cli:show",
        "status": "asya_lab.status_cli:status",
        "unexpose": "asya_lab.expose_cli:unexpose",
    },
)
@click.version_option(version=get_version(), prog_name="asya")
def main():
    """Developer tools for debugging and operating Asya framework."""


if __name__ == "__main__":
    main()
