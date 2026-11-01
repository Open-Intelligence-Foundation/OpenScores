"""Primary/fallback token selection, memory of which repositories need the
fallback, and the collector's "this token may not read the repository" signal."""
import json
from datetime import datetime, timezone

import pytest

from test_collect import FakeClient

from whitescore import collect, pipeline, tokens
from whitescore.collect import RepositoryForbidden

SAML_DENIED = [{"type": "FORBIDDEN", "path": ["repository"],
                "message": "Resource protected by organization SAML enforcement. You must grant your "
                           "Personal Access token access to this organization."}]
CLASSIC_DENIED = [{"type": "FORBIDDEN", "path": ["repository"],
                   "message": "The 'acme' organization forbids access via a personal access token (classic)."}]
FIELD_DENIED = [{"type": "FORBIDDEN", "path": ["repository", "stargazers"],
                 "message": "Resource not accessible by personal access token"}]


class Client(FakeClient):
    def __init__(self, token, data=None, errors=None):
        super().__init__(data, errors)
        self.token = token
        self.requests_made, self.graphql_points_used = 0, 0


# ------------------------------------------------------------- denial detection
def test_repository_denied_only_for_whole_repository_errors():
    assert collect.repository_denied(SAML_DENIED)
    assert collect.repository_denied(CLASSIC_DENIED)
    assert collect.repository_denied([{"type": "INSUFFICIENT_SCOPES", "message": "needs public_repo"}])
    assert not collect.repository_denied(FIELD_DENIED)                       # one field: handled by fetch_core
    assert not collect.repository_denied([{"type": "NOT_FOUND", "path": ["repository"]}])


def test_collect_repo_raises_for_a_denied_repository_but_not_a_missing_one():
    with pytest.raises(RepositoryForbidden) as info:
        collect.collect_repo(Client("t", {"repository": None}, SAML_DENIED), "acme/tool")
    assert "acme/tool" in str(info.value) and "SAML" in str(info.value)
    missing = Client("t", {"repository": None}, [{"type": "NOT_FOUND", "path": ["repository"]}])
    assert collect.collect_repo(missing, "acme/gone") is None


# ------------------------------------------------------------------- the pool
def test_pool_without_fallback_only_offers_the_primary():
    pool = tokens.TokenPool(Client("p"))
    assert [w for w, _ in pool.clients_for("a/b")] == ["primary"]
    assert not pool.prefers_fallback("a/b")
    assert pool.split(["a/b", "c/d"]) == (["a/b", "c/d"], [])


def test_pool_prefers_fallback_for_remembered_repos_and_their_owner():
    pool = tokens.TokenPool(Client("p"), Client("f"), {"acme/one": "2026-10-31T00:00:00Z"})
    assert [w for w, _ in pool.clients_for("acme/one")] == ["fallback", "primary"]
    assert [w for w, _ in pool.clients_for("ACME/two")] == ["fallback", "primary"]   # same owner, case-insensitive
    assert [w for w, _ in pool.clients_for("other/x")] == ["primary", "fallback"]
    assert pool.split(["other/x", "acme/two", "acme/one"]) == (["other/x"], ["acme/two", "acme/one"])


def test_pool_remember_learns_and_forgets():
    pool = tokens.TokenPool(Client("p"), Client("f"))
    pool.remember("Acme/One", "fallback", "2026-11-01T00:00:00Z")
    pool.remember("acme/one", "fallback", "2026-11-01T06:00:00Z")           # same repo, counted once
    assert pool.learned == 1 and pool.fallback_repos == {"acme/one": "2026-11-01T06:00:00Z"}
    pool.remember("acme/one", "primary", "2026-11-02T00:00:00Z")           # primary works again
    assert pool.fallback_repos == {}


def test_preferences_round_trip_prune_and_bad_files(tmp_path):
    path = tmp_path / "prefs" / "token-preferences.json"
    pool = tokens.TokenPool(Client("p"), Client("f"))
    tokens.save_preferences(path, pool)                                     # nothing to say, nothing written
    assert not path.exists()
    pool.remember("acme/one", "fallback", "2026-11-01T00:00:00Z")
    pool.remember("gone/old", "fallback", "2026-11-01T00:00:00Z")
    tokens.save_preferences(path, pool, keep=["ACME/one", "other/x"])
    assert tokens.load_preferences(path) == {"acme/one": "2026-11-01T00:00:00Z"}   # pruned to current targets
    path.write_text("not json")
    assert tokens.load_preferences(path) == {}
    path.write_text(json.dumps({"version": 99, "fallback_repos": {"a/b": "x"}}))
    assert tokens.load_preferences(path) == {}


def test_build_pool_ignores_a_fallback_equal_to_the_primary(tmp_path, monkeypatch):
    monkeypatch.setattr(tokens, "GitHubClient", Client)
    primary = Client("same")
    assert build(primary, tmp_path, "same").fallback is None
    pool = build(primary, tmp_path, "different")
    assert pool.fallback is not None and pool.fallback.token == "different"
    monkeypatch.delenv("GITHUB_TOKEN_FALLBACK", raising=False)
    assert build(primary, tmp_path, None).fallback is None


def build(primary, tmp_path, token):
    return tokens.build_pool(primary, tmp_path / "prefs.json", fallback_token=token)


# ------------------------------------------------------- pipeline integration
def test_collect_with_fallback_retries_and_remembers(monkeypatch):
    primary, fallback = Client("p"), Client("f")
    pool = tokens.TokenPool(primary, fallback)
    seen = []

    def fake_collect(client, name, now):
        seen.append(client.token)
        if client is primary and name.startswith("acme/"):
            raise RepositoryForbidden(name, CLASSIC_DENIED)
        return {"full_name": name}

    monkeypatch.setattr(pipeline, "collect_repo", fake_collect)
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert pipeline.collect_with_fallback(pool, "acme/one", now, "stamp")["full_name"] == "acme/one"
    assert seen == ["p", "f"] and pool.fallback_repos == {"acme/one": "stamp"}
    seen.clear()
    pipeline.collect_with_fallback(pool, "acme/two", now, "stamp")       # sibling: fallback goes first
    assert seen == ["f"]
    seen.clear()
    pipeline.collect_with_fallback(pool, "other/x", now, "stamp")
    assert seen == ["p"] and "other/x" not in pool.fallback_repos


def test_collect_with_fallback_raises_when_every_token_is_refused(monkeypatch):
    pool = tokens.TokenPool(Client("p"), Client("f"))

    def always_denied(client, name, now):
        raise RepositoryForbidden(name, SAML_DENIED)

    monkeypatch.setattr(pipeline, "collect_repo", always_denied)
    with pytest.raises(RepositoryForbidden):
        pipeline.collect_with_fallback(pool, "acme/one", datetime.now(timezone.utc), "stamp")
    assert pool.fallback_repos == {}
