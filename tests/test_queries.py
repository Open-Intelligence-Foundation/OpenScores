"""Validate every GraphQL document against GitHub's public schema.

The schema is not vendored (1.5 MB). Set GITHUB_GRAPHQL_SCHEMA to a local copy of
https://docs.github.com/public/fpt/schema.docs.graphql to enable these tests;
they are skipped otherwise.
"""
import os
import pathlib

import pytest

from whitescore import queries

graphql = pytest.importorskip("graphql")

SCHEMA_PATH = os.environ.get("GITHUB_GRAPHQL_SCHEMA")

DOCUMENTS = {name: getattr(queries, name) for name in dir(queries)
             if name.isupper() and isinstance(getattr(queries, name), str)}


@pytest.fixture(scope="module")
def schema():
    if not SCHEMA_PATH or not pathlib.Path(SCHEMA_PATH).exists():
        pytest.skip("GITHUB_GRAPHQL_SCHEMA not set")
    return graphql.build_schema(pathlib.Path(SCHEMA_PATH).read_text())


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_document_is_valid(schema, name):
    errors = graphql.validate(schema, graphql.parse(DOCUMENTS[name]))
    assert not errors, "%s: %s" % (name, [e.message for e in errors])


def test_reduced_core_query_is_valid(schema):
    reduced = queries.build_repo_core({"stargazers", "forks", "recentIssues", "watchers"})
    errors = graphql.validate(schema, graphql.parse(reduced))
    assert not errors, [e.message for e in errors]


def test_light_refresh_query_is_valid(schema):
    from whitescore.incremental import build_light_query
    errors = graphql.validate(schema, graphql.parse(build_light_query(["acme/ai-tool", "other/repo"])))
    assert not errors, [e.message for e in errors]


def test_core_query_has_no_sponsors_fields():
    # Sponsors fields are FORBIDDEN for fine-grained tokens and, being non-null,
    # would null out the whole repository. They must stay in their own query.
    assert "hasSponsorsListing" not in queries.REPO_CORE
    assert "fundingLinks" not in queries.REPO_CORE
    assert "mentionableUsers" not in queries.REPO_CORE
    assert "hasSponsorsListing" in queries.REPO_SPONSORS
