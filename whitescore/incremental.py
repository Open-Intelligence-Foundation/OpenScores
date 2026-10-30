"""Incremental collection.

A full collection costs roughly ten API requests per repository, which puts a
daily run of 1,000 repositories past GitHub's hourly budget.  Instead, each
repository gets a full collection at least every FULL_REFRESH_DAYS days, spread
across runs (oldest first, at most MAX_FULL_COLLECT per run), and every other
repository is refreshed from the previous run's metrics plus one cheap "light"
GraphQL query that reads fifty repositories at a time: stars, forks, watchers,
open issues and PRs, archived flag and last commit date.

The cache lives outside site/ so it is committed but never served.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import config
from .collect import days_since, parse_dt
from .github import GitHubClient, GitHubError

log = logging.getLogger("whitescore.incremental")

CACHE_VERSION = 1
CACHE_KEEP_DAYS = 30  # entries for repositories that fell off the list expire after this

LIGHT_FIELDS = """nameWithOwner stargazerCount forkCount pushedAt isArchived isDisabled
      watchers { totalCount }
      openIssues: issues(states: OPEN) { totalCount }
      openPRs: pullRequests(states: OPEN) { totalCount }
      defaultBranchRef { target { ... on Commit { committedDate } } }"""


# ----------------------------------------------------------------- cache file
def load_cache(path: Path) -> Dict[str, dict]:
    """lower-cased full_name -> {"collected_at": iso, "metrics": {...}}."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        log.warning("Could not parse %s; starting with an empty cache", path)
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        log.info("Ignoring metrics cache with unknown version at %s", path)
        return {}
    entries = data.get("entries") or {}
    return {k.lower(): v for k, v in entries.items()
            if isinstance(v, dict) and isinstance(v.get("metrics"), dict) and v.get("collected_at")}


def save_cache(path: Path, cache: Dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": CACHE_VERSION, "entries": cache},
                               separators=(",", ":"), sort_keys=True))


def prune_cache(cache: Dict[str, dict], keep: Iterable[str], now: datetime,
                keep_days: int = CACHE_KEEP_DAYS) -> Dict[str, dict]:
    """Keep entries for current targets and anything collected recently."""
    wanted = {k.lower() for k in keep}
    out = {}
    for key, entry in cache.items():
        collected = parse_dt(entry.get("collected_at"))
        age = days_since(collected, now) if collected else None
        if key in wanted or (age is not None and age < keep_days):
            out[key] = entry
    return out


# --------------------------------------------------------------------- planning
def plan_collection(targets: List[str], cache: Dict[str, dict], now: datetime,
                    max_full: Optional[int] = None, refresh_days: Optional[float] = None
                    ) -> Tuple[List[str], List[str], Dict[str, int]]:
    """Split targets into (full collections, cache reuse) for this run.

    Never-collected repositories go first, then the stalest cached ones, up to
    ``max_full``.  Whatever does not fit is reused from cache this run and
    picked up by the next.  Returns the two lists and counts for the log.
    """
    max_full = config.MAX_FULL_COLLECT if max_full is None else max_full
    refresh_days = config.FULL_REFRESH_DAYS if refresh_days is None else refresh_days
    new: List[str] = []
    stale: List[Tuple[float, str]] = []
    fresh: List[str] = []
    for name in targets:
        entry = cache.get(name.lower())
        if not entry:
            new.append(name)
            continue
        collected = parse_dt(entry.get("collected_at"))
        age = days_since(collected, now) if collected else None
        if age is None or age >= refresh_days:
            stale.append((float("inf") if age is None else age, name))
        else:
            fresh.append(name)
    stale.sort(key=lambda t: (-t[0], t[1].lower()))
    due = new + [name for _, name in stale]
    if max_full is not None and max_full >= 0:
        full, deferred = due[:max_full], due[max_full:]
    else:
        full, deferred = due, []
    stats = {"new": len(new), "stale": len(stale), "deferred": len(deferred), "fresh": len(fresh)}
    return full, fresh + deferred, stats


# ---------------------------------------------------------------- light refresh
def build_light_query(names: Iterable[str]) -> str:
    """One GraphQL document reading the light fields of several repositories."""
    parts = []
    for i, name in enumerate(names):
        owner, _, repo = name.partition("/")
        parts.append("  r%d: repository(owner: %s, name: %s) {\n      %s\n  }"
                     % (i, json.dumps(owner), json.dumps(repo), LIGHT_FIELDS))
    return "query LightRefresh {\n  rateLimit { cost remaining resetAt }\n" + "\n".join(parts) + "\n}\n"


def fetch_light(client: GitHubClient, names: Iterable[str], batch: Optional[int] = None) -> Dict[str, dict]:
    """lower-cased requested name -> light payload, for every repo GitHub returned."""
    batch = batch or config.LIGHT_BATCH
    names = list(names)
    out: Dict[str, dict] = {}
    for start in range(0, len(names), batch):
        chunk = names[start:start + batch]
        try:
            data = client.graphql(build_light_query(chunk))
        except GitHubError as exc:
            log.warning("light refresh batch of %d repositories failed: %s", len(chunk), exc)
            continue
        for i, name in enumerate(chunk):
            payload = data.get("r%d" % i)
            if payload:
                out[name.lower()] = payload
    return out


def apply_light(metrics: dict, light: Optional[dict], now: datetime) -> dict:
    """Cached metrics brought up to date with the light payload (or aged when absent)."""
    m = dict(metrics)
    base = parse_dt(m.get("refreshed_at") or m.get("collected_at"))
    elapsed = days_since(base, now) if base else 0.0
    elapsed = max(0.0, elapsed or 0.0)

    if light:
        m["stars"] = int(light.get("stargazerCount") or 0)
        m["forks"] = int(light.get("forkCount") or 0)
        m["watchers"] = int((light.get("watchers") or {}).get("totalCount") or 0)
        m["open_issues"] = int((light.get("openIssues") or {}).get("totalCount") or 0)
        m["open_prs"] = int((light.get("openPRs") or {}).get("totalCount") or 0)
        m["is_archived"] = bool(light.get("isArchived"))
        committed = parse_dt((((light.get("defaultBranchRef") or {}).get("target") or {}).get("committedDate")))
    else:
        committed = None

    if committed:
        m["days_since_commit"] = days_since(committed, now)
    elif m.get("days_since_commit") is not None:
        m["days_since_commit"] = m["days_since_commit"] + elapsed
    if m.get("days_since_release") is not None:
        m["days_since_release"] = m["days_since_release"] + elapsed
    if m.get("age_months") is not None:
        m["age_months"] = m["age_months"] + elapsed / 30.44

    m["refreshed_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    m["from_cache"] = True
    return m
