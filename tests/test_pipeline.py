"""End-to-end run of pipeline.run with the API replaced by fakes: two consecutive
runs exercise the incremental plan, the metrics cache and the light refresh."""
import json
from datetime import datetime, timezone

from test_collect import fake_repo

from whitescore import collect, config, pipeline


class FakeGitHubClient:
    def __init__(self, token=None, *a, **kw):
        self.token = token or "primary-token"
        self.requests_made = 0
        self.graphql_points_used = 0

    def rest(self, path, params=None, allow_404=True, headers=None):
        return None


def metrics_for(name):
    repo = fake_repo()
    owner, _, short = name.partition("/")
    repo.update({"nameWithOwner": name, "name": short, "url": "https://github.com/" + name})
    repo["owner"] = {"__typename": "Organization", "login": owner}
    return collect.build_metrics(repo, [], {k: 1 for k in ("issuesOpened", "issuesClosed", "prsOpened", "prsMerged",
                                                           "prsClosed", "staleIssues", "breaking")},
                                 10, 0.9, datetime.now(timezone.utc))


def test_two_runs_use_cache_and_light_refresh(tmp_path, monkeypatch):
    collected, light_calls = [], []
    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(pipeline, "collect_repo", lambda client, name, now: (collected.append(name), metrics_for(name))[1])
    monkeypatch.setattr(pipeline, "fetch_star_history_rest",
                        lambda client, name, now, window_days=None: 4321 if name == "a/one" else None)
    monkeypatch.setattr(pipeline, "fetch_light", lambda client, names: (light_calls.append(list(names)),
                                                                        {n.lower(): {"stargazerCount": 999} for n in names})[1])
    monkeypatch.setattr(pipeline, "catalog_candidates",
                        lambda min_stars: {"a/one": {"stars": 300, "topics": ["llm"]}, "a/two": {"stars": 200, "topics": []},
                                           "a/three": {"stars": 100, "topics": []}})
    monkeypatch.setattr(pipeline, "load_seed_file", lambda: [])
    monkeypatch.setattr(config, "SEED_REPOS", [])
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "LEADERBOARD_PATH", tmp_path / "leaderboard.json")
    monkeypatch.setattr(pipeline, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(pipeline, "CACHE_PATH", tmp_path / "cache" / "metrics-cache.json")
    monkeypatch.setattr(pipeline, "TOKEN_PREFS_PATH", tmp_path / "cache" / "token-preferences.json")
    monkeypatch.delenv("GITHUB_TOKEN_FALLBACK", raising=False)

    # run 1: nothing cached, budget of two full collections -> third repo deferred
    board = pipeline.run(max_repos=3, max_full=2)
    assert collected == ["a/one", "a/two"]
    assert board["project_count"] == 2 and board["failures"] == []
    assert board["deferred"] == ["a/three"]
    assert light_calls == [["a/three"]]           # asked, but nothing cached to apply it to
    cache = json.loads((tmp_path / "cache" / "metrics-cache.json").read_text())
    assert set(cache["entries"]) == {"a/one", "a/two"}

    # run 2: the two cached repos are fresh -> only the deferred one is collected
    collected.clear(); light_calls.clear()
    board = pipeline.run(max_repos=3, max_full=2)
    assert collected == ["a/three"]
    assert board["project_count"] == 3 and board["failures"] == [] and board["deferred"] == []
    assert sorted(light_calls[0]) == ["a/one", "a/two"]
    by_name = {p["full_name"]: p for p in board["projects"]}
    assert by_name["a/one"]["metrics"]["from_cache"] is True
    assert by_name["a/one"]["metrics"]["stars"] == 999       # light refresh applied
    # cached repositories get exact star growth from the star history endpoint on every run
    assert by_name["a/one"]["metrics"]["stars_90d"] == 4321 and by_name["a/one"]["metrics"]["stars_90d_exact"] is True
    assert by_name["a/two"]["metrics"]["stars_90d_exact"] is False   # endpoint answered nothing: cached figure kept
    assert "from_cache" not in by_name["a/three"]["metrics"]
    assert by_name["a/one"]["topics"] and "llm" in by_name["a/one"]["topics"]   # catalog topics merged
    assert [p["rank"] for p in board["projects"]] == [1, 2, 3]
    cache = json.loads((tmp_path / "cache" / "metrics-cache.json").read_text())
    assert set(cache["entries"]) == {"a/one", "a/two", "a/three"}
    assert cache["entries"]["a/one"]["metrics"]["stars"] == 999   # cache carries the refreshed numbers


def test_explicit_repos_always_collect_fully(tmp_path, monkeypatch):
    collected = []
    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(pipeline, "collect_repo", lambda client, name, now: (collected.append(name), metrics_for(name))[1])
    monkeypatch.setattr(pipeline, "fetch_light", lambda client, names: {})
    monkeypatch.setattr(pipeline, "CACHE_PATH", tmp_path / "metrics-cache.json")
    monkeypatch.setattr(pipeline, "TOKEN_PREFS_PATH", tmp_path / "token-preferences.json")
    monkeypatch.delenv("GITHUB_TOKEN_FALLBACK", raising=False)
    board = pipeline.run(repos=["b/x", "b/y"], dry_run=True)
    assert collected == ["b/x", "b/y"] and board["project_count"] == 2
    assert not (tmp_path / "metrics-cache.json").exists()      # dry run writes nothing


def test_fallback_token_rescues_repositories_the_primary_may_not_read(tmp_path, monkeypatch):
    """One organization refuses the classic token: its repository is collected with the
    fallback, remembered on disk, and the next run's light refresh asks the fallback for it."""
    from whitescore import tokens
    from whitescore.collect import RepositoryForbidden
    light_calls = []

    def fake_collect(client, name, now):
        if client.token == "classic" and name.startswith("saml-org/"):
            raise RepositoryForbidden(name, [{"type": "FORBIDDEN", "path": ["repository"], "message": "SAML"}])
        return metrics_for(name)

    monkeypatch.setenv("GITHUB_TOKEN_FALLBACK", "fine-grained")
    monkeypatch.setattr(pipeline, "GitHubClient", lambda *a, **kw: FakeGitHubClient("classic"))
    monkeypatch.setattr(tokens, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(pipeline, "collect_repo", fake_collect)
    monkeypatch.setattr(pipeline, "fetch_light",
                        lambda client, names: (light_calls.append((client.token, sorted(names))), {})[1])
    monkeypatch.setattr(pipeline, "catalog_candidates",
                        lambda min_stars: {"saml-org/tool": {"stars": 300, "topics": []}, "open/one": {"stars": 200, "topics": []}})
    monkeypatch.setattr(pipeline, "load_seed_file", lambda: [])
    monkeypatch.setattr(config, "SEED_REPOS", [])
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "LEADERBOARD_PATH", tmp_path / "leaderboard.json")
    monkeypatch.setattr(pipeline, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(pipeline, "CACHE_PATH", tmp_path / "data" / "metrics-cache.json")
    prefs = tmp_path / "data" / "token-preferences.json"
    monkeypatch.setattr(pipeline, "TOKEN_PREFS_PATH", prefs)

    board = pipeline.run(max_repos=2, max_full=-1)
    assert board["failures"] == [] and board["project_count"] == 2
    assert json.loads(prefs.read_text())["fallback_repos"].keys() == {"saml-org/tool"}

    # run 2: both are fresh in the cache; the light refresh is split by token
    board = pipeline.run(max_repos=2, max_full=-1)
    assert board["project_count"] == 2
    assert sorted(light_calls) == [("classic", ["open/one"]), ("fine-grained", ["saml-org/tool"])]


def test_a_failed_collection_keeps_the_cached_project_on_the_board(tmp_path, monkeypatch):
    """Run 1 collects both repositories; in run 2 one of them cannot be collected
    (a token problem, an API hiccup): it stays on the board with its cached metrics."""
    broken = set()

    def fake_collect(client, name, now):
        if name in broken:
            raise collect.GitHubError("GraphQL error: INSUFFICIENT_SCOPES")
        return metrics_for(name)

    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(pipeline, "collect_repo", fake_collect)
    monkeypatch.setattr(pipeline, "fetch_light", lambda client, names: {})
    monkeypatch.setattr(pipeline, "catalog_candidates",
                        lambda min_stars: {"a/one": {"stars": 300, "topics": []}, "a/two": {"stars": 200, "topics": []}})
    monkeypatch.setattr(pipeline, "load_seed_file", lambda: [])
    monkeypatch.setattr(config, "SEED_REPOS", [])
    monkeypatch.setattr(config, "FULL_REFRESH_DAYS", 0)          # everything is due every run
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "LEADERBOARD_PATH", tmp_path / "leaderboard.json")
    monkeypatch.setattr(pipeline, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(pipeline, "CACHE_PATH", tmp_path / "cache" / "metrics-cache.json")
    monkeypatch.setattr(pipeline, "TOKEN_PREFS_PATH", tmp_path / "cache" / "token-preferences.json")
    monkeypatch.delenv("GITHUB_TOKEN_FALLBACK", raising=False)

    assert pipeline.run(max_repos=2, max_full=-1)["project_count"] == 2
    broken.add("a/one")
    board = pipeline.run(max_repos=2, max_full=-1)
    assert board["failures"] == ["a/one"]
    assert board["project_count"] == 2                            # still on the board
    kept = next(p for p in board["projects"] if p["full_name"] == "a/one")
    assert kept["metrics"]["from_cache"] is True


# ---------------------------------------------------------------- selection policy on the board
def test_licence_policy_exclusions_and_overrides_apply_to_the_board(tmp_path, monkeypatch):
    def metrics_with_licence(name):
        m = metrics_for(name)
        m["license"] = {"a/one": "MIT", "a/seed": "NOASSERTION", "a/fixed": "NOASSERTION"}.get(name, "MIT")
        return m

    monkeypatch.setattr(pipeline, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(pipeline, "collect_repo", lambda client, name, now: metrics_with_licence(name))
    monkeypatch.setattr(pipeline, "fetch_light", lambda client, names: {})
    monkeypatch.setattr(pipeline, "catalog_candidates",
                        lambda min_stars: {"a/one": {"stars": 300, "topics": []}, "a/excluded": {"stars": 250, "topics": []}})
    monkeypatch.setattr(pipeline, "load_seed_file", lambda: [])
    monkeypatch.setattr(pipeline, "load_exclusions", lambda: ["a/excluded"])
    monkeypatch.setattr(pipeline, "load_category_overrides", lambda: {"a/one": "Computer Vision"})
    monkeypatch.setattr(config, "SEED_REPOS", ["a/seed", "a/fixed"])
    monkeypatch.setattr(config, "LICENSE_OVERRIDES", {"a/fixed": "BSD-3-Clause"})
    monkeypatch.setattr(config, "REQUIRE_RECOGNIZED_LICENSE", True)
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "LEADERBOARD_PATH", tmp_path / "leaderboard.json")
    monkeypatch.setattr(pipeline, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(pipeline, "CACHE_PATH", tmp_path / "cache" / "metrics-cache.json")
    monkeypatch.setattr(pipeline, "TOKEN_PREFS_PATH", tmp_path / "cache" / "token-preferences.json")
    monkeypatch.delenv("GITHUB_TOKEN_FALLBACK", raising=False)

    board = pipeline.run(max_repos=10, max_full=-1)
    names = {p["full_name"]: p for p in board["projects"]}
    assert "a/excluded" not in names                       # manual exclusion
    assert "a/seed" not in names                           # a seed with an unrecognised licence is dropped
    assert names["a/fixed"]["license"] == "BSD-3-Clause"   # hand-checked override is credited
    assert names["a/fixed"]["metrics"]["has_license"] is True
    assert names["a/one"]["category"] == "Computer Vision"
    assert board["license"] == "CC-BY-4.0" and board["license_url"]
    terms = json.loads((tmp_path / "terms.json").read_text())
    assert terms["excluded"] == ["a/excluded"] and terms["category_overrides"] == {"a/one": "Computer Vision"}
    assert "MIT" in terms["osi_licenses"] and terms["license_overrides"] == {"a/fixed": "BSD-3-Clause"}


# ---------------------------------------------------------------- star growth and history hygiene
def _series(day_stars):
    return [{"d": d, "o": 50.0, "stars": s} for d, s in day_stars]


def test_star_growth_is_exact_once_the_history_spans_the_window():
    series = _series([("2026-01-01", 1000), ("2026-02-01", 1500), ("2026-03-15", 2000), ("2026-05-20", 2600)])
    # 2026-05-25 minus 90 days is 2026-02-24: the most recent point beyond that is 2026-02-01
    assert pipeline.star_growth_from_history(series, 2700, "2026-05-25") == (1200, False)


def test_star_growth_is_extrapolated_from_a_short_history():
    series = _series([("2026-05-01", 1000), ("2026-05-10", 1090)])
    gained, estimated = pipeline.star_growth_from_history(series, 1100, "2026-05-11")
    assert estimated is True
    assert gained == 900            # 100 stars in 10 days -> 900 over 90


def test_star_growth_is_unknown_with_too_little_history():
    series = _series([("2026-05-09", 1000)])
    assert pipeline.star_growth_from_history(series, 1100, "2026-05-11") == (None, None)
    assert pipeline.star_growth_from_history([], 1100, "2026-05-11") == (None, None)


def test_apply_star_history_overrides_an_empty_collected_timeline():
    history = {"a/one": _series([("2026-01-01", 100), ("2026-05-01", 400)])}
    metrics = {"full_name": "a/one", "stars": 500, "stars_90d": 0, "stars_90d_estimated": False}
    out = pipeline.apply_star_history(dict(metrics), history, "2026-05-25")
    assert (out["stars_90d"], out["stars_90d_estimated"]) == (400, False)
    # a repository with no usable history keeps a positive collected sample, or becomes unknown
    kept = pipeline.apply_star_history({"full_name": "b/two", "stars": 50, "stars_90d": 7, "stars_90d_estimated": False},
                                       history, "2026-05-25")
    assert kept["stars_90d"] == 7
    unknown = pipeline.apply_star_history({"full_name": "b/two", "stars": 50, "stars_90d": 0}, history, "2026-05-25")
    assert unknown["stars_90d"] is None


def test_prune_history_drops_points_before_the_first_real_collection():
    history = {"a/one": _series([("2026-08-15", 10), ("2026-10-28", 20), ("2026-10-29", 30)]),
               "b/two": _series([("2026-09-01", 5)])}
    pruned = pipeline.prune_history(history, "2026-10-29")
    assert list(pruned) == ["a/one"]
    assert [pt["d"] for pt in pruned["a/one"]] == ["2026-10-29"]
    assert pipeline.prune_history(history, "") == history


def test_apply_star_history_keeps_an_exact_figure_from_the_star_history_endpoint():
    history = {"a/one": _series([("2026-01-01", 100), ("2026-05-01", 400)])}
    metrics = {"full_name": "a/one", "stars": 500, "stars_90d": 123, "stars_90d_estimated": False, "stars_90d_exact": True}
    out = pipeline.apply_star_history(dict(metrics), history, "2026-05-25")
    assert (out["stars_90d"], out["stars_90d_estimated"]) == (123, False)


def test_build_project_carries_the_image_out_of_the_metrics():
    m = metrics_for("a/one")
    m["image"], m["image_source"] = "https://example.org/logo.png", "repo"
    project = pipeline.build_project(m)
    assert (project["image"], project["image_source"]) == ("https://example.org/logo.png", "repo")
    assert "image" not in project["metrics"]
    assert pipeline.build_project(metrics_for("a/two"))["image"] is None
