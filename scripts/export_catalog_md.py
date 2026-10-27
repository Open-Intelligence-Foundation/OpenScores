"""Export a readable Markdown digest of the catalog: top projects per category.

    python scripts/export_catalog_md.py [--per-category 25] [--out CATALOG.md]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=25)
    ap.add_argument("--out", type=Path, default=ROOT / "CATALOG.md")
    ap.add_argument("--src", type=Path, default=ROOT / "site" / "data" / "catalog.json")
    args = ap.parse_args()
    data = json.loads(args.src.read_text())
    projects = [p for p in data["projects"] if not p["is_list"] and p["signal"] >= 2]
    lists = [p for p in data["projects"] if p["is_list"]]
    adjacent = [p for p in data["projects"] if not p["is_list"] and p["signal"] < 2]
    by = defaultdict(list)
    for p in projects:
        by[p["category"]].append(p)

    out = ["# Open Source AI on GitHub: the OpenScores catalog", "",
           "Generated %s from %s GitHub search requests across %d topics plus a name/description keyword pass." % (
               data["generated_at"][:10], "{:,}".format(data["requests"]), len(data["topics_searched"])),
           "", "| | Count |", "|---|---|",
           "| AI projects (>= %d stars, not archived, not forks) | %s |" % (data["min_stars"], "{:,}".format(len(projects))),
           "| AI-adjacent (generic tag only, excluded below) | %s |" % "{:,}".format(len(adjacent)),
           "| Curated lists, courses, paper collections | %s |" % "{:,}".format(len(lists)),
           "| Categories | %d |" % len(by), "",
           "The full data, including every project and its topics, is in `site/data/catalog.json`; "
           "the site's Catalog page lets you browse and search all of it.", "",
           "## Categories", "", "| Category | Projects | Combined stars |", "|---|---|---|"]
    for cat, items in sorted(by.items(), key=lambda kv: -len(kv[1])):
        out.append("| [%s](#%s) | %s | %s |" % (cat, anchor(cat), "{:,}".format(len(items)),
                                                "{:,}".format(sum(p["stars"] for p in items))))
    for cat, items in sorted(by.items(), key=lambda kv: -len(kv[1])):
        out += ["", "## %s" % cat, "", "Top %d of %s by stars." % (min(args.per_category, len(items)), "{:,}".format(len(items))), "",
                "| # | Project | Stars | Language | License | Description |", "|---|---|---|---|---|---|"]
        for i, p in enumerate(items[:args.per_category], 1):
            desc = (p["description"] or "").replace("|", "\\|").replace("\n", " ")[:120]
            out.append("| %d | [%s](https://github.com/%s) | %s | %s | %s | %s |" % (
                i, p["full_name"], p["full_name"], "{:,}".format(p["stars"]), p["language"] or "", p["license"] or "", desc))
    out += ["", "## Curated lists, courses and paper collections", "", "Top 25 by stars (not scored on the leaderboard).", "",
            "| # | Repository | Stars | Description |", "|---|---|---|---|"]
    for i, p in enumerate(lists[:25], 1):
        desc = (p["description"] or "").replace("|", "\\|")[:120]
        out.append("| %d | [%s](https://github.com/%s) | %s | %s |" % (i, p["full_name"], p["full_name"], "{:,}".format(p["stars"]), desc))
    args.out.write_text("\n".join(out) + "\n")
    print("wrote %s (%d categories, %d projects)" % (args.out, len(by), len(projects)))


def anchor(title: str) -> str:
    return "".join(ch for ch in title.lower().replace(" ", "-") if ch.isalnum() or ch == "-")


if __name__ == "__main__":
    main()
