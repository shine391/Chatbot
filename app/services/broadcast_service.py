"""Broadcast messaging service with token bucket rate limiting and Meta 24h compliance."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broadcast import (
    BroadcastCampaign,
    BroadcastRecipient,
    CampaignStatus,
    RecipientStatus,
)
from app.models.conversation import Conversation, Message, MessageRole, MessageType
from app.models.customer import Customer
from app.schemas.broadcast import BroadcastCampaignCreate


class TokenBucketRateLimiter:
    """Async token bucket rate limiter to throttle API dispatches (default: 10 msg/sec)."""

    def __init__(self, rate: float = 10.0, capacity: float = 10.0) -> None:
        self.rate = rate  # Tokens per second
        self.capacity = capacity
        self.tokens = capacity
        self.last_check = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_check
                self.last_check = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

                # Calculate sleep duration until next token is available
                needed = 1.0 - self.tokens
                sleep_time = needed / self.rate
                await asyncio.sleep(sleep_time)


class BroadcastService:
    """Service to create, execute, pause, and report mass broadcast messaging campaigns."""

    ALLOWED_META_TAGS = {
        "CONFIRMED_EVENT_UPDATE",
        "POST_PURCHASE_UPDATE",
        "ACCOUNT_UPDATE",
    }

    def __init__(self, session: AsyncSession, rate_limit_per_sec: float = 10.0) -> None:
        self.session = session
        self.rate_limiter = TokenBucketRateLimiter(
            rate=rate_limit_per_sec, capacity=rate_limit_per_sec
        )

    async def create_campaign(self, data: BroadcastCampaignCreate) -> BroadcastCampaign:
        """Create a new broadcast campaign and populate eligible recipients."""
        campaign = BroadcastCampaign(
            name=data.name,
            channel=data.channel,
            message_content=data.message_content,
            media_url=data.media_url,
            message_tag=data.message_tag,
            status=CampaignStatus.DRAFT,
            filter_criteria=data.filter_criteria,
        )
        self.session.add(campaign)
        await self.session.flush()

        # Build customer query based on filter criteria
        stmt = select(Customer)
        if data.channel:
            stmt = stmt.where(Customer.platform == data.channel)

        funnel_stage = data.filter_criteria.get("funnel_stage")
        if funnel_stage:
            stmt = stmt.where(Customer.funnel_stage == funnel_stage)

        res = await self.session.execute(stmt)
        customers = res.scalars().all()

        recipients: list[BroadcastRecipient] = []
        for cust in customers:
            recipients.append(
                BroadcastRecipient(
                    campaign_id=campaign.id,
                    customer_id=cust.id,
                    recipient_identifier=cust.platform_user_id,
                    status=RecipientStatus.PENDING,
                )
            )

        self.session.add_all(recipients)
        campaign.total_recipients = len(recipients)
        await self.session.commit()
        await self.session.refresh(campaign)

        logger.info(
            f"Created Broadcast Campaign #{campaign.id} '{campaign.name}' with {len(recipients)} recipients."
        )
        return campaign

    async def start_campaign(self, campaign_id: int) -> dict[str, Any]:
        """Start or resume execution of a broadcast campaign."""
        stmt = select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
        res = await self.session.execute(stmt)
        campaign = res.scalar_one_or_none()
        if not campaign:
            raise ValueError("Campaign not found")

        if campaign.status in (CampaignStatus.COMPLETED, CampaignStatus.CANCELLED):
            return {"status": campaign.status.value, "message": "Campaign cannot be run"}

        campaign.status = CampaignStatus.RUNNING
        if campaign.started_at is None:
            campaign.started_at = datetime.now(timezone.utc)
        await self.session.commit()

        # Execute campaign delivery in batches
        return await self._execute_delivery(campaign_id)

    async def pause_campaign(self, campaign_id: int) -> dict[str, Any]:
        """Pause a currently running campaign."""
        stmt = select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
        res = await self.session.execute(stmt)
        campaign = res.scalar_one_or_none()
        if not campaign:
            raise ValueError("Campaign not found")

        if campaign.status == CampaignStatus.RUNNING:
            campaign.status = CampaignStatus.PAUSED
            await self.session.commit()
            logger.info(f"Broadcast Campaign #{campaign_id} paused.")

        return {"status": campaign.status.value}

    async def _execute_delivery(self, campaign_id: int) -> dict[str, Any]:
        """Internal delivery loop with rate limiting and 24h Meta compliance check."""
        now = datetime.now(timezone.utc)
        twenty_four_hours_ago = now - timedelta(hours=24)

        # Re-fetch campaign
        camp_stmt = select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
        campaign = (await self.session.execute(camp_stmt)).scalar_one_or_none()
        if not campaign or campaign.status != CampaignStatus.RUNNING:
            return {"status": "aborted"}

        from app.channels.facebook_channel import FacebookChannel
        from app.services.message_sender import MessageSender

        fb_channel = await FacebookChannel.from_settings(self.session)
        sender = await MessageSender.from_settings(self.session)

        # Get pending recipients
        rec_stmt = (
            select(BroadcastRecipient)
            .where(
                BroadcastRecipient.campaign_id == campaign_id,
                BroadcastRecipient.status == RecipientStatus.PENDING,
            )
            .limit(500)
        )
        recipients = (await self.session.execute(rec_stmt)).scalars().all()

        for rec in recipients:
            # Check if campaign was paused/cancelled mid-flight
            await self.session.refresh(campaign)
            if campaign.status != CampaignStatus.RUNNING:
                logger.info(f"Campaign #{campaign_id} was paused/cancelled. Halting delivery.")
                break

            # Fetch customer & last interaction
            cust_stmt = select(Customer).where(Customer.id == rec.customer_id)
            cust = (await self.session.execute(cust_stmt)).scalar_one_or_none()
            if not cust:
                rec.status = RecipientStatus.FAILED
                rec.error_message = "Customer record not found"
                campaign.failed_count += 1
                continue

            last_active = cust.last_contact_at or cust.first_contact_at
            is_outside_24h = last_active < twenty_four_hours_ago if last_active else True

            # 24-HOUR POLICY ENFORCEMENT
            if is_outside_24h:
                # If outside 24h, a valid Meta tag is strictly REQUIRED
                if not campaign.message_tag or campaign.message_tag not in self.ALLOWED_META_TAGS:
                    rec.status = RecipientStatus.SKIPPED_POLICY
                    rec.error_message = (
                        "Skipped: Outside 24h window and no valid Meta Message Tag configured"
                    )
                    campaign.skipped_count += 1
                    continue

            # Throttle send rate to 10 msg/sec
            await self.rate_limiter.acquire()

            try:
                if cust.platform == "facebook":
                    # Tagged Facebook message
                    messaging_type = (
                        "MESSAGE_TAG" if (is_outside_24h and campaign.message_tag) else "RESPONSE"
                    )
                    resp = await fb_channel.send_text(
                        recipient_id=rec.recipient_identifier,
                        text=campaign.message_content,
                        messaging_type=messaging_type,
                        tag=campaign.message_tag if is_outside_24h else None,
                    )
                    if resp.success:
                        rec.status = RecipientStatus.SENT
                        rec.sent_at = datetime.now(timezone.utc)
                        campaign.sent_count += 1
                    else:
                        rec.status = RecipientStatus.FAILED
                        rec.error_message = resp.error or "Facebook send failed"
                        campaign.failed_count += 1
                else:
                    send_res = await sender.send_text(
                        platform=str(cust.platform),
                        recipient_id=rec.recipient_identifier,
                        text=campaign.message_content,
                    )
                    if send_res.success:
                        rec.status = RecipientStatus.SENT
                        rec.sent_at = datetime.now(timezone.utc)
                        campaign.sent_count += 1
                    else:
                        rec.status = RecipientStatus.FAILED
                        rec.error_message = send_res.error or "Channel send failed"
                        campaign.failed_count += 1

                # Save record in conversation message history
                conv_stmt = (
                    select(Conversation)
                    .where(Conversation.customer_id == cust.id)
                    .order_by(Conversation.id.desc())
                )
                conv = (await self.session.execute(conv_stmt)).scalars().first()
                if conv:
                    self.session.add(
                        Message(
                            conversation_id=conv.id,
                            role=MessageRole.BOT,
                            content=campaign.message_content,
                            message_type=MessageType.TEXT,
                        )
                    )

            except Exception as exc:
                rec.status = RecipientStatus.FAILED
                rec.error_message = str(exc)
                campaign.failed_count += 1

        # Check if all completed
        remaining_stmt = select(BroadcastRecipient.id).where(
            BroadcastRecipient.campaign_id == campaign_id,
            BroadcastRecipient.status == RecipientStatus.PENDING,
        )
        remaining = (await self.session.execute(remaining_stmt)).scalars().first()
        if remaining is None and campaign.status == CampaignStatus.RUNNING:
            campaign.status = CampaignStatus.COMPLETED
            campaign.completed_at = datetime.now(timezone.utc)

        await self.session.commit()
        await self.session.refresh(campaign)

        return {
            "status": campaign.status.value,
            "sent_count": campaign.sent_count,
            "failed_count": campaign.failed_count,
            "skipped_count": campaign.skipped_count,
            "total_recipients": campaign.total_recipients,
        }
