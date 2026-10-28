from datetime import datetime, timedelta, timezone

from whitescore import collect

NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def commit(days_ago, login=None, email=None, name=None):
    return {"committedDate": iso(NOW - timedelta(days=days_ago)),
            "author": {"user": {"login": login} if login else None, "email": email or "", "name": name or ""}}


def fake_repo():
    commits = [commit(d, "alice") for d in range(0, 60, 2)]           # 30 commits, 0-58 days ago
    commits += [commit(d, "bob") for d in range(1, 120, 10)]         # 12 commits, spans both halves
    commits += [commit(d, "carol") for d in (100, 130, 160)]         # prior window only
    commits += [commit(3, "dependabot[bot]")]                        # ignored
    return {
        "nameWithOwner": "acme/ai-tool", "name": "ai-tool", "description": "An AI tool",
        "url": "https://github.com/acme/ai-tool", "homepageUrl": "https://ai-tool.dev",
        "createdAt": iso(NOW - timedelta(days=365 * 3)), "pushedAt": iso(NOW),
        "isArchived": False, "isFork": False, "isDisabled": False,
        "stargazerCount": 12000, "forkCount": 900, "watchers": {"totalCount": 150},
        "licenseInfo": {"spdxId": "Apache-2.0", "name": "Apache License 2.0", "key": "apache-2.0"},
        "primaryLanguage": {"name": "Python"},
        "repositoryTopics": {"nodes": [{"topic": {"name": "llm-inference"}}, {"topic": {"name": "python"}}]},
        "owner": {"__typename": "Organization", "login": "acme", "hasSponsorsListing": False},
        "fundingLinks": [{"platform": "GITHUB", "url": "https://github.com/sponsors/acme"}],
        "codeOfConduct": {"key": "contributor_covenant", "name": "Contributor Covenant"},
        "contributingGuidelines": {"url": "https://github.com/acme/ai-tool/blob/main/CONTRIBUTING.md"},
        "isSecurityPolicyEnabled": True,
        "issueTemplates": [{"name": "Bug report"}], "pullRequestTemplates": [],
        "hasIssuesEnabled": True, "mentionableUsers": {"totalCount": 80},
        "openIssues": {"totalCount": 40}, "openPRs": {"totalCount": 12},
        "defaultBranchRef": {"name": "main", "target": {
            "committedDate": iso(NOW - timedelta(hours=6)),
            "recent90": {"totalCount": 44},
            "history": {"totalCount": len(commits), "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": commits}}},
        "releases": {"totalCount": 8, "nodes": [
            {"tagName": "v1.%d.0" % (7 - i), "name": "", "createdAt": iso(NOW - timedelta(days=15 + 40 * i)),
             "publishedAt": iso(NOW - timedelta(days=15 + 40 * i)), "isPrerelease": False, "isDraft": False}
            for i in range(8)]},
        "tags": {"totalCount": 8, "nodes": []},
        "recentIssues": {"nodes": [
            {"createdAt": iso(NOW - timedelta(days=10)), "closedAt": None, "author": {"login": "someone"},
             "comments": {"nodes": [{"createdAt": iso(NOW - timedelta(days=10) + timedelta(hours=12)),
                                     "author": {"login": "alice"}}]}},
            {"createdAt": iso(NOW - timedelta(days=20)), "closedAt": iso(NOW - timedelta(days=19)),
             "author": {"login": "other"}, "comments": {"nodes": []}},
            {"createdAt": iso(NOW - timedelta(days=1)), "closedAt": None, "author": {"login": "fresh"},
             "comments": {"nodes": []}},  # too young, ignored
        ]},
        "recentPRs": {"nodes": [
            {"createdAt": iso(NOW - timedelta(days=5)), "mergedAt": iso(NOW - timedelta(days=4)), "closedAt": None,
             "author": {"login": "bob"}, "reviews": {"nodes": [{"createdAt": iso(NOW - timedelta(days=5) + timedelta(hours=6)),
                                                                "author": {"login": "alice"}}]},
             "comments": {"nodes": []}},
        ]},
        "stargazers": {"edges": [{"starredAt": iso(NOW - timedelta(days=d))} for d in range(0, 50)]},
        "forks": {"nodes": [{"createdAt": iso(NOW - timedelta(days=d * 2))} for d in range(0, 100)]},
        "root": {"entries": [{"name": "README.md", "type": "blob"}, {"name": "tests", "type": "tree"},
                             {"name": "docs", "type": "tree"}, {"name": "examples", "type": "tree"},
                             {"name": "CHANGELOG.md", "type": "blob"}]},
        "dotgithub": {"entries": [{"name": "workflows", "type": "tree"}, {"name": "FUNDING.yml", "type": "blob"}]},
        "workflows": {"entries": [{"name": "ci.yml", "type": "blob"}]},
        "docsDir": {"entries": []},
        "readmeMd": {"text": "# ai-tool\n\n## Installation\n\npip install ai-tool\n\n## Usage\n\n```python\nimport ai_tool\n```\n\n## FAQ\n", "byteSize": 100},
        "readmeRst": None, "readmeLower": None, "readmePlain": None,
    }


def test_build_metrics_derives_expected_values():
    counts = {"issuesOpened": 30, "issuesClosed": 36, "prsOpened": 50, "prsMerged": 40,
              "prsClosed": 45, "staleIssues": 4, "breaking": 1}
    m = collect.build_metrics(fake_repo(), fake_repo()["defaultBranchRef"]["target"]["history"]["nodes"],
                              counts, 120, 0.9, NOW)
    assert m["full_name"] == "acme/ai-tool"
    assert m["category"] == "LLMs & Inference"
    assert 35 < m["age_months"] < 37
    assert m["releases_12m"] == 8          # 15 + 40*7 = 295 days -> all inside 365
    assert 14 < m["days_since_release"] < 16
    assert m["uses_semver"] is True
    assert m["has_changelog"] and m["has_tests"] and m["has_ci"]
    assert m["has_install_docs"] and m["has_examples"] and m["has_api_docs"] and m["has_troubleshooting"]
    assert m["has_license"] and m["has_contributing"] and m["has_code_of_conduct"]
    assert m["has_security_policy"] and m["has_issue_templates"]
    assert m["has_sponsorship"] and m["owner_is_org"]
    assert m["commits_90d"] == 44
    assert m["active_contributors_90d"] == 2          # alice + bob (carol is older, bot ignored)
    assert m["active_maintainers_180d"] == 3          # all three have >= 3 commits
    assert m["bus_factor"] == 1                       # alice alone covers 30/45 > 50%
    assert abs(m["top_contributor_share"] - 30 / 45) < 1e-9
    assert m["contributor_retention"] == 0.5          # bob persisted, alice did not exist before
    # issue response: 12h and 24h (closed) -> median 18h; young issue ignored
    assert abs(m["median_issue_response_hours"] - 18) < 0.01
    assert abs(m["median_pr_response_hours"] - 6) < 0.01
    assert m["stars_90d"] == 92 and m["stars_90d_estimated"] is True   # 50 stars in 49 days -> extrapolated to 90d
    assert m["forks_90d"] == 46 and m["forks_90d_estimated"] is False
    assert m["contributors_total"] == 120
    assert m["ci_success_rate"] == 0.9
    assert m["breaking_changes_12m"] == 1              # search hit; no major bumps in v1.x
    assert 0 < m["release_cadence_consistency"] <= 1   # perfectly regular 40-day cadence -> ~1


def test_release_fallback_to_tags():
    repo = fake_repo()
    repo["releases"] = {"totalCount": 0, "nodes": []}
    repo["tags"] = {"totalCount": 2, "nodes": [
        {"name": "1.2.0", "target": {"tagger": {"date": iso(NOW - timedelta(days=30))}}},
        {"name": "1.1.0", "target": {"committedDate": iso(NOW - timedelta(days=90))}},
    ]}
    counts = {k: 0 for k in ("issuesOpened", "issuesClosed", "prsOpened", "prsMerged", "prsClosed", "staleIssues", "breaking")}
    m = collect.build_metrics(repo, [], counts, None, None, NOW)
    assert m["releases_12m"] == 2
    assert 29 < m["days_since_release"] < 31
    assert m["uses_semver"] is True
    assert m["median_issue_response_hours"] is not None


def test_growth_window_not_extrapolated_when_sample_spans_window():
    dates = [NOW - timedelta(days=d) for d in (1, 5, 50, 200, 300)]
    assert collect._growth_in_window(dates, NOW, 90) == (3, False)
    assert collect._growth_in_window([], NOW, 90) == (0, False)
    recent = [NOW - timedelta(days=d) for d in range(0, 10)]
    assert collect._growth_in_window(recent, NOW, 90) == (100, True)   # 10 in 9 days -> 100 per 90 days


# ---------------------------------------------------------------- optional queries
class FakeClient:
    """Minimal stand-in for GitHubClient.graphql_full with a scripted answer."""

    def __init__(self, data=None, errors=None):
        self.data, self.errors = data or {}, errors or []
        self.calls = 0
        self.disabled = {}

    def graphql_full(self, query, variables=None):
        self.calls += 1
        return self.data, self.errors

    def query_disabled(self, key):
        return key in self.disabled

    def disable_query(self, key, reason=""):
        self.disabled[key] = reason

    def disabled_fields(self, query_name):
        return frozenset(getattr(self, "fields", set()))

    def disable_field(self, query_name, field, reason=""):
        self.fields = getattr(self, "fields", set()) | {field}


FORBIDDEN = [{"type": "FORBIDDEN", "path": ["repository", "owner", "hasSponsorsListing"],
              "message": "Resource not accessible by personal access token"}]


def test_fetch_optional_returns_repository_payload():
    client = FakeClient({"repository": {"fundingLinks": [{"platform": "GITHUB"}]}})
    assert collect.fetch_optional(client, "x", "query", {"name": "r"}) == {"fundingLinks": [{"platform": "GITHUB"}]}
    assert not client.disabled


def test_fetch_optional_disables_query_after_forbidden():
    client = FakeClient({"repository": None}, FORBIDDEN)
    assert collect.fetch_optional(client, "sponsors", "query", {"name": "r"}) == {}
    assert "sponsors" in client.disabled
    assert "FORBIDDEN at /repository/owner/hasSponsorsListing" in client.disabled["sponsors"]
    # subsequent calls are skipped without touching the API
    assert collect.fetch_optional(client, "sponsors", "query", {"name": "r"}) == {}
    assert client.calls == 1


def test_fetch_optional_not_found_does_not_disable():
    client = FakeClient({"repository": None}, [{"type": "NOT_FOUND", "path": ["repository"], "message": "nope"}])
    assert collect.fetch_optional(client, "sponsors", "query", {"name": "r"}) == {}
    assert not client.disabled


def test_describe_errors_format():
    from whitescore.github import describe_errors
    assert describe_errors([]) == ""
    text = describe_errors(FORBIDDEN + [{"message": "untyped"}])
    assert text.startswith(": FORBIDDEN at /repository/owner/hasSponsorsListing: Resource not accessible")
    assert "ERROR: untyped" in text


class ScriptedClient(FakeClient):
    """Answers each GraphQL document differently; REST endpoints return nothing."""

    def __init__(self, core_repo, forbidden_optional=True, forbid_stargazers=False, rest_pages=None):
        super().__init__()
        self.core_repo = core_repo
        self.forbidden_optional = forbidden_optional
        self.forbid_stargazers = forbid_stargazers
        self.rest_pages = rest_pages or {}
        self.seen = []

    def graphql_full(self, query, variables=None):
        from whitescore import queries
        self.calls += 1
        if "query RepoCore" in query:
            self.seen.append("core")
            if self.forbid_stargazers and "stargazers(" in query:
                return {"repository": None}, [{"type": "FORBIDDEN", "path": ["repository", "stargazers"],
                                               "message": "Resource not accessible by personal access token"}]
            repo = dict(self.core_repo)
            for field in self.disabled_fields("repository"):
                repo.pop(field, None)
            return {"repository": repo}, []
        if query in (queries.REPO_EXTRAS, queries.REPO_SPONSORS):
            self.seen.append("optional")
            if self.forbidden_optional:
                return {"repository": None}, FORBIDDEN
            return {"repository": {"fundingLinks": [{"platform": "GITHUB"}], "mentionableUsers": {"totalCount": 5},
                                   "owner": {"hasSponsorsListing": True}}}, []
        if query is queries.COUNTS:
            self.seen.append("counts")
            return {k: {"issueCount": 3} for k in variables}, []
        raise AssertionError("unexpected query")

    def graphql(self, query, variables=None):
        return self.graphql_full(query, variables)[0]

    def rest(self, path, params=None, allow_404=True, headers=None):
        self.seen.append("rest:" + path)
        return self.rest_pages.get(path)

    def rest_json(self, path, params=None):
        return None


def _core_only(repo):
    repo = dict(repo)
    for key in ("fundingLinks", "mentionableUsers"):
        repo.pop(key, None)
    repo["owner"] = {"__typename": "Organization", "login": "acme"}
    return repo


def test_collect_repo_survives_forbidden_optional_fields():
    client = ScriptedClient(_core_only(fake_repo()))
    metrics = collect.collect_repo(client, "acme/ai-tool", NOW)
    assert metrics is not None and metrics["full_name"] == "acme/ai-tool"
    assert metrics["stars"] == 12000
    assert client.seen.count("core") == 1 and client.seen.count("counts") == 1
    assert set(client.disabled) == {"funding links", "sponsors listing"}
    # second repository: the optional queries are no longer attempted
    client.seen.clear()
    assert collect.collect_repo(client, "acme/ai-tool", NOW) is not None
    assert "optional" not in client.seen


def test_collect_repo_uses_optional_fields_when_allowed():
    client = ScriptedClient(_core_only(fake_repo()), forbidden_optional=False)
    metrics = collect.collect_repo(client, "acme/ai-tool", NOW)
    assert metrics["has_sponsorship"] is True
    assert metrics["contributors_total"] == 5
    assert not client.disabled


class FakeResponse:
    def __init__(self, body, link=""):
        self.body, self.headers = body, {"Link": link}

    def json(self):
        return self.body


def test_fetch_core_drops_forbidden_field_and_backfills_stars_over_rest():
    stars = [{"starred_at": iso(NOW - timedelta(days=d)), "user": {}} for d in range(0, 30)]
    client = ScriptedClient(_core_only(fake_repo()), forbid_stargazers=True,
                            rest_pages={"/repos/acme/ai-tool/stargazers": FakeResponse(stars)})
    metrics = collect.collect_repo(client, "acme/ai-tool", NOW)
    assert metrics is not None
    assert client.fields == {"stargazers"}
    assert client.seen.count("core") == 2                      # refused once, retried without the field
    assert "rest:/repos/acme/ai-tool/stargazers" in client.seen
    assert metrics["stars_90d"] == 93 and metrics["stars_90d_estimated"] is True   # 30 stars in 29 days
    assert metrics["forks_90d"] == 46                           # forks still came from GraphQL
    # next repository: the field is left out up front, no second round trip
    client.seen.clear()
    assert collect.collect_repo(client, "acme/ai-tool", NOW) is not None
    assert client.seen.count("core") == 1


def test_growth_is_null_when_no_source_available():
    client = ScriptedClient(_core_only(fake_repo()), forbid_stargazers=True)   # REST returns nothing
    metrics = collect.collect_repo(client, "acme/ai-tool", NOW)
    assert metrics["stars_90d"] is None and metrics["stars_90d_estimated"] is None
    from whitescore.scoring import score_all
    assert 0 <= score_all(metrics)["popularity"] <= 100       # scorer tolerates the null


def test_fetch_core_gives_up_on_non_removable_error():
    client = FakeClient({"repository": None}, [{"type": "NOT_FOUND", "path": ["repository"], "message": "gone"}])
    repo, errors = collect.fetch_core(client, {"owner": "a", "name": "b"})
    assert repo is None and errors and client.calls == 1


def test_build_repo_core_variants():
    from whitescore.queries import REMOVABLE_CORE_FIELDS, build_repo_core
    q = build_repo_core({"stargazers", "forks", "meta"})
    assert "stargazers(" not in q and "forks(" not in q
    assert "nameWithOwner" in q                                  # meta can never be dropped
    assert "stargazers" in REMOVABLE_CORE_FIELDS and "meta" not in REMOVABLE_CORE_FIELDS
