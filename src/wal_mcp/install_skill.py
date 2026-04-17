"""Install the WAL skill directory for Claude Code."""

import argparse
import shutil
import sys
from importlib.resources import as_file, files
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install the WAL Claude Code skill into a project"
    )
    parser.add_argument(
        "dest",
        nargs="?",
        default=".claude/skills",
        help="Directory to install the skill into (default: .claude/skills)",
    )
    args = parser.parse_args()

    dest = Path(args.dest) / "wal"

    skill_pkg = files("wal_mcp") / "skill"
    with as_file(skill_pkg) as skill_src:
        if not skill_src.is_dir():
            print("Error: skill data not found in wal-mcp package.", file=sys.stderr)
            sys.exit(1)

        if dest.exists():
            shutil.rmtree(dest)

        shutil.copytree(skill_src, dest)

    print(f"Installed WAL skill to {dest}")


if __name__ == "__main__":
    main()
