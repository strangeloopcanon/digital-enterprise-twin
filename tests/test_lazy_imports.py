from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager

import typer.testing


@contextmanager
def _temporarily_purge_modules(*prefixes: str):
    saved_modules: dict[str, object] = {}
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
            saved_modules[name] = sys.modules.pop(name)
    try:
        yield
    finally:
        for name in list(sys.modules):
            if any(
                name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes
            ):
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        for name, module in saved_modules.items():
            parent_name, _, child_name = name.rpartition(".")
            if not parent_name:
                continue
            parent_module = sys.modules.get(parent_name)
            if parent_module is None:
                continue
            setattr(parent_module, child_name, module)


def test_root_cli_import_stays_lazy_for_heavy_modules() -> None:
    with _temporarily_purge_modules(
        "vei.cli.vei",
        "vei.cli.vei_whatif",
        "vei.whatif",
        "vei.twin.api",
        "fastapi",
    ):
        vei_cli = importlib.import_module("vei.cli.vei")

        assert "vei.whatif" not in sys.modules
        assert "vei.twin.api" not in sys.modules
        assert "fastapi" not in sys.modules

        runner = typer.testing.CliRunner()
        root_help = runner.invoke(vei_cli.app, ["--help"])

        assert root_help.exit_code == 0, root_help.output

        whatif_help = runner.invoke(vei_cli.app, ["whatif", "--help"])

        assert whatif_help.exit_code == 0, whatif_help.output
        assert "vei.whatif" in sys.modules


def test_sdk_import_stays_lazy_until_symbol_access() -> None:
    with _temporarily_purge_modules(
        "vei.sdk",
        "vei.sdk.api",
        "vei.whatif",
        "vei.twin.api",
        "fastapi",
    ):
        sdk = importlib.import_module("vei.sdk")

        assert "vei.sdk.api" not in sys.modules
        assert "vei.whatif" not in sys.modules
        assert "vei.twin.api" not in sys.modules
        assert "fastapi" not in sys.modules

        create_session = sdk.create_session

        assert callable(create_session)
        assert "vei.sdk.api" in sys.modules
        assert "fastapi" not in sys.modules
