"""Thin GitHub API client with rate-limit awareness and retries."""
from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

log = logging.getLogger("whitescore.github")

API_ROOT = "https://api.github.com"
GRAPHQL_URL = API_ROOT + "/graphql"


class GitHubError(RuntimeError):
    pass


def _looks_rate_limited(resp: requests.Response) -> bool:
    """403 bodies for primary/secondary rate limits mention it; permission
    denials ("Resource not accessible by personal access token") do not."""
    text = resp.text[:500].lower()
    return any(marker in text for marker in ("rate limit", "abuse", "secondary", "too many requests"))


def describe_errors(errors: List[Dict[str, Any]], limit: int = 3) -> str:
    """Compact ': TYPE at /path: message; ...' suffix for log lines ('' if none)."""
    parts = []
    for err in errors[:limit]:
        path = err.get("path") or []
        where = (" at /" + "/".join(str(p) for p in path)) if path else ""
        parts.append("%s%s: %s" % (err.get("type") or "ERROR", where, str(err.get("message", ""))[:200]))
    return (": " + "; ".join(parts)) if parts else ""


class RateLimited(GitHubError):
    def __init__(self, reset_epoch: float):
        super().__init__("rate limited until %s" % time.strftime("%H:%M:%S", time.localtime(reset_epoch)))
        self.reset_epoch = reset_epoch


class GitHubClient:
    def __init__(self, token: Optional[str] = None, max_retries: int = 5, timeout: int = 60):
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not self.token:
            raise GitHubError(
                "A GitHub token is required (GraphQL cannot be used anonymously). "
                "Set GITHUB_TOKEN in the environment.")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "whitescore-collector",
        })
        self.max_retries = max_retries
        self.timeout = timeout
        self._lock = threading.Lock()
        self.requests_made = 0
        self.graphql_points_used = 0
        self._disabled_queries: Set[str] = set()
        self._disabled_fields: Dict[str, Set[str]] = {}

    # ------------------------------------------------------ optional queries
    def query_disabled(self, key: str) -> bool:
        with self._lock:
            return key in self._disabled_queries

    def disable_query(self, key: str, reason: str = "") -> None:
        """Stop issuing an optional query for the rest of the run (logged once)."""
        with self._lock:
            if key in self._disabled_queries:
                return
            self._disabled_queries.add(key)
        log.warning("Skipping optional '%s' data for the rest of this run: the token is not "
                    "allowed to read it%s", key, reason)

    def disabled_fields(self, query_name: str) -> frozenset:
        with self._lock:
            return frozenset(self._disabled_fields.get(query_name, ()))

    def disable_field(self, query_name: str, field: str, reason: str = "") -> None:
        """Drop one selection from a query for the rest of the run (logged once)."""
        with self._lock:
            fields = self._disabled_fields.setdefault(query_name, set())
            if field in fields:
                return
            fields.add(field)
        log.warning("Dropping '%s' from the %s query for the rest of this run: the token is not "
                    "allowed to read it%s. A classic personal access token has no such restriction.",
                    field, query_name, reason)

    # ------------------------------------------------------------------ core
    def _sleep_until(self, epoch: float, floor: float = 2.0) -> None:
        delay = max(floor, epoch - time.time() + 1)
        log.warning("Rate limit hit, sleeping %.0fs", delay)
        time.sleep(delay)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:  # network blip
                last_exc = exc
                time.sleep(2 ** attempt + random.random())
                continue
            with self._lock:
                self.requests_made += 1

            if resp.status_code in (403, 429):
                remaining = resp.headers.get("X-RateLimit-Remaining")
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    time.sleep(float(retry_after) + 1)
                    continue
                if remaining == "0":
                    self._sleep_until(float(resp.headers.get("X-RateLimit-Reset", time.time() + 60)))
                    continue
                if resp.status_code == 403 and not _looks_rate_limited(resp):
                    # A plain permission denial: retrying will not help.
                    return resp
                # secondary rate limit without headers: back off
                time.sleep(min(120, 10 * (2 ** attempt)) + random.random())
                continue
            if resp.status_code >= 500 or resp.status_code == 202:
                time.sleep(2 ** attempt + random.random())
                last_exc = GitHubError("HTTP %s for %s" % (resp.status_code, url))
                continue
            return resp
        raise GitHubError("Giving up on %s %s: %s" % (method, url, last_exc))

    # ------------------------------------------------------------------ REST
    def rest(self, path: str, params: Optional[Dict[str, Any]] = None, allow_404: bool = True,
             headers: Optional[Dict[str, str]] = None) -> Optional[requests.Response]:
        url = path if path.startswith("http") else API_ROOT + path
        resp = self._request("GET", url, params=params, headers=headers)
        if allow_404 and resp.status_code in (403, 404, 451):
            # missing, token not allowed to read it, or legally blocked (DMCA):
            # all of these mean "no data here", not "the run is broken"
            if resp.status_code != 404:
                log.debug("HTTP %s for %s: %s", resp.status_code, url, resp.text[:200])
            return None
        if resp.status_code >= 400:
            raise GitHubError("HTTP %s for %s: %s" % (resp.status_code, url, resp.text[:200]))
        return resp

    def rest_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        resp = self.rest(path, params)
        return resp.json() if resp is not None else None

    # --------------------------------------------------------------- GraphQL
    def graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.graphql_full(query, variables)[0]

    def graphql_full(self, query: str, variables: Optional[Dict[str, Any]] = None
                     ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Run a query; returns (data, errors) so callers can explain a null result."""
        for attempt in range(self.max_retries):
            resp = self._request("POST", GRAPHQL_URL, json={"query": query, "variables": variables or {}})
            if resp.status_code >= 400:
                raise GitHubError("GraphQL HTTP %s: %s" % (resp.status_code, resp.text[:300]))
            payload = resp.json()
            errors = payload.get("errors") or []
            rate = (payload.get("data") or {}).get("rateLimit")
            if rate:
                with self._lock:
                    self.graphql_points_used += rate.get("cost", 0)
                if rate.get("remaining", 1) < 50:
                    log.warning("GraphQL budget nearly exhausted (%s left)", rate.get("remaining"))
            if errors:
                types = {e.get("type") for e in errors}
                if "RATE_LIMITED" in types:
                    reset = resp.headers.get("X-RateLimit-Reset")
                    self._sleep_until(float(reset) if reset else time.time() + 60)
                    continue
                # NOT_FOUND on optional sub-fields (e.g. missing README) is fine:
                # GraphQL still returns partial data. Only fail on hard errors.
                hard = [e for e in errors if e.get("type") not in ("NOT_FOUND", "FORBIDDEN")]
                if hard and not payload.get("data"):
                    raise GitHubError("GraphQL error: %s" % hard[:2])
                if hard:
                    log.debug("GraphQL partial errors: %s", hard[:2])
            return payload.get("data") or {}, errors
        raise GitHubError("GraphQL retries exhausted")

    def rate_limit(self) -> Dict[str, Any]:
        return self.rest_json("/rate_limit") or {}
