from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Mapping

import click
import typer
from typer.main import get_group


@dataclass(frozen=True)
class LazyCommandSpec:
    module_path: str
    help: str
    app_attr: str = "app"


class LazyTyperGroup(typer.core.TyperGroup):
    lazy_commands: Mapping[str, LazyCommandSpec] = {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        del ctx
        return sorted(self.lazy_commands)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        del ctx
        spec = self.lazy_commands.get(cmd_name)
        if spec is None:
            return None
        module = importlib.import_module(spec.module_path)
        typer_app = getattr(module, spec.app_attr)
        command = get_group(typer_app)
        command.name = cmd_name
        if spec.help and not getattr(command, "help", None):
            command.help = spec.help
        if spec.help and not getattr(command, "short_help", None):
            command.short_help = spec.help
        return command

    def format_commands(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        rows = [
            (name, spec.help)
            for name, spec in sorted(self.lazy_commands.items())
            if spec.help
        ]
        if not rows:
            return
        with formatter.section("Commands"):
            formatter.write_dl(rows)


__all__ = ["LazyCommandSpec", "LazyTyperGroup"]
