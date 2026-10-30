"""CLI: python -m whitescore [--repos owner/name ...] [--max-repos N] [--dry-run]"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import pipeline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="whitescore", description="Compute White Scores for open source AI projects on GitHub.")
    parser.add_argument("--repos", nargs="*", help="score only these owner/name repos (skips discovery)")
    parser.add_argument("--max-repos", type=int, default=None, help="cap on tracked repositories")
    parser.add_argument("--max-full", type=int, default=None,
                        help="cap on full (expensive) collections this run; the rest are refreshed from the "
                             "metrics cache (-1 = collect everything that is due)")
    parser.add_argument("--dry-run", action="store_true", help="collect and score but do not write site/data")
    parser.add_argument("--print", dest="print_json", action="store_true", help="print the leaderboard JSON to stdout")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    board = pipeline.run(repos=args.repos, max_repos=args.max_repos, dry_run=args.dry_run,
                         max_full=args.max_full)
    if args.print_json:
        json.dump(board, sys.stdout, indent=2)
    return 0 if board["project_count"] else 1


if __name__ == "__main__":
    sys.exit(main())
