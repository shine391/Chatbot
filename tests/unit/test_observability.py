"""Unit tests for Observability & Production Hardening (Prometheus metrics & SlowAPI rate limiting)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.main import create_app


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint(db_session: AsyncSession):
    """Test that the /metrics endpoint is exposed and returns Prometheus formatted metrics."""
    app = create_app()

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Trigger an API request first to generate request metrics
        await client.get("/health")

        # Now query /metrics
        metrics_res = await client.get("/metrics")
        assert metrics_res.status_code == 200
        content = metrics_res.text
        # Check standard Prometheus headers/metrics
        assert "http_requests_total" in content or "fastapi" in content or "# HELP" in content


@pytest.mark.asyncio
async def test_slowapi_rate_limiting_on_login(db_session: AsyncSession):
    """Test that spamming /api/admin/login triggers HTTP 429 Too Many Requests."""
    app = create_app()

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = []
        # Limit is 5/minute on /api/admin/login
        for _ in range(7):
            res = await client.post(
                "/api/admin/login",
                json={"username": "attacker", "password": "wrong_password"},
            )
            responses.append(res.status_code)

        # At least one request beyond the limit should be 429 Too Many Requests
        assert 429 in responses
