"""Install the FDA meta-skill directly from GitHub (standard library only).

    python3 scripts/install_skill.py
    python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)"

Use ``--source zip`` to install from the uploadable Claude skill archive, and
``--dir`` to choose a different skills directory (Codex/Cursor can point this
at their own skills folder).
"""
import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

RAW_BASE = ("https://raw.githubusercontent.com/fathyshalaby/"
            "forward-deployed-agents/main")
SKILL_FILE = "skills/fda-agent-builder/SKILL.md"
SKILL_ZIP = "integrations/fda-skill.zip"
SKILL_NAME = "fda-agent-builder"


def download(url: str, timeout: float = 15.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def validate(text: str) -> None:
    if not text.startswith("---\n") or "name: %s" % SKILL_NAME not in text:
        raise ValueError("downloaded file is not the FDA meta-skill")


def install(raw_base: str, destination: Path, source: str = "md") -> Path:
    if source == "zip":
        archive = download(raw_base.rstrip("/") + "/" + SKILL_ZIP)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = bundle.namelist()
            if names != ["%s/SKILL.md" % SKILL_NAME]:
                raise ValueError("unexpected contents in FDA skill zip")
            text = bundle.read(names[0]).decode("utf-8")
    else:
        text = download(raw_base.rstrip("/") + "/" + SKILL_FILE).decode("utf-8")
    validate(text)
    target = destination / SKILL_NAME / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=str(Path.home() / ".claude" / "skills"),
                        help="skills directory (default: ~/.claude/skills)")
    parser.add_argument("--source", choices=("md", "zip"), default="md")
    parser.add_argument("--raw", default=RAW_BASE,
                        help="raw GitHub base URL (for forks or pins)")
    args = parser.parse_args(argv)
    try:
        target = install(args.raw, Path(args.dir).expanduser(), args.source)
    except Exception as exc:  # keep the CLI output honest and short
        print("install failed: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)
        return 1
    print("installed %s" % target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
