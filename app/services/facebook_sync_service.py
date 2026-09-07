"""Facebook Historical Sync Service.

Synchronizes past conversations, messages, and customer profiles from Facebook Fanpage
via Meta Graph API v21.0 into CRM and Live Chat.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    MessageType,
)
from app.models.customer import Customer, FunnelStage
from app.models.customer import Platform as PlatformType
from app.models.setting import SettingCategory
from app.schemas.message import ChannelType
from app.services.funnel_service import FunnelService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


def _parse_created_time(time_str: str | None) -> datetime:
    """Safely parse Facebook ISO8601 created_time string into UTC datetime."""
    if not time_str:
        return datetime.now(UTC)
    try:
        clean_str = time_str.replace("+0000", "+00:00")
        if clean_str.endswith("Z"):
            clean_str = clean_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return datetime.now(UTC)


def _normalize_dt(dt: datetime | None) -> datetime | None:
    """Normalize datetime to timezone-aware UTC to prevent SQLite comparison errors."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class FacebookSyncService:
    """Service to synchronize historical Facebook conversations and messages."""

    _state: dict[str, Any] = {
        "status": "idle",
        "progress_percent": 0,
        "synced_conversations": 0,
        "total_conversations": 0,
        "synced_messages": 0,
        "new_customers": 0,
        "error_message": None,
    }

    @classmethod
    def get_status(cls) -> dict[str, Any]:
        """Return current status and progress metrics."""
        return dict(cls._state)

    @classmethod
    def is_running(cls) -> bool:
        """Check if sync process is currently running."""
        return bool(cls._state["status"] == "running")

    @classmethod
    def reset_status(cls) -> None:
        """Reset state back to idle."""
        cls._state = {
            "status": "idle",
            "progress_percent": 0,
            "synced_conversations": 0,
            "total_conversations": 0,
            "synced_messages": 0,
            "new_customers": 0,
            "error_message": None,
        }

    @classmethod
    def set_running(cls, max_conversations: int = 50) -> None:
        """Set state to running with planned target conversations."""
        cls._state["status"] = "running"
        cls._state["progress_percent"] = 0
        cls._state["synced_conversations"] = 0
        cls._state["total_conversations"] = max_conversations
        cls._state["synced_messages"] = 0
        cls._state["new_customers"] = 0
        cls._state["error_message"] = None

    @classmethod
    async def sync_page_conversations(
        cls,
        session: AsyncSession,
        page_id: str,
        access_token: str,
        max_conversations: int = 50,
        tenant_id: str = "default-system-tenant",
    ) -> dict[str, Any]:
        """Query Meta Graph API v21.0 to ingest past conversations and messages.

        CRITICAL GUARDRAIL: Under NO circumstances trigger outbound messages to Facebook.
        This operation is strictly read-only ingestion.
        """
        cls.set_running(max_conversations)

        synced_convs = 0
        synced_msgs = 0
        new_custs = 0

        clean_page_id = str(page_id).strip()
        clean_token = str(access_token).strip()

        limit_target = max(1, max_conversations)
        page_size = min(25, limit_target)

        base_url = f"https://graph.facebook.com/v21.0/{clean_page_id}/conversations"
        current_url: str | None = base_url
        current_params: dict[str, Any] | None = {
            "fields": "id,updated_time,participants,messages.limit(50){id,message,created_time,from,attachments}",
            "limit": page_size,
            "access_token": clean_token,
        }

        seen_conv_ids: set[str] = set()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while current_url and synced_convs < limit_target:
                    resp = await client.get(current_url, params=current_params)
                    if resp.status_code != 200:
                        err_msg = f"HTTP {resp.status_code}"
                        err_code = None
                        try:
                            err_body = resp.json()
                            if isinstance(err_body, dict) and "error" in err_body:
                                err_msg = err_body["error"].get("message", err_msg)
                                err_code = err_body["error"].get("code")
                        except Exception:
                            pass
                        if resp.status_code == 429 or err_code in (4, 17, 32, 613):
                            err_msg = f"Meta Graph API Rate Limit exceeded: {err_msg}"
                        logger.error("Meta Graph API error during sync: %s", err_msg)
                        cls._state["status"] = "error"
                        cls._state["error_message"] = err_msg
                        return dict(cls._state)

                    resp_data = resp.json()
                    conv_items = resp_data.get("data", [])
                    if not conv_items:
                        break

                    for conv in conv_items:
                        if synced_convs >= limit_target:
                            break

                        conv_fb_id = str(conv.get("id") or "").strip()
                        if conv_fb_id and conv_fb_id in seen_conv_ids:
                            continue
                        if conv_fb_id:
                            seen_conv_ids.add(conv_fb_id)

                        try:
                            # 1. Identify customer participant (p["id"] != clean_page_id)
                            participants = conv.get("participants", {}).get("data", [])
                            cust_participant: dict[str, Any] | None = None
                            for p in participants:
                                p_id = str(p.get("id") or "").strip()
                                if p_id and p_id != clean_page_id:
                                    cust_participant = p
                                    break

                            if not cust_participant:
                                if participants:
                                    for p in participants:
                                        p_id = str(p.get("id") or "").strip()
                                        if p_id != clean_page_id:
                                            cust_participant = p
                                            break
                                if not cust_participant:
                                    continue

                            psid = str(cust_participant.get("id", "")).strip()
                            if not psid or psid == clean_page_id:
                                continue

                            cust_name = cust_participant.get("name")
                            now_dt = datetime.now(UTC)

                            # 2. Get or create Customer
                            stmt_cust = select(Customer).where(
                                Customer.platform == PlatformType.FACEBOOK.value,
                                Customer.platform_user_id == psid,
                                Customer.tenant_id == tenant_id,
                            )
                            customer = (await session.execute(stmt_cust)).scalar_one_or_none()
                            is_new_customer = False
                            if not customer:
                                customer = Customer(
                                    tenant_id=tenant_id,
                                    platform=PlatformType.FACEBOOK.value,
                                    platform_user_id=psid,
                                    name=cust_name,
                                    funnel_stage=FunnelStage.LEAD.value,
                                    first_contact_at=now_dt,
                                    last_contact_at=now_dt,
                                )
                                session.add(customer)
                                await session.flush()
                                new_custs += 1
                                is_new_customer = True
                            else:
                                if cust_name and not customer.name:
                                    customer.name = cust_name

                            # 3. Get or create Conversation
                            stmt_conv = (
                                select(Conversation)
                                .where(
                                    Conversation.customer_id == customer.id,
                                    Conversation.channel == ChannelType.FACEBOOK.value,
                                    Conversation.tenant_id == tenant_id,
                                )
                                .order_by(Conversation.started_at.desc())
                            )
                            conv_record = (await session.execute(stmt_conv)).scalars().first()
                            is_new_conv = False
                            if not conv_record:
                                conv_record = Conversation(
                                    tenant_id=tenant_id,
                                    customer_id=customer.id,
                                    channel=ChannelType.FACEBOOK.value,
                                    status=ConversationStatus.ACTIVE,
                                    started_at=now_dt,
                                )
                                session.add(conv_record)
                                await session.flush()
                                is_new_conv = True

                            conv_id = conv_record.id
                            cust_first_contact = (
                                None
                                if is_new_customer
                                else _normalize_dt(customer.first_contact_at)
                            )
                            cust_last_contact = (
                                None if is_new_customer else _normalize_dt(customer.last_contact_at)
                            )
                            cust_funnel_stage = str(customer.funnel_stage or FunnelStage.LEAD.value)
                            conv_started_at = (
                                None if is_new_conv else _normalize_dt(conv_record.started_at)
                            )

                            # 4. Ingest and deduplicate messages (ordered chronologically)
                            raw_messages = conv.get("messages", {}).get("data", [])
                            sorted_messages = sorted(
                                raw_messages,
                                key=lambda m: str(m.get("created_time") or ""),
                            )

                            # Batch deduplication query: fetch all existing platform_message_ids in one query
                            msg_ids = [
                                str(m.get("id")).strip() for m in sorted_messages if m.get("id")
                            ]
                            existing_ids: set[str] = set()
                            if msg_ids:
                                stmt_msg_ids = select(Message.platform_message_id).where(
                                    Message.platform_message_id.in_(msg_ids)
                                )
                                existing_ids = {
                                    mid
                                    for mid in (await session.execute(stmt_msg_ids)).scalars().all()
                                    if mid is not None
                                }

                            for msg in sorted_messages:
                                msg_id = str(msg.get("id") or "").strip()
                                if not msg_id:
                                    continue

                                if msg_id in existing_ids:
                                    continue
                                existing_ids.add(msg_id)

                                from_info = msg.get("from") or {}
                                from_id = str(from_info.get("id") or "").strip()
                                role = (
                                    MessageRole.AGENT
                                    if from_id == clean_page_id
                                    else MessageRole.CUSTOMER
                                )

                                content = msg.get("message") or ""

                                # Extract media attachments supporting Graph API payload, image_data, video_data, file_url, url
                                media_urls: list[str] = []
                                attachments = msg.get("attachments", {}).get("data", [])
                                for att in attachments:
                                    if isinstance(att, dict):
                                        p_raw = att.get("payload")
                                        p_obj = p_raw if isinstance(p_raw, dict) else {}
                                        img_raw = att.get("image_data")
                                        img_obj = img_raw if isinstance(img_raw, dict) else {}
                                        vid_raw = att.get("video_data")
                                        vid_obj = vid_raw if isinstance(vid_raw, dict) else {}
                                        url = (
                                            p_obj.get("url")
                                            or img_obj.get("url")
                                            or vid_obj.get("url")
                                            or att.get("file_url")
                                            or att.get("url")
                                        )
                                        if url:
                                            media_urls.append(str(url))

                                msg_type = MessageType.IMAGE if media_urls else MessageType.TEXT
                                sent_at = _parse_created_time(msg.get("created_time"))

                                # Detect funnel progression on customer messages
                                if role == MessageRole.CUSTOMER and content:
                                    new_stage = FunnelService.detect_funnel_progression(
                                        content, cust_funnel_stage
                                    )
                                    if new_stage and new_stage != cust_funnel_stage:
                                        cust_funnel_stage = new_stage

                                # Track contact timestamps strictly based on messages
                                if cust_first_contact is None or sent_at < cust_first_contact:
                                    cust_first_contact = sent_at

                                if cust_last_contact is None or sent_at > cust_last_contact:
                                    cust_last_contact = sent_at

                                if conv_started_at is None or sent_at < conv_started_at:
                                    conv_started_at = sent_at

                                new_message = Message(
                                    tenant_id=tenant_id,
                                    conversation_id=conv_id,
                                    role=role,
                                    content=content,
                                    media_urls=media_urls,
                                    message_type=msg_type,
                                    platform_message_id=msg_id,
                                    sent_at=sent_at,
                                )
                                session.add(new_message)
                                synced_msgs += 1

                            # Fallback if conversation had no messages
                            conv_updated_at = _parse_created_time(conv.get("updated_time"))
                            if cust_first_contact is None:
                                cust_first_contact = conv_updated_at or now_dt
                            if cust_last_contact is None:
                                cust_last_contact = conv_updated_at or now_dt
                            if conv_started_at is None:
                                conv_started_at = conv_updated_at or now_dt

                            # Write back aggregated contact timestamps and funnel stage
                            customer.funnel_stage = cust_funnel_stage
                            customer.first_contact_at = cust_first_contact
                            customer.last_contact_at = cust_last_contact
                            conv_record.started_at = conv_started_at

                            synced_convs += 1
                            await session.commit()

                            # Update progress stats
                            cls._state["synced_conversations"] = synced_convs
                            cls._state["synced_messages"] = synced_msgs
                            cls._state["new_customers"] = new_custs
                            cls._state["progress_percent"] = min(
                                99, int((synced_convs / limit_target) * 100)
                            )
                        except Exception as conv_err:
                            logger.warning(
                                "Error processing Facebook conversation %s: %s",
                                conv.get("id"),
                                conv_err,
                            )
                            await session.rollback()
                            continue

                    if synced_convs >= limit_target:
                        break

                    # Cursor pagination
                    paging = resp_data.get("paging", {})
                    next_url = paging.get("next")
                    after_cursor = paging.get("cursors", {}).get("after")

                    if next_url:
                        current_url = next_url
                        current_params = None
                    elif after_cursor:
                        current_url = base_url
                        current_params = {
                            "fields": "id,updated_time,participants,messages.limit(50){id,message,created_time,from,attachments}",
                            "limit": min(25, limit_target - synced_convs),
                            "access_token": clean_token,
                            "after": after_cursor,
                        }
                    else:
                        break

            # Persist last sync information in dynamic settings
            try:
                settings_service = SettingsService(session)
                now_str = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")
                await settings_service.set_setting(
                    key="facebook_last_sync_time",
                    value=now_str,
                    description="Thời gian đồng bộ tin nhắn Facebook gần nhất",
                    category=SettingCategory.CHANNELS,
                )
                await settings_service.set_setting(
                    key="facebook_last_sync_conversations",
                    value=str(synced_convs),
                    description="Số hội thoại Facebook đã đồng bộ",
                    category=SettingCategory.CHANNELS,
                )
                await settings_service.set_setting(
                    key="facebook_last_sync_messages",
                    value=str(synced_msgs),
                    description="Số tin nhắn Facebook đã đồng bộ",
                    category=SettingCategory.CHANNELS,
                )
                await session.commit()
            except Exception as set_err:
                logger.warning("Could not save sync stats to settings: %s", set_err)

            cls._state["status"] = "completed"
            cls._state["progress_percent"] = 100
            cls._state["synced_conversations"] = synced_convs
            cls._state["synced_messages"] = synced_msgs
            cls._state["new_customers"] = new_custs
            cls._state["error_message"] = None
            return dict(cls._state)

        except Exception as exc:
            logger.exception("Unexpected error during Facebook sync: %s", exc)
            await session.rollback()
            cls._state["status"] = "error"
            cls._state["error_message"] = str(exc)
            return dict(cls._state)
