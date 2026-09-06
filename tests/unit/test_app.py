"""Unit tests for FastAPI app — health check, app creation."""

import pytest
from httpx import AsyncClient

from app.main import create_app


class TestHealthCheck:
    """Test the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_returns_200(self, app_client: AsyncClient):
        response = await app_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_check_response_body(self, app_client: AsyncClient):
        response = await app_client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert "app_name" in data
        assert "environment" in data

    @pytest.mark.asyncio
    async def test_health_check_shows_app_name(self, app_client: AsyncClient):
        response = await app_client.get("/health")
        data = response.json()
        assert data["app_name"] == "AI Customer Service Agent"


class TestAppCreation:
    """Test FastAPI app factory."""

    def test_create_app_returns_fastapi(self):
        app = create_app()
        assert app is not None
        assert app.title == "AI Customer Service Agent"

    def test_app_has_version(self):
        app = create_app()
        assert app.version == "0.1.0"

    @pytest.mark.asyncio
    async def test_404_on_unknown_route(self, app_client: AsyncClient):
        response = await app_client.get("/nonexistent")
        assert response.status_code == 404
