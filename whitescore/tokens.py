"""Primary token plus an optional fallback token.

Some organizations refuse one kind of personal access token: an organization
with SAML single sign-on, or with a personal-access-token policy, may answer
every request for its repositories with FORBIDDEN ("Resource protected by
organization SAML enforcement", "forbids access via a personal access token
(classic)", ...).  A classic token gets the richest data everywhere else, so
the collector runs with a classic token as primary and, when the environment
provides a second token (``GITHUB_TOKEN_FALLBACK``, typically fine-grained),
retries a denied repository with that one.

Repositories that needed the fallback are remembered in
``data/token-preferences.json`` so later runs go straight to the token that
works, and sibling repositories of the same owner start with it too.  This is
an access fallback, not request pooling: a repository is only ever read with
one token per run.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .github import GitHubClient

log = logging.getLogger("whitescore.tokens")

PREFERENCES_VERSION = 1
PRIMARY = "primary"
FALLBACK = "fallback"


class TokenPool:
    def __init__(self, primary: GitHubClient, fallback: Optional[GitHubClient] = None,
                 fallback_repos: Optional[Dict[str, str]] = None):
        self.primary = primary
        self.fallback = fallback
        # lower-cased full_name -> ISO time the fallback was last needed
        self.fallback_repos: Dict[str, str] = dict(fallback_repos or {})
        self.learned = 0
        self._lock = threading.Lock()

    @property
    def has_fallback(self) -> bool:
        return self.fallback is not None

    def prefers_fallback(self, full_name: str) -> bool:
        """True when this repository, or another of the same owner, needed the fallback before."""
        if not self.fallback:
            return False
        key = full_name.lower()
        owner_prefix = key.partition("/")[0] + "/"
        with self._lock:
            return key in self.fallback_repos or any(k.startswith(owner_prefix) for k in self.fallback_repos)

    def clients_for(self, full_name: str) -> List[Tuple[str, GitHubClient]]:
        """(label, client) pairs in the order to try for this repository."""
        order = [(PRIMARY, self.primary)]
        if self.fallback:
            order.append((FALLBACK, self.fallback))
            if self.prefers_fallback(full_name):
                order.reverse()
        return order

    def remember(self, full_name: str, which: str, stamp: str) -> None:
        key = full_name.lower()
        with self._lock:
            if which == FALLBACK:
                if key not in self.fallback_repos:
                    self.learned += 1
                self.fallback_repos[key] = stamp
            else:
                self.fallback_repos.pop(key, None)   # the primary token works for it (again)

    def split(self, names: Iterable[str]) -> Tuple[List[str], List[str]]:
        """Names into (for the primary token, for the fallback token)."""
        primary: List[str] = []
        fallback: List[str] = []
        for name in names:
            (fallback if self.prefers_fallback(name) else primary).append(name)
        return primary, fallback

    def request_totals(self) -> Tuple[int, int]:
        requests_made = self.primary.requests_made + (self.fallback.requests_made if self.fallback else 0)
        points = self.primary.graphql_points_used + (self.fallback.graphql_points_used if self.fallback else 0)
        return requests_made, points


def fallback_token_from_env() -> Optional[str]:
    token = (os.environ.get("GITHUB_TOKEN_FALLBACK") or "").strip()
    return token or None


def build_pool(primary: GitHubClient, preferences_path: Path,
               fallback_token: Optional[str] = None) -> TokenPool:
    fallback_token = fallback_token or fallback_token_from_env()
    fallback = None
    if fallback_token:
        if fallback_token == primary.token:
            log.warning("GITHUB_TOKEN_FALLBACK is the same token as GITHUB_TOKEN; ignoring it")
        else:
            fallback = GitHubClient(token=fallback_token)
    remembered = load_preferences(preferences_path)
    pool = TokenPool(primary, fallback, remembered)
    if fallback:
        log.info("Fallback token configured; %d repositories remembered as needing it", len(remembered))
    elif remembered:
        log.info("%d repositories needed a fallback token before, but none is configured now", len(remembered))
    return pool


# ------------------------------------------------------------------ persistence
def load_preferences(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        log.warning("Could not parse %s; starting with no token preferences", path)
        return {}
    if not isinstance(data, dict) or data.get("version") != PREFERENCES_VERSION:
        return {}
    repos = data.get("fallback_repos") or {}
    return {str(k).lower(): str(v) for k, v in repos.items() if isinstance(k, str)}


def save_preferences(path: Path, pool: TokenPool, keep: Optional[Iterable[str]] = None) -> None:
    """Write the remembered repositories, pruned to ``keep`` (current targets) when given."""
    repos = dict(pool.fallback_repos)
    if keep is not None:
        wanted = {k.lower() for k in keep}
        repos = {k: v for k, v in repos.items() if k in wanted}
    if not repos and not path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": PREFERENCES_VERSION, "fallback_repos": repos},
                               indent=1, sort_keys=True) + "\n")


def utc_stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")
