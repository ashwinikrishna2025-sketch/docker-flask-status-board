"""Tests for the status board.

Nothing here touches the network: the checks are replaced with stubs so the
suite is fast and gives the same answer on a laptop and in CI.
"""

from __future__ import annotations

import pytest

from app import checks, main
from app.checks import CheckCache, Result, Service, load_services


@pytest.fixture
def client():
    return main.app.test_client()


class StubCache:
    """Stands in for CheckCache with a fixed set of results."""

    def __init__(self, results: list[Result], last_checked: float | None = 1_700_000_000.0):
        self._results = results
        self.last_checked = last_checked

    def get(self, force: bool = False) -> list[Result]:
        return self._results


UP = Result(name="Up", url="https://up.test", ok=True, status=200, latency_ms=12)
DOWN = Result(
    name="Down", url="https://down.test", ok=False, status=None, latency_ms=5000,
    error="timed out",
)


# --- configuration parsing -------------------------------------------------

def test_load_services_parses_name_and_url_pairs():
    services = load_services("GitHub=https://api.github.com, PyPI=https://pypi.org/simple/")
    assert services == [
        Service("GitHub", "https://api.github.com"),
        Service("PyPI", "https://pypi.org/simple/"),
    ]


def test_load_services_uses_the_url_as_the_name_when_none_is_given():
    assert load_services("https://example.com") == [
        Service("https://example.com", "https://example.com")
    ]


def test_load_services_ignores_blank_entries():
    assert load_services(" , ,  ") == []


# --- the cache -------------------------------------------------------------

def test_cache_checks_once_then_serves_the_stored_results(monkeypatch):
    calls = []

    def fake_check_all(services, timeout):
        calls.append(services)
        return [UP]

    monkeypatch.setattr(checks, "check_all", fake_check_all)
    cache = CheckCache([Service("Up", "https://up.test")], ttl_seconds=60)

    assert cache.get() == [UP]
    assert cache.get() == [UP]
    assert len(calls) == 1, "the second call should come from the cache"


def test_cache_rechecks_when_forced(monkeypatch):
    calls = []
    monkeypatch.setattr(
        checks, "check_all", lambda services, timeout: calls.append(1) or [UP]
    )
    cache = CheckCache([Service("Up", "https://up.test")], ttl_seconds=60)

    cache.get()
    cache.get(force=True)
    assert len(calls) == 2


# --- endpoints -------------------------------------------------------------

def test_healthz_is_ok_and_makes_no_outbound_calls(client, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("/healthz must not check anything over the network")

    monkeypatch.setattr(checks, "check_all", explode)

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_api_status_returns_200_when_everything_is_up(client, monkeypatch):
    monkeypatch.setattr(main, "_cache", StubCache([UP]))

    response = client.get("/api/status")
    assert response.status_code == 200

    body = response.get_json()
    assert body["all_ok"] is True
    assert body["checked_at"].endswith("+00:00")
    assert body["services"] == [
        {
            "name": "Up",
            "url": "https://up.test",
            "ok": True,
            "status": 200,
            "latency_ms": 12,
            "error": None,
        }
    ]


def test_api_status_returns_503_when_a_service_is_down(client, monkeypatch):
    monkeypatch.setattr(main, "_cache", StubCache([UP, DOWN]))

    response = client.get("/api/status")
    assert response.status_code == 503

    body = response.get_json()
    assert body["all_ok"] is False
    assert body["services"][1]["error"] == "timed out"


def test_api_status_is_ok_when_nothing_is_configured(client, monkeypatch):
    monkeypatch.setattr(main, "_cache", StubCache([], last_checked=None))

    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.get_json() == {"all_ok": True, "checked_at": None, "services": []}


def test_index_renders_each_service(client, monkeypatch):
    monkeypatch.setattr(main, "_cache", StubCache([UP, DOWN]))

    response = client.get("/")
    assert response.status_code == 200

    page = response.get_data(as_text=True)
    assert "Some services are down" in page
    assert "https://up.test" in page
    assert "timed out" in page
