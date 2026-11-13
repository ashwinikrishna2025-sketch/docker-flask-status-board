"""A small Flask app that reports whether a list of HTTP services is up."""

from __future__ import annotations

import datetime as dt
import os

from flask import Flask, jsonify, render_template

from app.checks import CheckCache, load_services

app = Flask(__name__)

_cache = CheckCache(
    services=load_services(),
    ttl_seconds=float(os.environ.get("CACHE_TTL_SECONDS", "15")),
    timeout_seconds=float(os.environ.get("CHECK_TIMEOUT_SECONDS", "5")),
)


@app.get("/healthz")
def healthz():
    """Liveness probe for the container and for orchestrators.

    It deliberately makes no outbound calls: this endpoint answers
    "is this process alive", not "is the internet reachable".
    """
    return jsonify(status="ok"), 200


@app.get("/api/status")
def api_status():
    """Machine-readable status of every configured service."""
    results = _cache.get()
    all_ok = all(result.ok for result in results) if results else True
    payload = {
        "all_ok": all_ok,
        "checked_at": _checked_at_iso(),
        "services": [result.to_dict() for result in results],
    }
    return jsonify(payload), (200 if all_ok else 503)


@app.get("/")
def index():
    """The status board itself."""
    results = _cache.get()
    return render_template(
        "index.html",
        results=results,
        all_ok=all(result.ok for result in results) if results else True,
        checked_at=_checked_at_iso(),
    )


def _checked_at_iso() -> str | None:
    if _cache.last_checked is None:
        return None
    moment = dt.datetime.fromtimestamp(_cache.last_checked, tz=dt.UTC)
    return moment.isoformat(timespec="seconds")
