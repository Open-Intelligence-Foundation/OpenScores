"""Collect the raw metrics for one repository.

The output is a flat dict of metric values consumed by ``scoring.py``. Every
metric is derived from public GitHub data; where the API only gives us a
sample (recent commits, recent issues, recent stargazers) the derivation is
documented inline and the metric is marked as estimated where relevant.
"""
from __future__ import annotations

import html
import logging
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlsplit

import requests

from . import config
from .discover import categorize
from .github import GitHubClient, GitHubError, describe_errors
from .queries import (COUNTS, MORE_HISTORY, PRIOR_HISTORY, REMOVABLE_CORE_FIELDS, REPO_EXTRAS,
                      REPO_SPONSORS, build_repo_core, selection_at_line)

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


# ------------------------------------------------------------------ project image
# A project's picture on the board, found in this order: the owner's GitHub
# avatar (the picture at the top of every repository page), a logo file or the
# README's logo in the repository, the website's icon.  Every candidate is
# fetched once to make sure it is really an image; a project with none stays
# without a picture.

IMAGE_EXTS = (".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".ico")
LOGO_FILE_RE = re.compile(r"^(logo|icon|favicon)[^/]*\.(png|svg|jpe?g|webp)$", re.I)
LOGO_WORD_RE = re.compile(r"logo|icon", re.I)
DARK_VARIANT_RE = re.compile(r"white|dark", re.I)        # a glyph drawn for dark backgrounds
README_HEAD_RE = re.compile(r"\n\s{0,3}#{2,6}\s|<h2\b", re.I)   # the first second-level heading
README_IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^\s)>]+)>?[^)]*\)|<img\b[^>]*>", re.I)
IMG_ATTR_RE = re.compile(r"""\b(src|alt)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.I)
TAG_ATTR_RE = re.compile(r"""\b(rel|href|sizes)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
BADGE_MARKERS = ("shields.io", "badge", "badgen.net", "codecov.io", "coveralls.io", "circleci.com", "travis-ci",
                 "pepy.tech", "pypistats", "colab.research.google.com", "/actions/workflows/", "readthedocs.org/projects",
                 "star-history", "contrib.rocks", "repobeats", "snyk.io", "codeclimate", "deepwiki", "discord.com/api",
                 "img.youtube", "trendshift.io", "producthunt", "sourcegraph", "gitpod.io", "codespaces.new")
GENERIC_SITE_HOSTS = ("github.com", "www.github.com", "pypi.org", "huggingface.co", "arxiv.org", "discord.gg",
                      "discord.com", "twitter.com", "x.com", "youtube.com", "www.youtube.com", "medium.com",
                      "colab.research.google.com", "npmjs.com", "www.npmjs.com", "crates.io", "t.me", "linkedin.com")
IMAGE_HEADERS = {"User-Agent": "OpenScores collector (+https://openscores.io)", "Accept": "image/*,text/html;q=0.9,*/*;q=0.5"}
IMAGE_TIMEOUT = 8
INLINE_ICON_MAX = 8_192      # an icon declared as a data: URI is kept as is, up to this many characters
_image_session = requests.Session()


def _http_get(url: str, stream: bool = False) -> Optional[requests.Response]:
    """A plain GET of a public URL; None on any failure.  Tests stub this."""
    if urlsplit(url).scheme not in ("http", "https"):
        return None
    try:
        resp = _image_session.get(url, headers=IMAGE_HEADERS, timeout=IMAGE_TIMEOUT, stream=stream, allow_redirects=True)
    except (requests.RequestException, ValueError):
        return None
    return resp if resp.status_code == 200 else None


def _url_is_image(url: str) -> bool:
    resp = _http_get(url, stream=True)
    if resp is None:
        return False
    try:
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype.startswith("image/"):
            return True
        # some hosts serve a real picture as octet-stream; trust the extension then
        path = urlsplit(resp.url or url).path.lower()
        return ctype in ("application/octet-stream", "") and path.endswith(IMAGE_EXTS)
    finally:
        resp.close()


def _fetch_text(url: str, limit: int = 300_000) -> str:
    resp = _http_get(url, stream=True)
    if resp is None:
        return ""
    try:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "xml" not in ctype and ctype:
            return ""
        chunks, size = [], 0
        for chunk in resp.iter_content(chunk_size=65536):
            chunks.append(chunk)
            size += len(chunk)
            if size >= limit:
                break
        return b"".join(chunks).decode("utf-8", "replace")
    except (requests.RequestException, ValueError):
        return ""
    finally:
        resp.close()


def _attrs(tag: str, pattern) -> Dict[str, str]:
    out = {}
    for m in pattern.finditer(tag):
        out[m.group(1).lower()] = html.unescape(m.group(3) if m.group(3) is not None
                                                else m.group(4) if m.group(4) is not None else m.group(5) or "")
    return out


def _raw_github_url(full_name: str, src: str) -> Optional[str]:
    """A README image reference as a fetchable URL: relative paths and
    github.com blob links become raw.githubusercontent.com links."""
    src = html.unescape(src.strip()).split("#")[0]
    if not src or src.startswith("data:"):
        return None
    parts = urlsplit(src)
    if parts.scheme in ("http", "https"):
        host = parts.netloc.lower()
        if host in ("github.com", "www.github.com"):
            m = re.match(r"^/([^/]+)/([^/]+)/(?:blob|raw)/([^/]+)/(.+)$", parts.path)
            if m:
                return "https://raw.githubusercontent.com/%s/%s/%s/%s" % m.groups()
            return "https://github.com" + parts.path if "/assets/" in parts.path else None
        return src
    if parts.scheme:
        return None
    path = re.sub(r"^(\./)+", "", parts.path).lstrip("/")
    if not path or ".." in path.split("/"):
        return None
    return "https://raw.githubusercontent.com/%s/HEAD/%s" % (full_name, quote(path, safe="/%:@+,"))


def _is_badge(src: str, alt: str) -> bool:
    low = src.lower()
    return any(marker in low for marker in BADGE_MARKERS) or "badge" in alt.lower()


def readme_images(text: str) -> List[Tuple[str, str]]:
    """(src, alt) of every image in a README, markdown and HTML alike, in order."""
    out = []
    for m in README_IMG_RE.finditer(text or ""):
        if m.group(0).lower().startswith("<img"):
            a = _attrs(m.group(0), IMG_ATTR_RE)
            if a.get("src"):
                out.append((a["src"], a.get("alt", "")))
        else:
            out.append((m.group(2), m.group(1) or ""))
    return out


def image_candidates(repo: dict) -> List[Tuple[str, str]]:
    """Possible pictures for a repository, best first, as (url, source).
    Sources are "org" (the GitHub organisation's avatar), "user" (a personal
    account's avatar) and "repo" (a logo in the repository); the website is
    tried separately, last."""
    full_name = repo.get("nameWithOwner") or ""
    found: List[Tuple[str, str]] = []
    seen = set()

    def add(url: Optional[str], source: str) -> None:
        if url and url not in seen:
            seen.add(url)
            found.append((url, source))

    # The avatar shown at the top of the repository page on GitHub: the
    # picture people associate with the project, and present for every owner.
    owner = repo.get("owner") or {}
    if owner.get("avatarUrl") and owner.get("__typename") in ("Organization", "User"):
        add(owner["avatarUrl"], "org" if owner["__typename"] == "Organization" else "user")

    # Then a logo file in the repository, then the README's logo.  The
    # project's own logo sits at the top of the README, before the first
    # second-level heading; logos named after the project count anywhere.
    # Further down, "logo" images are usually other products' (providers,
    # browsers, sponsors).  A variant drawn for dark backgrounds would vanish
    # on the board's light tile, so it ranks last.
    plain, dark = [], []
    for key, prefix in (("root", ""), ("dotgithub", ".github/"), ("docsDir", "docs/")):
        for e in (repo.get(key) or {}).get("entries") or []:
            if e.get("type") == "blob" and LOGO_FILE_RE.match(e.get("name") or ""):
                url = "https://raw.githubusercontent.com/%s/HEAD/%s%s" % (full_name, prefix, quote(e["name"]))
                (dark if DARK_VARIANT_RE.search(e["name"]) else plain).append(url)
    readme = _readme_text(repo)
    head_len = len(README_HEAD_RE.split(readme, 1)[0])
    names = [n.lower() for n in full_name.split("/") if len(n) >= 3]
    for m in README_IMG_RE.finditer(readme):
        if m.group(0).lower().startswith("<img"):
            a = _attrs(m.group(0), IMG_ATTR_RE)
            src, alt = a.get("src", ""), a.get("alt", "")
        else:
            src, alt = m.group(2), m.group(1) or ""
        if not src or _is_badge(src, alt):
            continue
        filename = urlsplit(src).path.rsplit("/", 1)[-1]
        if not (LOGO_WORD_RE.search(filename) or LOGO_WORD_RE.search(alt)):
            continue
        named = any(n in filename.lower() for n in names)
        if m.start() > head_len and not named:
            continue
        (dark if DARK_VARIANT_RE.search(filename) else plain).append(_raw_github_url(full_name, src))
    for url in plain + dark:
        add(url, "repo")
    return found


def site_icon(homepage: str, fetch_text: Callable[[str], str] = _fetch_text,
              probe: Callable[[str], bool] = _url_is_image) -> Optional[str]:
    """The website's icon: the largest <link rel=icon> it declares, else
    /favicon.ico.  An icon embedded in the page as a small data: URI is
    returned as it is."""
    parts = urlsplit((homepage or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower()
    if host in GENERIC_SITE_HOSTS or host.endswith((".github.com", ".pypi.org")):
        return None
    page = fetch_text(homepage)
    ranked: List[Tuple[int, str]] = []
    for tag in LINK_TAG_RE.findall(page):
        a = _attrs(tag, TAG_ATTR_RE)
        rel = (a.get("rel") or "").lower().split()
        if not a.get("href") or not any(r in ("icon", "apple-touch-icon", "apple-touch-icon-precomposed", "shortcut") for r in rel):
            continue
        size = 180 if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel else 0
        m = re.match(r"(\d+)x(\d+)", (a.get("sizes") or "").lower())
        if m:
            size = max(size, int(m.group(1)))
        href = a["href"].strip()
        if href.lower().startswith("data:"):
            if href.lower().startswith("data:image/") and len(href) <= INLINE_ICON_MAX:
                ranked.append((size or 256, href))
            continue
        if href.lower().endswith(".svg"):
            size = max(size, 512)
        ranked.append((size, urljoin(homepage, href)))
    for _, url in sorted(ranked, key=lambda r: -r[0]):
        if url.startswith("data:") or probe(url):
            return url
    fallback = "%s://%s/favicon.ico" % (parts.scheme, parts.netloc)
    return fallback if probe(fallback) else None


def resolve_project_image(repo: dict, homepage: str, probe: Callable[[str], bool] = _url_is_image,
                          fetch_text: Callable[[str], str] = _fetch_text) -> Tuple[Optional[str], Optional[str]]:
    """(url, source) of the project's picture, or (None, None) when none is found."""
    for url, source in image_candidates(repo):
        if probe(url):
            return url, source
    icon = site_icon(homepage, fetch_text=fetch_text, probe=probe)
    if icon:
        return icon, "website"
    return None, None


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse GitHub timestamps to aware UTC datetimes.

    Most API fields are ISO-8601 in UTC with a trailing Z, but git dates (tag
    taggers, commit authors) keep their original offset, e.g.
    2025-02-03T14:29:39+08:00, and some carry fractional seconds.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    elif len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]  # +0800 -> +08:00 (python 3.8 fromisoformat)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        log.debug("unparseable timestamp %r", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def days_since(value: Optional[datetime], now: datetime) -> Optional[float]:
    if value is None:
        return None
    return max(0.0, (now - value).total_seconds() / 86400.0)


def _is_bot(login: Optional[str]) -> bool:
    if not login:
        return False
    low = login.lower()
    return low in config.BOT_LOGINS or low.endswith("[bot]") or low.endswith("-bot")


def _is_bot_actor(actor: Optional[dict]) -> bool:
    """An issue, PR, comment or review author node.  GitHub Apps come back as
    the `Bot` type (hence `__typename` in the queries); the rest is the login
    list, which also catches automations running as ordinary user accounts."""
    if not actor:
        return False
    return actor.get("__typename") == "Bot" or _is_bot(actor.get("login"))


# Logins that name an automation without GitHub's [bot] suffix: assistant,
# bot, automation or ci as a whole word (acme-ci, ci_runner, bot-helper) or,
# for the three longer words, as a bare suffix (ultralyticsassistant).  "ci"
# is not a suffix because two letters end too many ordinary names (Marci,
# Ricci, Vinci).
_AUTOMATION_WORD = re.compile(r"(?:^|[^a-z0-9])(?:assistant|bot|automation|ci)(?:[^a-z0-9]|$)")
_AUTOMATION_SUFFIX = re.compile(r"(?:assistant|bot|automation)$")

# A login that answers within this many seconds of the item being opened, in
# at least this many of the sampled items, is an auto-responder whatever its
# account type (UltralyticsAssistant answers in 20 seconds from a user account).
FAST_RESPONDER_SECONDS = 60
FAST_RESPONDER_MIN_ITEMS = 3


def _looks_automated(login: str) -> bool:
    low = login.lower()
    return bool(_AUTOMATION_WORD.search(low) or _AUTOMATION_SUFFIX.search(low))


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

    A response is the first comment/review by someone other than the author,
    or the close/merge event. Items younger than 7 days with no response are
    ignored (not yet observable); older unanswered items count as their
    current age, so silence is penalised.

    Bots are not responses: GitHub Apps (`Bot` actors), listed bot logins,
    logins that name an automation (see _looks_automated), and, per
    repository, any login whose median delay as first responder is under
    FAST_RESPONDER_SECONDS across at least FAST_RESPONDER_MIN_ITEMS items.
    The next human comment is used instead, which is why the queries fetch
    three comments per item.
    """
    created_at: Dict[int, datetime] = {}
    replies: Dict[int, List[Tuple[datetime, str]]] = {}
    first_delays: Dict[str, List[float]] = {}
    for i, item in enumerate(items):
        created = parse_dt(item.get("createdAt"))
        if not created:
            continue
        author = ((item.get("author") or {}).get("login") or "").lower()
        responders = list((item.get("comments") or {}).get("nodes") or [])
        if kind == "pr":
            responders += list((item.get("reviews") or {}).get("nodes") or [])
        found: List[Tuple[datetime, str]] = []
        for c in responders:
            actor = c.get("author") or {}
            login = (actor.get("login") or "").lower()
            dt = parse_dt(c.get("createdAt"))
            if not login or not dt or login == author:
                continue
            if _is_bot_actor(actor) or _looks_automated(login):
                continue
            found.append((dt, login))
        found.sort()
        created_at[i] = created
        replies[i] = found
        if found:
            first_dt, first_login = found[0]
            first_delays.setdefault(first_login, []).append((first_dt - created).total_seconds())

    fast_responders = {
        login for login, delays in first_delays.items()
        if len(delays) >= FAST_RESPONDER_MIN_ITEMS and statistics.median(delays) < FAST_RESPONDER_SECONDS
    }

    hours: List[float] = []
    for i, created in created_at.items():
        item = items[i]
        candidates = [dt for dt, login in replies[i] if login not in fast_responders]
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


def _history_total(repo: dict) -> int:
    target = ((repo.get("defaultBranchRef") or {}).get("target") or {})
    return int((target.get("history") or {}).get("totalCount") or 0)


def prior_window_unsampled(repo: dict, commits: List[dict], cutoff90: datetime) -> bool:
    """True when the commit sample stops short of the 180-day window and every
    sampled commit is newer than ``cutoff90``: the sample then says nothing
    about who was active in the 90 days before, and contributor retention
    cannot be derived from it (very active projects exhaust the sample inside
    the current window)."""
    if _history_total(repo) <= len(commits):
        return False
    for c in commits:
        dt = parse_dt(c.get("committedDate"))
        if dt and dt < cutoff90:
            return False
    return True


def fetch_prior_window(client: GitHubClient, owner: str, name: str, since180: str, since90: str
                       ) -> Optional[List[dict]]:
    """The newest commits between 180 and 90 days ago, or None when they could
    not be fetched (the caller then leaves retention unknown)."""
    try:
        data = client.graphql(PRIOR_HISTORY, {"owner": owner, "name": name,
                                              "since180": since180, "since90": since90})
    except GitHubError as exc:
        log.warning("prior commit window unavailable for %s/%s: %s", owner, name, exc)
        return None
    target = (((data.get("repository") or {}).get("defaultBranchRef") or {}).get("target"))
    if target is None:
        return None
    return list(((target.get("history") or {}).get("nodes")) or [])


def fetch_counts(client: GitHubClient, full_name: str, now: datetime) -> Dict[str, int]:
    d90 = (now - timedelta(days=config.WINDOW_DAYS)).strftime("%Y-%m-%d")
    d180 = (now - timedelta(days=config.STALE_ISSUE_DAYS)).strftime("%Y-%m-%d")
    d365 = (now - timedelta(days=config.RELEASE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    base = "repo:%s " % full_name
    # Pull requests opened by well-known automation apps are left out of the
    # PR activity counts (opened, merged and closed together, so the merge
    # rate stays a ratio of like with like).  GitHub search can exclude a
    # GitHub App by `-author:app/<slug>`, and nothing more general: an
    # automation that runs as an ordinary user account, or an app we do not
    # name in config.BOT_APP_SLUGS, still counts here.
    human_prs = " " + " ".join("-author:app/%s" % slug for slug in config.BOT_APP_SLUGS)
    variables = {
        "issuesOpened": base + "is:issue created:>=%s" % d90,
        "issuesClosed": base + "is:issue is:closed closed:>=%s" % d90,
        "prsOpened": base + "is:pr created:>=%s" % d90 + human_prs,
        "prsMerged": base + "is:pr is:merged merged:>=%s" % d90 + human_prs,
        "prsClosed": base + "is:pr is:closed closed:>=%s" % d90 + human_prs,
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


FORBIDDEN_TYPES = ("FORBIDDEN", "INSUFFICIENT_SCOPES")


class RepositoryForbidden(GitHubError):
    """The token may not read the repository at all (an organization token
    policy or SAML enforcement), as opposed to a missing repository or a
    single refused field. The caller may retry with a different token."""

    def __init__(self, full_name: str, errors: List[dict]):
        super().__init__("%s: this token is not allowed to read the repository%s"
                         % (full_name, describe_errors(errors, limit=1)))
        self.full_name = full_name
        self.errors = errors


def repository_denied(errors: List[dict]) -> bool:
    """True when GitHub refused the repository itself, not just a field of it."""
    for err in errors:
        path = err.get("path") or []
        if err.get("type") in FORBIDDEN_TYPES and (not path or list(path) == ["repository"]):
            return True
    return False
STAR_JSON = {"Accept": "application/vnd.github.star+json"}


def fetch_core(client: GitHubClient, variables: dict) -> Tuple[Optional[dict], List[dict]]:
    """Run the repository query, dropping any top-level field the token is not
    allowed to read and retrying.  Dropped fields stay dropped for the whole run
    (fine-grained personal access tokens are refused e.g. the stargazer timeline)."""
    errors: List[dict] = []
    for _ in range(len(REMOVABLE_CORE_FIELDS) + 1):
        excluded = client.disabled_fields("repository")
        document = build_repo_core(excluded)
        data, errors = client.graphql_full(document, variables)
        repo = data.get("repository")
        if repo:
            return repo, errors
        dropped = False
        for err in errors:
            field = refused_selection(err, document)
            if field in REMOVABLE_CORE_FIELDS and field not in excluded:
                client.disable_field("repository", field, describe_errors([err], limit=1))
                dropped = True
        if not dropped:
            break
    return None, errors


def refused_selection(err: dict, document: str) -> Optional[str]:
    """The top-level repository selection a FORBIDDEN / INSUFFICIENT_SCOPES
    error refers to.  FORBIDDEN errors name it in their path; INSUFFICIENT_SCOPES
    errors (a classic token lacking a scope) carry only a source location."""
    if err.get("type") not in FORBIDDEN_TYPES:
        return None
    path = err.get("path") or []
    if path:
        return path[1] if len(path) > 1 and path[0] == "repository" else None
    for loc in err.get("locations") or []:
        field = selection_at_line(document, int(loc.get("line") or 0))
        if field:
            return field
    return None


def _last_page(link_header: str) -> int:
    m = re.search(r'[?&]page=(\d+)>; rel="last"', link_header or "")
    return int(m.group(1)) if m else 1


def fetch_recent_stars_rest(client: GitHubClient, full_name: str) -> Optional[List[str]]:
    """starred_at of the most recent ~100-200 stargazers.  The REST list is
    oldest-first, so read the last page (and the one before it when short)."""
    path = "/repos/%s/stargazers" % full_name
    first = client.rest(path, {"per_page": 100}, headers=STAR_JSON)
    if first is None:
        return None
    last = _last_page(first.headers.get("Link", ""))
    if last <= 1:
        entries = first.json()
    else:
        tail = client.rest(path, {"per_page": 100, "page": last}, headers=STAR_JSON)
        entries = list(tail.json()) if tail is not None else []
        if len(entries) < 100:
            if last == 2:
                prev = first.json()
            else:
                resp = client.rest(path, {"per_page": 100, "page": last - 1}, headers=STAR_JSON)
                prev = resp.json() if resp is not None else []
            entries = list(prev) + entries
    dates = [e.get("starred_at") for e in entries if isinstance(e, dict) and e.get("starred_at")]
    if entries and not dates:
        return None  # the star+json media type was not honoured
    return dates


def stars_in_window(weeks: List[dict], now: datetime, window_days: int) -> Optional[int]:
    """Stars gained in the last ``window_days`` days from the star history
    endpoint's weekly rows (``week`` epoch of the Sunday, ``days`` Sunday first)."""
    if not isinstance(weeks, list):
        return None
    cutoff = (now - timedelta(days=window_days)).date()
    today = now.date()
    total, seen = 0, False
    for row in weeks:
        if not isinstance(row, dict) or not isinstance(row.get("days"), list):
            continue
        try:
            start = datetime.fromtimestamp(int(row["week"]), timezone.utc).date()
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        seen = True
        for i, n in enumerate(row["days"]):
            day = start + timedelta(days=i)
            if cutoff <= day <= today:
                total += int(n or 0)
    return total if seen else None


def fetch_star_history_rest(client: GitHubClient, full_name: str, now: datetime,
                            window_days: Optional[int] = None) -> Optional[int]:
    """Exact stars gained in the window, from GitHub's star history endpoint
    (weekly rows with daily counts, newest first, back to the repository's
    creation).  One page of 30 weeks covers 210 days; more are read only when
    the window is longer.  None when the endpoint is unavailable."""
    window = config.WINDOW_DAYS if window_days is None else window_days
    path = "/repos/%s/stargazers/history" % full_name
    cutoff = (now - timedelta(days=window)).date()
    rows: List[dict] = []
    for page in range(1, 6):
        resp = client.rest(path, {"per_page": 30, "page": page})
        if resp is None:
            return None if not rows else stars_in_window(rows, now, window)
        try:
            body = resp.json()
        except ValueError:
            return None
        if not isinstance(body, list):
            return None
        rows.extend(r for r in body if isinstance(r, dict))
        if not body or 'rel="next"' not in (resp.headers.get("Link") or ""):
            break
        oldest = min((r.get("week") or 0) for r in body if isinstance(r, dict))
        if datetime.fromtimestamp(int(oldest), timezone.utc).date() < cutoff:
            break
    return stars_in_window(rows, now, window)


def fetch_recent_forks_rest(client: GitHubClient, full_name: str) -> Optional[List[str]]:
    data = client.rest_json("/repos/%s/forks" % full_name, {"sort": "newest", "per_page": 100})
    if data is None:
        return None
    return [f.get("created_at") for f in data if isinstance(f, dict) and f.get("created_at")]


def fetch_optional(client: GitHubClient, key: str, query: str, variables: dict) -> dict:
    """Run a query whose fields some tokens cannot read.  Returns the repository
    dict, or {} when it is unavailable; after a FORBIDDEN answer the query is
    skipped for the rest of the run instead of failing every repository."""
    if client.query_disabled(key):
        return {}
    try:
        data, errors = client.graphql_full(query, variables)
    except GitHubError as exc:
        log.debug("optional '%s' query failed for %s: %s", key, variables.get("name"), exc)
        return {}
    repo = data.get("repository")
    if repo:
        return repo
    if {e.get("type") for e in errors} & {"FORBIDDEN", "INSUFFICIENT_SCOPES"}:
        client.disable_query(key, describe_errors(errors, limit=1))
    return {}


def collect_repo(client: GitHubClient, full_name: str, now: Optional[datetime] = None) -> Optional[dict]:
    """Fetch everything for one repo. Returns None if the repo is missing."""
    now = now or utcnow()
    owner, name = full_name.split("/", 1)
    since180 = (now - timedelta(days=config.MAINTAINER_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    since90 = (now - timedelta(days=config.WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    repo, errors = fetch_core(client, {"owner": owner, "name": name, "since180": since180, "since90": since90})
    if not repo:
        if repository_denied(errors):
            raise RepositoryForbidden(full_name, errors)
        log.warning("Repository %s not found or inaccessible%s", full_name, describe_errors(errors))
        return None
    full_name = repo["nameWithOwner"]  # canonical casing / renames

    # GitHub's star history endpoint gives exact daily star counts back to the
    # repository's creation; the sampled stargazer timeline, which GitHub no
    # longer serves to most tokens, is only a fallback.
    repo["starsInWindow"] = fetch_star_history_rest(client, full_name, now)

    # Fields dropped from the GraphQL query because the token may not read them
    # are backfilled over REST where an equivalent exists.
    if "stargazers" not in repo and repo["starsInWindow"] is None:
        dates = fetch_recent_stars_rest(client, full_name)
        if dates is not None:
            repo["stargazers"] = {"edges": [{"starredAt": d} for d in dates]}
    if "forks" not in repo:
        dates = fetch_recent_forks_rest(client, full_name)
        if dates is not None:
            repo["forks"] = {"nodes": [{"createdAt": d} for d in dates]}

    # Optional fields the token may not be allowed to read live in their own queries.
    extras = fetch_optional(client, "funding links", REPO_EXTRAS, {"owner": owner, "name": name})
    repo["fundingLinks"] = extras.get("fundingLinks") or []
    repo["mentionableUsers"] = extras.get("mentionableUsers")
    sponsors = fetch_optional(client, "sponsors listing", REPO_SPONSORS, {"owner": owner, "name": name})
    repo.setdefault("owner", {}).update(sponsors.get("owner") or {})

    commits = fetch_commit_sample(client, owner, name, repo, since180)
    prior_commits = None
    if prior_window_unsampled(repo, commits, now - timedelta(days=config.WINDOW_DAYS)):
        prior_commits = fetch_prior_window(client, owner, name, since180, since90)
    counts = fetch_counts(client, full_name, now)
    contributors_total = fetch_contributor_count(client, full_name)
    if contributors_total is None:
        contributors_total = ((repo.get("mentionableUsers") or {}).get("totalCount"))
    ci_rate = fetch_ci_stats(client, full_name, now)

    metrics = build_metrics(repo, commits, counts, contributors_total, ci_rate, now, prior_commits=prior_commits)
    metrics["image"], metrics["image_source"] = resolve_project_image(repo, metrics["homepage"])
    metrics["image_rules"] = config.IMAGE_RULES_VERSION
    return metrics


def build_metrics(repo: dict, commits: List[dict], counts: Dict[str, int],
                  contributors_total: Optional[int], ci_rate: Optional[float], now: datetime,
                  prior_commits: Optional[List[dict]] = None) -> dict:
    """Pure transformation from raw API payloads to the metrics dict.

    ``prior_commits`` are commits from the 90 days before the current window,
    fetched separately when the sample did not reach that far (see
    ``prior_window_unsampled``); an empty list means the window was fetched
    and held nothing, None that it was not fetched."""
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
    for c in prior_commits or []:
        key = author_key(c.get("author"))
        dt = parse_dt(c.get("committedDate"))
        if key and dt and dt < cutoff90:
            authors_prior.add(key)
    history_total_180 = _history_total(repo)
    commits_90d = int((target.get("recent90") or {}).get("totalCount") or 0)
    sample_truncated = history_total_180 > len(commits)
    prior_known = prior_commits is not None or not prior_window_unsampled(repo, commits, cutoff90)

    active_contributors_90d = len(counts_90)
    active_maintainers_180d = sum(1 for _, n in counts_180.items() if n >= 3)
    total_180 = sum(counts_180.values())
    top_share = (counts_180.most_common(1)[0][1] / float(total_180)) if total_180 else 0.0
    current_authors = set(counts_90)
    # Share of the current window's authors who were also active in the 90
    # days before.  Unknown (None) when the sample never reached the prior
    # window and it could not be fetched; scoring treats that as neutral.
    # Nobody active now means nobody was retained, not an unknown.
    if not current_authors:
        retention: Optional[float] = 0.0
    elif not prior_known:
        retention = None
    else:
        retention = len(current_authors & authors_prior) / float(len(current_authors))

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

    # Templates are read from the file tree: .github/ISSUE_TEMPLATE/, a
    # template file in .github, the repository root or docs/ (the GraphQL
    # issueTemplates field needs the classic `repo` scope).
    docs_dirs, docs_files = _entry_names(repo.get("docsDir"))
    has_issue_templates = bool(repo.get("issueTemplates")) \
        or "issue_template" in (gh_dirs | root_dirs | docs_dirs) \
        or any("issue_template" in f for f in gh_files | root_files | docs_files)

    owner = repo.get("owner") or {}
    owner_is_org = owner.get("__typename") == "Organization"
    has_sponsorship = bool(repo.get("fundingLinks")) or bool(owner.get("hasSponsorsListing")) \
        or "funding.yml" in gh_files
    license_info = repo.get("licenseInfo") or {}

    # ---- popularity -------------------------------------------------------
    stars_exact = repo.get("starsInWindow") is not None
    if stars_exact:
        stars_90d, stars_est = int(repo["starsInWindow"]), False
    elif repo.get("stargazers") is None:
        stars_90d, stars_est = None, None  # timeline unavailable to this token
    else:
        star_dates = [parse_dt(e.get("starredAt")) for e in (repo.get("stargazers") or {}).get("edges") or []]
        star_dates = [d for d in star_dates if d]
        stars_90d, stars_est = _growth_in_window(star_dates, now, config.WINDOW_DAYS)
    if repo.get("forks") is None:
        forks_90d, forks_est = None, None
    else:
        fork_dates = [parse_dt(n.get("createdAt")) for n in (repo.get("forks") or {}).get("nodes") or []]
        fork_dates = [d for d in fork_dates if d]
        forks_90d, forks_est = _growth_in_window(fork_dates, now, config.WINDOW_DAYS)

    recent_issues = (repo.get("recentIssues") or {}).get("nodes") or []
    recent_prs = (repo.get("recentPRs") or {}).get("nodes") or []
    maintainers = {k[1:] for k in counts_180 if k.startswith("@")}
    authors = [(i.get("author") or {}) for i in recent_issues + recent_prs]
    sample = [(a.get("login") or "").lower() for a in authors if not _is_bot_actor(a)]
    sample = [s for s in sample if s]
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
        "stars_90d": stars_90d, "stars_90d_estimated": stars_est, "stars_90d_exact": stars_exact,
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
