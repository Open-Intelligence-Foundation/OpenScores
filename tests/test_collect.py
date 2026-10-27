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
