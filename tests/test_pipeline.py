"""End-to-end run of pipeline.run with the API replaced by fakes: two consecutive
runs exercise the incremental plan, the metrics cache and the light refresh."""
import json
from datetime import datetime, timezone

from test_collect import fake_repo

from whitescore import collect, config, pipeline


class FakeGitHubClient:
    def __init__(self, *a, **kw):
        self.requests_made = 0
        self.graphql_points_used = 0


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

    # run 1: nothing cached, budget of two full collections -> third repo deferred
    board = pipeline.run(max_repos=3, max_full=2)
    assert collected == ["a/one", "a/two"]
    assert board["project_count"] == 2 and board["failures"] == ["a/three"]
    assert light_calls == [["a/three"]]           # asked, but nothing cached to apply it to
    cache = json.loads((tmp_path / "cache" / "metrics-cache.json").read_text())
    assert set(cache["entries"]) == {"a/one", "a/two"}

    # run 2: the two cached repos are fresh -> only the deferred one is collected
    collected.clear(); light_calls.clear()
    board = pipeline.run(max_repos=3, max_full=2)
    assert collected == ["a/three"]
    assert board["project_count"] == 3 and board["failures"] == []
    assert sorted(light_calls[0]) == ["a/one", "a/two"]
    by_name = {p["full_name"]: p for p in board["projects"]}
    assert by_name["a/one"]["metrics"]["from_cache"] is True
    assert by_name["a/one"]["metrics"]["stars"] == 999       # light refresh applied
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
    board = pipeline.run(repos=["b/x", "b/y"], dry_run=True)
    assert collected == ["b/x", "b/y"] and board["project_count"] == 2
    assert not (tmp_path / "metrics-cache.json").exists()      # dry run writes nothing
