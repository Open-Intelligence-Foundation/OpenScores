"""Orchestrate a full run: discover -> collect -> score -> write site data."""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__, config
from .collect import collect_repo
from .discover import discover, select_repos
from .github import GitHubClient, GitHubError
from .scoring import interpret, score_all

log = logging.getLogger("whitescore.pipeline")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
LEADERBOARD_PATH = DATA_DIR / "leaderboard.json"
HISTORY_PATH = DATA_DIR / "history.json"
SEED_FILE = ROOT / "seed_repos.txt"
CATALOG_PATH = DATA_DIR / "catalog.json"


def load_seed_file() -> List[str]:
    if not SEED_FILE.exists():
        return []
    return [line.strip() for line in SEED_FILE.read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def catalog_candidates(min_stars: int) -> Dict[str, dict]:
    """Candidate pool from site/data/catalog.json (built by whitescore.catalog), if present."""
    catalog = load_json(CATALOG_PATH, None)
    if not catalog:
        return {}
    found: Dict[str, dict] = {}
    for p in catalog.get("projects") or []:
        if p.get("stars", 0) < min_stars:
            continue
        if p.get("is_list") and not config.INCLUDE_CURATED_LISTS:
            continue
        if p.get("signal", 99) < config.CATALOG_MIN_SIGNAL:
            continue
        if config.REQUIRE_RECOGNIZED_LICENSE and not p.get("license_recognized"):
            continue
        found[p["full_name"]] = {"stars": p["stars"], "topics": p.get("topics") or [], "hits": len(p.get("hits") or [])}
    return found


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            log.warning("Could not parse %s; starting fresh", path)
    return default


def update_history(history: Dict[str, list], projects: List[dict], day: str) -> Dict[str, list]:
    for p in projects:
        series = history.setdefault(p["full_name"], [])
        point = {"d": day, "o": p["scores"]["overall"], "m": p["scores"]["maturity"],
                 "h": p["scores"]["health"], "p": p["scores"]["popularity"],
                 "r": p["scores"]["risk"], "s": p["scores"]["sustainability"],
                 "stars": p["metrics"]["stars"]}
        if series and series[-1]["d"] == day:
            series[-1] = point
        else:
            series.append(point)
        del series[:-config.HISTORY_MAX_POINTS]
    return history


def previous_scores(history: Dict[str, list], full_name: str, day: str, days_back: int = 7) -> Optional[dict]:
    """The most recent history point at least ``days_back`` days before ``day``."""
    series = history.get(full_name) or []
    target = datetime.strptime(day, "%Y-%m-%d")
    candidates = [pt for pt in series if (target - datetime.strptime(pt["d"], "%Y-%m-%d")).days >= days_back]
    return candidates[-1] if candidates else None


def build_project(metrics: dict) -> dict:
    scores = score_all(metrics)
    bands = {k: interpret(k, scores[k]) for k in ("maturity", "health", "popularity", "risk", "sustainability")}
    return {
        "full_name": metrics["full_name"],
        "name": metrics["name"],
        "owner": metrics["owner"],
        "description": metrics["description"],
        "url": metrics["url"],
        "homepage": metrics["homepage"],
        "language": metrics["language"],
        "topics": metrics["topics"],
        "category": metrics["category"],
        "license": metrics["license"],
        "scores": scores,
        "bands": bands,
        "metrics": {k: v for k, v in metrics.items()
                    if k not in ("name", "owner", "description", "url", "homepage", "language",
                                 "topics", "category", "license", "full_name")},
    }


def run(repos: Optional[List[str]] = None, max_repos: Optional[int] = None, dry_run: bool = False) -> dict:
    started = time.time()
    client = GitHubClient()
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    max_repos = max_repos or config.MAX_REPOS

    if repos:
        targets = repos
        discovered = {}
    else:
        discovered = catalog_candidates(config.MIN_STARS)
        if discovered:
            log.info("using %d candidates from %s", len(discovered), CATALOG_PATH)
        else:
            discovered = discover(client)
        targets = select_repos(discovered, seeds=config.SEED_REPOS + load_seed_file(), max_repos=max_repos)
    log.info("Collecting %d repositories (%d candidates)", len(targets), len(discovered))

    projects: List[dict] = []
    failures: List[str] = []

    def work(full_name: str) -> Optional[dict]:
        try:
            metrics = collect_repo(client, full_name, now)
        except GitHubError as exc:
            log.error("%s: %s", full_name, exc)
            return None
        if metrics is None:
            return None
        if metrics["full_name"] in discovered:
            # merge topics seen across search results (repositoryTopics is capped)
            extra = discovered[metrics["full_name"]].get("topics") or []
            metrics["topics"] = sorted(set(metrics["topics"]) | set(extra))[:15]
        return build_project(metrics)

    with ThreadPoolExecutor(max_workers=max(1, config.WORKERS)) as pool:
        futures = {pool.submit(work, r): r for r in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            if result:
                projects.append(result)
            else:
                failures.append(futures[fut])
            if i % 25 == 0 or i == len(futures):
                log.info("progress %d/%d (requests=%d, graphql points=%d)", i, len(futures),
                         client.requests_made, client.graphql_points_used)

    # de-duplicate on canonical name (renames can collapse two targets)
    seen = set()
    unique = []
    for p in sorted(projects, key=lambda p: -p["scores"]["overall"]):
        if p["full_name"].lower() in seen:
            continue
        seen.add(p["full_name"].lower())
        unique.append(p)
    projects = unique

    history = load_json(HISTORY_PATH, {})
    history = update_history(history, projects, day)
    for p in projects:
        prev = previous_scores(history, p["full_name"], day)
        p["delta_7d"] = None if not prev else {
            "overall": round(p["scores"]["overall"] - prev["o"], 1),
            "stars": p["metrics"]["stars"] - prev.get("stars", p["metrics"]["stars"]),
        }
    for rank, p in enumerate(projects, 1):
        p["rank"] = rank

    categories = sorted({p["category"] for p in projects})
    leaderboard = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": __version__,
        "window_days": config.WINDOW_DAYS,
        "project_count": len(projects),
        "categories": categories,
        "benchmarks": config.POPULARITY_BENCHMARKS,
        "weights": {
            "overall": config.OVERALL_WEIGHTS, "maturity": config.MATURITY_WEIGHTS,
            "health": config.HEALTH_WEIGHTS, "popularity": config.POPULARITY_WEIGHTS,
            "risk": config.RISK_WEIGHTS, "sustainability": config.SUSTAINABILITY_WEIGHTS,
        },
        "failures": failures,
        "sample": False,
        "projects": projects,
    }

    if dry_run:
        log.info("dry run: not writing files")
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LEADERBOARD_PATH.write_text(json.dumps(leaderboard, separators=(",", ":")))
        HISTORY_PATH.write_text(json.dumps(history, separators=(",", ":")))
        log.info("wrote %s (%d projects) and %s", LEADERBOARD_PATH, len(projects), HISTORY_PATH)

    log.info("done in %.0fs; %d requests, %d graphql points, %d failures",
             time.time() - started, client.requests_made, client.graphql_points_used, len(failures))
    return leaderboard
