"""Entry point: python3 -m fda  (MCP stdio server by default)."""
from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
