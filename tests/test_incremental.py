from datetime import datetime, timedelta, timezone

from whitescore import config, incremental

NOW = datetime(2026, 10, 30, 6, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def entry(days_ago, **metrics):
    base = {"full_name": "x/y", "stars": 100, "forks": 10, "watchers": 5, "open_issues": 3, "open_prs": 1,
            "days_since_commit": 2.0, "days_since_release": 20.0, "age_months": 24.0,
            "image": None, "image_rules": config.IMAGE_RULES_VERSION,
            "collected_at": iso(NOW - timedelta(days=days_ago))}
    base.update(metrics)
    return {"collected_at": iso(NOW - timedelta(days=days_ago)), "metrics": base}


# ------------------------------------------------------------------- planning
def test_plan_new_repos_first_then_stalest():
    cache = {"a/fresh": entry(1), "a/stale1": entry(4), "a/stale2": entry(9), "a/mixed": entry(2.5)}   # keys are lower-cased
    targets = ["a/fresh", "a/stale1", "a/new", "a/stale2", "a/Mixed"]
    full, reuse, stats = incremental.plan_collection(targets, cache, NOW, max_full=3, refresh_days=3)
    assert full == ["a/new", "a/stale2", "a/stale1"]        # new, then oldest first
    assert sorted(reuse) == ["a/Mixed", "a/fresh"]            # fresh + deferred (case-insensitive lookup)
    assert stats == {"new": 1, "stale": 2, "deferred": 0, "fresh": 2}


def test_plan_without_cap_collects_everything_due():
    cache = {"a/fresh": entry(0.5)}
    full, reuse, stats = incremental.plan_collection(["a/fresh", "a/b", "a/c"], cache, NOW, max_full=-1, refresh_days=3)
    assert full == ["a/b", "a/c"] and reuse == ["a/fresh"]


def test_plan_treats_unparseable_timestamp_as_stalest():
    cache = {"a/bad": {"collected_at": "garbage", "metrics": {"full_name": "a/bad"}}, "a/old": entry(10)}
    full, _, _ = incremental.plan_collection(["a/old", "a/bad"], cache, NOW, max_full=1, refresh_days=3)
    assert full == ["a/bad"]


def test_plan_retries_pictureless_repos_collected_under_older_picture_rules():
    cache = {"a/pictured": entry(0.5, image="https://example.org/logo.png", image_rules=1),   # has one: waits its turn
             "a/old-rules": entry(0.5, image=None, image_rules=1),                            # none, old rules: due
             "a/never": entry(0.5), "a/fresh": entry(0.5)}                                     # none, current rules: waits
    del cache["a/never"]["metrics"]["image"]; del cache["a/never"]["metrics"]["image_rules"]   # before pictures existed
    full, reuse, stats = incremental.plan_collection(["a/pictured", "a/old-rules", "a/never", "a/fresh"], cache, NOW,
                                                     max_full=-1, refresh_days=3)
    assert sorted(full) == ["a/never", "a/old-rules"]
    assert sorted(reuse) == ["a/fresh", "a/pictured"]
    assert stats["stale"] == 2 and stats["fresh"] == 2


# --------------------------------------------------------------- light refresh
def test_build_light_query_aliases_and_escapes():
    q = incremental.build_light_query(["acme/ai-tool", 'odd/na"me'])
    assert 'r0: repository(owner: "acme", name: "ai-tool")' in q
    assert 'r1: repository(owner: "odd", name: "na\\"me")' in q
    assert q.count("stargazerCount") == 2 and "rateLimit" in q


class FakeClient:
    def __init__(self, answers):
        self.answers, self.queries = answers, []

    def graphql(self, query, variables=None):
        self.queries.append(query)
        return self.answers.pop(0)


def test_fetch_light_batches_and_keys_by_lowercase_name():
    client = FakeClient([{"r0": {"stargazerCount": 1}, "r1": None}, {"r0": {"stargazerCount": 3}}])
    out = incremental.fetch_light(client, ["A/B", "a/missing", "c/d"], batch=2)
    assert len(client.queries) == 2
    assert out == {"a/b": {"stargazerCount": 1}, "c/d": {"stargazerCount": 3}}


def test_apply_light_updates_counts_and_commit_age():
    light = {"stargazerCount": 150, "forkCount": 12, "isArchived": True,
             "watchers": {"totalCount": 7}, "openIssues": {"totalCount": 9}, "openPRs": {"totalCount": 2},
             "defaultBranchRef": {"target": {"committedDate": iso(NOW - timedelta(hours=12))}}}
    m = incremental.apply_light(entry(2)["metrics"], light, NOW)
    assert (m["stars"], m["forks"], m["watchers"], m["open_issues"], m["open_prs"]) == (150, 12, 7, 9, 2)
    assert m["is_archived"] is True
    assert abs(m["days_since_commit"] - 0.5) < 1e-6
    assert abs(m["days_since_release"] - 22.0) < 1e-6            # aged by the 2 elapsed days
    assert m["from_cache"] is True and m["refreshed_at"] == iso(NOW)


def test_apply_light_ages_from_last_refresh_not_collection():
    metrics = entry(5)["metrics"]
    metrics["refreshed_at"] = iso(NOW - timedelta(days=1))
    metrics["days_since_release"] = 25.0                          # already aged at the last refresh
    m = incremental.apply_light(metrics, None, NOW)
    assert abs(m["days_since_release"] - 26.0) < 1e-6
    assert abs(m["days_since_commit"] - 3.0) < 1e-6


# ------------------------------------------------------------------ cache file
def test_cache_round_trip_and_prune(tmp_path):
    path = tmp_path / "cache.json"
    cache = {"a/current": entry(2), "a/recent": entry(10), "a/ancient": entry(45)}
    incremental.save_cache(path, cache)
    loaded = incremental.load_cache(path)
    assert set(loaded) == set(cache)
    pruned = incremental.prune_cache(loaded, keep=["A/current"], now=NOW)
    assert set(pruned) == {"a/current", "a/recent"}              # ancient entry expired


def test_load_cache_ignores_bad_or_foreign_files(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not json")
    assert incremental.load_cache(path) == {}
    path.write_text('{"version": 99, "entries": {"a/b": {}}}')
    assert incremental.load_cache(path) == {}
    assert incremental.load_cache(tmp_path / "missing.json") == {}


def test_light_refresh_keeps_the_owner_avatar_as_the_picture():
    assert "avatarUrl" in incremental.build_light_query(["acme/ai-tool"])
    light = {"stargazerCount": 1, "forkCount": 1, "owner": {"__typename": "User", "avatarUrl": "https://avatars.githubusercontent.com/u/9"}}
    m = incremental.apply_light(entry(2, image="https://example.org/old-logo.png", image_source="repo", image_rules=1)["metrics"], light, NOW)
    assert (m["image"], m["image_source"], m["image_rules"]) == ("https://avatars.githubusercontent.com/u/9", "user", config.IMAGE_RULES_VERSION)
    # no owner in the payload: the cached picture stays
    m = incremental.apply_light(entry(2, image="https://example.org/logo.png", image_source="repo")["metrics"], {"stargazerCount": 1}, NOW)
    assert m["image"] == "https://example.org/logo.png"
