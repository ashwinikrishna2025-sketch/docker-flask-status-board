"""Container HEALTHCHECK: exit 0 when /healthz answers 200.

Kept as a module so the Dockerfile's HEALTHCHECK stays readable instead of
becoming a long one-liner with nested quoting.
"""

from __future__ import annotations

import os
import sys
import urllib.request


def main() -> int:
    port = os.environ.get("PORT", "8000")
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 0 if response.status == 200 else 1
    except Exception:  # noqa: BLE001 - any failure means "unhealthy"
        return 1


if __name__ == "__main__":
    sys.exit(main())
