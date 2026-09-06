"""Unit tests for JWT authentication module."""

from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database.session import get_db_session
from app.main import app
from app.models.user import AdminUser


@pytest_asyncio.fixture
async def seeded_session(db_session: AsyncSession) -> AsyncSession:
    """Seed test admin users in the in-memory database."""
    admin = AdminUser(
        username="admin",
        hashed_password=hash_password("admin123"),
        display_name="Administrator",
        role="admin",
        is_active=True,
    )
    inactive_admin = AdminUser(
        username="inactive_admin",
        hashed_password=hash_password("admin123"),
        display_name="Inactive Administrator",
        role="admin",
        is_active=False,
    )
    db_session.add(admin)
    db_session.add(inactive_admin)
    await db_session.commit()
    return db_session


@pytest.fixture
def client(seeded_session: AsyncSession) -> Generator[TestClient, None, None]:
    """Create test client with database override containing admin user."""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield seeded_session

    app.dependency_overrides[get_db_session] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestPasswordHashing:
    """Tests for password hashing utilities."""

    def test_hash_and_verify_correct_password(self) -> None:
        """Hashing then verifying the same password should return True."""
        password = "my_secure_password_123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_verify_wrong_password(self) -> None:
        """Verifying a wrong password should return False."""
        hashed = hash_password("correct_password")
        assert not verify_password("wrong_password", hashed)

    def test_hash_produces_unique_outputs(self) -> None:
        """Two calls to hash_password produce different hashes (bcrypt salt)."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_verify_corrupt_hash_returns_false(self) -> None:
        """Verifying with a malformed hash string returns False without crashing."""
        assert not verify_password("admin", "invalid_salt_or_hash")
        assert not verify_password("admin", "")

    def test_hash_and_verify_long_unicode_password(self) -> None:
        """Passwords exceeding 72 bytes with Vietnamese Unicode characters are safely handled."""
        pwd = "Mật khẩu quản trị bảo mật cao cấp trên 72 bytes của chatbot AI thông minh 2026!@#"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed)
        assert not verify_password("Sai_" + pwd, hashed)
        assert not verify_password(pwd[:20], hashed)


class TestJWTTokens:
    """Tests for JWT token creation and decoding."""

    def test_create_and_decode_access_token(self) -> None:
        """Access token should encode and decode correctly."""
        data: dict[str, Any] = {"sub": "admin", "role": "admin"}
        token = create_access_token(data, expires_minutes=30)
        payload = decode_token(token)
        assert payload["sub"] == "admin"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_create_and_decode_refresh_token(self) -> None:
        """Refresh token should encode and decode correctly."""
        data: dict[str, Any] = {"sub": "admin", "role": "admin"}
        token = create_refresh_token(data)
        payload = decode_token(token)
        assert payload["sub"] == "admin"
        assert payload["type"] == "refresh"

    def test_expired_token_raises_401(self) -> None:
        """Expired token should raise HTTPException with 401."""
        data: dict[str, Any] = {"sub": "admin", "role": "admin"}
        token = create_access_token(data, expires_minutes=-1)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401

    def test_invalid_token_raises_401(self) -> None:
        """Garbage token should raise HTTPException with 401."""
        with pytest.raises(HTTPException) as exc_info:
            decode_token("not.a.valid.token")
        assert exc_info.value.status_code == 401


class TestLoginEndpoint:
    """Tests for POST /api/admin/login."""

    def test_login_success(self, client: TestClient) -> None:
        """Valid credentials should return JWT tokens."""
        resp = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "admin"

    def test_login_wrong_password(self, client: TestClient) -> None:
        """Wrong password should return 401."""
        resp = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "wrong_password"},
        )
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client: TestClient) -> None:
        """Nonexistent user should return 401."""
        resp = client.post(
            "/api/admin/login",
            json={"username": "nobody", "password": "any"},
        )
        assert resp.status_code == 401

    def test_login_inactive_user_returns_403(self, client: TestClient) -> None:
        """Inactive user account should return 403 Forbidden."""
        resp = client.post(
            "/api/admin/login",
            json={"username": "inactive_admin", "password": "admin123"},
        )
        assert resp.status_code == 403
        assert "vô hiệu hóa" in resp.json()["detail"]


class TestProtectedEndpoints:
    """Tests for JWT-protected API routes."""

    def _get_auth_header(self, client: TestClient) -> dict[str, str]:
        """Helper to login and get Authorization header."""
        resp = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_protected_endpoint_without_token_returns_401(self, client: TestClient) -> None:
        """Accessing protected endpoint without token should return 401."""
        resp = client.get("/api/admin/dashboard/stats")
        assert resp.status_code == 401

    def test_protected_endpoint_with_valid_token(self, client: TestClient) -> None:
        """Accessing protected endpoint with valid token should succeed."""
        headers = self._get_auth_header(client)
        resp = client.get("/api/admin/dashboard/stats", headers=headers)
        assert resp.status_code == 200

    def test_protected_endpoint_with_invalid_token(self, client: TestClient) -> None:
        """Accessing protected endpoint with garbage token should return 401."""
        headers = {"Authorization": "Bearer invalid.token.here"}
        resp = client.get("/api/admin/dashboard/stats", headers=headers)
        assert resp.status_code == 401

    def test_protected_endpoint_with_expired_token(self, client: TestClient) -> None:
        """Accessing protected endpoint with expired token should return 401."""
        token = create_access_token({"sub": "admin", "role": "admin"}, expires_minutes=-1)
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get("/api/admin/dashboard/stats", headers=headers)
        assert resp.status_code == 401

    def test_settings_endpoint_protected(self, client: TestClient) -> None:
        """Settings endpoint (sensitive data) must require auth."""
        resp = client.get("/api/admin/settings")
        assert resp.status_code == 401

        headers = self._get_auth_header(client)
        resp = client.get("/api/admin/settings", headers=headers)
        assert resp.status_code == 200

    def test_products_endpoint_protected(self, client: TestClient) -> None:
        """Products endpoint must require auth."""
        resp = client.get("/api/admin/products")
        assert resp.status_code == 401

        headers = self._get_auth_header(client)
        resp = client.get("/api/admin/products", headers=headers)
        assert resp.status_code == 200

    def test_protected_endpoint_with_refresh_token_type_fails(self, client: TestClient) -> None:
        """Passing a refresh token instead of access token to protected endpoint should return 401."""
        refresh_tok = create_refresh_token({"sub": "admin", "role": "admin"})
        headers = {"Authorization": f"Bearer {refresh_tok}"}
        resp = client.get("/api/admin/dashboard/stats", headers=headers)
        assert resp.status_code == 401
        assert "Token không đúng loại" in resp.json()["detail"]

    def test_protected_endpoint_missing_sub_fails(self, client: TestClient) -> None:
        """Access token without 'sub' claim should return 401."""
        token = create_access_token({"role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get("/api/admin/dashboard/stats", headers=headers)
        assert resp.status_code == 401
        assert "không chứa thông tin người dùng" in resp.json()["detail"]

    def test_protected_endpoint_inactive_user_fails(self, client: TestClient) -> None:
        """Valid token for an inactive user should return 401."""
        token = create_access_token({"sub": "inactive_admin", "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get("/api/admin/dashboard/stats", headers=headers)
        assert resp.status_code == 401
        assert "vô hiệu hóa" in resp.json()["detail"]


class TestRefreshToken:
    """Tests for POST /api/admin/refresh-token."""

    def test_refresh_success(self, client: TestClient) -> None:
        """Valid refresh token should return new access token."""
        login_resp = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        resp = client.post(
            "/api/admin/refresh-token",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_refresh_with_access_token_fails(self, client: TestClient) -> None:
        """Using access token as refresh token should fail."""
        login_resp = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        access_token = login_resp.json()["access_token"]

        resp = client.post(
            "/api/admin/refresh-token",
            json={"refresh_token": access_token},
        )
        assert resp.status_code == 401

    def test_refresh_inactive_user_fails(self, client: TestClient) -> None:
        """Refresh token for an inactive user should return 401."""
        token = create_refresh_token({"sub": "inactive_admin", "role": "admin"})
        resp = client.post(
            "/api/admin/refresh-token",
            json={"refresh_token": token},
        )
        assert resp.status_code == 401


class TestMeEndpoint:
    """Tests for GET /api/admin/me."""

    def test_me_returns_user_info(self, client: TestClient) -> None:
        """Authenticated user should get their own info."""
        login_resp = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get("/api/admin/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"


class TestLiveChatWebSocketAuth:
    """Tests for LiveChat WebSocket token authentication."""

    def test_websocket_missing_token_rejected(self, client: TestClient) -> None:
        """Connecting to /ws/livechat without token should be rejected with code 1008."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/admin/ws/livechat"):
                pass
        assert exc_info.value.code == 1008

    def test_websocket_invalid_token_rejected(self, client: TestClient) -> None:
        """Connecting to /ws/livechat with invalid token should be rejected with code 1008."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/admin/ws/livechat?token=not-a-valid-token"):
                pass
        assert exc_info.value.code == 1008

    def test_websocket_refresh_token_rejected(self, client: TestClient) -> None:
        """Connecting to /ws/livechat with refresh token should be rejected with code 1008."""
        refresh_token = create_refresh_token({"sub": "admin", "role": "admin"})
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/api/admin/ws/livechat?token={refresh_token}"):
                pass
        assert exc_info.value.code == 1008

    def test_websocket_valid_token_success(self, client: TestClient) -> None:
        """Connecting with valid access token should succeed and respond to ping."""
        token = create_access_token({"sub": "admin", "role": "admin"})
        with client.websocket_connect(f"/api/admin/ws/livechat?token={token}") as ws:
            ws.send_text("ping")
            assert ws.receive_text() == "pong"
