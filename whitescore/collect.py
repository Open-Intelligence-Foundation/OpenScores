"""Collect the raw metrics for one repository.

The output is a flat dict of metric values consumed by ``scoring.py``. Every
metric is derived from public GitHub data; where the API only gives us a
sample (recent commits, recent issues, recent stargazers) the derivation is
documented inline and the metric is marked as estimated where relevant.
"""
from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from . import config
from .discover import categorize
from .github import GitHubClient
from .queries import COUNTS, MORE_HISTORY, REPO_CORE

log = logging.getLogger("whitescore.collect")

SEMVER_RE = re.compile(r"^v?\d+\.\d+(\.\d+)?([-+.].*)?$")
CHANGELOG_RE = re.compile(r"^(changelog|changes|history|news|releases|release[-_]notes)(\..*)?$", re.I)
TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "testing", "e2e", "unittests", "unit_tests"}
TEST_FILES = {"pytest.ini", "tox.ini", "conftest.py", "noxfile.py", "jest.config.js", "jest.config.ts",
              "jest.config.mjs", "vitest.config.ts", "vitest.config.js", "karma.conf.js", "phpunit.xml"}
CI_FILES = {".travis.yml", ".gitlab-ci.yml", "jenkinsfile", "azure-pipelines.yml", ".drone.yml",
            "bitbucket-pipelines.yml", "appveyor.yml", "cloudbuild.yaml", ".cirrus.yml"}
CI_DIRS = {".circleci", ".buildkite", ".github/workflows"}
DOC_DIRS = {"docs", "doc", "documentation", "wiki", "site"}
EXAMPLE_DIRS = {"examples", "example", "samples", "sample", "demo", "demos", "notebooks", "tutorials", "cookbook", "recipes"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def days_since(value: Optional[datetime], now: datetime) -> Optional[float]:
    if value is None:
        return None
    return max(0.0, (now - value).total_seconds() / 86400.0)


def _is_bot(login: Optional[str]) -> bool:
    if not login:
        return False
    low = login.lower()
    return low in config.BOT_LOGINS or low.endswith("[bot]") or low.endswith("-bot")


def author_key(author: Optional[dict]) -> Optional[str]:
    """Stable identity for a commit author: login, else email, else name."""
    if not author:
        return None
    user = author.get("user") or {}
    login = user.get("login")
    if login:
        return None if _is_bot(login) else "@" + login.lower()
    email = (author.get("email") or "").lower()
    name = (author.get("name") or "").strip()
    if "noreply.github.com" in email or _is_bot(name) or name.lower().endswith("[bot]"):
        return None
    return email or name.lower() or None


# ---------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------
def _entry_names(tree: Optional[dict]) -> Tuple[set, set]:
    """Return (dir names, file names) lower-cased from a GraphQL Tree."""
    dirs, files = set(), set()
    for e in (tree or {}).get("entries") or []:
        (dirs if e.get("type") == "tree" else files).add(e["name"].lower())
    return dirs, files


def _readme_text(repo: dict) -> str:
    for key in ("readmeMd", "readmeRst", "readmeLower", "readmePlain"):
        blob = repo.get(key) or {}
        if blob.get("text"):
            return blob["text"][:200_000]
    return ""


def _release_list(repo: dict) -> List[Tuple[str, datetime]]:
    """Releases (preferred) or tags, as (tag name, date) sorted desc."""
    releases = []
    for r in (repo.get("releases") or {}).get("nodes") or []:
        if r.get("isDraft"):
            continue
        dt = parse_dt(r.get("publishedAt") or r.get("createdAt"))
        if dt:
            releases.append((r.get("tagName") or r.get("name") or "", dt))
    if releases:
        return sorted(releases, key=lambda x: x[1], reverse=True)
    tags = []
    for t in (repo.get("tags") or {}).get("nodes") or []:
        target = t.get("target") or {}
        dt = parse_dt((target.get("tagger") or {}).get("date") or target.get("committedDate"))
        if dt:
            tags.append((t.get("name") or "", dt))
    return sorted(tags, key=lambda x: x[1], reverse=True)


def _cadence_consistency(dates: List[datetime]) -> float:
    """1 - coefficient of variation of release intervals (0 if < 3 releases)."""
    if len(dates) < 3:
        return 0.0
    gaps = [(dates[i] - dates[i + 1]).total_seconds() / 86400.0 for i in range(len(dates) - 1)]
    gaps = [g for g in gaps if g >= 0]
    if len(gaps) < 2:
        return 0.0
    mean = statistics.mean(gaps)
    if mean <= 0:
        return 0.0
    cv = statistics.pstdev(gaps) / mean
    return max(0.0, 1.0 - min(1.0, cv))


def _major(tag: str) -> Optional[int]:
    m = re.match(r"^v?(\d+)\.", tag or "")
    return int(m.group(1)) if m else None


def _median_response_hours(items: List[dict], now: datetime, kind: str) -> Optional[float]:
    """Median hours to first response for recent issues or PRs.

    A response is the first comment/review by someone other than the author
    (bots excluded), or the close/merge event. Items younger than 7 days with
    no response are ignored (not yet observable); older unanswered items count
    as their current age, so silence is penalised.
    """
    hours: List[float] = []
    for item in items:
        created = parse_dt(item.get("createdAt"))
        if not created:
            continue
        author = ((item.get("author") or {}).get("login") or "").lower()
        candidates: List[datetime] = []
        responders = list((item.get("comments") or {}).get("nodes") or [])
        if kind == "pr":
            responders += list((item.get("reviews") or {}).get("nodes") or [])
        for c in responders:
            login = ((c.get("author") or {}).get("login") or "").lower()
            if login and login != author and not _is_bot(login):
                dt = parse_dt(c.get("createdAt"))
                if dt:
                    candidates.append(dt)
        for key in ("closedAt", "mergedAt"):
            dt = parse_dt(item.get(key))
            if dt:
                candidates.append(dt)
        if candidates:
            hours.append(max(0.0, (min(candidates) - created).total_seconds() / 3600.0))
        else:
            age_h = (now - created).total_seconds() / 3600.0
            if age_h > 7 * 24:
                hours.append(age_h)
    return statistics.median(hours) if hours else None


def _growth_in_window(dates: List[datetime], now: datetime, window_days: int) -> Tuple[int, bool]:
    """Count events in the window from a 'most recent N' sample.

    If the whole sample falls inside the window the true count is larger than
    the sample; we extrapolate from the observed rate and flag it as estimated.
    """
    cutoff = now - timedelta(days=window_days)
    inside = [d for d in dates if d >= cutoff]
    if not dates:
        return 0, False
    if len(inside) < len(dates):
        return len(inside), False
    span_days = max(1.0, (now - min(dates)).total_seconds() / 86400.0)
    return int(round(len(dates) / span_days * window_days)), True


def _bus_factor(counts: Counter) -> int:
    """Smallest number of authors whose commits cover 50% of the total."""
    total = sum(counts.values())
    if total == 0:
        return 0
    running, n = 0, 0
    for _, c in counts.most_common():
        running += c
        n += 1
        if running >= total / 2.0:
            return n
    return n


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def fetch_commit_sample(client: GitHubClient, owner: str, name: str, repo: dict, since180: str) -> List[dict]:
    target = ((repo.get("defaultBranchRef") or {}).get("target") or {})
    history = target.get("history") or {}
    nodes = list(history.get("nodes") or [])
    info = history.get("pageInfo") or {}
    pages = 1
    while info.get("hasNextPage") and pages < config.MAX_COMMIT_PAGES:
        data = client.graphql(MORE_HISTORY, {"owner": owner, "name": name, "since180": since180,
                                             "after": info.get("endCursor")})
        hist = ((((data.get("repository") or {}).get("defaultBranchRef") or {}).get("target") or {})
                .get("history") or {})
        nodes += list(hist.get("nodes") or [])
        info = hist.get("pageInfo") or {}
        pages += 1
    return nodes


def fetch_counts(client: GitHubClient, full_name: str, now: datetime) -> Dict[str, int]:
    d90 = (now - timedelta(days=config.WINDOW_DAYS)).strftime("%Y-%m-%d")
    d180 = (now - timedelta(days=config.STALE_ISSUE_DAYS)).strftime("%Y-%m-%d")
    d365 = (now - timedelta(days=config.RELEASE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    base = "repo:%s " % full_name
    variables = {
        "issuesOpened": base + "is:issue created:>=%s" % d90,
        "issuesClosed": base + "is:issue is:closed closed:>=%s" % d90,
        "prsOpened": base + "is:pr created:>=%s" % d90,
        "prsMerged": base + "is:pr is:merged merged:>=%s" % d90,
        "prsClosed": base + "is:pr is:closed closed:>=%s" % d90,
        "staleIssues": base + "is:issue is:open updated:<%s" % d180,
        "breaking": base + "is:pr is:merged merged:>=%s breaking in:title" % d365,
    }
    data = client.graphql(COUNTS, variables)
    return {k: int((data.get(k) or {}).get("issueCount") or 0) for k in variables}


def fetch_contributor_count(client: GitHubClient, full_name: str) -> Optional[int]:
    """Total contributors via the Link header of the contributors endpoint."""
    resp = client.rest("/repos/%s/contributors" % full_name, {"per_page": 1, "anon": "true"})
    if resp is None:
        return None
    link = resp.headers.get("Link", "")
    m = re.search(r'[?&]page=(\d+)>; rel="last"', link)
    if m:
        return int(m.group(1))
    body = resp.json()
    return len(body) if isinstance(body, list) else None


def fetch_ci_stats(client: GitHubClient, full_name: str, now: datetime) -> Optional[float]:
    """Success rate of GitHub Actions runs in the window (None if no runs)."""
    since = (now - timedelta(days=config.WINDOW_DAYS)).strftime("%Y-%m-%d")
    data = client.rest_json("/repos/%s/actions/runs" % full_name,
                            {"per_page": 100, "created": ">=" + since, "status": "completed"})
    runs = (data or {}).get("workflow_runs") or []
    runs = [r for r in runs if r.get("conclusion") in ("success", "failure", "timed_out", "startup_failure")]
    if not runs:
        return None
    ok = sum(1 for r in runs if r["conclusion"] == "success")
    return ok / float(len(runs))


def collect_repo(client: GitHubClient, full_name: str, now: Optional[datetime] = None) -> Optional[dict]:
    """Fetch everything for one repo. Returns None if the repo is missing."""
    now = now or utcnow()
    owner, name = full_name.split("/", 1)
    since180 = (now - timedelta(days=config.MAINTAINER_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    since90 = (now - timedelta(days=config.WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = client.graphql(REPO_CORE, {"owner": owner, "name": name, "since180": since180, "since90": since90})
    repo = data.get("repository")
    if not repo:
        log.warning("Repository %s not found or inaccessible", full_name)
        return None
    full_name = repo["nameWithOwner"]  # canonical casing / renames

    commits = fetch_commit_sample(client, owner, name, repo, since180)
    counts = fetch_counts(client, full_name, now)
    contributors_total = fetch_contributor_count(client, full_name)
    if contributors_total is None:
        contributors_total = ((repo.get("mentionableUsers") or {}).get("totalCount"))
    ci_rate = fetch_ci_stats(client, full_name, now)

    return build_metrics(repo, commits, counts, contributors_total, ci_rate, now)


def build_metrics(repo: dict, commits: List[dict], counts: Dict[str, int],
                  contributors_total: Optional[int], ci_rate: Optional[float], now: datetime) -> dict:
    """Pure transformation from raw API payloads to the metrics dict."""
    full_name = repo["nameWithOwner"]
    created = parse_dt(repo.get("createdAt"))
    target = ((repo.get("defaultBranchRef") or {}).get("target") or {})
    last_commit = parse_dt(target.get("committedDate"))

    # ---- commits & people -------------------------------------------------
    cutoff90 = now - timedelta(days=config.WINDOW_DAYS)
    counts_180: Counter = Counter()
    counts_90: Counter = Counter()
    authors_prior: set = set()
    for c in commits:
        key = author_key(c.get("author"))
        dt = parse_dt(c.get("committedDate"))
        if not key or not dt:
            continue
        counts_180[key] += 1
        if dt >= cutoff90:
            counts_90[key] += 1
        else:
            authors_prior.add(key)
    history_total_180 = int((target.get("history") or {}).get("totalCount") or 0)
    commits_90d = int((target.get("recent90") or {}).get("totalCount") or 0)
    sample_truncated = history_total_180 > len(commits)

    active_contributors_90d = len(counts_90)
    active_maintainers_180d = sum(1 for _, n in counts_180.items() if n >= 3)
    total_180 = sum(counts_180.values())
    top_share = (counts_180.most_common(1)[0][1] / float(total_180)) if total_180 else 0.0
    current_authors = set(counts_90)
    retention = (len(current_authors & authors_prior) / float(len(current_authors))) if current_authors else None

    # ---- releases ---------------------------------------------------------
    releases = _release_list(repo)
    release_dates = [d for _, d in releases]
    cutoff365 = now - timedelta(days=config.RELEASE_WINDOW_DAYS)
    releases_12m = sum(1 for d in release_dates if d >= cutoff365)
    total_releases = int((repo.get("releases") or {}).get("totalCount") or 0) or int((repo.get("tags") or {}).get("totalCount") or 0)
    if len(releases) == 30 and releases_12m == 30 and total_releases > 30:
        releases_12m = total_releases  # all of the sample is recent; lower bound is the full count
    last_release = release_dates[0] if release_dates else None
    semver = bool(releases) and sum(1 for t, _ in releases[:10] if SEMVER_RE.match(t)) >= max(1, min(10, len(releases)) * 0.6)
    majors = [_major(t) for t, d in releases if d >= cutoff365]
    majors = [x for x in majors if x is not None]
    major_bumps = sum(1 for i in range(len(majors) - 1) if majors[i] > majors[i + 1])

    # ---- files & docs -----------------------------------------------------
    root_dirs, root_files = _entry_names(repo.get("root"))
    gh_dirs, gh_files = _entry_names(repo.get("dotgithub"))
    wf_dirs, wf_files = _entry_names(repo.get("workflows"))
    readme = _readme_text(repo).lower()
    has_readme = bool(readme) or any(f.startswith("readme") for f in root_files)
    has_docs_dir = bool(root_dirs & DOC_DIRS) or bool(repo.get("docsDir"))
    homepage = (repo.get("homepageUrl") or "").strip()
    has_install = any(k in readme for k in ("pip install", "npm install", "npm i ", "yarn add", "cargo add",
                                             "cargo install", "go get", "go install", "brew install", "docker run",
                                             "docker pull", "conda install", "## install", "# install",
                                             "installation", "getting started", "quick start", "quickstart"))
    has_examples = bool(root_dirs & EXAMPLE_DIRS) or any(k in readme for k in ("## example", "## usage", "# usage", "## quick", "```"))
    has_api_docs = has_docs_dir or bool(homepage) or any(k in readme for k in ("api reference", "readthedocs", "documentation"))
    has_troubleshooting = any(k in readme for k in ("troubleshoot", "faq", "known issues", "common issues", "common problems")) \
        or "support.md" in root_files or "support.md" in gh_files
    has_changelog = any(CHANGELOG_RE.match(f) for f in root_files) or any(CHANGELOG_RE.match(f) for f in root_dirs)
    has_tests = bool(root_dirs & TEST_DIRS) or bool(root_files & TEST_FILES)
    has_ci = bool(wf_files) or bool(root_files & CI_FILES) or bool(root_dirs & {".circleci", ".buildkite"})

    issue_templates = list(repo.get("issueTemplates") or [])
    has_issue_templates = bool(issue_templates) or "issue_template" in gh_dirs or "issue_template.md" in gh_files

    owner = repo.get("owner") or {}
    owner_is_org = owner.get("__typename") == "Organization"
    has_sponsorship = bool(repo.get("fundingLinks")) or bool(owner.get("hasSponsorsListing")) \
        or "funding.yml" in gh_files
    license_info = repo.get("licenseInfo") or {}

    # ---- popularity -------------------------------------------------------
    star_dates = [parse_dt(e.get("starredAt")) for e in (repo.get("stargazers") or {}).get("edges") or []]
    star_dates = [d for d in star_dates if d]
    stars_90d, stars_est = _growth_in_window(star_dates, now, config.WINDOW_DAYS)
    fork_dates = [parse_dt(n.get("createdAt")) for n in (repo.get("forks") or {}).get("nodes") or []]
    fork_dates = [d for d in fork_dates if d]
    forks_90d, forks_est = _growth_in_window(fork_dates, now, config.WINDOW_DAYS)

    recent_issues = (repo.get("recentIssues") or {}).get("nodes") or []
    recent_prs = (repo.get("recentPRs") or {}).get("nodes") or []
    maintainers = {k[1:] for k in counts_180 if k.startswith("@")}
    sample = [((i.get("author") or {}).get("login") or "").lower() for i in recent_issues + recent_prs]
    sample = [s for s in sample if s and not _is_bot(s)]
    external_fraction = (sum(1 for s in sample if s not in maintainers) / float(len(sample))) if sample else 0.5
    external_engagement = int(round((counts["issuesOpened"] + counts["prsOpened"]) * external_fraction))

    topics = [t["topic"]["name"] for t in (repo.get("repositoryTopics") or {}).get("nodes") or []]

    return {
        # identity
        "full_name": full_name,
        "name": repo.get("name"),
        "owner": owner.get("login"),
        "description": (repo.get("description") or "")[:300],
        "url": repo.get("url"),
        "homepage": homepage,
        "language": (repo.get("primaryLanguage") or {}).get("name"),
        "topics": topics[:15],
        "category": categorize(topics, repo.get("description") or "", full_name),
        "license": license_info.get("spdxId"),
        "created_at": repo.get("createdAt"),
        "collected_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        # maturity inputs
        "age_months": days_since(created, now) / 30.44 if created else 0.0,
        "releases_12m": releases_12m,
        "days_since_release": days_since(last_release, now),
        "has_readme": has_readme, "has_install_docs": has_install, "has_examples": has_examples,
        "has_api_docs": has_api_docs, "has_troubleshooting": has_troubleshooting,
        "has_license": bool(license_info.get("spdxId")) and license_info.get("spdxId") != "NOASSERTION",
        "has_contributing": bool(repo.get("contributingGuidelines")) or "contributing.md" in root_files or "contributing.md" in gh_files,
        "has_code_of_conduct": bool(repo.get("codeOfConduct")) or "code_of_conduct.md" in root_files or "code_of_conduct.md" in gh_files,
        "has_security_policy": bool(repo.get("isSecurityPolicyEnabled")) or "security.md" in root_files or "security.md" in gh_files,
        "has_issue_templates": has_issue_templates,
        "has_ci": has_ci, "has_tests": has_tests, "ci_success_rate": ci_rate,
        "active_maintainers_180d": active_maintainers_180d,
        "uses_semver": semver, "has_changelog": has_changelog,
        "release_cadence_consistency": _cadence_consistency(release_dates[:12]),
        "breaking_changes_12m": counts["breaking"] + major_bumps,
        # health inputs
        "commits_90d": commits_90d,
        "days_since_commit": days_since(last_commit, now),
        "median_issue_response_hours": _median_response_hours(recent_issues, now, "issue"),
        "median_pr_response_hours": _median_response_hours(recent_prs, now, "pr"),
        "issues_opened_90d": counts["issuesOpened"], "issues_closed_90d": counts["issuesClosed"],
        "prs_opened_90d": counts["prsOpened"], "prs_merged_90d": counts["prsMerged"],
        "prs_closed_90d": counts["prsClosed"],
        "open_issues": int((repo.get("openIssues") or {}).get("totalCount") or 0),
        "open_prs": int((repo.get("openPRs") or {}).get("totalCount") or 0),
        "active_contributors_90d": active_contributors_90d,
        # popularity inputs
        "stars": int(repo.get("stargazerCount") or 0),
        "stars_90d": stars_90d, "stars_90d_estimated": stars_est,
        "forks": int(repo.get("forkCount") or 0),
        "forks_90d": forks_90d, "forks_90d_estimated": forks_est,
        "watchers": int((repo.get("watchers") or {}).get("totalCount") or 0),
        "contributors_total": contributors_total,
        "external_engagement_90d": external_engagement,
        # risk / sustainability inputs
        "bus_factor": _bus_factor(counts_180),
        "top_contributor_share": top_share,
        "stale_open_issues": counts["staleIssues"],
        "owner_is_org": owner_is_org,
        "is_archived": bool(repo.get("isArchived")),
        "has_sponsorship": has_sponsorship,
        "contributor_retention": retention,
        "commit_sample_truncated": sample_truncated,
        "commit_sample_size": len(commits),
    }
