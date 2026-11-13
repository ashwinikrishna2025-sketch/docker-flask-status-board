"""Health checks for a configurable list of HTTP services."""

from __future__ import annotations

import concurrent.futures
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = "service-status-board/1.0"
DEFAULT_SERVICES = (
    "GitHub API=https://api.github.com,"
    "PyPI=https://pypi.org/simple/,"
    "Example=https://example.com"
)


@dataclass(frozen=True)
class Service:
    """One thing to check: a display name and the URL to request."""

    name: str
    url: str


@dataclass(frozen=True)
class Result:
    """The outcome of a single check."""

    name: str
    url: str
    ok: bool
    status: int | None
    latency_ms: int
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "ok": self.ok,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def load_services(raw: str | None = None) -> list[Service]:
    """Parse comma-separated ``Name=URL`` pairs from config.

    Falls back to the SERVICES environment variable, then to a small
    default list so the container is useful the moment it starts.
    """
    if raw is None:
        raw = os.environ.get("SERVICES", DEFAULT_SERVICES)

    services: list[Service] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, separator, url = chunk.partition("=")
        if not separator:
            name, url = chunk, chunk
        services.append(Service(name=name.strip(), url=url.strip()))
    return services


def check(service: Service, timeout: float = 5.0) -> Result:
    """Make one GET request and turn the outcome into a Result."""
    started = time.perf_counter()
    request = urllib.request.Request(
        service.url, method="GET", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            response.read(2048)
    except urllib.error.HTTPError as exc:
        # The service answered, just not with a success code.
        return Result(
            name=service.name,
            url=service.url,
            ok=200 <= exc.code < 400,
            status=exc.code,
            latency_ms=_elapsed_ms(started),
            error=f"HTTP {exc.code}",
        )
    except Exception as exc:  # noqa: BLE001 - any failure means "down"
        return Result(
            name=service.name,
            url=service.url,
            ok=False,
            status=None,
            latency_ms=_elapsed_ms(started),
            error=str(exc) or type(exc).__name__,
        )

    return Result(
        name=service.name,
        url=service.url,
        ok=200 <= status < 400,
        status=status,
        latency_ms=_elapsed_ms(started),
    )


def check_all(services: list[Service], timeout: float = 5.0) -> list[Result]:
    """Check every service in parallel, so one slow host does not block the rest."""
    if not services:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(services))) as pool:
        return list(pool.map(lambda service: check(service, timeout), services))


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class CheckCache:
    """Caches results so refreshing the page does not re-check every service."""

    def __init__(
        self,
        services: list[Service],
        ttl_seconds: float = 15.0,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._services = services
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._results: list[Result] = []
        self._expires_at = 0.0
        self.last_checked: float | None = None

    def get(self, force: bool = False) -> list[Result]:
        with self._lock:
            if force or time.monotonic() >= self._expires_at:
                self._results = check_all(self._services, self._timeout)
                self._expires_at = time.monotonic() + self._ttl
                self.last_checked = time.time()
            return self._results
