"""Shared test setup: the suite never reaches the network."""
import pytest

from whitescore import collect


@pytest.fixture(autouse=True)
def no_http(monkeypatch):
    """Project image discovery fetches logos, avatars and websites over plain
    HTTP; tests stub that layer out and get 'nothing found' unless they say
    otherwise."""
    monkeypatch.setattr(collect, "_http_get", lambda url, stream=False: None)
