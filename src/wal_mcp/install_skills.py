"""Install WAL Claude Code skills into a project."""

import argparse
import shutil
import sys
from importlib.resources import as_file, files
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install WAL Claude Code skills into a project"
    )
    parser.add_argument(
        "dest",
        nargs="?",
        default=None,
        help="Directory to install skills into (default: .claude/skills)",
    )
    parser.add_argument(
        "--user",
        action="store_true",
        help="Install into the user-local skill directory (~/.claude/skills)",
    )
    args = parser.parse_args()

    if args.user and args.dest is not None:
        parser.error("dest and --user are mutually exclusive")

    if args.user:
        dest = Path.home() / ".claude" / "skills"
    else:
        dest = Path(args.dest if args.dest is not None else ".claude/skills")

    skills_pkg = files("wal_mcp") / "skills"
    with as_file(skills_pkg) as skills_src:
        if not skills_src.is_dir():
            print("Error: skills data not found in wal-mcp package.", file=sys.stderr)
            sys.exit(1)

        for skill_dir in sorted(skills_src.iterdir()):
            if not skill_dir.is_dir():
                continue

            target = dest / skill_dir.name
            if target.exists():
                shutil.rmtree(target)

            shutil.copytree(skill_dir, target)
            print(f"Installed skill: {skill_dir.name} -> {target}")


if __name__ == "__main__":
    main()
