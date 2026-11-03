"""Orchestrate a full run: discover -> collect -> score -> write site data."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__, config
from .collect import RepositoryForbidden, collect_repo, fetch_star_history_rest
from .discover import (AI_WORDS, WEAK_AI_WORDS, discover, effective_license, license_allowed, load_category_overrides,
                       load_exclusions, select_repos)
from .github import GitHubClient, GitHubError
from .incremental import apply_light, fetch_light, load_cache, plan_collection, prune_cache, save_cache
from .scoring import interpret, score_all
from .tokens import TokenPool, build_pool, save_preferences

log = logging.getLogger("whitescore.pipeline")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
LEADERBOARD_PATH = DATA_DIR / "leaderboard.json"
HISTORY_PATH = DATA_DIR / "history.json"
TERMS_FILE = "terms.json"                     # the selection rules, published next to the leaderboard
SEED_FILE = ROOT / "seed_repos.txt"
CATALOG_PATH = DATA_DIR / "catalog.json"
CACHE_PATH = ROOT / "data" / "metrics-cache.json"   # carried between runs by the workflow, not committed
TOKEN_PREFS_PATH = ROOT / "data" / "token-preferences.json"   # repos that need the fallback token


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


def prune_history(history: Dict[str, list], ignore_before: Optional[str] = None) -> Dict[str, list]:
    """Drop history points dated before ``ignore_before`` (fabricated sample
    points from before the first real collection)."""
    cutoff = config.HISTORY_IGNORE_BEFORE if ignore_before is None else ignore_before
    if not cutoff:
        return history
    pruned = {}
    dropped = 0
    for name, series in history.items():
        kept = [pt for pt in series if pt.get("d", "") >= cutoff]
        dropped += len(series) - len(kept)
        if kept:
            pruned[name] = kept
    if dropped:
        log.info("dropped %d history points dated before %s", dropped, cutoff)
    return pruned


def star_growth_from_history(series: list, stars_now: int, day: str,
                             window_days: Optional[int] = None) -> Tuple[Optional[int], Optional[bool]]:
    """Stars gained over the window, from the daily star counts in ``series``.

    Exact once a point at least ``window_days`` old exists; before that an
    extrapolation from the oldest point (flagged estimated) when it is at
    least HISTORY_MIN_SPAN_DAYS old; otherwise (None, None)."""
    window = config.WINDOW_DAYS if window_days is None else window_days
    target = datetime.strptime(day, "%Y-%m-%d")
    dated = []
    for pt in series or []:
        if pt.get("stars") is None:
            continue
        try:
            age = (target - datetime.strptime(pt["d"], "%Y-%m-%d")).days
        except (KeyError, ValueError):
            continue
        dated.append((age, int(pt["stars"])))
    exact = [p for p in dated if p[0] >= window]
    if exact:
        age, stars = min(exact)             # the most recent point beyond the window
        return max(0, int(stars_now) - stars), False
    if not dated:
        return None, None
    age, stars = max(dated)                 # the oldest point we have
    if age < config.HISTORY_MIN_SPAN_DAYS:
        return None, None
    gained = max(0, int(stars_now) - stars)
    return int(round(gained / float(age) * window)), True


def apply_star_history(metrics: dict, history: Dict[str, list], day: str) -> dict:
    """Fill stars_90d from the daily history when the collector could not read
    GitHub's star history endpoint.  An exact figure from that endpoint is
    kept; the sampled stargazer timeline, which GitHub no longer serves, is
    normally empty and is only kept while the history is too short to use."""
    if metrics.get("stars_90d_exact"):
        return metrics
    series = history.get(metrics["full_name"]) or []
    gained, estimated = star_growth_from_history(series, metrics.get("stars") or 0, day)
    if gained is None:
        if not metrics.get("stars_90d"):
            metrics["stars_90d"], metrics["stars_90d_estimated"] = None, None
        return metrics
    metrics["stars_90d"], metrics["stars_90d_estimated"] = gained, estimated
    return metrics


def refresh_star_growth(client_for, names: List[str], now: datetime) -> Dict[str, int]:
    """Exact stars gained in the window for cached repositories, one REST call
    each to GitHub's star history endpoint.  Repositories the endpoint does not
    answer for are left out and keep their cached or history-derived figure."""
    def one(name: str) -> Tuple[str, Optional[int]]:
        try:
            return name.lower(), fetch_star_history_rest(client_for(name), name, now)
        except GitHubError as exc:
            log.debug("star history unavailable for %s: %s", name, exc)
            return name.lower(), None

    out: Dict[str, int] = {}
    if not names:
        return out
    with ThreadPoolExecutor(max_workers=max(1, config.WORKERS)) as pool:
        for key, gained in pool.map(one, names):
            if gained is not None:
                out[key] = gained
    log.info("exact star growth read for %d of %d cached repositories", len(out), len(names))
    return out


def previous_scores(history: Dict[str, list], full_name: str, day: str, days_back: int = 7) -> Optional[dict]:
    """The most recent history point at least ``days_back`` days before ``day``."""
    series = history.get(full_name) or []
    target = datetime.strptime(day, "%Y-%m-%d")
    candidates = [pt for pt in series if (target - datetime.strptime(pt["d"], "%Y-%m-%d")).days >= days_back]
    return candidates[-1] if candidates else None


def selection_terms() -> dict:
    """Everything that decides which projects are tracked, as published data."""
    return {
        "ai_topics": list(config.AI_TOPICS),
        "generic_topics": sorted(config.GENERIC_TOPICS),
        "keyword_queries": list(config.KEYWORD_QUERIES),
        "ai_words": [w.strip() for w in AI_WORDS],
        "weak_ai_words": list(WEAK_AI_WORDS),
        "min_signal": config.CATALOG_MIN_SIGNAL,
        "min_stars": config.MIN_STARS,
        "catalog_min_stars": config.CATALOG_MIN_STARS,
        "require_license": config.REQUIRE_RECOGNIZED_LICENSE,
        "osi_licenses": sorted(config.OSI_APPROVED_LICENSES),
        "license_overrides": dict(config.LICENSE_OVERRIDES),
        "seeds": sorted(set(config.SEED_REPOS) | set(load_seed_file())),
        "excluded": load_exclusions(),
        "category_overrides": load_category_overrides(),
        "categories": [name for name, _ in config.CATEGORY_RULES] + [config.DEFAULT_CATEGORY],
    }


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


def collect_with_fallback(pool: TokenPool, full_name: str, now: datetime, stamp: str) -> Optional[dict]:
    """collect_repo with the pool's tokens in preference order.  A repository
    the first token may not read is retried with the other; whichever worked
    is remembered for later runs.  Raises RepositoryForbidden when every token
    is refused."""
    denied: Optional[RepositoryForbidden] = None
    for which, client in pool.clients_for(full_name):
        try:
            metrics = collect_repo(client, full_name, now)
        except RepositoryForbidden as exc:
            if denied is None and pool.has_fallback:
                log.info("%s: the %s token was refused; retrying with the other token", full_name, which)
            denied = exc
            continue
        if metrics is not None:
            pool.remember(metrics["full_name"], which, stamp)
        return metrics
    assert denied is not None
    raise denied


def run(repos: Optional[List[str]] = None, max_repos: Optional[int] = None, dry_run: bool = False,
        max_full: Optional[int] = None) -> dict:
    started = time.time()
    client = GitHubClient()
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    token_pool = build_pool(client, TOKEN_PREFS_PATH)
    max_repos = max_repos or config.MAX_REPOS

    excluded = load_exclusions()
    category_overrides = load_category_overrides()
    if repos:
        targets = repos
        discovered = {}
    else:
        discovered = catalog_candidates(config.MIN_STARS)
        if discovered:
            log.info("using %d candidates from %s", len(discovered), CATALOG_PATH)
        else:
            discovered = discover(client)
        targets = select_repos(discovered, seeds=config.SEED_REPOS + load_seed_file(), max_repos=max_repos,
                               exclude=excluded)
    log.info("Tracking %d repositories (%d candidates)", len(targets), len(discovered))
    history = prune_history(load_json(HISTORY_PATH, {}))

    # Incremental plan: full collections for new/stale repos, cache + light refresh for the rest.
    cache = load_cache(CACHE_PATH)
    if repos:
        full, reuse, stats = list(targets), [], {"new": 0, "stale": 0, "deferred": 0, "fresh": 0}
    else:
        full, reuse, stats = plan_collection(targets, cache, now, max_full=max_full)
    log.info("Plan: %d full collections (%d new, %d stale, %d deferred to later runs), %d refreshed from cache",
             len(full), stats["new"], stats["stale"], stats["deferred"], len(reuse))

    projects: List[dict] = []
    failures: List[str] = []
    deferred: List[str] = []   # due for collection but over this run's budget, with nothing cached yet
    cache_lock = threading.Lock()

    def merge_topics(metrics: dict) -> dict:
        if metrics["full_name"] in discovered:
            # merge topics seen across search results (repositoryTopics is capped)
            extra = discovered[metrics["full_name"]].get("topics") or []
            metrics["topics"] = sorted(set(metrics["topics"]) | set(extra))[:15]
        return metrics

    def finish(metrics: dict) -> dict:
        metrics = merge_topics(metrics)
        metrics["license"] = effective_license(metrics.get("license"), metrics["full_name"])
        if metrics["license"] in config.OSI_APPROVED_LICENSES:
            metrics["has_license"] = True
        override = category_overrides.get(metrics["full_name"].lower())
        if override:
            metrics["category"] = override
        return build_project(apply_star_history(metrics, history, day))

    def work(full_name: str) -> Optional[dict]:
        try:
            metrics = collect_with_fallback(token_pool, full_name, now, stamp)
        except RepositoryForbidden as exc:
            hint = "" if token_pool.has_fallback else \
                " (set GITHUB_TOKEN_FALLBACK to a token of the other kind to retry such repositories)"
            log.error("%s%s", exc, hint)
            return None
        except GitHubError as exc:
            log.error("%s: %s", full_name, exc)
            return None
        except Exception:  # one odd repository must not take the whole run down
            log.exception("%s: unexpected error while collecting", full_name)
            return None
        if metrics is None:
            return None
        with cache_lock:
            cache[metrics["full_name"].lower()] = {"collected_at": stamp, "metrics": dict(metrics)}
            if full_name.lower() != metrics["full_name"].lower():
                cache.pop(full_name.lower(), None)  # renamed: drop the stale key
        return finish(metrics)

    if full:
        with ThreadPoolExecutor(max_workers=max(1, config.WORKERS)) as pool:
            futures = {pool.submit(work, r): r for r in full}
            for i, fut in enumerate(as_completed(futures), 1):
                result = fut.result()
                if result:
                    projects.append(result)
                else:
                    failures.append(futures[fut])
                if i % 25 == 0 or i == len(futures):
                    log.info("progress %d/%d (requests=%d, graphql points=%d)", i, len(futures),
                             *token_pool.request_totals())
        if token_pool.learned:
            log.info("%d repositories newly remembered as needing the fallback token", token_pool.learned)
        # A repository that could not be collected this run keeps its place on
        # the board with its last cached metrics (light-refreshed like the
        # others) instead of disappearing until a later run succeeds.
        kept = [name for name in failures if name.lower() in cache]
        if kept:
            log.warning("%d repositories could not be collected this run; keeping their cached metrics", len(kept))
            reuse = list(reuse) + kept

    if reuse:
        primary_names, fallback_names = token_pool.split(reuse)
        light = fetch_light(client, primary_names) if primary_names else {}
        if fallback_names:
            light.update(fetch_light(token_pool.fallback, fallback_names))
        fallback_set = {n.lower() for n in fallback_names}

        def client_for(name: str) -> GitHubClient:
            return token_pool.fallback if token_pool.fallback and name.lower() in fallback_set else client

        growth = refresh_star_growth(client_for, [n for n in reuse if n.lower() in cache], now)
        for name in reuse:
            entry = cache.get(name.lower())
            if not entry:
                deferred.append(name)
                continue
            metrics = apply_light(entry["metrics"], light.get(name.lower()), now)
            gained = growth.get(name.lower())
            if gained is not None:
                metrics.update(stars_90d=gained, stars_90d_estimated=False, stars_90d_exact=True)
            entry["metrics"] = metrics
            projects.append(finish(dict(metrics)))
        log.info("refreshed %d cached repositories with %d light payloads (requests=%d, graphql points=%d)",
                 len(reuse) - len(deferred), len(light), *token_pool.request_totals())
        if deferred:
            log.info("%d repositories have no cached metrics yet and wait for the next run", len(deferred))

    # the licence policy applies to seeds too, which bypass the candidate filter
    unlicensed = [p for p in projects if not license_allowed(p["license"], p["full_name"])]
    if unlicensed:
        log.info("%d repositories left off the board by the licence policy: %s", len(unlicensed),
                 ", ".join("%s (%s)" % (p["full_name"], p["license"] or "none") for p in unlicensed[:20]))
        projects = [p for p in projects if license_allowed(p["license"], p["full_name"])]

    # de-duplicate on canonical name (renames can collapse two targets)
    seen = set()
    unique = []
    for p in sorted(projects, key=lambda p: -p["scores"]["overall"]):
        if p["full_name"].lower() in seen:
            continue
        seen.add(p["full_name"].lower())
        unique.append(p)
    projects = unique

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
        "license": config.DATA_LICENSE, "license_url": config.DATA_LICENSE_URL, "attribution": config.DATA_ATTRIBUTION,
        "failures": failures,
        "deferred": deferred,
        "sample": False,
        "projects": projects,
    }

    if dry_run:
        log.info("dry run: not writing files")
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LEADERBOARD_PATH.write_text(json.dumps(leaderboard, separators=(",", ":")))
        (DATA_DIR / TERMS_FILE).write_text(json.dumps(selection_terms(), separators=(",", ":")))
        HISTORY_PATH.write_text(json.dumps(history, separators=(",", ":")))
        save_cache(CACHE_PATH, prune_cache(cache, targets, now))
        save_preferences(TOKEN_PREFS_PATH, token_pool, keep=None if repos else targets)
        log.info("wrote %s (%d projects), %s and %s", LEADERBOARD_PATH, len(projects), HISTORY_PATH, CACHE_PATH)

    requests_made, points = token_pool.request_totals()
    log.info("done in %.0fs; %d requests, %d graphql points, %d failures",
             time.time() - started, requests_made, points, len(failures))
    if failures and not projects:
        log.error("Every repository failed to collect. The first 'not found or inaccessible' "
                  "warnings above carry the GraphQL error returned by GitHub; check the token's "
                  "permissions (a fine-grained token needs 'Public repositories (read-only)').")
    return leaderboard
