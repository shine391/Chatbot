"""Unit tests for Facebook Historical Sync Service & Admin Endpoints.

Tests Meta Graph API v21.0 conversation/message ingestion, customer resolution,
message deduplication, funnel stage auto-progression, zero-risk guardrails,
and admin sync API endpoints.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message, MessageRole, MessageType
from app.models.customer import Customer, FunnelStage
from app.models.setting import SettingCategory, SystemSetting
from app.services.facebook_sync_service import FacebookSyncService
from app.services.message_sender import MessageSender
from app.services.settings_service import SettingsService

PAGE_ID = "999888777"
ACCESS_TOKEN = "EAAMockAccessToken123"

SAMPLE_GRAPH_CONVERSATIONS = {
    "data": [
        {
            "id": "t_conv_001",
            "updated_time": "2024-01-01T10:15:00+0000",
            "participants": {
                "data": [
                    {"id": "cust_101", "name": "Nguyễn Văn A"},
                    {"id": PAGE_ID, "name": "AI Fashion Shop"},
                ]
            },
            "messages": {
                "data": [
                    {
                        "id": "m_001",
                        "message": "Shop ơi mẫu áo khoác này giá bao nhiêu?",
                        "created_time": "2024-01-01T10:00:00+0000",
                        "from": {"id": "cust_101", "name": "Nguyễn Văn A"},
                    },
                    {
                        "id": "m_002",
                        "message": "Dạ chào bạn, áo khoác gió giá 350k ạ!",
                        "created_time": "2024-01-01T10:05:00+0000",
                        "from": {"id": PAGE_ID, "name": "AI Fashion Shop"},
                    },
                    {
                        "id": "m_003",
                        "message": "Shop ship cho mình 1 chiếc size L về Hà Nội nhé",
                        "created_time": "2024-01-01T10:10:00+0000",
                        "from": {"id": "cust_101", "name": "Nguyễn Văn A"},
                        "attachments": {
                            "data": [{"payload": {"url": "https://example.com/photos/jacket.jpg"}}]
                        },
                    },
                ]
            },
        },
        {
            "id": "t_conv_002",
            "updated_time": "2024-01-02T14:30:00+0000",
            "participants": {
                "data": [
                    {"id": "cust_102", "name": "Trần Thị B"},
                    {"id": PAGE_ID, "name": "AI Fashion Shop"},
                ]
            },
            "messages": {
                "data": [
                    {
                        "id": "m_004",
                        "message": "Shop ơi tư vấn cho mình mẫu đầm dự tiệc",
                        "created_time": "2024-01-02T14:20:00+0000",
                        "from": {"id": "cust_102", "name": "Trần Thị B"},
                    },
                    {
                        "id": "m_005",
                        "message": "Dạ shop có rất nhiều mẫu đầm xinh ạ",
                        "created_time": "2024-01-02T14:25:00+0000",
                        "from": {"id": PAGE_ID, "name": "AI Fashion Shop"},
                    },
                ]
            },
        },
    ]
}


@pytest.mark.asyncio
async def test_sync_facebook_conversations_creates_customers_and_messages(
    db_session: AsyncSession,
) -> None:
    """Test full parsing of conversations and messages into Customer, Conversation, and Message tables."""
    FacebookSyncService.reset_status()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_GRAPH_CONVERSATIONS

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        res = await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token=ACCESS_TOKEN,
            max_conversations=50,
        )

    assert res["status"] == "completed"
    assert res["synced_conversations"] == 2
    assert res["synced_messages"] == 5
    assert res["new_customers"] == 2
    assert res["error_message"] is None

    # Check Customers
    stmt_cust_a = select(Customer).where(Customer.platform_user_id == "cust_101")
    cust_a = (await db_session.execute(stmt_cust_a)).scalar_one_or_none()
    assert cust_a is not None
    assert cust_a.name == "Nguyễn Văn A"
    assert cust_a.platform == "facebook"
    # Funnel progression: "ship cho mình 1 chiếc" -> INTENT
    assert cust_a.funnel_stage == FunnelStage.INTENT.value

    stmt_cust_b = select(Customer).where(Customer.platform_user_id == "cust_102")
    cust_b = (await db_session.execute(stmt_cust_b)).scalar_one_or_none()
    assert cust_b is not None
    assert cust_b.name == "Trần Thị B"
    assert cust_b.platform == "facebook"
    # Funnel progression: "tư vấn cho mình mẫu" -> INTERESTED
    assert cust_b.funnel_stage == FunnelStage.INTERESTED.value

    # Check Conversations
    stmt_conv = select(Conversation).where(Conversation.customer_id == cust_a.id)
    conv_a = (await db_session.execute(stmt_conv)).scalars().first()
    assert conv_a is not None
    assert conv_a.channel == "facebook"

    # Check Messages & Roles
    stmt_msgs = (
        select(Message).where(Message.conversation_id == conv_a.id).order_by(Message.sent_at)
    )
    msgs = (await db_session.execute(stmt_msgs)).scalars().all()
    assert len(msgs) == 3

    # Msg 1: Customer text
    assert msgs[0].role == MessageRole.CUSTOMER
    assert msgs[0].message_type == MessageType.TEXT
    assert "giá bao nhiêu" in (msgs[0].content or "")
    assert msgs[0].platform_message_id == "m_001"

    # Msg 2: Agent reply
    assert msgs[1].role == MessageRole.AGENT
    assert msgs[1].message_type == MessageType.TEXT
    assert "350k" in (msgs[1].content or "")
    assert msgs[1].platform_message_id == "m_002"

    # Msg 3: Customer with image attachment
    assert msgs[2].role == MessageRole.CUSTOMER
    assert msgs[2].message_type == MessageType.IMAGE
    assert msgs[2].media_urls == ["https://example.com/photos/jacket.jpg"]
    assert msgs[2].platform_message_id == "m_003"

    # Verify contact timestamps reflect historical message timestamps rather than sync run time
    assert cust_a.first_contact_at.year == 2024
    assert cust_a.first_contact_at.month == 1
    assert cust_a.first_contact_at.day == 1
    assert cust_a.first_contact_at.hour == 10
    assert cust_a.first_contact_at.minute == 0

    assert cust_a.last_contact_at.year == 2024
    assert cust_a.last_contact_at.month == 1
    assert cust_a.last_contact_at.day == 1
    assert cust_a.last_contact_at.hour == 10
    assert cust_a.last_contact_at.minute == 10

    assert conv_a.started_at.year == 2024
    assert conv_a.started_at.minute == 0


@pytest.mark.asyncio
async def test_sync_facebook_idempotent_no_duplicate_messages(
    db_session: AsyncSession,
) -> None:
    """Running sync multiple times with same data must not duplicate customers, conversations, or messages."""
    FacebookSyncService.reset_status()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_GRAPH_CONVERSATIONS

    # 1st run
    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        res1 = await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token=ACCESS_TOKEN,
            max_conversations=50,
        )
    assert res1["synced_conversations"] == 2
    assert res1["synced_messages"] == 5
    assert res1["new_customers"] == 2

    # Count records after 1st run
    cust_count_1 = (await db_session.execute(select(func.count(Customer.id)))).scalar()
    conv_count_1 = (await db_session.execute(select(func.count(Conversation.id)))).scalar()
    msg_count_1 = (await db_session.execute(select(func.count(Message.id)))).scalar()

    # 2nd run with same payload
    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        res2 = await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token=ACCESS_TOKEN,
            max_conversations=50,
        )
    assert res2["synced_conversations"] == 2
    assert res2["synced_messages"] == 0  # 0 new messages inserted
    assert res2["new_customers"] == 0  # 0 new customers created

    # Counts must remain strictly identical
    cust_count_2 = (await db_session.execute(select(func.count(Customer.id)))).scalar()
    conv_count_2 = (await db_session.execute(select(func.count(Conversation.id)))).scalar()
    msg_count_2 = (await db_session.execute(select(func.count(Message.id)))).scalar()

    assert cust_count_2 == cust_count_1
    assert conv_count_2 == conv_count_1
    assert msg_count_2 == msg_count_1


@pytest.mark.asyncio
async def test_sync_auto_funnel_progression_logic(db_session: AsyncSession) -> None:
    """Test funnel progression specifically for lead -> interested -> intent."""
    FacebookSyncService.reset_status()

    # Step 1: Customer asks general question -> INTERESTED
    graph_data_1 = {
        "data": [
            {
                "id": "t_conv_funnel",
                "updated_time": "2024-01-03T10:00:00+0000",
                "participants": {
                    "data": [
                        {"id": "cust_funnel_1", "name": "Khách Thử Nghiệm"},
                        {"id": PAGE_ID, "name": "AI Fashion Shop"},
                    ]
                },
                "messages": {
                    "data": [
                        {
                            "id": "m_fn_01",
                            "message": "Cho mình xem mẫu áo sơ mi trắng",
                            "created_time": "2024-01-03T10:00:00+0000",
                            "from": {"id": "cust_funnel_1", "name": "Khách Thử Nghiệm"},
                        }
                    ]
                },
            }
        ]
    }

    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = graph_data_1

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp1):
        await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token=ACCESS_TOKEN,
            max_conversations=50,
        )

    stmt = select(Customer).where(Customer.platform_user_id == "cust_funnel_1")
    cust = (await db_session.execute(stmt)).scalar_one()
    assert cust.funnel_stage == FunnelStage.INTERESTED.value

    # Step 2: Ingest follow-up message with buying intent -> INTENT
    graph_data_2 = {
        "data": [
            {
                "id": "t_conv_funnel",
                "updated_time": "2024-01-03T10:10:00+0000",
                "participants": {
                    "data": [
                        {"id": "cust_funnel_1", "name": "Khách Thử Nghiệm"},
                        {"id": PAGE_ID, "name": "AI Fashion Shop"},
                    ]
                },
                "messages": {
                    "data": [
                        {
                            "id": "m_fn_02",
                            "message": "Cho mình số tài khoản để chuyển khoản thanh toán nhé",
                            "created_time": "2024-01-03T10:10:00+0000",
                            "from": {"id": "cust_funnel_1", "name": "Khách Thử Nghiệm"},
                        }
                    ]
                },
            }
        ]
    }
    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = graph_data_2

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp2):
        await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token=ACCESS_TOKEN,
            max_conversations=50,
        )

    await db_session.refresh(cust)
    assert cust.funnel_stage == FunnelStage.INTENT.value


@pytest.mark.asyncio
async def test_sync_cursor_pagination(db_session: AsyncSession) -> None:
    """Test pagination using paging.cursors.after or paging.next across multiple pages."""
    FacebookSyncService.reset_status()

    page_1 = {
        "data": [
            {
                "id": "t_p1",
                "participants": {
                    "data": [
                        {"id": "cust_p1", "name": "Khách Trang 1"},
                        {"id": PAGE_ID, "name": "Shop"},
                    ]
                },
                "messages": {
                    "data": [
                        {
                            "id": "m_p1_1",
                            "message": "Tin nhắn trang 1",
                            "created_time": "2024-01-01T10:00:00+0000",
                            "from": {"id": "cust_p1"},
                        }
                    ]
                },
            }
        ],
        "paging": {
            "cursors": {"after": "cursor_page_2"},
            "next": f"https://graph.facebook.com/v21.0/{PAGE_ID}/conversations?after=cursor_page_2",
        },
    }

    page_2 = {
        "data": [
            {
                "id": "t_p2",
                "participants": {
                    "data": [
                        {"id": "cust_p2", "name": "Khách Trang 2"},
                        {"id": PAGE_ID, "name": "Shop"},
                    ]
                },
                "messages": {
                    "data": [
                        {
                            "id": "m_p2_1",
                            "message": "Tin nhắn trang 2",
                            "created_time": "2024-01-01T11:00:00+0000",
                            "from": {"id": "cust_p2"},
                        }
                    ]
                },
            }
        ],
        "paging": {},
    }

    mock_resp1 = MagicMock(status_code=200)
    mock_resp1.json.return_value = page_1
    mock_resp2 = MagicMock(status_code=200)
    mock_resp2.json.return_value = page_2

    with patch.object(
        httpx.AsyncClient, "get", new_callable=AsyncMock, side_effect=[mock_resp1, mock_resp2]
    ) as mock_get:
        res = await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token=ACCESS_TOKEN,
            max_conversations=10,
        )

    assert mock_get.call_count == 2
    assert res["status"] == "completed"
    assert res["synced_conversations"] == 2
    assert res["synced_messages"] == 2
    assert res["new_customers"] == 2


@pytest.mark.asyncio
async def test_sync_zero_risk_guardrail_no_outward_dispatch(
    db_session: AsyncSession,
) -> None:
    """CRITICAL GUARDRAIL: Syncing past messages must NEVER trigger outward messages to Facebook."""
    FacebookSyncService.reset_status()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_GRAPH_CONVERSATIONS

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        with patch.object(MessageSender, "send_message", new_callable=AsyncMock) as mock_sender:
            await FacebookSyncService.sync_page_conversations(
                session=db_session,
                page_id=PAGE_ID,
                access_token=ACCESS_TOKEN,
                max_conversations=50,
            )
            mock_sender.assert_not_called()


@pytest.mark.asyncio
async def test_sync_graph_api_error_handling(db_session: AsyncSession) -> None:
    """When Meta Graph API returns an error response, service state updates to error gracefully."""
    FacebookSyncService.reset_status()

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": {
            "message": "Invalid OAuth access token - Cannot parse access token",
            "type": "OAuthException",
            "code": 190,
        }
    }

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        res = await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token="bad_token",
            max_conversations=50,
        )

    assert res["status"] == "error"
    assert "Invalid OAuth access token" in str(res["error_message"])


@pytest.mark.asyncio
async def test_sync_admin_endpoints(
    app_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Test POST /api/admin/channels/facebook/sync and GET /api/admin/channels/facebook/sync/status."""
    FacebookSyncService.reset_status()

    # 1. Missing token & page ID -> 400
    res_no_token = await app_client.post(
        "/api/admin/channels/facebook/sync",
        json={"max_conversations": 25},
    )
    assert res_no_token.status_code == 400

    # 2. Configure page access token and page ID in Settings
    settings_service = SettingsService(db_session)
    await settings_service.set_setting(
        key="facebook_page_access_token",
        value="EAATestTokenReal999",
        category=SettingCategory.CHANNELS,
    )
    await settings_service.set_setting(
        key="facebook_page_id",
        value=PAGE_ID,
        category=SettingCategory.CHANNELS,
    )
    await db_session.commit()

    # 3. GET status initially -> idle
    res_status = await app_client.get("/api/admin/channels/facebook/sync/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert "status" in status_data
    assert status_data["status"] == "idle"

    # 4. Mock background sync execution and trigger POST /sync
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_GRAPH_CONVERSATIONS

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        res_trigger = await app_client.post(
            "/api/admin/channels/facebook/sync",
            json={"max_conversations": 50, "force": True},
        )
        assert res_trigger.status_code == 200
        trigger_data = res_trigger.json()
        assert trigger_data["status"] == "started"
        assert trigger_data["max_conversations"] == 50
        assert trigger_data["page_id"] == PAGE_ID

    # 5. Check status endpoint reflects metrics
    res_status_after = await app_client.get("/api/admin/channels/facebook/sync/status")
    assert res_status_after.status_code == 200
    after_data = res_status_after.json()
    assert after_data["status"] in ("running", "completed")


@pytest.mark.asyncio
async def test_sync_facebook_page_id_whitespace_resilience(
    db_session: AsyncSession,
) -> None:
    """Ensure page_id with leading/trailing whitespace does not match as customer or crash."""
    FacebookSyncService.reset_status()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_GRAPH_CONVERSATIONS

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        res = await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=f"  {PAGE_ID}  ",
            access_token=f"  {ACCESS_TOKEN}  ",
            max_conversations=50,
        )

    assert res["status"] == "completed"
    # Ensure no customer with PAGE_ID was created
    stmt_page_cust = select(Customer).where(Customer.platform_user_id == PAGE_ID)
    assert (await db_session.execute(stmt_page_cust)).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_sync_rate_limit_detection(db_session: AsyncSession) -> None:
    """Verify that HTTP 429 or Meta rate limit error code 613 is clearly reported."""
    FacebookSyncService.reset_status()

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.json.return_value = {
        "error": {
            "message": "Calls to this API have exceeded the rate limit.",
            "type": "OAuthException",
            "code": 613,
        }
    }

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        res = await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token=ACCESS_TOKEN,
            max_conversations=50,
        )

    assert res["status"] == "error"
    assert "Rate Limit" in str(res["error_message"])


@pytest.mark.asyncio
async def test_sync_auto_resolves_page_id_via_me(
    app_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """When page_id is missing, admin endpoint calls /me to auto-discover page_id."""
    FacebookSyncService.reset_status()

    # Configure token only, omit page_id
    settings_service = SettingsService(db_session)
    await settings_service.set_setting(
        key="facebook_page_access_token",
        value="EAATestTokenRealAutoMe",
        category=SettingCategory.CHANNELS,
    )
    # Clear any existing page_id
    stmt = select(SystemSetting).where(SystemSetting.key == "facebook_page_id")
    existing_setting = (await db_session.execute(stmt)).scalar_one_or_none()
    if existing_setting:
        await db_session.delete(existing_setting)
    await db_session.commit()

    mock_me_resp = MagicMock()
    mock_me_resp.status_code = 200
    mock_me_resp.json.return_value = {
        "id": "auto_resolved_page_123",
        "name": "Auto Shop Fanpage",
    }

    mock_conv_resp = MagicMock()
    mock_conv_resp.status_code = 200
    mock_conv_resp.json.return_value = {"data": []}

    async def _mock_get(url: str, **kwargs: Any) -> MagicMock:
        if "/me" in str(url):
            return mock_me_resp
        return mock_conv_resp

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, side_effect=_mock_get):
        res = await app_client.post(
            "/api/admin/channels/facebook/sync",
            json={"max_conversations": 25, "force": True},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "started"
        assert data["page_id"] == "auto_resolved_page_123"


@pytest.mark.asyncio
async def test_sync_per_conversation_error_isolation(db_session: AsyncSession) -> None:
    """A corrupted conversation payload in the batch should not crash the entire sync."""
    FacebookSyncService.reset_status()

    # Mix 1 corrupted conversation with 1 valid conversation
    mixed_data = {
        "data": [
            {
                # Corrupted conversation missing participants
                "id": "t_corrupted",
                "participants": {"data": None},
                "messages": {"data": []},
            },
            {
                # Valid conversation
                "id": "t_valid",
                "participants": {
                    "data": [
                        {"id": "cust_valid_99", "name": "Khách Hàng Hợp Lệ"},
                        {"id": PAGE_ID, "name": "Shop"},
                    ]
                },
                "messages": {
                    "data": [
                        {
                            "id": "m_valid_01",
                            "message": "Xin chào shop",
                            "created_time": "2024-02-01T08:00:00+0000",
                            "from": {"id": "cust_valid_99"},
                        }
                    ]
                },
            },
        ]
    }

    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = mixed_data

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
        res = await FacebookSyncService.sync_page_conversations(
            session=db_session,
            page_id=PAGE_ID,
            access_token=ACCESS_TOKEN,
            max_conversations=50,
        )

    # Valid conversation was synced despite corrupted conversation
    assert res["status"] == "completed"
    assert res["synced_conversations"] == 1
    assert res["synced_messages"] == 1
    assert res["new_customers"] == 1
