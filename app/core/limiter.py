"""Rate limiting instance using SlowAPI."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def get_rate_limit_key(request: Request) -> str:
    """Extract client IP for rate limiting, isolating unit test runs under pytest."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    client_ip = get_remote_address(request)
    if client_ip == "testclient":
        pytest_test = os.environ.get("PYTEST_CURRENT_TEST")
        if pytest_test:
            # Under pytest, isolate buckets by test function name
            test_name = pytest_test.split(" ")[0]
            return f"test_{test_name}"
    return client_ip


limiter = Limiter(key_func=get_rate_limit_key, default_limits=["200/minute"])
