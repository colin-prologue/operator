from __future__ import annotations

import argparse
from pathlib import Path

from operator_switchboard_mcp.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(prog="operator-switchboard-mcp")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", choices=("work", "personal"),
                        required=True)
    args = parser.parse_args()
    build_server(args.root, args.profile).run(transport="stdio")


if __name__ == "__main__":
    main()
