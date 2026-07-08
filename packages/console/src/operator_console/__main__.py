from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from operator_console.app import run_console


def main() -> None:
    parser = argparse.ArgumentParser(prog="operator-console")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", choices=("work", "personal"),
                        default="personal")
    parser.add_argument("--no-llm", action="store_true",
                        help="use the stub LLM (bench mode)")
    args = parser.parse_args()
    asyncio.run(run_console(args.root, args.profile, args.no_llm))


if __name__ == "__main__":
    main()
