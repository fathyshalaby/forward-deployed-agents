"""Entry point: python3 -m fda  (MCP stdio server)."""
from .mcp import stdio_loop
from .runtime import load_runtime


def main():
    return stdio_loop(load_runtime())


if __name__ == "__main__":
    raise SystemExit(main())
