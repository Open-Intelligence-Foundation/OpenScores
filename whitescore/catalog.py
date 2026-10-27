"""Build the full catalog of open source AI repositories on GitHub.

Uses the REST search API, which works without a token (10 requests/minute)
and faster with one (30 requests/minute). Topics with more than 1,000
matching repositories are split into star bands to get past GitHub's
1,000-results-per-query cap.

    python -m whitescore.catalog            # writes site/data/catalog.json
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from . import __version__, config
from .discover import ai_signal, categorize, is_curated_list

log = logging.getLogger("whitescore.catalog")

SEARCH_URL = "https://api.github.com/search/repositories"
ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "site" / "data" / "catalog.json"
STAR_BANDS = [(0, 299), (300, 499), (500, 999), (1000, 1999), (2000, 3999), (4000, 7999), (8000, 15999), (16000, None)]


class Searcher:
    def __init__(self, token: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/vnd.github+json", "User-Agent": "whitescore-catalog",
                                     "X-GitHub-Api-Version": "2022-11-28"})
        token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.authenticated = bool(token)
        if token:
            self.session.headers["Authorization"] = "Bearer " + token
        self.requests_made = 0

    def search(self, q: str, page: int) -> dict:
        for attempt in range(8):
            resp = self.session.get(SEARCH_URL, params={"q": q, "sort": "stars", "order": "desc",
                                                        "per_page": 100, "page": page}, timeout=60)
            self.requests_made += 1
            remaining = resp.headers.get("X-RateLimit-Remaining")
            reset = float(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            if resp.status_code in (403, 429) or remaining == "0":
                wait = max(2.0, reset - time.time() + 1)
                log.info("search rate limit reached; sleeping %.0fs", wait)
                time.sleep(min(wait, 120))
                continue
            if resp.status_code == 422:            # beyond the 1,000-result window
                return {"total_count": 0, "items": [], "incomplete_results": False}
            if resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            if remaining is not None and int(remaining) == 0:
                time.sleep(max(1.0, reset - time.time() + 1))
            return data
        raise RuntimeError("search failed repeatedly for %r" % q)


def _stars(lo: int, hi: Optional[int]) -> str:
    return "stars:>=%d" % lo if hi is None else "stars:%d..%d" % (lo, hi)


def _query(topic: str, lo: int, hi: Optional[int]) -> str:
    return "topic:%s %s archived:false fork:false" % (topic, _stars(lo, hi))


def _keyword_query(keyword: str, lo: int, hi: Optional[int]) -> str:
    kw = '"%s"' % keyword if " " in keyword else keyword
    return "%s in:name,description %s archived:false fork:false" % (kw, _stars(lo, hi))


def _ingest(items: List[dict], found: Dict[str, dict], topic: str) -> int:
    added = 0
    for it in items:
        name = it["full_name"]
        entry = found.get(name)
        if entry is None:
            lic = it.get("license") or {}
            entry = {
                "full_name": name,
                "description": (it.get("description") or "")[:300],
                "url": it.get("html_url"),
                "homepage": (it.get("homepage") or "").strip(),
                "stars": it.get("stargazers_count", 0),
                "forks": it.get("forks_count", 0),
                "open_issues": it.get("open_issues_count", 0),
                "language": it.get("language"),
                "license": lic.get("spdx_id"),
                "topics": set(it.get("topics") or []),
                "created_at": it.get("created_at"),
                "pushed_at": it.get("pushed_at"),
                "owner_type": (it.get("owner") or {}).get("type"),
                "hits": set(),
            }
            found[name] = entry
            added += 1
        entry["topics"].update(it.get("topics") or [])
        entry["hits"].add(topic)
    return added


def sweep(searcher: Searcher, topics: List[str], min_stars: int, max_requests: int = 2000,
          checkpoint=None) -> Dict[str, dict]:
    found: Dict[str, dict] = {}
    bands = [(max(lo, min_stars), hi) for lo, hi in STAR_BANDS if hi is None or hi >= min_stars]
    for ti, topic in enumerate(topics, 1):
        if searcher.requests_made >= max_requests:
            log.warning("request budget exhausted; stopping at topic %s", topic)
            break
        first = searcher.search(_query(topic, min_stars, None), 1)
        total = first.get("total_count", 0)
        added = _ingest(first.get("items") or [], found, topic)
        if total <= 1000:
            page = 2
            while page * 100 - 100 < total and page <= 10:
                data = searcher.search(_query(topic, min_stars, None), page)
                added += _ingest(data.get("items") or [], found, topic)
                page += 1
        else:
            for lo, hi in bands:
                page = 1
                while page <= 10:
                    data = searcher.search(_query(topic, lo, hi), page)
                    items = data.get("items") or []
                    added += _ingest(items, found, topic)
                    if len(items) < 100 or page * 100 >= data.get("total_count", 0):
                        break
                    page += 1
        log.info("[%d/%d] topic=%s total=%d new=%d catalog=%d requests=%d",
                 ti, len(topics), topic, total, added, len(found), searcher.requests_made)
        if checkpoint:
            checkpoint(found, ti)
    return found


def keyword_sweep(searcher: Searcher, keywords: List[str], min_stars: int, found: Dict[str, dict],
                  max_requests: int, checkpoint=None) -> None:
    """Name/description search for repositories that carry no topics."""
    bands = [(max(lo, min_stars), hi) for lo, hi in STAR_BANDS if hi is None or hi >= min_stars]
    for ki, keyword in enumerate(keywords, 1):
        if searcher.requests_made >= max_requests:
            log.warning("request budget exhausted; stopping at keyword %r", keyword)
            break
        added = 0
        for lo, hi in bands:
            page = 1
            while page <= 10:
                data = searcher.search(_keyword_query(keyword, lo, hi), page)
                items = data.get("items") or []
                added += _ingest(items, found, "kw:" + keyword)
                if len(items) < 100 or page * 100 >= data.get("total_count", 0):
                    break
                page += 1
        log.info("[kw %d/%d] %r new=%d catalog=%d requests=%d", ki, len(keywords), keyword, added, len(found),
                 searcher.requests_made)
        if checkpoint:
            checkpoint(found, ki)


def fetch_seeds(searcher: Searcher, seeds: List[str], found: Dict[str, dict]) -> int:
    """Fetch seed repositories directly (they may carry no topics at all)."""
    added = 0
    for name in seeds:
        if name in found:
            continue
        resp = searcher.session.get("https://api.github.com/repos/" + name, timeout=60)
        searcher.requests_made += 1
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = float(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            time.sleep(max(2.0, reset - time.time() + 1))
            resp = searcher.session.get("https://api.github.com/repos/" + name, timeout=60)
        if resp.status_code != 200:
            log.warning("seed %s: HTTP %s", name, resp.status_code)
            continue
        it = resp.json()
        if it.get("archived") or it.get("fork"):
            continue
        added += _ingest([it], found, "seed")
    log.info("seeds: %d added", added)
    return added


def load_existing(path: Path) -> Dict[str, dict]:
    """Rebuild the in-memory pool from a previous catalog so passes can be resumed."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    found: Dict[str, dict] = {}
    for p in data.get("projects") or []:
        e = dict(p)
        e["topics"] = set(p.get("topics") or [])
        e["hits"] = set(p.get("hits") or [])
        e.setdefault("url", "https://github.com/" + p["full_name"])
        found[p["full_name"]] = e
    log.info("loaded %d existing entries from %s", len(found), path)
    return found


KEEP = ("full_name", "description", "stars", "forks", "language", "license", "created_at", "pushed_at")


def finalize(found: Dict[str, dict], min_stars: int) -> List[dict]:
    projects = []
    for entry in found.values():
        if entry["stars"] < min_stars:
            continue
        hits = sorted(entry["hits"])
        topics = sorted(set(entry["topics"]) | {h for h in hits if not h.startswith("kw:") and h != "seed"})
        e = {k: entry.get(k) for k in KEEP}
        e["description"] = (e["description"] or "")[:200]
        e["topics"] = topics[:20]
        e["hits"] = hits
        e["is_list"] = is_curated_list(e["full_name"], e["description"], topics)
        e["category"] = categorize(topics, e["description"], e["full_name"])
        e["license_recognized"] = bool(e["license"]) and e["license"] != "NOASSERTION"
        e["signal"] = ai_signal(topics, hits, e["description"])
        if "seed" in hits:
            e["signal"] = max(e["signal"], 4)
        projects.append(e)
    projects.sort(key=lambda p: (-p["stars"], p["full_name"].lower()))
    return projects


WEB_KEYS = {"full_name": "n", "description": "d", "stars": "s", "forks": "f", "language": "l", "license": "lic",
            "category": "c", "signal": "sig"}


def write_catalog(found: Dict[str, dict], topics_done: List[str], partial: bool, min_stars: int,
                  requests_made: int, out: Path) -> dict:
    """Write the full catalog (for the collector) and a slim web copy (for the site)."""
    projects = finalize(found, min_stars)
    counts: Dict[str, int] = {}
    for p in projects:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    meta = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": __version__,
        "min_stars": min_stars,
        "partial": partial,
        "requests": requests_made,
        "project_count": len(projects),
        "category_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
    }
    catalog = dict(meta, topics_searched=topics_done, projects=projects)
    web = dict(meta, topics_searched=len(topics_done), projects=[
        dict({v: p[k] for k, v in WEB_KEYS.items()},
             d=(p["description"] or "")[:140], t=p["topics"][:6], p=(p["pushed_at"] or "")[:10],
             cr=(p["created_at"] or "")[:7], list=1 if p["is_list"] else 0, lr=1 if p["license_recognized"] else 0)
        for p in projects])
    out.parent.mkdir(parents=True, exist_ok=True)
    for path, payload in ((out, catalog), (out.with_name("catalog-web.json"), web)):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")))
        tmp.replace(path)
    return catalog


def build(topics: Optional[List[str]] = None, min_stars: Optional[int] = None, out: Path = CATALOG_PATH,
          max_requests: int = 2000, skip_topics: bool = False, skip_keywords: bool = False,
          resume: bool = False) -> dict:
    topics = topics or config.AI_TOPICS
    min_stars = config.CATALOG_MIN_STARS if min_stars is None else min_stars
    searcher = Searcher()
    log.info("catalog sweep: %d topics, %d keywords, min_stars=%d, authenticated=%s", len(topics),
             len(config.KEYWORD_QUERIES), min_stars, searcher.authenticated)
    started = time.time()
    found: Dict[str, dict] = {}
    if resume:
        found = load_existing(out)
        try:   # carry the previous run's request count forward so the total stays honest
            searcher.requests_made = int(json.loads(out.read_text()).get("requests") or 0)
        except (OSError, ValueError):
            pass

    def write(found: Dict[str, dict], topics_done: int, partial: bool) -> dict:
        return write_catalog(found, topics[:topics_done], partial, min_stars, searcher.requests_made, out)

    if not skip_topics:
        found.update(sweep(searcher, topics, min_stars, max_requests=max_requests,
                           checkpoint=lambda f, n: write(f, n, True)) if not found else
                     _merge(found, sweep(searcher, topics, min_stars, max_requests=max_requests,
                                         checkpoint=lambda f, n: write(f, n, True))))
    if not skip_keywords:
        keyword_sweep(searcher, config.KEYWORD_QUERIES, config.CATALOG_KEYWORD_MIN_STARS, found,
                      max_requests=max_requests, checkpoint=lambda f, n: write(f, len(topics), True))
    fetch_seeds(searcher, config.SEED_REPOS, found)
    catalog = write(found, len(topics), False)
    projects = catalog["projects"]
    log.info("wrote %s: %d projects in %.0fs using %d requests", out, len(projects), time.time() - started,
             searcher.requests_made)
    return catalog


def _merge(a: Dict[str, dict], b: Dict[str, dict]) -> Dict[str, dict]:
    for name, entry in b.items():
        if name in a:
            a[name]["topics"].update(entry["topics"])
            a[name]["hits"].update(entry["hits"])
        else:
            a[name] = entry
    return a


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="whitescore.catalog", description="Sweep GitHub for open source AI repositories.")
    parser.add_argument("--min-stars", type=int, default=None)
    parser.add_argument("--topics", nargs="*", help="override the topic list")
    parser.add_argument("--max-requests", type=int, default=2000)
    parser.add_argument("--out", type=Path, default=CATALOG_PATH)
    parser.add_argument("--resume", action="store_true", help="start from the existing catalog file")
    parser.add_argument("--skip-topics", action="store_true", help="skip the topic sweep (use with --resume)")
    parser.add_argument("--skip-keywords", action="store_true", help="skip the name/description keyword pass")
    parser.add_argument("--recategorize", action="store_true", help="no network: recompute categories/signal from the existing file")
    parser.add_argument("--source", type=Path, default=None, help="with --recategorize: read this file instead of --out")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.recategorize:
        src = args.source or args.out
        data = json.loads(src.read_text())
        found = load_existing(src)
        catalog = write_catalog(found, data.get("topics_searched") or [], bool(data.get("partial")),
                                args.min_stars or data.get("min_stars", config.CATALOG_MIN_STARS),
                                data.get("requests", 0), args.out)
        log.info("recategorized %d projects -> %s", catalog["project_count"], args.out)
        return 0
    build(topics=args.topics, min_stars=args.min_stars, out=args.out, max_requests=args.max_requests,
          skip_topics=args.skip_topics, skip_keywords=args.skip_keywords, resume=args.resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
