"""Allow `python -m vexilla` to delegate to the CLI."""

from vexilla.cli.app import app

if __name__ == "__main__":
    app()
